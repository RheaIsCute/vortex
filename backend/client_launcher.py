"""
Riot Client Launcher & Official PVP API Direct Sync for Valorant.
Handles:
- Riot Client auto-detection and pure keyboard auto-login
- Local REST API session signout
- Official Riot PVP token extraction for exact Username, Riot ID, Region, Level, Rank, Peak Rank, and Account Status (Playable/Banned/Suspended)
- Batch account verification worker ("Check Accounts")
"""

import os
import sys
import json
import re
import time
import logging
import logging.handlers
import subprocess
import threading
import winreg
import ctypes
import pyautogui
import pyperclip
import requests
import urllib3
import win32gui
import win32con
import win32process
import win32api
from ctypes import wintypes
from typing import Optional, Dict, Any, Tuple

from backend import elevation
from backend import runtime_audit

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
pyautogui.PAUSE = 0.04

# Enable Per-Monitor DPI awareness so window coordinates & clicks match physical pixels accurately
try:
    ctypes.windll.user32.SetProcessDpiAwarenessContext(-4)
except Exception:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass

# Same per-user writable location the database uses in a packaged build, so
# the log survives updates and is somewhere a user can actually find it.
if getattr(sys, "frozen", False):
    _LOG_DIR = os.path.join(os.getenv("LOCALAPPDATA") or os.path.expanduser("~"), "Vortex")
else:
    _LOG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.makedirs(_LOG_DIR, exist_ok=True)
LOGIN_LOG_FILE = os.path.join(_LOG_DIR, "login_debug.log")

login_logger = logging.getLogger("vortex.login")
login_logger.setLevel(logging.DEBUG)
if not login_logger.handlers:
    _handler = logging.handlers.RotatingFileHandler(
        LOGIN_LOG_FILE, maxBytes=2 * 1024 * 1024, backupCount=2, encoding="utf-8"
    )
    _handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    login_logger.addHandler(_handler)
    login_logger.propagate = False

class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ('dwSize', ctypes.c_uint32),
        ('cntUsage', ctypes.c_uint32),
        ('th32ProcessID', ctypes.c_uint32),
        ('th32DefaultHeapID', ctypes.c_size_t),
        ('th32ModuleID', ctypes.c_uint32),
        ('cntThreads', ctypes.c_uint32),
        ('th32ParentProcessID', ctypes.c_uint32),
        ('pcPriClassBase', ctypes.c_long),
        ('dwFlags', ctypes.c_uint32),
        ('szExeFile', ctypes.c_wchar * 260)
    ]


def _is_process_running_fast(targets: set) -> bool:
    if os.name != "nt":
        return False
    try:
        CreateToolhelp32Snapshot = ctypes.windll.kernel32.CreateToolhelp32Snapshot
        Process32FirstW = ctypes.windll.kernel32.Process32FirstW
        Process32NextW = ctypes.windll.kernel32.Process32NextW
        CloseHandle = ctypes.windll.kernel32.CloseHandle

        h_snap = CreateToolhelp32Snapshot(0x00000002, 0)
        if h_snap == -1 or not h_snap:
            return False
        try:
            entry = _PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
            if not Process32FirstW(h_snap, ctypes.byref(entry)):
                return False
            while True:
                if entry.szExeFile.lower() in targets:
                    return True
                if not Process32NextW(h_snap, ctypes.byref(entry)):
                    break
            return False
        finally:
            CloseHandle(h_snap)
    except Exception:
        return False


def _running_process_ids(targets: set) -> set:
    """Return matching process IDs from one Toolhelp snapshot."""
    if os.name != "nt":
        return set()
    wanted = {str(name).lower() for name in targets}
    found = set()
    try:
        k32 = ctypes.windll.kernel32
        snap = k32.CreateToolhelp32Snapshot(0x00000002, 0)
        if snap == -1 or not snap:
            return found
        try:
            entry = _PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
            if not k32.Process32FirstW(snap, ctypes.byref(entry)):
                return found
            while True:
                if entry.szExeFile.lower() in wanted:
                    found.add(int(entry.th32ProcessID))
                if not k32.Process32NextW(snap, ctypes.byref(entry)):
                    break
        finally:
            k32.CloseHandle(snap)
    except Exception:
        pass
    return found


_VALORANT_PROCS = {"valorant.exe", "valorant-win64-shipping.exe"}
_RIOT_PROCS = {"riotclientservices.exe", "riotclientux.exe",
               "riotclientuxrender.exe", "riotclientcrashhandler.exe"}

# Riot can briefly show an authenticated-looking error modal after a submit.
# Keep this retry budget local to one login request so a flaky client cannot
# create an unbounded sign-out/sign-in loop.
_RIOT_POPUP_MAX_ATTEMPTS = 3
_RIOT_POPUP_RESULT_TIMEOUT = 45.0

# Opt-in, credential-free performance diagnostics. Milestone names and elapsed
# durations are logged; account identifiers and credential properties are not.
_LOGIN_TIMING_ENABLED = (os.getenv("VORTEX_LOGIN_TIMING") or "").strip().lower() in {
    "1", "true", "yes", "on",
}
_LOGIN_TIMING_LOCAL = threading.local()
_LOGIN_UI_SCAN_LOCAL = threading.local()
_LOGIN_TIMING_LOCK = threading.Lock()
_LAST_LOGIN_FINISHED_MONOTONIC = 0.0


def _timing_begin() -> None:
    previous = _LAST_LOGIN_FINISHED_MONOTONIC
    now = time.perf_counter()
    _LOGIN_TIMING_LOCAL.trace = {
        "started": now, "last": now, "previous": previous, "marks": set(),
    }
    if _LOGIN_TIMING_ENABLED:
        login_logger.info("timing milestone=attempt_started elapsed_ms=0.0 delta_ms=0.0")


def _timing_mark(milestone: str) -> None:
    if not _LOGIN_TIMING_ENABLED:
        return
    trace = getattr(_LOGIN_TIMING_LOCAL, "trace", None)
    if trace is None:
        _timing_begin()
        trace = _LOGIN_TIMING_LOCAL.trace
    if milestone in trace["marks"]:
        return
    trace["marks"].add(milestone)
    now = time.perf_counter()
    elapsed = (now - trace["started"]) * 1000.0
    delta = (now - trace["last"]) * 1000.0
    trace["last"] = now
    previous = trace.get("previous") or 0.0
    batch = f" batch_transition_ms={(now - previous) * 1000.0:.1f}" if previous else ""
    login_logger.info(
        "timing milestone=%s elapsed_ms=%.1f delta_ms=%.1f%s",
        milestone, elapsed, delta, batch,
    )


def _timing_finish() -> None:
    global _LAST_LOGIN_FINISHED_MONOTONIC
    with _LOGIN_TIMING_LOCK:
        _LAST_LOGIN_FINISHED_MONOTONIC = time.perf_counter()


def is_valorant_running() -> bool:
    """Checks if VALORANT is currently running (ultra-fast Win32 check)."""
    targets = {"valorant.exe", "valorant-win64-shipping.exe"}
    try:
        return _is_process_running_fast(targets)
    except Exception:
        pass
    try:
        output = subprocess.check_output(
            ["tasklist", "/FI", "IMAGENAME eq VALORANT.exe", "/NH"],
            shell=False,
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=1.0
        )
        return "VALORANT.exe" in output
    except Exception:
        return False


def is_valorant_foreground() -> bool:
    """True only when VALORANT owns the foreground window.

    Used to gate the Live Aim HUD: it should be on screen only while the
    player is actually in the game, not while they are alt-tabbed to a
    browser, Discord, or the Vortex window itself. Any failure is treated as
    "not foreground" so the HUD errs toward hidden.
    """
    if os.name != "nt":
        return False
    try:
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return False
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if not pid:
            return False
        # PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        runtime_audit.process_open(0x1000, f"pid={pid}", "read foreground process image name")
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            buf = ctypes.create_unicode_buffer(260)
            size = ctypes.c_uint32(260)
            if ctypes.windll.kernel32.QueryFullProcessImageNameW(
                handle, 0, buf, ctypes.byref(size)
            ):
                name = os.path.basename(buf.value).lower()
                return name in _VALORANT_PROCS
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    except Exception:
        pass
    return False


# Live per-session login progress, polled by the frontend to drive the
# "logging into Riot Client" animation. Single active login at a time.
LOGIN_PROGRESS: Dict[str, Any] = {
    "active": False,
    "username": "",
    "stage": "idle",   # idle | opening | signout | waiting_window | typing | submitted | done | error
    "message": "",
    "started_at": 0.0,
    "stage_at": 0.0,   # when the current stage was entered - drives the watchdog
    "attempt": 0,
    "can_retry": False,
    # Set when a login failed specifically because the Riot Client is running
    # elevated and Vortex is not. The UI turns this into a "Restart as
    # administrator" action instead of a plain retry.
    "needs_elevation": False,
}
_LOGIN_PROGRESS_CONDITION = threading.Condition()
_LOGIN_PROGRESS_REVISION = 0

# A login that hangs - a wedged UI Automation call, a Riot Client that never
# answers - used to leave the progress modal spinning with no error and no way
# back. The watchdog below forces it to an error if a single stage stalls or
# the whole attempt runs long.
_LOGIN_STAGE_STALL_LIMIT = 100.0
_LOGIN_HARD_LIMIT = 210.0

# Starting a login tears down both VALORANT and the Riot Client.  Two clicks
# arriving together must never run that sequence concurrently, otherwise each
# worker can close the window the other worker is trying to fill.
_LOGIN_START_LOCK = threading.Lock()
_LOGIN_CANCEL_EVENT = threading.Event()


def _set_login_stage(stage: str, message: str, username: Optional[str] = None) -> None:
    global _LOGIN_PROGRESS_REVISION
    terminal = stage in ("done", "error", "idle")
    if terminal:
        login_logger.info("[%s] login cleanup starting for terminal stage=%s", username or LOGIN_PROGRESS.get("username", ""), stage)
    LOGIN_PROGRESS["stage"] = stage
    LOGIN_PROGRESS["message"] = message
    LOGIN_PROGRESS["stage_at"] = time.time()
    if username is not None:
        LOGIN_PROGRESS["username"] = username
    if stage in ("opening", "signout"):
        LOGIN_PROGRESS["active"] = True
    if terminal:
        LOGIN_PROGRESS["active"] = False
    LOGIN_PROGRESS["can_retry"] = (stage == "error")
    if stage != "error":
        # Only an elevation-block error keeps this set; anything else clears it.
        LOGIN_PROGRESS["needs_elevation"] = False

    # Every stage transition is logged so a failure can be diagnosed after
    # the fact - the UI only ever shows the last message, this keeps the
    # full sequence that led up to it.
    level = logging.ERROR if stage == "error" else logging.INFO
    elapsed = time.time() - float(LOGIN_PROGRESS.get("started_at") or time.time())
    login_logger.log(
        level, "[%s] stage=%s elapsed=%.2fs msg=%s",
        LOGIN_PROGRESS.get("username", ""), stage, elapsed, message,
    )
    if terminal:
        login_logger.info("[%s] login cleanup complete; state reset and next attempt allowed",
                          LOGIN_PROGRESS.get("username", ""))
        if stage == "done":
            _timing_mark("login_result_observed")
            _timing_finish()
    with _LOGIN_PROGRESS_CONDITION:
        _LOGIN_PROGRESS_REVISION += 1
        _LOGIN_PROGRESS_CONDITION.notify_all()


def wait_for_login_progress_change(revision: int, timeout: float = 1.0):
    """Block until a login stage changes, returning ``(revision, snapshot)``."""
    with _LOGIN_PROGRESS_CONDITION:
        if _LOGIN_PROGRESS_REVISION == revision:
            _LOGIN_PROGRESS_CONDITION.wait(timeout=max(0.0, timeout))
        return _LOGIN_PROGRESS_REVISION, dict(LOGIN_PROGRESS)


def cancel_active_login(message: str = "Verification cancelled.") -> None:
    """Stop the active automation worker at its next safe checkpoint."""
    _LOGIN_CANCEL_EVENT.set()
    if LOGIN_PROGRESS.get("active"):
        _set_login_stage("error", message, LOGIN_PROGRESS.get("username") or None)


def _elevation_blocked_login(username: Optional[str] = None) -> bool:
    """
    Call this when a login has failed to see or focus the Riot Client window.
    If the reason is that the Riot Client is elevated and Vortex is not, set a
    dedicated error + the needs_elevation flag and return True. Otherwise
    return False and let the caller report its own error.
    """
    try:
        if not elevation.riot_client_is_elevated():
            return False
    except Exception:
        return False
    _set_login_stage(
        "error",
        "The Riot Client is running as administrator, so Windows won't let "
        "Vortex fill its login window. Restart Vortex as administrator to continue.",
        username,
    )
    LOGIN_PROGRESS["needs_elevation"] = True
    login_logger.warning("[%s] login blocked - Riot Client is elevated, Vortex is not", username or "")
    return True

# Riot writes the persisted-login blob here when "Stay signed in" was ticked.
# `riot-login.persist` stays null when it wasn't - which is the only way to
# tell after the fact whether the checkbox actually took.
PRIVATE_SETTINGS_PATH = os.path.join(
    os.getenv("LOCALAPPDATA") or os.path.expanduser("~"),
    "Riot Games", "Riot Client", "Data", "RiotGamesPrivateSettings.yaml"
)


def _uia():
    """
    The UI Automation module, or None where it isn't usable.

    Imported lazily and never at module scope: it pulls in comtypes, which
    initialises COM on import, and a failure to load it must degrade the
    login to "no checkbox" rather than taking the whole launcher down.
    """
    try:
        # comtypes writes generated typelib wrappers next to its own package.
        # That path is read-only inside a frozen build, so it's told to work
        # in memory instead and use the wrappers collected at build time.
        if getattr(sys, "frozen", False):
            try:
                import comtypes.client
                comtypes.client.gen_dir = None
            except Exception:
                pass
        import uiautomation
        return uiautomation
    except Exception as e:
        login_logger.warning("UI Automation unavailable: %s", e)
        return None


def _drop_stale_uia_client() -> None:
    """
    Make UI Automation rebuild its COM client on the calling thread.

    uiautomation keeps one process-wide IUIAutomation object, created in the
    COM apartment of whichever thread first needs it. comtypes gives every
    thread its own single-threaded apartment, so once that object exists on
    one thread, a call into it from another thread has to marshal back - and
    if that first thread has since exited or parked (a returned request-pool
    worker), the marshalled call never returns and the login hangs with no
    error at all.

    Every login funnels all of its UIA work onto one worker thread; calling
    this at the top of that worker means it builds its own client instead of
    inheriting one pinned to a thread from a previous login.
    """
    try:
        import uiautomation
        uiautomation.uiautomation._AutomationClient._instance = None
    except Exception:
        pass


class _ScopedUiChangeListener:
    """Process-scoped WinEvent wakeup for Riot UI structure/state changes.

    UIA's Python wrapper does not expose automation event registration. Native
    WinEvent hooks provide the equivalent create/show/hide/reorder/focus/state
    signals from the one Riot window process without subscribing to the whole
    desktop. Out-of-context callbacks are pumped on the login worker's COM/UI
    thread and every hook is removed by ``close``/the context manager.
    """

    _EVENT_OBJECT_CREATE = 0x8000
    _EVENT_OBJECT_STATECHANGE = 0x800A
    _WINEVENT_OUTOFCONTEXT = 0x0000
    _WINEVENT_SKIPOWNPROCESS = 0x0002
    _QS_ALLINPUT = 0x04FF
    _WAIT_OBJECT_0 = 0

    def __init__(self, hwnd: Optional[int]):
        self.hwnd = hwnd
        self.event = threading.Event()
        self.hook = None
        self._callback = None
        if os.name != "nt" or not hwnd:
            return
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if not pid:
                return
            callback_type = ctypes.WINFUNCTYPE(
                None,
                wintypes.HANDLE, wintypes.DWORD, wintypes.HWND,
                wintypes.LONG, wintypes.LONG, wintypes.DWORD, wintypes.DWORD,
            )

            def _wake(_hook, _event, _event_hwnd, _object_id, _child_id, _thread, _time):
                self.event.set()

            self._callback = callback_type(_wake)
            user32 = ctypes.windll.user32
            # ctypes otherwise assumes a 32-bit integer return value and can
            # truncate HWINEVENTHOOK on 64-bit Windows, leaking a hook that
            # UnhookWinEvent can no longer identify.
            user32.SetWinEventHook.argtypes = [
                wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE, callback_type,
                wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
            ]
            user32.SetWinEventHook.restype = wintypes.HANDLE
            user32.UnhookWinEvent.argtypes = [wintypes.HANDLE]
            user32.UnhookWinEvent.restype = wintypes.BOOL
            self.hook = user32.SetWinEventHook(
                self._EVENT_OBJECT_CREATE,
                self._EVENT_OBJECT_STATECHANGE,
                None,
                self._callback,
                int(pid),
                0,
                self._WINEVENT_OUTOFCONTEXT | self._WINEVENT_SKIPOWNPROCESS,
            )
        except Exception:
            self.hook = None

    @property
    def available(self) -> bool:
        return bool(self.hook)

    def poll(self, clear: bool = False) -> bool:
        try:
            win32gui.PumpWaitingMessages()
        except Exception:
            pass
        changed = self.event.is_set()
        if changed and clear:
            self.event.clear()
        return changed

    def wait(self, timeout: float, cancel_event: Optional[threading.Event] = None) -> bool:
        """Wait for a scoped event while remaining cancellation-responsive."""
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            if self.poll():
                self.event.clear()
                return True
            if cancel_event is not None and cancel_event.is_set():
                return False
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            wait_slice = min(remaining, 0.05)
            if not self.available:
                if cancel_event is not None:
                    cancel_event.wait(wait_slice)
                else:
                    time.sleep(wait_slice)
                continue
            try:
                ctypes.windll.user32.MsgWaitForMultipleObjects(
                    0, None, False, max(1, int(wait_slice * 1000)), self._QS_ALLINPUT
                )
            except Exception:
                time.sleep(wait_slice)

    def close(self) -> None:
        hook, self.hook = self.hook, None
        if hook:
            try:
                ctypes.windll.user32.UnhookWinEvent(hook)
            except Exception:
                pass
        self._callback = None

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        self.close()


def _login_watchdog() -> None:
    """
    Forces a stuck login to an error so the progress modal can never spin
    forever. A stage that hasn't advanced in _LOGIN_STAGE_STALL_LIMIT seconds,
    or a whole attempt past _LOGIN_HARD_LIMIT, is treated as dead.
    """
    while True:
        time.sleep(5.0)
        try:
            p = LOGIN_PROGRESS
            if not p.get("active") or p.get("stage") in ("done", "error", "idle"):
                continue
            now = time.time()
            started = float(p.get("started_at") or 0.0)
            stage_at = float(p.get("stage_at") or started)
            if now - stage_at > _LOGIN_STAGE_STALL_LIMIT or now - started > _LOGIN_HARD_LIMIT:
                login_logger.error(
                    "[%s] login watchdog - stuck in stage=%s for %.0fs, forcing error",
                    p.get("username", ""), p.get("stage"), now - stage_at,
                )
                _set_login_stage(
                    "error",
                    "Login timed out - the Riot Client stopped responding. Try again.",
                    p.get("username") or None,
                )
        except Exception:
            login_logger.exception("login watchdog iteration failed")


threading.Thread(target=_login_watchdog, name="vortex-login-watchdog", daemon=True).start()


def set_stay_signed_in(hwnd: int, window=None, checkbox=None,
                       password_field=None) -> Optional[bool]:
    """
    Ticks the Riot Client's "Stay signed in" checkbox, and puts keyboard focus
    back on the password field afterwards.

    Uses UI Automation to address the checkbox directly rather than counting
    Tab presses to reach it. The login form's tab order runs

        password -> Facebook -> Google -> Apple -> Xbox -> PlayStation
                 -> Stay signed in -> submit

    so every keyboard-based attempt at this has been a guess at how many
    social buttons are rendered, and landing one short means Space activates
    a social sign-in button and derails the login entirely. That is what the
    tab-walking versions were doing. The checkbox exposes a Toggle pattern,
    so it can just be found by name and set - no keystrokes, no mouse, and
    the current state is readable, so an already-ticked box is left alone
    instead of being toggled back off.

    Returns True if it ended up ticked, False if it couldn't be, None when UI
    Automation isn't available at all. Never raises.
    """
    auto = _uia()
    if auto is None or not hwnd:
        login_logger.info("stay-signed-in: UI Automation unavailable, skipping the checkbox")
        return None

    try:
        auto.SetGlobalSearchTimeout(0.25)
        window = window or auto.ControlFromHandle(hwnd)
        if not window:
            return None

        if checkbox is None:
            snapshot = ClientLauncher._scan_login_controls(window)
            checkbox = snapshot.get("stay_signed_in")
        if checkbox is None:
            login_logger.warning("stay-signed-in: checkbox not found in the login form")
            return False

        toggle = checkbox.GetTogglePattern()
        if toggle is None:
            return False

        # ToggleState: 0 off, 1 on, 2 indeterminate. Toggle() flips, so an
        # already-ticked box must be left alone or it comes back off.
        if toggle.ToggleState != 1:
            toggle.Toggle()
        ticked = checkbox.GetTogglePattern().ToggleState == 1
        # TogglePattern normally updates synchronously. If a Riot build delays
        # it, observe the actual state for a short bound instead of sleeping a
        # fixed amount on every successful normal-path toggle.
        deadline = time.monotonic() + 0.4
        while not ticked and time.monotonic() < deadline:
            if _LOGIN_CANCEL_EVENT.wait(0.02):
                return False
            ticked = checkbox.GetTogglePattern().ToggleState == 1

        login_logger.info("stay-signed-in: checkbox ticked=%s", ticked)
        return ticked
    except Exception as e:
        login_logger.warning("stay-signed-in: could not set the checkbox: %s", e)
        return False


def is_session_persisted() -> Optional[bool]:
    """
    True when Riot has a persisted login stored ("Stay signed in" is on),
    False when it doesn't, None when the file can't be read.

    Deliberately a dumb line scan rather than a YAML parse: the file holds
    auth cookies, this only ever needs to know whether one key is null, and
    adding a YAML dependency to read one boolean isn't worth it.
    """
    try:
        with open(PRIVATE_SETTINGS_PATH, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.read().splitlines()
    except OSError:
        return None

    in_section = False
    for i, raw in enumerate(lines):
        if not raw.strip():
            continue
        indent = len(raw) - len(raw.lstrip())
        stripped = raw.strip()
        if indent == 0:
            in_section = stripped.startswith("riot-login:")
            continue
        if not (in_section and stripped.startswith("persist:")):
            continue

        inline = stripped.split(":", 1)[1].strip().lower()
        if inline:
            return inline not in ("null", "~", "{}", "[]")

        # "persist:" with nothing after it is a block header, not an empty
        # value - the session is stored in the indented lines below it. Reading
        # the empty inline value as "off" would make every login re-tick the
        # checkbox and so untick one that was already on.
        for nxt in lines[i + 1:]:
            if not nxt.strip():
                continue
            return (len(nxt) - len(nxt.lstrip())) > indent
        return False
    return False


DEFAULT_VALORANT_PATHS = [
    r"C:\Riot Games\Riot Client\RiotClientServices.exe",
    r"D:\Riot Games\Riot Client\RiotClientServices.exe",
    r"E:\Riot Games\Riot Client\RiotClientServices.exe",
    r"F:\Riot Games\Riot Client\RiotClientServices.exe",
    r"C:\Program Files\Riot Client\RiotClientServices.exe",
    r"C:\Program Files (x86)\Riot Client\RiotClientServices.exe",
]

TIER_NAMES = [
    "UNRANKED", "Unused1", "Unused2",
    "IRON 1", "IRON 2", "IRON 3",
    "BRONZE 1", "BRONZE 2", "BRONZE 3",
    "SILVER 1", "SILVER 2", "SILVER 3",
    "GOLD 1", "GOLD 2", "GOLD 3",
    "PLATINUM 1", "PLATINUM 2", "PLATINUM 3",
    "DIAMOND 1", "DIAMOND 2", "DIAMOND 3",
    "ASCENDANT 1", "ASCENDANT 2", "ASCENDANT 3",
    "IMMORTAL 1", "IMMORTAL 2", "IMMORTAL 3",
    "RADIANT"
]

TIER_BASE_URL = "https://media.valorant-api.com/competitivetiers/03621f52-342b-cf4e-4f86-9350a49c6d04"


def _normalise_ui_text(value: Any) -> str:
    """Collapse UIA whitespace/case differences for text matching."""
    return " ".join(re.sub(r"\s+", " ", str(value or "")).strip().lower().split())


def _iter_uia_descendants(root):
    """Yield a UIA control tree without assuming a specific Riot control type."""
    pending = [root]
    while pending:
        control = pending.pop()
        yield control
        try:
            pending.extend(reversed(control.GetChildren() or []))
        except Exception:
            continue


class ClientLauncher:
    _last_riot_hwnd: Optional[int] = None
    _last_riot_pid: Optional[int] = None
    _cached_riot_client_path: Optional[str] = None

    @classmethod
    def detect_riot_client_path(cls) -> Optional[str]:
        """Find Riot once, reusing only the static executable path across a batch."""
        cached = cls._cached_riot_client_path
        if cached and os.path.exists(cached):
            return cached
        cls._cached_riot_client_path = None
        for path in DEFAULT_VALORANT_PATHS:
            if os.path.exists(path):
                cls._cached_riot_client_path = path
                return path

        registry_keys = [
            (winreg.HKEY_CURRENT_USER, r"Software\Riot Games\Riot Client", "RiotClientPath"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Riot Games, Inc\Riot Client", "RiotClientPath"),
            (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall\Riot Game valorant.live", "InstallLocation")
        ]

        for hkey, subkey, val_name in registry_keys:
            try:
                with winreg.OpenKey(hkey, subkey) as key:
                    val, _ = winreg.QueryValueEx(key, val_name)
                    if val and os.path.exists(val):
                        if os.path.isdir(val):
                            possible_exe = os.path.join(val, "RiotClientServices.exe")
                            if os.path.exists(possible_exe):
                                cls._cached_riot_client_path = possible_exe
                                return possible_exe
                        else:
                            cls._cached_riot_client_path = val
                            return val
            except Exception:
                continue

        return None

    @staticmethod
    def copy_to_clipboard(text: str) -> bool:
        """Copies text to the system clipboard."""
        try:
            pyperclip.copy(text)
            return True
        except Exception:
            return False

    @staticmethod
    def get_lockfile_auth() -> Optional[Tuple[int, str]]:
        """Reads port and password from Riot Client lockfile."""
        try:
            local_appdata = os.getenv("LOCALAPPDATA")
            if not local_appdata:
                return None
            lockfile_path = os.path.join(local_appdata, "Riot Games", "Riot Client", "Config", "lockfile")
            if os.path.exists(lockfile_path):
                with open(lockfile_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read().strip()
                parts = content.split(":")
                if len(parts) >= 5:
                    port = int(parts[2])
                    password = parts[3]
                    return port, password
        except Exception:
            pass
        return None

    @classmethod
    def get_active_riot_session(cls, expected_username: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Return only the inexpensive, local identity for the signed-in user.

        Live-match polling used to call :meth:`get_active_riot_account`, which
        also performs remote account-XP and MMR requests.  Doing that every
        second added latency and network load unrelated to the live score.
        This lightweight variant reads the local Riot Client only; callers
        that are explicitly syncing rank data should keep using the full
        method below.
        """
        auth_info = cls.get_lockfile_auth()
        if not auth_info:
            return None

        port, password = auth_info
        auth = ("riot", password)
        result: Dict[str, Any] = {
            "found": False,
            "username": "",
            "display_name": "",
            # No default guess here on purpose. This runs on every ~1s live
            # poll including the moment right after a Riot Client restart,
            # when userinfo/chat can still be empty - a wrong "NA" written
            # from a bare fallback sticks forever, because a stored region
            # always wins over a later, better live read. Blank is honest
            # about "not known yet" and is what account_needs_check() looks
            # for to get it corrected on the next real sync.
            "region": "",
            "status": "PLAYABLE",
            "puuid": "",
        }

        try:
            res = requests.get(
                f"https://127.0.0.1:{port}/rso-auth/v1/authorization/userinfo",
                auth=auth, verify=False, timeout=1.25,
            )
            if res.status_code == 200:
                raw = res.json().get("userInfo", "{}")
                info = json.loads(raw) if isinstance(raw, str) else (raw or {})
                result["username"] = info.get("username") or info.get("preferred_username", "")
                result["puuid"] = (info.get("sub") or info.get("puuid") or "").strip()

                acct = info.get("acct") or {}
                game_name = (acct.get("game_name") or "").strip()
                tag_line = (acct.get("tag_line") or "").strip()
                if game_name and tag_line:
                    result["display_name"] = f"{game_name}#{tag_line}"

                state = (acct.get("state") or "").upper()
                restrictions = ((info.get("ban") or {}).get("restrictions") or [])
                restriction_types = {(r.get("type") or "").upper() for r in restrictions}
                if state in ("BANNED", "PERMA_BANNED") or restriction_types & {"PERMANENT_BAN", "BANNED"}:
                    result["status"] = "BANNED"
                elif state in ("SUSPENDED", "TEMP_BANNED") or restriction_types & {"TEMPORARY_BAN", "SUSPENDED"}:
                    result["status"] = "SUSPENDED"

                region_id = str((info.get("region") or {}).get("id") or info.get("original_platform_id", "")).upper()
                if any(x in region_id for x in ("LA", "LAN", "LAS", "LATAM")):
                    result["region"] = "LATAM"
                elif "BR" in region_id:
                    result["region"] = "BR"
                elif any(x in region_id for x in ("EU", "TR", "RU")):
                    result["region"] = "EU"
                elif "KR" in region_id:
                    result["region"] = "KR"
                elif any(x in region_id for x in ("AP", "OC", "JP")):
                    result["region"] = "AP"
        except Exception:
            pass

        # Chat remains available during phases where userinfo is temporarily
        # sparse, and gives us the Riot ID needed to match the stored account.
        if not result["display_name"]:
            try:
                res = requests.get(
                    f"https://127.0.0.1:{port}/chat/v1/session",
                    auth=auth, verify=False, timeout=1.25,
                )
                if res.status_code == 200:
                    chat = res.json() or {}
                    game_name = (chat.get("game_name") or "").strip()
                    tag_line = (chat.get("game_tag") or "").strip()
                    if game_name and tag_line:
                        result["display_name"] = f"{game_name}#{tag_line}"
                    result["puuid"] = result["puuid"] or (chat.get("puuid") or "").strip()
                    pid = (chat.get("pid") or "").lower()
                    if any(x in pid for x in ("la1", "la2", "las")):
                        result["region"] = "LATAM"
                    elif "br" in pid:
                        result["region"] = "BR"
                    elif any(x in pid for x in ("eu", "tr")):
                        result["region"] = "EU"
                    elif "kr" in pid:
                        result["region"] = "KR"
                    elif any(x in pid for x in ("ap", "jp")):
                        result["region"] = "AP"
            except Exception:
                pass

        if not result["puuid"]:
            try:
                res = requests.get(
                    f"https://127.0.0.1:{port}/entitlements/v1/token",
                    auth=auth, verify=False, timeout=1.25,
                )
                if res.status_code == 200:
                    result["puuid"] = (res.json().get("subject") or "").strip()
            except Exception:
                pass

        if expected_username and result["username"]:
            if result["username"].strip().lower() != expected_username.strip().lower():
                return None

        result["found"] = bool(result["username"] or result["display_name"] or result["puuid"])
        return result if result["found"] else None

    @classmethod
    def get_active_riot_account(cls, expected_username: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Auto-detects the currently logged-in account's Username, Riot ID, Region,
        Level, Current Rank, Peak Rank, and Ban/Suspension Status directly from Riot Client APIs.
        If expected_username is provided, ensures the active session matches that username.
        """
        auth_info = cls.get_lockfile_auth()
        if not auth_info:
            return None

        port, password = auth_info
        auth = ("riot", password)

        result = {
            "found": False,
            "username": "",
            "display_name": "",
            "region": "NA",
            "rank_tier": "UNRANKED",
            "rank_division": "",
            "lp": 0,
            "rank_icon_url": f"{TIER_BASE_URL}/0/largeicon.png",
            "peak_rank_tier": "",
            "peak_rank_division": "",
            "peak_rank_icon_url": "",
            "status": "PLAYABLE",
            "puuid": "",
            # None is important: a client that is not in a usable party is
            # not evidence that Competitive is locked.
            "competitive_queue_eligible": None,
            "ranked_eligibility_source": ""
        }

        # 1. Parse official userinfo payload
        try:
            url_uinfo = f"https://127.0.0.1:{port}/rso-auth/v1/authorization/userinfo"
            res = requests.get(url_uinfo, auth=auth, verify=False, timeout=1.5)
            if res.status_code == 200:
                raw_json = res.json().get("userInfo", "{}")
                uinfo = json.loads(raw_json) if isinstance(raw_json, str) else raw_json

                result["username"] = uinfo.get("username") or uinfo.get("preferred_username", "")
                # Riot's stable per-account id. This is the key the account's
                # local VALORANT settings folder is named after, so capturing
                # it here is what makes crosshair/keybind copying possible.
                result["puuid"] = (uinfo.get("sub") or uinfo.get("puuid") or "").strip()
                
                # Verify expected username if supplied
                if expected_username and result["username"]:
                    if result["username"].strip().lower() != expected_username.strip().lower():
                        return None

                if result["username"]:
                    result["found"] = True

                acct = uinfo.get("acct", {})
                game_name = acct.get("game_name", "")
                tag_line = acct.get("tag_line", "")
                if game_name and tag_line:
                    result["display_name"] = f"{game_name}#{tag_line}"

                # Status parsing (Playable vs Banned vs Suspended)
                acct_state = (acct.get("state") or "").upper()
                ban_data = uinfo.get("ban", {}) or {}
                restrictions = ban_data.get("restrictions", []) or []

                if acct_state in ("BANNED", "PERMA_BANNED") or any(r.get("type") in ("PERMANENT_BAN", "BANNED") for r in restrictions):
                    result["status"] = "BANNED"
                elif acct_state in ("SUSPENDED", "TEMP_BANNED") or any(r.get("type") in ("TEMPORARY_BAN", "SUSPENDED") for r in restrictions):
                    result["status"] = "SUSPENDED"
                else:
                    result["status"] = "PLAYABLE"

                # Region parsing from official region ID
                region_id = (uinfo.get("region", {}).get("id") or uinfo.get("original_platform_id", "")).upper()
                if any(x in region_id for x in ["LA", "LAN", "LAS", "LATAM"]):
                    result["region"] = "LATAM"
                elif "BR" in region_id:
                    result["region"] = "BR"
                elif any(x in region_id for x in ["EU", "TR", "RU"]):
                    result["region"] = "EU"
                elif "KR" in region_id:
                    result["region"] = "KR"
                elif any(x in region_id for x in ["AP", "OC", "JP"]):
                    result["region"] = "AP"
                else:
                    result["region"] = "NA"
        except Exception:
            pass

        # userinfo comes back empty while the game is mid-session, but the
        # entitlements token always carries the puuid as its subject.
        if not result["puuid"]:
            try:
                url_ent = f"https://127.0.0.1:{port}/entitlements/v1/token"
                res = requests.get(url_ent, auth=auth, verify=False, timeout=1.5)
                if res.status_code == 200:
                    result["puuid"] = (res.json().get("subject") or "").strip()
            except Exception:
                pass

        # Fallback chat session for Riot ID & region if userinfo was incomplete
        if not result["display_name"]:
            try:
                url_chat = f"https://127.0.0.1:{port}/chat/v1/session"
                res = requests.get(url_chat, auth=auth, verify=False, timeout=1.5)
                if res.status_code == 200:
                    data = res.json()
                    game_name = data.get("game_name", "").strip()
                    tag_line = data.get("game_tag", "").strip()
                    pid = data.get("pid", "").lower()
                    if not result["puuid"]:
                        result["puuid"] = (data.get("puuid") or "").strip()
                    
                    if "la1" in pid or "la2" in pid or "las" in pid: result["region"] = "LATAM"
                    elif "br" in pid: result["region"] = "BR"
                    elif "eu" in pid or "tr" in pid: result["region"] = "EU"
                    elif "kr" in pid: result["region"] = "KR"
                    elif "ap" in pid or "jp" in pid: result["region"] = "AP"

                    if game_name and tag_line:
                        result["found"] = True
                        result["display_name"] = f"{game_name}#{tag_line}"
            except Exception:
                pass

        if not result["found"] and not result["username"]:
            return None

        # 2. Extract Entitlements Token for Official PVP Level & MMR sync
        try:
            url_token = f"https://127.0.0.1:{port}/entitlements/v1/token"
            r_token = requests.get(url_token, auth=auth, verify=False, timeout=1.5)
            if r_token.status_code == 200:
                tok = r_token.json()
                access_token = tok.get("accessToken")
                entitlements_token = tok.get("token")
                puuid = tok.get("subject")

                if access_token and entitlements_token and puuid:
                    headers = {
                        "Authorization": f"Bearer {access_token}",
                        "X-Riot-Entitlements-JWT": entitlements_token,
                        "X-Riot-ClientVersion": "release-08.11-shipping-9-2516482",
                        "X-Riot-ClientPlatform": "ew0KCSJwbGF0Zm9ybVR5cGUiOiAiUEMiLA0KCSJwbGF0Zm9ybU9TIjogIldpbmRvd3MiLA0KCSJwbGF0Zm9ybU9TVmVyc2lvbiI6ICIxMC4wLjE5MDQyLjEuMjU2LjY0Yml0IiwNCgkicGxhdGZvcm1DaGlwc2V0IjogIlVua25vd24iDQp9"
                    }

                    # PVP routing
                    region_sub = result["region"].lower()
                    if region_sub in ("latam", "br"): region_sub = "na"

                    # Fetch Official Level from Account-XP.
                    # Only set "level" when we actually got a real value back -
                    # leaving the key absent tells callers "no data this time"
                    # so they don't overwrite a good stored level. Defaulting
                    # to 1 here is indistinguishable from a real level-1
                    # account and would wipe the stored level on any failure.
                    url_xp = f"https://pd.{region_sub}.a.pvp.net/account-xp/v1/players/{puuid}"
                    r_xp = requests.get(url_xp, headers=headers, timeout=2.0)
                    if r_xp.status_code == 200:
                        xp_data = r_xp.json()
                        xp_level = (xp_data.get("Progress") or {}).get("Level")
                        if isinstance(xp_level, int) and xp_level > 0:
                            result["level"] = xp_level

                    # Fetch MMR & Peak Rank from Official MMR API
                    url_mmr = f"https://pd.{region_sub}.a.pvp.net/mmr/v1/players/{puuid}"
                    r_mmr = requests.get(url_mmr, headers=headers, timeout=2.0)
                    if r_mmr.status_code == 200:
                        mmr_data = r_mmr.json()
                        latest_update = mmr_data.get("LatestCompetitiveUpdate", {})
                        curr_tier_num = latest_update.get("TierAfterUpdate", 0)
                        result["lp"] = latest_update.get("RankedRatingAfterUpdate", 0)

                        if curr_tier_num and curr_tier_num < len(TIER_NAMES):
                            full_name = TIER_NAMES[curr_tier_num]
                            parts = full_name.split()
                            result["rank_tier"] = parts[0]
                            if len(parts) > 1: result["rank_division"] = parts[1]
                            result["rank_icon_url"] = f"{TIER_BASE_URL}/{curr_tier_num}/largeicon.png"

                        # Calculate All-Time Peak Tier from seasonal history
                        queue_skills = mmr_data.get("QueueSkills", {}).get("competitive", {})
                        seasonal = queue_skills.get("SeasonalInfoBySeasonID") or {}
                        peak_tier_num = 0
                        for _, s_info in seasonal.items():
                            t = s_info.get("CompetitiveTier", 0)
                            if t > peak_tier_num:
                                peak_tier_num = t

                        if peak_tier_num > 0 and peak_tier_num < len(TIER_NAMES):
                            p_name = TIER_NAMES[peak_tier_num]
                            p_parts = p_name.split()
                            result["peak_rank_tier"] = p_parts[0]
                            if len(p_parts) > 1: result["peak_rank_division"] = p_parts[1]
                            result["peak_rank_icon_url"] = f"{TIER_BASE_URL}/{peak_tier_num}/largeicon.png"
        except Exception:
            pass

        # Riot's eligible-queues party response is an actual matchmaking
        # capability signal.  In particular it can identify a grandfathered
        # sub-level-20 account without making an age/Beta-era guess.  This is
        # read-only and intentionally best-effort: no party/API response must
        # remain unknown rather than being stored as "not eligible".
        if result["found"]:
            try:
                from backend.valorant_client import ValorantLiveClient
                live_client = ValorantLiveClient()
                if live_client.connect() and live_client.puuid == result.get("puuid"):
                    eligible_queues = live_client.eligible_queue_ids()
                    if eligible_queues is not None:
                        result["competitive_queue_eligible"] = "competitive" in eligible_queues
                        result["ranked_eligibility_source"] = "party_eligible_queues"
            except Exception as exc:
                login_logger.debug("competitive eligibility unavailable: %s", exc)

        return result

    @classmethod
    def check_login_error(cls) -> Optional[str]:
        """
        Checks if Riot Client encountered an auth/credential error.
        """
        auth_info = cls.get_lockfile_auth()
        if not auth_info:
            return None

        port, password = auth_info
        auth = ("riot", password)

        try:
            url = f"https://127.0.0.1:{port}/rso-auth/v1/authorization"
            res = requests.get(url, auth=auth, verify=False, timeout=1.0)
            if res.status_code == 200:
                data = res.json()
                err = data.get("error") or data.get("type")
                if err in ("auth_failure", "invalid_credentials", "login_error"):
                    return str(err)
        except Exception:
            pass
        return None

    @classmethod
    def api_sign_out(cls) -> bool:
        """
        Signs out active account instantly using Riot Client's internal REST API.
        """
        auth_info = cls.get_lockfile_auth()
        if not auth_info:
            return False

        port, password = auth_info
        url = f"https://127.0.0.1:{port}/rso-auth/v1/session"
        try:
            runtime_audit.riot_api("GET", f"https://127.0.0.1:{port}/rso-auth/v1/session", "local Riot Client API - session check")
            res = requests.get(url, auth=("riot", password), verify=False, timeout=1.0)
            if res.status_code == 200 and res.json().get("type") == "authenticated":
                runtime_audit.riot_api("DELETE", f"https://127.0.0.1:{port}/rso-auth/v1/session", "local Riot Client API - sign out")
                runtime_audit.process_terminate("Riot session", "local Riot Client REST API", "sign out active account")
                del_res = requests.delete(url, auth=("riot", password), verify=False, timeout=1.5)
                return del_res.status_code in (200, 204)
        except Exception:
            pass
        return False

    @classmethod
    def find_riot_window(cls) -> Optional[int]:
        """Find the main Riot HWND, preferring the known/cached process window."""
        candidates = []

        def valid(hwnd, riot_pids=None):
            try:
                if not hwnd or not win32gui.IsWindow(hwnd) or not win32gui.IsWindowVisible(hwnd):
                    return False
                if "riot client" not in _normalise_ui_text(win32gui.GetWindowText(hwnd)):
                    return False
                rect = win32gui.GetWindowRect(hwnd)
                if (rect[2] - rect[0]) < 300 or (rect[3] - rect[1]) < 200:
                    return False
                if riot_pids is not None:
                    _, pid = win32process.GetWindowThreadProcessId(hwnd)
                    if pid not in riot_pids:
                        return False
                return True
            except Exception:
                return False

        # The normal path never enumerates the desktop: keep using the HWND
        # until Riot destroys/replaces it, then try its exact titles.
        if valid(cls._last_riot_hwnd):
            try:
                _, current_pid = win32process.GetWindowThreadProcessId(cls._last_riot_hwnd)
            except Exception:
                current_pid = None
            if cls._last_riot_pid is not None and current_pid == cls._last_riot_pid:
                return cls._last_riot_hwnd
        cls._last_riot_hwnd = None
        cls._last_riot_pid = None

        riot_pids = _running_process_ids(_RIOT_PROCS)
        for title in ("Riot Client", "Riot Client Main"):
            try:
                hwnd = win32gui.FindWindow(None, title)
            except Exception:
                hwnd = None
            if valid(hwnd, riot_pids):
                cls._last_riot_hwnd = hwnd
                _, cls._last_riot_pid = win32process.GetWindowThreadProcessId(hwnd)
                return hwnd

        def enum_cb(hwnd, _):
            try:
                if valid(hwnd, riot_pids):
                    rect = win32gui.GetWindowRect(hwnd)
                    candidates.append(((rect[2] - rect[0]) * (rect[3] - rect[1]), hwnd))
            except Exception:
                pass
            return True

        try:
            win32gui.EnumWindows(enum_cb, None)
            if candidates:
                # Sort by window area descending so the largest visible main window is preferred
                candidates.sort(reverse=True)
                cls._last_riot_hwnd = candidates[0][1]
                _, cls._last_riot_pid = win32process.GetWindowThreadProcessId(
                    cls._last_riot_hwnd
                )
                return cls._last_riot_hwnd
        except Exception:
            pass
        cls._last_riot_hwnd = None
        cls._last_riot_pid = None
        return None

    @staticmethod
    def focus_window(hwnd: int) -> bool:
        """
        Brings Riot Client to foreground reliably without sending
        defocusing keystrokes like Alt.
        """
        try:
            if not hwnd or not win32gui.IsWindow(hwnd):
                return False

            runtime_audit.window_automation(
                "ShowWindow + AttachThreadInput + SetForegroundWindow", "Riot Client"
            )
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            else:
                win32gui.ShowWindow(hwnd, win32con.SW_SHOW)

            try:
                ctypes.windll.user32.AllowSetForegroundWindow(-1)
            except Exception:
                pass

            fg_hwnd = win32gui.GetForegroundWindow()
            if fg_hwnd != hwnd:
                target_thread = win32process.GetWindowThreadProcessId(hwnd)[0]
                current_thread = win32api.GetCurrentThreadId()
                fg_thread = win32process.GetWindowThreadProcessId(fg_hwnd)[0] if fg_hwnd else 0

                attached_fg = False
                attached_self = False
                try:
                    if fg_thread and fg_thread != target_thread:
                        win32process.AttachThreadInput(fg_thread, target_thread, True)
                        attached_fg = True
                    if current_thread != target_thread:
                        win32process.AttachThreadInput(current_thread, target_thread, True)
                        attached_self = True

                    # Elevate z-order using TOPMOST toggle
                    win32gui.SetWindowPos(
                        hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                        win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW
                    )
                    win32gui.SetWindowPos(
                        hwnd, win32con.HWND_NOTOPMOST, 0, 0, 0, 0,
                        win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW
                    )
                    win32gui.BringWindowToTop(hwnd)
                    win32gui.SetForegroundWindow(hwnd)
                finally:
                    if attached_fg:
                        try:
                            win32process.AttachThreadInput(fg_thread, target_thread, False)
                        except Exception:
                            pass
                    if attached_self:
                        try:
                            win32process.AttachThreadInput(current_thread, target_thread, False)
                        except Exception:
                            pass

            return True
        except Exception as e:
            login_logger.warning("focus_window failed: %s", e)
            return False

    @classmethod
    def read_login_ui_state(cls, hwnd: Optional[int] = None):
        """Return popup and validation state from one scoped UIA traversal."""
        auto = _uia()
        if auto is None:
            return None, None
        try:
            hwnd = hwnd or cls.find_riot_window()
            if not hwnd:
                return None, None
            snapshot = cls._snapshot_for_hwnd(hwnd, auto)
            return snapshot.get("popup_sign_out"), snapshot.get("validation_error")
        except Exception as exc:
            login_logger.debug("login state detection failed: %s", exc)
            return None, None

    @classmethod
    def find_transient_login_popup(cls, hwnd: Optional[int] = None):
        """Return the Riot ``Sign out`` button for the transient login modal.

        The modal is identified by both its failure copy and its Sign out
        action. That keeps a generic Riot button, or a normal signed-in client,
        from triggering account recovery.
        """
        popup, _ = cls.read_login_ui_state(hwnd)
        return popup

    @classmethod
    def find_login_validation_error(cls, hwnd: Optional[int] = None) -> Optional[str]:
        """Return known client-side form validation copy without reading credentials."""
        _, validation_error = cls.read_login_ui_state(hwnd)
        return validation_error

    @classmethod
    def click_transient_login_sign_out(cls, hwnd: Optional[int] = None, button=None) -> bool:
        """Click the detected modal action through UI Automation."""
        button = button or cls.find_transient_login_popup(hwnd)
        if button is None:
            return False
        try:
            invoke = button.GetInvokePattern()
            if invoke is not None:
                invoke.Invoke()
            else:
                button.Click()
            return True
        except Exception as exc:
            try:
                button.Click()
                return True
            except Exception:
                login_logger.warning("could not click Riot transient login Sign out: %s", exc)
                return False

    @classmethod
    def wait_for_transient_login_popup_gone(cls, timeout: float = 8.0) -> bool:
        """Wait until the detected modal is no longer present."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if _LOGIN_CANCEL_EVENT.is_set():
                return False
            popup, _ = cls.read_login_ui_state()
            if popup is None:
                return True
            _LOGIN_CANCEL_EVENT.wait(0.1)
        popup, _ = cls.read_login_ui_state()
        return popup is None

    @classmethod
    def _monitor_login_result(cls, username: str, password: str,
                              stay_signed_in: bool, client_path: Optional[str] = None,
                              timeout: float = _RIOT_POPUP_RESULT_TIMEOUT) -> Optional[bool]:
        """Watch the submitted login for success, auth errors, or Riot's modal.

        This runs on the same worker that filled the form, which is important
        for UI Automation's single-threaded COM apartment. On the transient
        popup path it signs out, waits for a fresh form, and calls the existing
        fill routine again for the same account.
        """
        deadline = time.monotonic() + timeout
        popup_attempt = 1

        while time.monotonic() < deadline:
            if _LOGIN_CANCEL_EVENT.is_set():
                return False
            session = cls.get_active_riot_session(username)
            session_user = (session.get("username") or "").strip().lower() if session else ""
            if session and session.get("found") and session_user == username.strip().lower():
                _set_login_stage(
                    "done",
                    f"Signed in as {session.get('display_name') or username}.",
                    username,
                )
                return True

            popup_button, validation_error = cls.read_login_ui_state()
            if popup_button is not None:
                login_logger.warning("[%s] Riot transient login popup detected", username)
                if popup_attempt >= _RIOT_POPUP_MAX_ATTEMPTS:
                    message = f"Riot login temporarily unavailable after {_RIOT_POPUP_MAX_ATTEMPTS} attempts."
                    login_logger.error("[%s] Riot transient login failure persisted after %d attempts", username, popup_attempt)
                    _set_login_stage("error", message, username)
                    return False

                _set_login_stage("signout", "Riot login failed temporarily - signing out...", username)
                login_logger.info("[%s] Clicking Sign out", username)
                if not cls.click_transient_login_sign_out(button=popup_button):
                    _set_login_stage(
                        "error", "Riot's transient login failure could not be cleared.", username
                    )
                    return False
                if not cls.wait_for_transient_login_popup_gone():
                    _set_login_stage(
                        "error", "Riot's Sign out dialog did not close.", username
                    )
                    return False
                if not cls.wait_for_signed_out(timeout=8.0):
                    _set_login_stage(
                        "error", "Riot did not clear the failed login session.", username
                    )
                    return False

                popup_attempt += 1
                login_logger.info(
                    "[%s] Waiting for Riot login screen", username
                )
                _set_login_stage(
                    "waiting_window", "Waiting for Riot login screen...", username
                )
                if cls.wait_for_login_form(timeout=20.0) is None:
                    _set_login_stage(
                        "error", "Riot did not return to the sign-in screen after Sign out.", username
                    )
                    return False

                login_logger.info(
                    "[%s] Retrying login: attempt %d/%d",
                    username, popup_attempt, _RIOT_POPUP_MAX_ATTEMPTS,
                )
                _set_login_stage(
                    "typing",
                    f"Retrying login: attempt {popup_attempt}/{_RIOT_POPUP_MAX_ATTEMPTS}...",
                    username,
                )
                result = cls._attempt_login_fill(
                    username, password, stay_signed_in, tries=3, form_timeout=20.0
                )
                if result is not True:
                    _set_login_stage(
                        "error", "Riot's sign-in form was not ready for the retry.", username
                    )
                    return False
                continue

            if validation_error:
                login_logger.warning("[%s] Riot client-side validation detected: %s", username, validation_error)
                _set_login_stage(
                    "error",
                    "Riot rejected the sign-in form. Remove unsupported characters and try again.",
                    username,
                )
                return False

            auth_error = cls.check_login_error()
            if auth_error in ("auth_failure", "invalid_credentials"):
                _set_login_stage(
                    "error", "Invalid username or password. Please check your credentials.", username
                )
                return False
            if auth_error in ("rate_limited", "login_error"):
                _set_login_stage(
                    "error", "Riot rate limit or login error. Please wait a moment and try again.", username
                )
                return False

            _LOGIN_CANCEL_EVENT.wait(0.2)

        message = "Riot did not confirm this sign-in before the attempt timed out. Please try again."
        login_logger.warning("[%s] login result monitor timed out", username)
        _set_login_stage("error", message, username)
        return False

    # ------------------------------------------------------------------
    # Verified login steps
    #
    # Every step below checks that it actually happened instead of sleeping
    # for a plausible length of time and hoping. The old flow was a chain of
    # fixed delays - wait 2.5s for the splash, wait 0.9s for the form to be
    # "interactive", type, hope - and when any one of them was short on a
    # slow machine the login failed with nothing in the log to say which.
    # ------------------------------------------------------------------

    @classmethod
    def wait_for_signed_out(cls, timeout: float = 8.0) -> bool:
        """
        Blocks until the Riot Client reports no authenticated session.

        Sign-out is a request, not an instant state change - returning as soon
        as the DELETE is accepted means the next steps can race a session that
        is still tearing down, and the client then re-renders the login form
        underneath whatever has already been typed.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            if _LOGIN_CANCEL_EVENT.is_set():
                return None
            auth = cls.get_lockfile_auth()
            if not auth:
                # No lockfile means no client session at all - signed out by
                # definition.
                return True
            port, pw = auth
            try:
                res = requests.get(
                    f"https://127.0.0.1:{port}/rso-auth/v1/session",
                    auth=("riot", pw), verify=False, timeout=1.0
                )
                if res.status_code != 200 or res.json().get("type") != "authenticated":
                    return True
            except Exception:
                return True
            time.sleep(0.25)
        return False

    @staticmethod
    def wait_for_processes_gone(names: set, timeout: float = 8.0) -> bool:
        """Blocks until none of `names` is running. Lowercase exe names."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if _LOGIN_CANCEL_EVENT.is_set():
                return False
            if not _is_process_running_fast(names):
                return True
            _LOGIN_CANCEL_EVENT.wait(0.1)
        return not _is_process_running_fast(names)

    @classmethod
    def wait_for_login_form(cls, timeout: float = 45.0):
        """
        Blocks until the Riot Client is showing the credential section, and
        returns (window, username_field, password_field) - or None on timeout.

        This is the real "the client has finished opening" signal. The old
        check watched the window rectangle until it stopped changing, which
        is satisfied by the splash screen, by a half-drawn client, and by the
        client sitting on a completely different screen. Waiting for the two
        input controls to exist and be enabled cannot be satisfied by any of
        those.

        Returns None when UI Automation isn't available, so the caller can
        fall back to the timing-based path.
        """
        auto = _uia()
        if auto is None:
            return None

        deadline = time.monotonic() + max(0.0, timeout)
        last_seen = ""
        listener = None
        listener_hwnd = None
        poll_interval = 0.04
        try:
            while True:
                if _LOGIN_CANCEL_EVENT.is_set():
                    return None
                hwnd = cls.find_riot_window()
                if not hwnd:
                    last_seen = "no Riot Client window yet"
                else:
                    _timing_mark("riot_window_discovered")
                    form, state = cls._login_form_from_hwnd(hwnd, auto)
                    last_seen = state
                    if form is not None:
                        _timing_mark("login_controls_detected")
                        return form

                    if listener is None or listener_hwnd != hwnd:
                        if listener is not None:
                            listener.close()
                        listener = _ScopedUiChangeListener(hwnd)
                        listener_hwnd = hwnd
                        # Close the check/subscription race: controls can mount
                        # between the first tree read and hook registration.
                        form, state = cls._login_form_from_hwnd(hwnd, auto)
                        last_seen = state
                        if form is not None:
                            _timing_mark("login_controls_detected")
                            return form

                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                wait_for = min(remaining, poll_interval)
                woke = (
                    listener.wait(wait_for, _LOGIN_CANCEL_EVENT)
                    if listener else _LOGIN_CANCEL_EVENT.wait(wait_for)
                )
                poll_interval = 0.04 if woke else min(0.25, poll_interval * 1.6)
        finally:
            if listener is not None:
                listener.close()

        login_logger.warning("login form never appeared - last state: %s", last_seen)
        return None

    @classmethod
    def _login_form_from_hwnd(cls, hwnd: int, auto=None):
        """Resolve one scoped Riot root once; return ``(form, state)``."""
        auto = auto or _uia()
        if auto is None:
            return None, "UI Automation unavailable"
        try:
            auto.SetGlobalSearchTimeout(0.25)
            window = auto.ControlFromHandle(hwnd)
            if not window:
                return None, "Riot Client window has no UIA root"
            snapshot = cls._scan_login_controls(window)
            _LOGIN_UI_SCAN_LOCAL.cached = (hwnd, time.monotonic(), snapshot)
            user_field = snapshot.get("username")
            pass_field = snapshot.get("password")
            if user_field is None or pass_field is None:
                return None, "window up, credential fields not mounted yet"
            try:
                enabled = bool(user_field.IsEnabled and pass_field.IsEnabled)
            except Exception:
                return None, "credential controls became stale"
            if not enabled:
                return None, "credential fields present but not enabled yet"
            return (window, user_field, pass_field), "login form ready"
        except Exception as exc:
            return None, f"reading the window failed: {type(exc).__name__}"

    @staticmethod
    def _scan_login_controls(window):
        """Resolve all login controls in one scoped tree traversal.

        These dynamic objects are used only for the current page mount. A
        structure event or stale-control exception causes a new traversal.
        """
        edits = []
        buttons = []
        checkbox = None
        names = []
        for control in _iter_uia_descendants(window):
            name = _normalise_ui_text(getattr(control, "Name", ""))
            automation_id = _normalise_ui_text(getattr(control, "AutomationId", ""))
            control_type = _normalise_ui_text(getattr(control, "ControlTypeName", ""))
            if name:
                names.append(name)
            try:
                if getattr(control, "IsOffscreen", False) is True:
                    continue
            except Exception:
                pass
            if "edit" in control_type:
                edits.append(control)
            elif "button" in control_type or (not control_type and name == "sign out"):
                buttons.append((control, name, automation_id))
            elif "checkbox" in control_type and name == "stay signed in":
                checkbox = checkbox or control

        user_field = pass_field = None
        for field in edits:
            name = _normalise_ui_text(getattr(field, "Name", ""))
            automation_id = _normalise_ui_text(getattr(field, "AutomationId", ""))
            try:
                is_password = bool(getattr(field, "IsPassword", False))
            except Exception:
                is_password = False
            identity = f"{name} {automation_id}"
            if is_password or "password" in identity:
                pass_field = pass_field or field
            elif any(token in identity for token in ("username", "user name", "email")):
                user_field = user_field or field

        if len(edits) >= 2:
            user_field = user_field or edits[0]
            pass_field = pass_field or next((field for field in edits if field is not user_field), None)

        submit = None
        sign_out = None
        for button, name, automation_id in buttons:
            if name == "sign out":
                sign_out = sign_out or button
            if submit is None and (
                "sign in" in name or name == "login" or "submit" in automation_id
            ):
                submit = button
        all_text = " ".join(names)
        popup_failure = (
            "unable to load" in all_text or
            "trouble signing you in right now" in all_text
        )
        validation_error = None
        if "special characters" in all_text and (
            "can't put" in all_text or "cannot put" in all_text
        ):
            validation_error = "unsupported special characters"
        return {
            "window": window,
            "username": user_field,
            "password": pass_field,
            "submit": submit,
            "stay_signed_in": checkbox,
            "popup_sign_out": sign_out if popup_failure else None,
            "validation_error": validation_error,
        }

    @classmethod
    def _snapshot_for_hwnd(cls, hwnd: int, auto=None, max_age: float = 0.0):
        """Read current scoped controls, optionally reusing a same-operation scan."""
        cached = getattr(_LOGIN_UI_SCAN_LOCAL, "cached", None)
        now = time.monotonic()
        if max_age > 0 and cached and cached[0] == hwnd and now - cached[1] <= max_age:
            return cached[2]
        auto = auto or _uia()
        if auto is None:
            return {}
        auto.SetGlobalSearchTimeout(0.25)
        window = auto.ControlFromHandle(hwnd)
        if not window:
            return {}
        snapshot = cls._scan_login_controls(window)
        _LOGIN_UI_SCAN_LOCAL.cached = (hwnd, now, snapshot)
        return snapshot

    @staticmethod
    def _find_login_fields(window):
        """Find Riot's credential controls without depending on label casing.

        Riot has changed the accessible names and nesting of these controls
        more than once. Prefer semantic password/name properties, then fall
        back to the first two visible edit controls in form order.
        """
        snapshot = ClientLauncher._scan_login_controls(window)
        return snapshot.get("username"), snapshot.get("password")

    @staticmethod
    def _field_text(field) -> str:
        """Current text of an edit control, or '' if it can't be read."""
        try:
            vp = field.GetValuePattern()
            if vp is not None:
                return vp.Value or ""
        except Exception:
            pass
        try:
            return field.GetLegacyIAccessiblePattern().Value or ""
        except Exception:
            return ""

    @classmethod
    def fill_field_verified(cls, field, value: str, label: str,
                            masked: bool = False, attempts: int = 3) -> bool:
        """
        Puts `value` into one field and confirms it landed, retrying if not.

        The username field reads back as plain text, so it can be compared
        exactly. The password field reads back as bullets, so the check is on
        the character count - which is still enough to catch the two failures
        that actually happen: nothing landing at all, and the value landing in
        the wrong field (the classic "password typed into the username box").
        """
        # ValuePattern is synchronous in the normal Riot UIA provider. Try it
        # more than once for transient provider failures, but do not tax every
        # successful assignment with an arbitrary post-write sleep.
        native_attempts = max(1, min(attempts, 2))
        for attempt in range(1, native_attempts + 1):
            try:
                value_pattern = field.GetValuePattern()
                if value_pattern is not None and not getattr(value_pattern, "IsReadOnly", False):
                    value_pattern.SetValue(value)
                    got = cls._field_text(field)
                    ok = (len(got) == len(value)) if masked else (got == value)
                    if ok:
                        login_logger.info("%s: entered in background and verified (attempt %d)", label, attempt)
                        return True
            except Exception as e:
                login_logger.debug(
                    "%s: background ValuePattern entry unavailable (%s)",
                    label, type(e).__name__,
                )

        if _LOGIN_CANCEL_EVENT.is_set():
            return False

        # Some Riot builds expose a read-only ValuePattern even though keyboard
        # entry works. Keep one proven foreground attempt as compatibility
        # fallback only after bounded native retries.
        for attempt in range(1, max(1, attempts - native_attempts) + 1):
            try:
                field.SetFocus()
            except Exception as e:
                login_logger.warning("%s: could not focus the field (%s)", label, type(e).__name__)
                return False

            pyautogui.hotkey('ctrl', 'a')
            pyautogui.press('backspace')

            pyperclip.copy(value)
            pyautogui.hotkey('ctrl', 'v')

            got = cls._field_text(field)
            ok = (len(got) == len(value)) if masked else (got == value)
            if ok:
                login_logger.info("%s: entered and verified (attempt %d)", label, attempt)
                return True

            login_logger.warning(
                "%s: input did not verify on compatibility attempt %d",
                label, attempt,
            )

        login_logger.error("%s: gave up after %d attempts", label, attempts)
        return False

    @classmethod
    def submit_login_form(cls, window, pass_field, submit_control=None,
                          listener=None, timeout: float = 2.0) -> bool:
        """
        Submits the form from inside the password field, which is the only
        submission path the Riot Client handles reliably. Focus is re-asserted
        first, because ticking the checkbox moves it.
        """
        deadline = time.monotonic() + max(0.0, timeout)
        control = submit_control
        poll_interval = 0.04
        while not _LOGIN_CANCEL_EVENT.is_set():
            if control is None:
                try:
                    control = cls._scan_login_controls(window).get("submit")
                except Exception:
                    control = None
            if control is None:
                break
            try:
                enabled = bool(getattr(control, "IsEnabled", True))
                invoke = control.GetInvokePattern() if enabled else None
                if enabled and invoke is not None:
                    invoke.Invoke()
                    _timing_mark("login_invoked")
                    return True
            except Exception:
                # The button may have been recreated; invalidate and reacquire.
                control = None
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            wait_for = min(remaining, poll_interval)
            woke = (
                listener.wait(wait_for, _LOGIN_CANCEL_EVENT)
                if listener is not None else _LOGIN_CANCEL_EVENT.wait(wait_for)
            )
            poll_interval = 0.04 if woke else min(0.2, poll_interval * 1.6)
            try:
                control = cls._scan_login_controls(window).get("submit")
            except Exception:
                control = None

        if _LOGIN_CANCEL_EVENT.is_set():
            return False
        try:
            pass_field.SetFocus()
        except Exception:
            pass
        pyautogui.press('enter')
        _timing_mark("login_invoked_keyboard_fallback")
        return True

    @classmethod
    def _attempt_login_fill(cls, username: str, password: str, stay_signed_in: bool,
                            tries: int = 3, form_timeout: float = 35.0) -> Optional[bool]:
        """
        Fills and submits the login form in whatever window is already open,
        re-doing the whole fill if the form resets underneath it.

        The Riot Client re-mounts its sign-in page a moment after it first
        paints - the fields are real and accept input, then the page reloads
        and they come back empty. Filling the username, then the password,
        then submitting is exactly long enough to straddle that reload, which
        is why logins were being submitted with an empty password box.

        Two things guard against it. The controls are re-resolved from the
        window on every attempt, because a reload leaves the previous
        references pointing at elements that no longer exist. And the username
        is re-read after the password has been entered - a reload between the
        two clears it, and that is the only way to notice.

        Returns True on submit, False when the form is there but can't be
        filled, and None when no form appeared at all.
        """
        for attempt in range(1, tries + 1):
            if _LOGIN_CANCEL_EVENT.is_set():
                return False
            form = cls.wait_for_login_form(timeout=form_timeout if attempt == 1 else 10.0)
            if form is None:
                return None

            window, user_field, pass_field = form
            hwnd = cls.find_riot_window()
            with _ScopedUiChangeListener(hwnd) as listener:
                # Re-read after registering the hook so a remount between the
                # readiness check and subscription cannot leave stale fields.
                refreshed, _ = cls._login_form_from_hwnd(hwnd) if hwnd else (None, "")
                if refreshed is not None:
                    window, user_field, pass_field = refreshed
                try:
                    snapshot = cls._scan_login_controls(window)
                except Exception:
                    continue

                if snapshot.get("popup_sign_out") is not None:
                    cls.click_transient_login_sign_out(
                        hwnd, button=snapshot.get("popup_sign_out")
                    )
                    cls.wait_for_transient_login_popup_gone(timeout=8.0)
                    cls.wait_for_signed_out(timeout=8.0)
                    continue

                if attempt > 1:
                    login_logger.info("refilling the form after a page reset (attempt %d)", attempt)
                    _set_login_stage(
                        "typing",
                        f"The sign-in page reset - entering the credentials again (try {attempt})...",
                        username
                    )

                _set_login_stage("typing", "Entering username...", username)
                if not cls.fill_field_verified(user_field, username, "username"):
                    continue
                _timing_mark("username_assigned")

                # Pump any structure/state notification raised during the
                # synchronous write. Only rescan here when Riot actually
                # changed the page; otherwise the mid-entry popup check is free.
                if listener.poll(clear=True):
                    try:
                        snapshot = cls._scan_login_controls(window)
                    except Exception:
                        continue
                    if snapshot.get("popup_sign_out") is not None:
                        cls.click_transient_login_sign_out(
                            hwnd, button=snapshot.get("popup_sign_out")
                        )
                        cls.wait_for_transient_login_popup_gone(timeout=8.0)
                        cls.wait_for_signed_out(timeout=8.0)
                        continue
                    user_field = snapshot.get("username") or user_field
                    pass_field = snapshot.get("password") or pass_field
                    if cls._field_text(user_field) != username:
                        continue
                if _LOGIN_CANCEL_EVENT.is_set():
                    return False

                _set_login_stage("typing", "Entering password...", username)
                if not cls.fill_field_verified(pass_field, password, "password", masked=True):
                    continue
                _timing_mark("password_assigned")
                if _LOGIN_CANCEL_EVENT.is_set():
                    return False

                # One fresh scoped traversal is both the final popup check and
                # stale-control invalidation. It replaces three independent
                # full-tree scans plus the fixed post-password delay.
                try:
                    snapshot = cls._scan_login_controls(window)
                    user_field = snapshot.get("username")
                    pass_field = snapshot.get("password")
                except Exception:
                    continue
                if snapshot.get("popup_sign_out") is not None:
                    cls.click_transient_login_sign_out(
                        hwnd, button=snapshot.get("popup_sign_out")
                    )
                    cls.wait_for_transient_login_popup_gone(timeout=8.0)
                    cls.wait_for_signed_out(timeout=8.0)
                    continue
                if user_field is None or pass_field is None:
                    continue
                if cls._field_text(user_field) != username or len(cls._field_text(pass_field)) != len(password):
                    login_logger.warning("the form reset before submission; reacquiring controls")
                    continue

                if stay_signed_in:
                    _set_login_stage("typing", "Ticking \"Stay signed in\"...", username)
                    set_stay_signed_in(
                        hwnd,
                        window=window,
                        checkbox=snapshot.get("stay_signed_in"),
                        password_field=pass_field,
                    )
                    if _LOGIN_CANCEL_EVENT.is_set():
                        return False
                    if cls._field_text(user_field) != username:
                        login_logger.warning("the form reset while setting stay-signed-in")
                        continue

                _set_login_stage("typing", "Submitting the login...", username)
                if not cls.submit_login_form(
                    window,
                    pass_field,
                    submit_control=snapshot.get("submit"),
                    listener=listener,
                ):
                    return False
                _set_login_stage("submitted", "Signing in... waiting for Riot to respond.", username)
                login_logger.info("login form submitted on attempt %d", attempt)
                return True

        login_logger.error("[%s] the form kept resetting - gave up after %d attempts", username, tries)
        return False

    @classmethod
    def auto_fill_credentials(cls, username: str, password: str, cold_start: bool = False,
                              stay_signed_in: bool = True, client_path: Optional[str] = None):
        """
        Enters the credentials, checking every step, and recovering from the
        sign-in page resetting underneath it.

        Escalates in exactly two stages, and no further:

          1. Fill and submit in the window that is already open, re-doing the
             fill if the page resets. Nothing is restarted for this - the
             window on screen is fine, it just reloaded, and killing the
             client to deal with a reload is what made retrying feel like it
             never retried at all.
          2. Only if that never lands: kill the client once, start it again,
             and fill the fresh window.

        If the second stage fails too it stops and says so. There is no third
        attempt, because a login that has failed twice this way is failing for
        a reason another relaunch won't change.

        After a form submission, the result monitor also handles Riot's
        transient "Unable to load" modal with up to three total submissions.
        That popup-specific retry does not change the form-reset/relaunch
        policy above.
        """
        if getattr(_LOGIN_TIMING_LOCAL, "trace", None) is None:
            _timing_begin()
        _set_login_stage("waiting_window", "Waiting for the Riot Client to open...", username)
        if _LOGIN_CANCEL_EVENT.is_set():
            return
        hwnd = cls.find_riot_window()
        if hwnd:
            _timing_mark("riot_window_discovered")
            login_logger.info("Riot Client window is up")
        runtime_audit.window_automation(
            "background UIA credential fill; foreground input only as fallback", "Riot Client"
        )
        _set_login_stage("waiting_window", "Waiting for the sign-in screen...", username)

        # ---- stage 1: the window that's already open ----------------------
        result = cls._attempt_login_fill(username, password, stay_signed_in, tries=3)
        if _LOGIN_CANCEL_EVENT.is_set():
            return
        if result is True:
            cls._monitor_login_result(username, password, stay_signed_in, client_path)
            return

        if result is None:
            # No readable form at all. Most often this is Riot running elevated
            # while Vortex is not - UI Automation then can't see into its window
            # at all. Say so plainly instead of falling through to a blind path
            # that will only fail to focus the window a few seconds later.
            if _elevation_blocked_login(username):
                return
            # Otherwise: UI Automation isn't usable in this build, or the
            # client never reached a sign-in screen. The timing-based path can
            # still handle the first of those.
            login_logger.info(
                "[%s] no readable login form - falling back to the timing-based entry path", username
            )
            cls._fill_credentials_blind(hwnd, username, password, cold_start, stay_signed_in)
            cls._monitor_login_result(username, password, stay_signed_in, client_path)
            return

        # ---- stage 2: one restart, then one more go -----------------------
        target_path = client_path or cls.detect_riot_client_path()
        if not target_path or not os.path.exists(target_path):
            _set_login_stage(
                "error",
                "The sign-in page kept resetting, and the Riot Client couldn't be restarted "
                "to try again - check its path in Settings.",
                username
            )
            return

        _set_login_stage("opening", "The sign-in page kept resetting - restarting the Riot Client once...", username)
        login_logger.info("[%s] restarting the client for a second and final attempt", username)
        cls.force_kill_riot_client()
        cls.wait_for_processes_gone(_RIOT_PROCS, timeout=10.0)
        time.sleep(1.2)

        try:
            runtime_audit.process_launch(target_path, "restart Riot Client (sign-in page reset)")
            subprocess.Popen([target_path], shell=False)
            _timing_mark("riot_process_started")
        except Exception as e:
            _set_login_stage("error", f"Couldn't restart the Riot Client: {e}", username)
            return

        _set_login_stage("waiting_window", "Waiting for the Riot Client to reopen...", username)
        result = cls._attempt_login_fill(username, password, stay_signed_in, tries=3, form_timeout=60.0)
        if result is True:
            cls._monitor_login_result(username, password, stay_signed_in, client_path)
            return

        _set_login_stage(
            "error",
            "The Riot Client's sign-in page kept resetting while the credentials were being "
            "entered, on both attempts. Nothing was submitted. Try again, or sign in manually.",
            username
        )

    @classmethod
    def _fill_credentials_blind(cls, hwnd: int, username: str, password: str,
                                cold_start: bool, stay_signed_in: bool):
        """
        The timing-based entry path, for when UI Automation can't be used.

        This is the v3 sequence unchanged - the one that logs in reliably.
        There is deliberately no keyboard route to the "Stay signed in"
        checkbox here: reaching it means tabbing across the social sign-in
        buttons, and landing one short activates one of them instead.
        """
        if cold_start:
            stable_checks = 0
            last_rect = None
            for _ in range(60):
                time.sleep(0.15)
                current_hwnd = cls.find_riot_window()
                if not current_hwnd:
                    continue
                hwnd = current_hwnd
                try:
                    rect = win32gui.GetWindowRect(hwnd)
                except Exception:
                    rect = None
                if rect and rect == last_rect and rect[2] - rect[0] > 300:
                    stable_checks += 1
                    if stable_checks >= 6:
                        break
                else:
                    stable_checks = 0
                last_rect = rect

            time.sleep(1.2)

            focused_ok = False
            for _ in range(6):
                cls.focus_window(hwnd)
                time.sleep(0.25)
                try:
                    if win32gui.GetForegroundWindow() == hwnd:
                        focused_ok = True
                        break
                except Exception:
                    pass
            if not focused_ok:
                if _elevation_blocked_login(username):
                    return
                _set_login_stage("error", "Could not focus the Riot Client window.", username)
                return
        else:
            cls.focus_window(hwnd)

        time.sleep(0.9)
        _set_login_stage("typing", "Entering credentials into Riot Client...", username)

        try:
            orig_clipboard = pyperclip.paste()
        except Exception:
            orig_clipboard = ""

        try:
            pyautogui.hotkey('ctrl', 'a')
            time.sleep(0.04)
            pyautogui.press('backspace')
            time.sleep(0.04)
            pyperclip.copy(username)
            pyautogui.hotkey('ctrl', 'v')
            time.sleep(0.15)

            pyautogui.press('tab')
            time.sleep(0.3)

            pyautogui.hotkey('ctrl', 'a')
            time.sleep(0.04)
            pyautogui.press('backspace')
            time.sleep(0.04)
            pyperclip.copy(password)
            pyautogui.hotkey('ctrl', 'v')
            time.sleep(0.08)

            pyautogui.press('enter')
            _set_login_stage("submitted", "Signing in... waiting for Riot to respond.", username)
        except Exception as e:
            login_logger.exception("[%s] Failed to type credentials: %s", username, e)
            _set_login_stage("error", f"Failed to type credentials: {e}", username)
        finally:
            try:
                pyperclip.copy(orig_clipboard or "")
            except Exception:
                pass

    # Backward compatibility alias
    auto_fill_credentials_pure_keyboard = auto_fill_credentials

    @staticmethod
    def is_valorant_running() -> bool:
        """Checks if VALORANT is currently running (ultra-fast Win32 check)."""
        return is_valorant_running()

    @staticmethod
    def is_valorant_foreground() -> bool:
        """True only when VALORANT owns the foreground window."""
        return is_valorant_foreground()

    @staticmethod
    def kill_valorant() -> bool:
        """Force closes any running VALORANT game instances."""
        try:
            cmd = ["taskkill", "/F", "/T", "/IM", "VALORANT.exe", "/IM", "VALORANT-Win64-Shipping.exe"]
            runtime_audit.process_terminate("VALORANT.exe", "taskkill /F", "account switch teardown")
            runtime_audit.child_command(cmd)
            res = subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=True
            )
            return res.returncode == 0
        except Exception:
            return False

    @classmethod
    def login_account(cls, username: str, password: str, client_path: Optional[str] = None,
                      stay_signed_in: bool = True, restart_client: bool = True) -> Dict[str, Any]:
        """
        Signs the current account out and logs the given one in.

        Fast path: if the Riot Client is already open, sign the live session
        out through its own API and type the credentials straight into the
        sign-in page that comes up - no kill, no relaunch, no lost window. If
        it is already sitting on the sign-in page with nothing signed in, it
        goes straight to typing.

        This is only taken when the USERNAME/PASSWORD fields actually
        materialise (which the splash, a half-drawn client, an error screen or
        the region picker cannot fake). Anything else falls through to the
        full teardown below - kill VALORANT, kill the client, relaunch clean -
        and `auto_fill_credentials` still keeps one restart in reserve if the
        page fights back. Each step is confirmed before the next runs.
        """
        with _LOGIN_START_LOCK:
            age = time.time() - float(LOGIN_PROGRESS.get("started_at") or 0.0)
            if LOGIN_PROGRESS.get("active") and age < 150.0:
                active_user = LOGIN_PROGRESS.get("username") or "another account"
                return {
                    "success": False,
                    "busy": True,
                    "message": f"A login for {active_user} is already in progress.",
                }

            # Claim the login before doing any process work.  _set_login_stage
            # keeps the claim until the verifier marks the attempt done/error.
            LOGIN_PROGRESS["started_at"] = time.time()
            LOGIN_PROGRESS["attempt"] = LOGIN_PROGRESS.get("attempt", 0) + 1
            LOGIN_PROGRESS["stay_signed_in"] = None
            LOGIN_PROGRESS["needs_elevation"] = False
            LOGIN_PROGRESS["active"] = True
            _LOGIN_CANCEL_EVENT.clear()
        login_logger.info("[%s] login attempt started mode=%s", username,
                          "retry" if not restart_client else "standard")
        _set_login_stage("opening", "Preparing to sign in...", username)

        target_path = client_path or cls.detect_riot_client_path()
        if not target_path or not os.path.exists(target_path):
            _set_login_stage("error", "Riot Client executable not found.", username)
            return {
                "success": False,
                "message": "Riot Client executable not found. Please set path in Settings."
            }

        # Retrying into a sign-in page that is already open doesn't need any of
        # the teardown below. Killing the client to retry is what made Retry
        # feel like it never retried: it closed the window the user was
        # looking at and started the whole wait over.
        if not restart_client and cls.find_riot_window():
            login_logger.info("[%s] retrying in the window that's already open", username)
            _set_login_stage("waiting_window", "Retrying in the open Riot Client...", username)

            def _retry_worker():
                try:
                    _drop_stale_uia_client()
                    _timing_begin()
                    cls.auto_fill_credentials(username, password, False, stay_signed_in, target_path)
                except Exception as e:
                    login_logger.exception("[%s] retry worker crashed", username)
                    _set_login_stage("error", f"Login automation crashed: {e}", username)

            threading.Thread(target=_retry_worker, daemon=True).start()
            return {"success": True, "message": f"Retrying the login for {username}..."}

        # Fast path: the client is already open. Hand the whole login to one
        # worker thread - close VALORANT, sign the live session out through the
        # client's own API, wait for its sign-in page, and type straight into
        # it. Only if that page never shows does it fall through to the full
        # teardown-and-relaunch.
        #
        # Every UI Automation call in a login must run on the SAME thread.
        # comtypes puts each thread in its own single-threaded COM apartment,
        # and the frozen build's UIA client, once built on one thread, hangs
        # forever when touched from another. login_account runs on a pooled
        # request thread that is about to be parked, so it makes no UIA call
        # itself - the worker makes every one of them.
        if cls.find_riot_window():
            _set_login_stage("opening", "Using the Riot Client that's already open...", username)

            def _warm_worker():
                try:
                    _drop_stale_uia_client()
                    _timing_begin()

                    if cls.is_valorant_running():
                        _set_login_stage("opening", "Closing VALORANT...", username)
                        cls.kill_valorant()
                        cls.wait_for_processes_gone(_VALORANT_PROCS, timeout=8.0)

                    had_session = bool(cls.get_lockfile_auth())
                    if had_session:
                        _set_login_stage("signout", "Signing out of the current session...", username)
                        cls.api_sign_out()
                        cls.wait_for_signed_out(timeout=8.0)
                        _set_login_stage("waiting_window", "Loading the sign-in page...", username)
                    else:
                        _set_login_stage("waiting_window", "Opening the sign-in page...", username)

                    form = cls.wait_for_login_form(timeout=20.0 if had_session else 8.0)
                    if form is not None:
                        login_logger.info(
                            "[%s] warm login - typing into the sign-in page already on screen", username
                        )
                        cls.auto_fill_credentials(
                            username, password, cold_start=False,
                            stay_signed_in=stay_signed_in, client_path=target_path,
                        )
                        return

                    login_logger.info(
                        "[%s] warm login - no sign-in page appeared, restarting the client", username
                    )
                    cls._full_restart_login(username, password, stay_signed_in, target_path)
                except Exception as e:
                    login_logger.exception("[%s] warm login worker crashed", username)
                    _set_login_stage("error", f"Login automation crashed: {e}", username)

            threading.Thread(target=_warm_worker, daemon=True).start()
            return {"success": True, "message": f"Logging in to {username}..."}

        # Cold path: nothing open to reuse - full teardown and relaunch, on a
        # worker thread for the same UIA-threading reason.
        threading.Thread(
            target=cls._full_restart_login,
            args=(username, password, stay_signed_in, target_path),
            daemon=True,
        ).start()
        return {"success": True, "message": f"Logging in to {username}..."}

    @classmethod
    def _full_restart_login(cls, username: str, password: str,
                            stay_signed_in: bool, target_path: str) -> None:
        """
        The teardown-and-relaunch login, start to finish on the calling
        thread: close VALORANT, sign the current session out through the API,
        kill the Riot Client, start it fresh, and fill the new sign-in page.

        Callers must invoke this on a dedicated worker thread, never the
        request thread - every UI Automation call for the login happens here
        and they all share this thread's COM apartment (see
        auto_fill_credentials and _drop_stale_uia_client).
        """
        try:
            _drop_stale_uia_client()
            _timing_begin()

            # 1. VALORANT first - the Riot Client can't switch accounts under a
            #    running game, and confirm it's actually gone before moving on.
            if cls.is_valorant_running():
                cls.kill_valorant()
                if cls.wait_for_processes_gone(_VALORANT_PROCS, timeout=8.0):
                    login_logger.info("[%s] VALORANT closed", username)
                else:
                    login_logger.warning("[%s] VALORANT did not exit in time", username)

            # 2. Sign the current session out through the API before killing
            #    the client. Killing it alone doesn't end the session, so a
            #    client with "stay signed in" set would come back up already
            #    logged into the previous account and never show the form.
            _set_login_stage("signout", "Signing out of the current session...", username)
            if cls.get_lockfile_auth():
                cls.api_sign_out()
                if cls.wait_for_signed_out(timeout=8.0):
                    login_logger.info("[%s] previous session signed out", username)
                else:
                    login_logger.warning(
                        "[%s] sign-out not confirmed - restarting the client anyway", username
                    )

            # 3. Restart the client from scratch.
            _set_login_stage("opening", "Restarting the Riot Client...", username)
            cls.force_kill_riot_client()
            if cls.wait_for_processes_gone(_RIOT_PROCS, timeout=10.0):
                login_logger.info("[%s] Riot Client processes closed", username)
            else:
                login_logger.warning(
                    "[%s] some Riot Client processes are still running", username
                )
            # Windows needs a moment to release the client's file locks and
            # its single-instance mutex, or the relaunch is swallowed.
            time.sleep(0.7)

            runtime_audit.process_launch(target_path, "start Riot Client for login")
            subprocess.Popen([target_path], shell=False)
            _timing_mark("riot_process_started")
            _set_login_stage("waiting_window", "Waiting for the Riot Client to open...", username)
            cls.auto_fill_credentials(username, password, True, stay_signed_in, target_path)
        except Exception as e:
            login_logger.exception("[%s] restart-login worker crashed", username)
            _set_login_stage("error", f"Login automation crashed: {e}", username)

    @staticmethod
    def force_kill_riot_client():
        """Force closes all Riot Client processes cleanly to reset rate limits and release session lock."""
        ClientLauncher._last_riot_hwnd = None
        ClientLauncher._last_riot_pid = None
        try:
            cmd = ["taskkill", "/F", "/T", "/IM", "RiotClientServices.exe", "/IM", "RiotClientUx.exe", "/IM", "RiotClientCrashHandler.exe"]
            runtime_audit.process_terminate("RiotClientServices.exe", "taskkill /F", "reset session lock / rate limits")
            runtime_audit.child_command(cmd)
            subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=True
            )
        except Exception:
            pass
