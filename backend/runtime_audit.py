r"""Opt-in runtime forensic log for Vortex's sensitive operations.

Vortex is designed to interact with Riot Client / VALORANT *externally* only:
read-only local APIs, documented authenticated game endpoints, OS-level window
and input automation, and process start/stop via the shell. It never opens a
process handle with write/operation/thread rights, never reads or writes another
process's memory, never injects code, and never loads a driver.

This module makes that behaviour observable. Set ``VORTEX_AUDIT_RUNTIME=1``
before starting Vortex and every sensitive operation below is appended to

    %LOCALAPPDATA%\Vortex\runtime_audit.log      (frozen build)
    <repo>\runtime_audit.log                     (source run)

as a single line: timestamp, category, and a short non-secret description.

What is logged:
    process.open       - an OS process handle was opened (with the access mask)
    process.launch     - a child process / external application was started
    process.terminate  - a process was asked to stop (taskkill / API sign-out)
    riot.api           - a request to a Riot local/remote API (method + path only)
    window.automation  - a UI-automation / input-automation action on a window
    child.command      - a subprocess command line Vortex executed
    file.outside       - a file op with a path outside Vortex's own directories
    live.provider      - an Overwolf / VAL Tracker provider action

What is NEVER logged: passwords, Riot tokens, Authorization headers, lockfile
passwords, account identifiers, or request/response bodies. Callers pass already
-redacted strings; this module additionally strips obvious query strings and
``riot:`` basic-auth prefixes as a backstop.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import re
import sys
import threading

_ENABLED = (os.getenv("VORTEX_AUDIT_RUNTIME") or "").strip().lower() in {"1", "true", "yes", "on"}

_logger = logging.getLogger("vortex.runtime_audit")
_logger.setLevel(logging.INFO)
_logger.propagate = False
_configured = False
_lock = threading.Lock()

_SECRET_QUERY = re.compile(r"\?.*$")
_BASIC_AUTH = re.compile(r"//[^/@]*@")


def _ensure_handler() -> None:
    global _configured
    if _configured:
        return
    with _lock:
        if _configured:
            return
        if getattr(sys, "frozen", False):
            base = os.path.join(os.getenv("LOCALAPPDATA") or os.path.expanduser("~"), "Vortex")
        else:
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        try:
            os.makedirs(base, exist_ok=True)
            handler = logging.handlers.RotatingFileHandler(
                os.path.join(base, "runtime_audit.log"),
                maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8",
            )
            handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
            _logger.addHandler(handler)
        except OSError:
            _logger.addHandler(logging.NullHandler())
        _configured = True


def enabled() -> bool:
    return _ENABLED


def _scrub(text: str) -> str:
    text = str(text)
    text = _BASIC_AUTH.sub("//", text)
    text = _SECRET_QUERY.sub("?<redacted>", text) if "?" in text else text
    return text


def record(category: str, detail: str) -> None:
    """Append one audit line. No-op unless VORTEX_AUDIT_RUNTIME is set."""
    if not _ENABLED:
        return
    _ensure_handler()
    try:
        _logger.info("%-18s %s", category, _scrub(detail))
    except Exception:
        pass


# -- typed helpers -----------------------------------------------------------

_ACCESS_NAMES = {
    0x1000: "PROCESS_QUERY_LIMITED_INFORMATION",
    0x0400: "PROCESS_QUERY_INFORMATION",
    0x0008: "PROCESS_VM_READ",
    0x0010: "PROCESS_VM_WRITE",
    0x0020: "PROCESS_VM_OPERATION",
    0x0002: "PROCESS_CREATE_THREAD",
    0x0040: "PROCESS_DUP_HANDLE",
    0x0800: "PROCESS_SUSPEND_RESUME",
    0x1F0FFF: "PROCESS_ALL_ACCESS",
}

_INVASIVE_BITS = 0x0010 | 0x0020 | 0x0002  # VM_WRITE | VM_OPERATION | CREATE_THREAD


def process_open(access_mask: int, target: str, reason: str = "") -> None:
    names = _ACCESS_NAMES.get(access_mask)
    if not names:
        names = "|".join(
            label for bit, label in _ACCESS_NAMES.items()
            if bit != 0x1F0FFF and access_mask & bit == bit
        ) or hex(access_mask)
    invasive = " INVASIVE" if access_mask & _INVASIVE_BITS else ""
    record("process.open", f"{target} access={names} ({hex(access_mask)}){invasive} {reason}".rstrip())


def process_launch(path: str, reason: str = "") -> None:
    record("process.launch", f"{path} {('- ' + reason) if reason else ''}".rstrip())


def process_terminate(target: str, how: str, reason: str = "") -> None:
    record("process.terminate", f"{target} via={how} {('- ' + reason) if reason else ''}".rstrip())


def riot_api(method: str, url: str, kind: str = "") -> None:
    record("riot.api", f"{method.upper()} {url} {kind}".rstrip())


def window_automation(action: str, window: str) -> None:
    record("window.automation", f"{action} target={window}")


def child_command(argv) -> None:
    if isinstance(argv, (list, tuple)):
        argv = " ".join(str(a) for a in argv)
    record("child.command", str(argv))


def live_provider(action: str, detail: str = "") -> None:
    record("live.provider", f"{action} {detail}".rstrip())
