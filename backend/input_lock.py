"""
Physical mouse + keyboard lockout for the duration of an automated login.

Vortex drives the Riot Client's sign-in page with UI Automation and synthetic
keystrokes. A stray click or keypress from the user lands in the middle of that
sequence, steals focus from the window being typed into, and the login either
fills the wrong field or fails outright. Suppressing real input for those few
seconds removes the whole class of failure.

WHY NOT BlockInput
------------------
The obvious primitive, ``BlockInput``, cannot be used here. Its documentation
is explicit that while a block is held, "the thread that is blocking input can
affect [key state] by calling SendInput. **No other thread can do this.**" The
block therefore has to live on the very thread doing the typing - but that
thread is busy inside long UI Automation calls and cannot also police a
timeout, so a stuck login would strand a machine-wide input block with nothing
able to lift it (only the blocking thread may unblock). Holding it on a
dedicated thread instead - the only way to keep the safety net - silently
swallows Vortex's *own* synthetic keystrokes, which is exactly how v5.6.4
shipped a build that filled the login form (UI Automation ``SetValue``, an API
call, unaffected) but could never submit it.

Low-level hooks have neither problem. ``WH_KEYBOARD_LL``/``WH_MOUSE_LL`` see a
flag on every event saying whether it was **injected** by software, so real
input is swallowed while Vortex's own synthetic input passes through untouched.
The hooks are also owned by whichever thread installed them, which can pump
messages and enforce its own timeout.

SAFETY
------
A lock that fails to lift leaves the machine unusable, so nothing here rests on
a single release path:

* **One dedicated thread owns the hooks**, pumps their messages, and always
  removes them in a ``finally`` - including on crash.
* **A hard ceiling.** The hold never outlives ``timeout`` seconds.
* **Tapping ESC** lifts it immediately.
* **Ctrl+Alt+Del** is a secure attention sequence the OS handles below any
  hook, so it is always available and cannot be suppressed.
* **Windows itself** silently drops a low-level hook whose thread stops
  responding, so a wedged holder fails open rather than closed.
* **Process exit** releases via ``atexit``.

Mouse *movement* is deliberately left alone. Moving the pointer cannot steal
focus or type anything, and a cursor frozen mid-login is indistinguishable
from a hung machine. Buttons, wheel and every key are suppressed.
"""

import atexit
import ctypes
import logging
import os
import threading
import time
from ctypes import wintypes
from typing import Any, Dict, Optional

logger = logging.getLogger("vortex.input_lock")

_IS_WINDOWS = os.name == "nt"

WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14

# Set on an event that software generated rather than real hardware.
LLKHF_INJECTED = 0x10
LLMHF_INJECTED = 0x01

VK_ESCAPE = 0x1B

WM_MOUSEMOVE = 0x0200

QS_ALLINPUT = 0x04FF
PM_REMOVE = 0x0001
WAIT_OBJECT_0 = 0x0
INFINITE = 0xFFFFFFFF

# Absolute ceiling on a single hold. The login watchdog forces a stuck attempt
# to an error at 210s, so this only ever fires if that failed too.
DEFAULT_TIMEOUT = 240.0

if _IS_WINDOWS:
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    LRESULT = ctypes.c_ssize_t
    _HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

    class KBDLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [
            ("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD),
            ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.c_void_p),
        ]

    class MSLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [
            ("pt", wintypes.POINT), ("mouseData", wintypes.DWORD),
            ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.c_void_p),
        ]

    _user32.SetWindowsHookExW.argtypes = [ctypes.c_int, _HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
    _user32.SetWindowsHookExW.restype = wintypes.HHOOK
    _user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
    _user32.UnhookWindowsHookEx.restype = wintypes.BOOL
    _user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
    _user32.CallNextHookEx.restype = LRESULT
    _user32.MsgWaitForMultipleObjects.argtypes = [
        wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE), wintypes.BOOL,
        wintypes.DWORD, wintypes.DWORD,
    ]
    _user32.MsgWaitForMultipleObjects.restype = wintypes.DWORD
    _user32.PeekMessageW.argtypes = [
        ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT,
    ]
    _user32.PeekMessageW.restype = wintypes.BOOL
    _kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
    _kernel32.CreateEventW.restype = wintypes.HANDLE
    _kernel32.SetEvent.argtypes = [wintypes.HANDLE]
    _kernel32.SetEvent.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL
else:  # pragma: no cover - the app only ships on Windows
    _user32 = None
    _kernel32 = None
    _HOOKPROC = None

_STATE_LOCK = threading.Lock()
_blocked = threading.Event()        # set only while input is really suppressed
_holder: Optional[threading.Thread] = None
_stop_handle: Optional[int] = None  # Win32 event the holder waits on
_escape_pressed = threading.Event()
_state: Dict[str, Any] = {
    "enabled": True,                # mirrors the lock_input_during_login setting
    "reason": "",
    "since": 0.0,
    "released_by": "",
    "last_error": "",
    "suppressed": 0,
}


def set_enabled(enabled: bool) -> None:
    """Mirror the user's ``lock_input_during_login`` preference."""
    with _STATE_LOCK:
        _state["enabled"] = bool(enabled)


def is_enabled() -> bool:
    with _STATE_LOCK:
        return bool(_state["enabled"])


def is_locked() -> bool:
    """True only while physical input is actually being suppressed."""
    return _blocked.is_set()


def status() -> Dict[str, Any]:
    with _STATE_LOCK:
        snapshot = dict(_state)
    snapshot["locked"] = is_locked()
    if snapshot["locked"] and snapshot["since"]:
        snapshot["held_for"] = round(time.time() - snapshot["since"], 2)
    return snapshot


def _count_suppressed() -> None:
    with _STATE_LOCK:
        _state["suppressed"] += 1


def _keyboard_callback(n_code, w_param, l_param):
    """Swallow real keystrokes; let Vortex's own injected ones through."""
    try:
        if n_code >= 0 and _blocked.is_set():
            info = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            if not (info.flags & LLKHF_INJECTED):
                # ESC is the user's escape hatch out of the lock.
                if info.vkCode == VK_ESCAPE:
                    _escape_pressed.set()
                    if _stop_handle:
                        _kernel32.SetEvent(_stop_handle)
                _count_suppressed()
                return 1
    except Exception:
        # A failure here must never suppress input, and must never raise into
        # the hook chain.
        logger.exception("keyboard hook callback failed")
    return _user32.CallNextHookEx(None, n_code, w_param, l_param)


def _mouse_callback(n_code, w_param, l_param):
    """
    Swallow real clicks and wheel events; let injected ones through.

    Movement is passed through on purpose - it cannot steal focus, and a frozen
    cursor reads as a hung machine.
    """
    try:
        if n_code >= 0 and _blocked.is_set() and w_param != WM_MOUSEMOVE:
            info = ctypes.cast(l_param, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
            if not (info.flags & LLMHF_INJECTED):
                _count_suppressed()
                return 1
    except Exception:
        logger.exception("mouse hook callback failed")
    return _user32.CallNextHookEx(None, n_code, w_param, l_param)


def _hold(reason: str, timeout: float, stop_handle: int, started: threading.Event) -> None:
    """
    Own one lock from start to finish.

    Low-level hooks are delivered to the thread that installed them, so this
    thread installs them, pumps their messages, enforces the timeout, and
    always removes them in the ``finally``.
    """
    kb_hook = None
    ms_hook = None
    released_by = "release()"
    # Held in locals for the whole hold: if these are garbage collected the
    # hook chain calls into freed memory.
    kb_proc = _HOOKPROC(_keyboard_callback)
    ms_proc = _HOOKPROC(_mouse_callback)
    try:
        kb_hook = _user32.SetWindowsHookExW(WH_KEYBOARD_LL, kb_proc, None, 0)
        ms_hook = _user32.SetWindowsHookExW(WH_MOUSE_LL, ms_proc, None, 0)
        if not kb_hook or not ms_hook:
            err = ctypes.get_last_error()
            message = f"could not install input hooks (WinError {err})"
            logger.warning("input lock unavailable: %s", message)
            with _STATE_LOCK:
                _state["last_error"] = message
            return

        _blocked.set()
        with _STATE_LOCK:
            _state["reason"] = reason
            _state["since"] = time.time()
            _state["released_by"] = ""
            _state["last_error"] = ""
            _state["suppressed"] = 0
        # Signal arm() as soon as the outcome is known, not when the hold ends.
        started.set()
        logger.info("input locked (%s), ceiling %.0fs", reason, timeout)

        handles = (wintypes.HANDLE * 1)(stop_handle)
        deadline = time.monotonic() + max(1.0, timeout)
        msg = wintypes.MSG()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                released_by = "timeout"
                logger.error(
                    "input lock hit its %.0fs ceiling during '%s' - releasing", timeout, reason
                )
                break
            # Wake on the stop event or on any message, so hook callbacks are
            # serviced promptly. Windows drops a low-level hook whose thread
            # stalls past LowLevelHooksTimeout (300ms by default).
            wait_ms = min(int(remaining * 1000), 100)
            result = _user32.MsgWaitForMultipleObjects(
                1, handles, False, wait_ms, QS_ALLINPUT
            )
            if result == WAIT_OBJECT_0:
                if _escape_pressed.is_set():
                    released_by = "escape key"
                    logger.warning("input lock released early - ESC during '%s'", reason)
                break
            while _user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                pass
    except Exception:
        released_by = "internal error"
        logger.exception("input lock holder crashed - releasing input")
    finally:
        _blocked.clear()
        for hook in (kb_hook, ms_hook):
            if hook:
                try:
                    _user32.UnhookWindowsHookEx(hook)
                except Exception:
                    logger.exception("UnhookWindowsHookEx failed")
        with _STATE_LOCK:
            _state["released_by"] = released_by
            suppressed = _state["suppressed"]
            _state["since"] = 0.0
        logger.info(
            "input unlocked (%s) after '%s'; suppressed %d real events",
            released_by, reason, suppressed,
        )
        started.set()


def arm(reason: str = "login", timeout: float = DEFAULT_TIMEOUT) -> bool:
    """
    Suppress real input until :func:`release`, ``timeout`` seconds, or ESC.

    Vortex's own synthetic input is never suppressed, so an automated login
    types normally while the lock is held.

    Returns True only if input is genuinely being suppressed. A disabled
    preference, a non-Windows host, or hooks that failed to install all return
    False and leave the caller running unprotected - which is correct, since
    the alternative is reporting a lock that isn't there.
    """
    if not _IS_WINDOWS or _user32 is None:
        return False
    if not is_enabled():
        return False

    global _stop_handle, _holder
    with _STATE_LOCK:
        if _holder is not None and _holder.is_alive():
            return _blocked.is_set()      # already held; don't stack locks
        handle = _kernel32.CreateEventW(None, True, False, None)
        if not handle:
            _state["last_error"] = "could not create the release event"
            return False
        _escape_pressed.clear()
        started = threading.Event()
        holder = threading.Thread(
            target=_hold, args=(reason, timeout, handle, started),
            name="vortex-input-lock", daemon=True,
        )
        _stop_handle = handle
        _holder = holder
        holder.start()

    started.wait(2.0)
    return _blocked.is_set()


def release(reason: str = "login finished") -> None:
    """Lift the lock. Safe to call when nothing is held, and from any thread."""
    global _stop_handle, _holder
    with _STATE_LOCK:
        handle, holder = _stop_handle, _holder
        _stop_handle = None
        _holder = None
    if handle is None:
        return
    logger.debug("input lock release requested (%s)", reason)
    try:
        _kernel32.SetEvent(handle)
    except Exception:
        logger.exception("SetEvent on the input lock failed")
    if holder is not None and holder.is_alive() and holder is not threading.current_thread():
        # Bounded: the holder only has its unhook calls left to run.
        holder.join(3.0)
        if holder.is_alive():
            logger.error("input lock holder did not exit within 3s")
    try:
        _kernel32.CloseHandle(handle)
    except Exception:
        pass


@atexit.register
def _release_on_exit() -> None:  # pragma: no cover - shutdown path
    if _blocked.is_set():
        release("process exit")
