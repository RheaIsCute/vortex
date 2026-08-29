"""
Global keyboard shortcut for toggling the Quick Panel overlay window.

Registered at the OS level via RegisterHotKey - the same mechanism most
launcher/overlay tools use (Steam, Discord's non-injected features, etc) -
rather than a keyboard hook or anything that touches VALORANT's process.
Nothing here reads input from, injects into, or otherwise interacts with the
game; it only listens for one specific key combination system-wide and calls
back into this app when it fires.
"""

import ctypes
import ctypes.wintypes
import logging
import re
import threading
from typing import Callable, Dict, Optional, Tuple

logger = logging.getLogger("vortex.overlay_hotkey")

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

WM_HOTKEY = 0x0312

_MODIFIERS = {
    "CTRL": MOD_CONTROL, "CONTROL": MOD_CONTROL,
    "SHIFT": MOD_SHIFT,
    "ALT": MOD_ALT,
    "WIN": MOD_WIN, "WINDOWS": MOD_WIN, "META": MOD_WIN, "SUPER": MOD_WIN,
}

# Virtual-key codes for the names a user is realistically going to type.
# Letters and digits are handled separately (their VK code is just the
# ASCII/uppercase codepoint), this only needs the named keys.
_NAMED_KEYS: Dict[str, int] = {
    "SPACE": 0x20, "TAB": 0x09, "ESC": 0x1B, "ESCAPE": 0x1B,
    "ENTER": 0x0D, "RETURN": 0x0D, "BACKSPACE": 0x08,
    "INSERT": 0x2D, "DELETE": 0x2E, "DEL": 0x2E,
    "HOME": 0x24, "END": 0x23, "PAGEUP": 0x21, "PAGEDOWN": 0x22,
    "UP": 0x26, "DOWN": 0x28, "LEFT": 0x25, "RIGHT": 0x27,
    "PRINTSCREEN": 0x2C, "PAUSE": 0x13,
}
for _n in range(1, 25):
    _NAMED_KEYS[f"F{_n}"] = 0x6F + _n if _n > 12 else 0x70 + (_n - 1)
# F1..F12 are 0x70..0x7B; F13..F24 are 0x7C..0x87 - fix the range above.
for _n in range(1, 13):
    _NAMED_KEYS[f"F{_n}"] = 0x70 + (_n - 1)
for _n in range(13, 25):
    _NAMED_KEYS[f"F{_n}"] = 0x7C + (_n - 13)


class InvalidHotkey(ValueError):
    pass


def parse_hotkey(spec: str) -> Tuple[int, int]:
    """
    "CTRL+SHIFT+F8" -> (modifiers, virtual_key_code). Raises InvalidHotkey
    with a message that names the actual problem, since this is user-typed
    text that free-form Settings input has to validate before it's stored.
    """
    parts = [p.strip().upper() for p in re.split(r"[+\s]+", spec.strip()) if p.strip()]
    if not parts:
        raise InvalidHotkey("Enter a key combination, e.g. CTRL+SHIFT+F8.")

    modifiers = 0
    key_part = None
    for part in parts:
        if part in _MODIFIERS:
            modifiers |= _MODIFIERS[part]
        elif key_part is None:
            key_part = part
        else:
            raise InvalidHotkey(f"\"{part}\" isn't a modifier and a key was already given.")

    if key_part is None:
        raise InvalidHotkey("Add a key after the modifiers, e.g. CTRL+SHIFT+F8.")
    if not modifiers:
        raise InvalidHotkey("Add at least one modifier (CTRL, ALT, SHIFT or WIN) so this doesn't fire on plain typing.")

    if key_part in _NAMED_KEYS:
        vk = _NAMED_KEYS[key_part]
    elif len(key_part) == 1 and (key_part.isalnum()):
        vk = ord(key_part)
    else:
        raise InvalidHotkey(f"\"{key_part}\" isn't a key this can bind - use a letter, digit, or F1-F24.")

    return modifiers, vk


class OverlayHotkey:
    """
    Owns one global hotkey registration on a dedicated thread. RegisterHotKey
    ties a hotkey's delivery to the thread that registered it, so the
    listener needs its own thread with its own Win32 message loop - it can't
    just be a callback bolted onto an existing one.
    """

    def __init__(self):
        self._thread: Optional[threading.Thread] = None
        self._thread_id = 0
        self._stop_requested = False
        self.active_spec = ""

    def start(self, spec: str, on_trigger: Callable[[], None]) -> Optional[str]:
        """Starts listening for `spec`. Returns an error string on failure, else None."""
        try:
            modifiers, vk = parse_hotkey(spec)
        except InvalidHotkey as e:
            return str(e)

        self.stop()
        ready = threading.Event()
        result: Dict[str, Optional[str]] = {"error": None}

        def run():
            user32 = ctypes.windll.user32
            self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
            if not user32.RegisterHotKey(None, 1, modifiers | MOD_NOREPEAT, vk):
                result["error"] = (
                    f"Windows refused to register {spec} - it's probably already "
                    "claimed by another running application."
                )
                ready.set()
                return

            ready.set()
            msg = ctypes.wintypes.MSG()
            try:
                while not self._stop_requested:
                    # A timeout-bounded wait via PeekMessage, rather than a
                    # blocking GetMessage, so _stop_requested is actually
                    # checked instead of sleeping in the OS call forever
                    # until a hotkey happens to fire.
                    if user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                        if msg.message == WM_HOTKEY:
                            try:
                                on_trigger()
                            except Exception:
                                logger.exception("overlay hotkey callback failed")
                        user32.TranslateMessage(ctypes.byref(msg))
                        user32.DispatchMessageW(ctypes.byref(msg))
                    else:
                        ctypes.windll.kernel32.Sleep(50)
            finally:
                user32.UnregisterHotKey(None, 1)

        self._stop_requested = False
        self._thread = threading.Thread(target=run, daemon=True, name="vortex-overlay-hotkey")
        self._thread.start()
        ready.wait(timeout=3.0)

        if result["error"]:
            self._thread = None
            return result["error"]

        self.active_spec = spec
        logger.info("overlay hotkey armed: %s", spec)
        return None

    def stop(self) -> None:
        if not self._thread:
            return
        self._stop_requested = True
        self._thread.join(timeout=2.0)
        self._thread = None
        self.active_spec = ""
