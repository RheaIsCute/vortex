"""Keep Overwolf's VALORANT event provider running, quietly, in the background.

Live combat stats (see live_combat.py) come from Overwolf's Game Events
Provider, which only emits while Overwolf itself is running. Riot ships no
live-data API for VALORANT and its own game log carries no combat events, so
Overwolf - a Riot-approved partner that Vanguard explicitly permits - is the
only sanctioned source. This module makes that dependency invisible:

  * find an existing Overwolf install (registry first, then the usual paths)
  * start it the same way Overwolf's own startup entry does, so it goes
    straight to the tray with no window
  * install it, silently, but only after the user has said yes once

Installing is deliberately gated on stored consent. Putting third-party
software on someone's machine unannounced is what antivirus vendors classify
as bundleware, and Vortex's installer is unsigned already - a silent,
undisclosed third-party install is a fast route to being quarantined.
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
import winreg
from typing import Any, Dict

import requests

from backend.client_launcher import _is_process_running_fast, login_logger

# Overwolf's own Run entry is `OverwolfLauncher.exe -overwolfsilent`, which is
# how it starts itself at boot: no window, straight to the tray. Reusing that
# exact invocation means we never show a window the user has to dismiss.
_SILENT_FLAG = "-overwolfsilent"
_LAUNCHER = "OverwolfLauncher.exe"
_PROCS = {"overwolf.exe"}

_INSTALLER_URL = "https://download.overwolf.com/install/Download?Channel=vortex"
# The uninstaller is registered as `OWUninstaller.exe /S`, so the package is
# NSIS and the installer takes the same silent switch.
_INSTALL_ARGS = ["/S"]

_REG_PATHS = (
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Overwolf", "InstallFolder"),
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Overwolf", "InstallFolder"),
    (winreg.HKEY_LOCAL_MACHINE,
     r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Overwolf",
     "InstallLocation"),
)

# Starting Overwolf is fire-and-forget, but the caller polls often enough that
# without a cooldown a slow start would be re-launched every tick.
_START_COOLDOWN = 45.0
_last_start_at = 0.0
_start_lock = threading.Lock()

INSTALL_STATE: Dict[str, Any] = {
    "active": False,
    "stage": "idle",      # idle | downloading | installing | done | failed
    "message": "",
    "percent": 0,
}


def _reg_install_folder() -> str:
    for hive, path, value in _REG_PATHS:
        try:
            with winreg.OpenKey(hive, path) as key:
                folder = (winreg.QueryValueEx(key, value)[0] or "").strip()
                if folder and os.path.isdir(folder):
                    return folder
        except OSError:
            continue
    return ""


def launcher_path() -> str:
    """Full path to OverwolfLauncher.exe, or "" when Overwolf isn't installed."""
    folder = _reg_install_folder()
    candidates = [os.path.join(folder, _LAUNCHER)] if folder else []
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
        if base:
            candidates.append(os.path.join(base, "Overwolf", _LAUNCHER))
    for path in candidates:
        if path and os.path.exists(path):
            return path
    return ""


def is_installed() -> bool:
    return bool(launcher_path())


def is_running() -> bool:
    return _is_process_running_fast(_PROCS)


def ensure_running() -> bool:
    """
    Start Overwolf in the tray if it's installed and not already up.

    Returns True when Overwolf is running (or was just asked to start), False
    when it isn't installed. Safe to call on every poll.
    """
    global _last_start_at

    if is_running():
        return True
    path = launcher_path()
    if not path:
        return False

    with _start_lock:
        if time.time() - _last_start_at < _START_COOLDOWN:
            return True  # a start is already in flight
        _last_start_at = time.time()

    try:
        subprocess.Popen(
            [path, _SILENT_FLAG],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        login_logger.info("started Overwolf in the tray for live combat stats")
        return True
    except Exception as e:
        login_logger.warning("could not start Overwolf: %s", e)
        return False


def _set_install(stage: str, message: str, percent: int = 0, active: bool = True) -> None:
    INSTALL_STATE.update(
        {"stage": stage, "message": message, "percent": percent, "active": active}
    )


def _install_worker() -> None:
    tmp = os.path.join(
        os.environ.get("TEMP") or os.getcwd(), "OverwolfSetup-vortex.exe"
    )
    try:
        _set_install("downloading", "Downloading Overwolf...", 0)
        with requests.get(_INSTALLER_URL, stream=True, timeout=60) as res:
            if res.status_code != 200:
                _set_install("failed", f"Download failed (HTTP {res.status_code}).",
                             0, active=False)
                return
            total = int(res.headers.get("Content-Length", 0))
            done = 0
            with open(tmp, "wb") as f:
                for chunk in res.iter_content(chunk_size=1024 * 256):
                    if not chunk:
                        continue
                    f.write(chunk)
                    done += len(chunk)
                    if total:
                        _set_install("downloading", "Downloading Overwolf...",
                                     min(95, int(done / total * 95)))

        _set_install("installing", "Installing Overwolf...", 96)
        proc = subprocess.Popen(
            [tmp] + _INSTALL_ARGS,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        proc.wait(timeout=600)

        # The installer returns before the files have all settled, so confirm
        # by what actually matters: the launcher being on disk.
        for _ in range(30):
            if is_installed():
                break
            time.sleep(1.0)

        if not is_installed():
            _set_install("failed", "Overwolf didn't finish installing.", 0, active=False)
            return

        ensure_running()
        _set_install("done", "Overwolf is installed and running in the tray.",
                     100, active=False)
        login_logger.info("Overwolf installed and started")
    except Exception as e:
        login_logger.exception("Overwolf install failed")
        _set_install("failed", f"Overwolf install failed: {e}", 0, active=False)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def start_install() -> Dict[str, Any]:
    """Kick off a silent install. The caller is responsible for consent."""
    if is_installed():
        ensure_running()
        return {"success": True, "message": "Overwolf is already installed."}
    if INSTALL_STATE["active"]:
        return {"success": False, "message": "An Overwolf install is already running."}

    _set_install("downloading", "Starting the Overwolf download...", 0)
    threading.Thread(target=_install_worker, daemon=True).start()
    return {"success": True, "message": "Installing Overwolf..."}


def status() -> Dict[str, Any]:
    return {
        "installed": is_installed(),
        "running": is_running(),
        "install": dict(INSTALL_STATE),
    }
