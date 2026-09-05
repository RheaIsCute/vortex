"""
Windows elevation helpers.

Vortex's packaged executable advertises ``requireAdministrator`` in its
manifest, so Windows elevates it before Python starts. Source-mode launches do
not have that manifest; the helpers here perform the equivalent handoff before
the backend, WebView, Riot discovery, or optional integrations are imported.

The older Riot/Vortex integrity-mismatch helpers remain for API compatibility
and diagnostics, but an initialized application is now always elevated.
"""

import ctypes
import os
import subprocess
import sys
from ctypes import wintypes
from typing import Optional

from backend import runtime_audit

_RIOT_EXES = {
    "riotclientservices.exe",
    "riot client.exe",
    "riotclientux.exe",
    "riotclientuxrender.exe",
}

# TokenElevation: token is elevated (1) or not (0).
_TOKEN_ELEVATION = 20
_TOKEN_QUERY = 0x0008
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_TH32CS_SNAPPROCESS = 0x00000002
_ELEVATION_SENTINEL = "--vortex-elevation-requested"


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.c_uint32),
        ("cntUsage", ctypes.c_uint32),
        ("th32ProcessID", ctypes.c_uint32),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", ctypes.c_uint32),
        ("cntThreads", ctypes.c_uint32),
        ("th32ParentProcessID", ctypes.c_uint32),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", ctypes.c_uint32),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


def is_self_elevated() -> bool:
    """True if this process is already running with an elevated token."""
    if os.name != "nt":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _process_elevation(pid: int) -> Optional[bool]:
    """
    True/False if the process token's elevation could be read, else None.

    A None here is itself a signal: OpenProcessToken failing with access
    denied on a process we can otherwise see almost always means that process
    sits above us, i.e. it is the elevated one.
    """
    k32 = ctypes.windll.kernel32
    a32 = ctypes.windll.advapi32
    runtime_audit.process_open(
        _PROCESS_QUERY_LIMITED_INFORMATION, f"pid={pid}", "read elevation token (Riot-elevation check)"
    )
    h_proc = k32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h_proc:
        return None
    try:
        h_tok = wintypes.HANDLE()
        if not a32.OpenProcessToken(h_proc, _TOKEN_QUERY, ctypes.byref(h_tok)):
            return None
        try:
            out = wintypes.DWORD()
            ret_len = wintypes.DWORD()
            ok = a32.GetTokenInformation(
                h_tok, _TOKEN_ELEVATION, ctypes.byref(out),
                ctypes.sizeof(out), ctypes.byref(ret_len),
            )
            if not ok:
                return None
            return bool(out.value)
        finally:
            k32.CloseHandle(h_tok)
    finally:
        k32.CloseHandle(h_proc)


def _iter_processes():
    """Yield (lower-case exe name, pid) for every running process."""
    k32 = ctypes.windll.kernel32
    snap = k32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if snap == -1 or not snap:
        return
    try:
        entry = _PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
        if not k32.Process32FirstW(snap, ctypes.byref(entry)):
            return
        while True:
            yield entry.szExeFile.lower(), int(entry.th32ProcessID)
            if not k32.Process32NextW(snap, ctypes.byref(entry)):
                break
    finally:
        k32.CloseHandle(snap)


def riot_client_is_elevated() -> bool:
    """
    True when a main Riot Client process is running elevated while Vortex is
    not - the exact combination that blocks login automation. False if we are
    already elevated (then there is no mismatch to act on) or nothing Riot is
    running above us.
    """
    if os.name != "nt" or is_self_elevated():
        return False
    try:
        for name, pid in _iter_processes():
            if name not in _RIOT_EXES:
                continue
            elevated = _process_elevation(pid)
            # True  -> confirmed elevated.
            # None  -> we can see the process but not open its token, which in
            #          practice means it outranks us. Treat as elevated.
            if elevated is None or elevated is True:
                return True
    except Exception:
        pass
    return False


def _source_script_path() -> str:
    """Return the absolute source entry point without trusting malformed argv."""
    argv0 = str(sys.argv[0]) if sys.argv and isinstance(sys.argv[0], str) else ""
    script = os.path.abspath(argv0) if argv0.lower().endswith(".py") else ""
    if not script or not os.path.exists(script):
        script = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py"
        )
    return script


def relaunch_command():
    """Return ``(executable, parameters)`` for a safe elevated handoff.

    ``subprocess.list2cmdline`` applies Windows' native quoting rules, so source
    paths and user arguments containing spaces or quotes survive ShellExecuteW.
    Credentials are never accepted as command-line arguments by Vortex and this
    command is deliberately not logged.
    """
    forwarded = [str(arg) for arg in sys.argv[1:] if isinstance(arg, str)]
    if _ELEVATION_SENTINEL not in forwarded:
        forwarded.append(_ELEVATION_SENTINEL)
    if getattr(sys, "frozen", False):
        return sys.executable, subprocess.list2cmdline(forwarded)
    args = [_source_script_path(), *forwarded]
    return sys.executable, subprocess.list2cmdline(args)


def relaunch_elevated() -> bool:
    """
    Start a fresh, elevated copy of Vortex via the UAC "runas" verb. Returns
    True if Windows accepted the request (the prompt was shown / consented);
    the caller then exits this instance so only the elevated one remains.

    The caller must terminate immediately after a successful handoff. No Vortex
    services or windows are initialized before this function is used at startup.
    """
    if os.name != "nt" or is_self_elevated():
        return False
    exe, params = relaunch_command()
    try:
        workdir = (
            os.path.dirname(sys.executable)
            if getattr(sys, "frozen", False)
            else os.path.dirname(_source_script_path())
        ) or None
        # ShellExecuteW returns >32 on success.
        runtime_audit.process_launch(exe, "relaunch Vortex elevated (UAC runas)")
        rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, workdir, 1)
        return int(rc) > 32
    except Exception:
        return False


def startup_elevation_action() -> str:
    """Return ``continue``, ``relaunched``, or ``failed`` for startup.

    In an unelevated process this requests one UAC handoff. The original caller
    must exit for both ``relaunched`` and ``failed``. The private sentinel
    prevents a loop if Windows starts the child without a high token.
    """
    if os.name != "nt":
        return "continue"
    if is_self_elevated():
        return "continue"
    if _ELEVATION_SENTINEL in sys.argv[1:]:
        return "failed"
    return "relaunched" if relaunch_elevated() else "failed"


def ensure_elevated_startup() -> bool:
    """Compatibility boolean for callers that only need continue/exit."""
    return startup_elevation_action() == "continue"
