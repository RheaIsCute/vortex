"""
Physical mouse + keyboard lockout for the duration of an automated login.

Vortex drives the Riot Client's sign-in page with UI Automation and synthetic
keystrokes. A stray click or keypress from the user lands in the middle of that
sequence, steals focus from the window being typed into, and the login either
fills the wrong field or fails outright. Blocking real input for those few
seconds removes the whole class of failure.

The primitive is Win32 ``BlockInput``, which drops physical mouse/keyboard input
before it reaches any application's input queue.

SAFETY
------
A lock that fails to lift leaves the machine unusable, so nothing here holds
input on a single point of failure. Every one of these releases it:

* **One dedicated thread owns the block.** Windows only lets the thread that
  called ``BlockInput(TRUE)`` call ``BlockInput(FALSE)`` - a watchdog on another
  thread physically cannot lift it. So the owning thread does its own waiting
  and always releases in a ``finally``, including if it crashes.
* **A hard ceiling.** The hold never outlives ``timeout`` seconds regardless of
  what the caller does, so a caller that forgets to release still recovers.
* **Holding ESC.** ``BlockInput`` stops input reaching the input queue but the
  system keeps tracking physical key state, so ``GetAsyncKeyState`` still sees
  the key. Holding ESC for ~0.4s lifts the lock immediately.
* **Ctrl+Alt+Del.** Windows lifts a ``BlockInput`` hold itself on the secure
  attention sequence. This one is guaranteed by the OS and cannot be suppressed.
* **Process exit.** An ``atexit`` hook releases if Vortex is shutting down.

``BlockInput`` needs the caller to be at least as privileged as the foreground
process; unelevated Vortex simply fails the call and the login proceeds
unlocked rather than pretending it is protected.
"""

import atexit
import ctypes
import logging
import os
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("vortex.input_lock")

_IS_WINDOWS = os.name == "nt"

VK_ESCAPE = 0x1B
_KEY_DOWN_MASK = 0x8000

# Poll cadence while holding. Also how often the ESC escape hatch is sampled.
_POLL_INTERVAL = 0.2
# Consecutive polls with ESC physically down before the hold is abandoned.
_ESC_HOLD_POLLS = 2

# Absolute ceiling on a single hold. The login watchdog forces a stuck attempt
# to an error at 210s, so this only ever fires if that failed too.
DEFAULT_TIMEOUT = 240.0

if _IS_WINDOWS:
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _user32.BlockInput.argtypes = [ctypes.c_int]
    _user32.BlockInput.restype = ctypes.c_int
    _user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    _user32.GetAsyncKeyState.restype = ctypes.c_short
else:  # pragma: no cover - the app only ships on Windows
    _user32 = None

_STATE_LOCK = threading.Lock()
_blocked = threading.Event()        # set only while input is really blocked
_release_event: Optional[threading.Event] = None
_holder: Optional[threading.Thread] = None
_state: Dict[str, Any] = {
    "enabled": True,                # mirrors the lock_input_during_login setting
    "reason": "",
    "since": 0.0,
    "released_by": "",
    "last_error": "",
}


def set_enabled(enabled: bool) -> None:
    """Mirror the user's ``lock_input_during_login`` preference."""
    with _STATE_LOCK:
        _state["enabled"] = bool(enabled)


def is_enabled() -> bool:
    with _STATE_LOCK:
        return bool(_state["enabled"])


def is_locked() -> bool:
    """True only while physical input is actually being blocked."""
    return _blocked.is_set()


def status() -> Dict[str, Any]:
    with _STATE_LOCK:
        snapshot = dict(_state)
    snapshot["locked"] = is_locked()
    if snapshot["locked"] and snapshot["since"]:
        snapshot["held_for"] = round(time.time() - snapshot["since"], 2)
    return snapshot


def _esc_is_down() -> bool:
    try:
        return bool(_user32.GetAsyncKeyState(VK_ESCAPE) & _KEY_DOWN_MASK)
    except Exception:
        # Never let a failed key read keep input blocked.
        return False


def _hold(reason: str, timeout: float,
          release_event: threading.Event, started: threading.Event) -> None:
    """
    Own one block from start to finish.

    Runs on its own thread because only the blocking thread may unblock. The
    ``finally`` is the last line of defence: whatever happens above it, input
    comes back.
    """
    acquired = False
    released_by = "release()"
    try:
        if not _user32.BlockInput(True):
            err = ctypes.get_last_error()
            # ERROR_ACCESS_DENIED (5) means another thread already holds a
            # block, or Vortex is not elevated enough to take one.
            message = f"BlockInput was refused (WinError {err})"
            logger.warning("input lock unavailable: %s", message)
            with _STATE_LOCK:
                _state["last_error"] = message
            return

        acquired = True
        _blocked.set()
        with _STATE_LOCK:
            _state["reason"] = reason
            _state["since"] = time.time()
            _state["released_by"] = ""
            _state["last_error"] = ""
        # Hand control back to arm() the instant the outcome is known, rather
        # than when the hold ends - otherwise every login pays arm()'s full
        # wait before it can start typing.
        started.set()
        logger.info("input locked (%s), ceiling %.0fs", reason, timeout)

        deadline = time.monotonic() + max(1.0, timeout)
        esc_polls = 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                released_by = "timeout"
                logger.error(
                    "input lock hit its %.0fs ceiling during '%s' - releasing", timeout, reason
                )
                break
            if release_event.wait(min(_POLL_INTERVAL, remaining)):
                break
            if _esc_is_down():
                esc_polls += 1
                if esc_polls >= _ESC_HOLD_POLLS:
                    released_by = "escape key"
                    logger.warning("input lock released early - ESC held during '%s'", reason)
                    break
            else:
                esc_polls = 0
    except Exception:
        released_by = "internal error"
        logger.exception("input lock holder crashed - releasing input")
    finally:
        if acquired:
            try:
                _user32.BlockInput(False)
            except Exception:
                logger.exception("BlockInput(False) raised; input may still be held")
            _blocked.clear()
            with _STATE_LOCK:
                _state["released_by"] = released_by
                _state["since"] = 0.0
            logger.info("input unlocked (%s) after '%s'", released_by, reason)
        started.set()


def arm(reason: str = "login", timeout: float = DEFAULT_TIMEOUT) -> bool:
    """
    Block physical input until :func:`release`, ``timeout`` seconds, or ESC.

    Returns True only if input is genuinely blocked. A disabled preference, a
    non-Windows host, or a refused ``BlockInput`` all return False and leave the
    caller running unprotected - which is correct, since the alternative is
    reporting a lock that isn't there.
    """
    if not _IS_WINDOWS or _user32 is None:
        return False
    if not is_enabled():
        return False

    with _STATE_LOCK:
        if _holder is not None and _holder.is_alive():
            return _blocked.is_set()      # already held; don't stack blocks
        release_event = threading.Event()
        started = threading.Event()
        holder = threading.Thread(
            target=_hold, args=(reason, timeout, release_event, started),
            name="vortex-input-lock", daemon=True,
        )
        globals()["_release_event"] = release_event
        globals()["_holder"] = holder
        holder.start()

    # The holder sets `started` as soon as it knows whether it got the block.
    started.wait(2.0)
    return _blocked.is_set()


def release(reason: str = "login finished") -> None:
    """Lift the block. Safe to call when nothing is held, and from any thread."""
    with _STATE_LOCK:
        release_event, holder = _release_event, _holder
        globals()["_release_event"] = None
        globals()["_holder"] = None
    if release_event is None:
        return
    logger.debug("input lock release requested (%s)", reason)
    release_event.set()
    if holder is not None and holder.is_alive() and holder is not threading.current_thread():
        # Bounded: the holder only has BlockInput(False) left to run.
        holder.join(3.0)
        if holder.is_alive():
            logger.error("input lock holder did not exit within 3s")


@atexit.register
def _release_on_exit() -> None:  # pragma: no cover - shutdown path
    if _blocked.is_set():
        release("process exit")
