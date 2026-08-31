"""Keep Overwolf running quietly in the background for Vortex Telemetry.

Live combat stats (see live_combat.py) are supplied by Vortex Telemetry, a
background-only Overwolf companion. Its GEP subscription only works while
Overwolf itself is running. Riot ships no public live-data API for VALORANT,
so this module starts Overwolf itself quietly in the tray:

  * find an existing Overwolf install (registry first, then the usual paths)
  * install it silently if it's missing
  * start it the same way Overwolf's own startup entry does, so it goes
    straight to the tray with no window

The server gates all of it behind the visible `overwolf_enabled` and
`valorant_tracker_enabled` settings. Install is attempted once per run: a machine that
can't install it (offline, no admin rights) shouldn't re-download a 200MB
installer on every poll.
"""

from __future__ import annotations

import json
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

# VALORANT Tracker's Overwolf app UID. The install/Download endpoint with an
# ExtensionId returns a small stub ("Valorant Tracker - Installer.exe") that
# adds the app to an existing Overwolf, or installs Overwolf + the app if it
# is missing. Same NSIS package, same silent switch.
_TRACKER_UID = "ipmlnnogholfmdmenfijjifldcpjoecappfccceh"
_TRACKER_INSTALLER_URL = (
    "https://download.overwolf.com/install/Download"
    f"?ExtensionId={_TRACKER_UID}&Channel=vortex"
)
# The VALORANT GEP game id. An extension that can actually produce VALORANT
# match events lists this in its manifest's data.game_events.
_VALORANT_GEP_ID = 21640

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

# Install runs at most once per process, success or failure. Retrying a large
# download on a machine that can't complete it just burns bandwidth forever.
_install_attempted = False

INSTALL_STATE: Dict[str, Any] = {
    "active": False,
    "stage": "idle",      # idle | downloading | installing | done | failed
    "message": "",
    "percent": 0,
}

TRACKER_INSTALL_STATE: Dict[str, Any] = {
    "active": False,
    "stage": "idle",
    "message": "",
    "percent": 0,
}

# The tracker install is attempted once per run too - it can fail for the same
# reasons (offline, Overwolf store hiccup) and shouldn't loop on a poll.
_tracker_install_attempted = False


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
    """Kick off a silent install in the background."""
    global _install_attempted

    if is_installed():
        ensure_running()
        return {"success": True, "message": "Overwolf is already installed."}
    if INSTALL_STATE["active"]:
        return {"success": False, "message": "An Overwolf install is already running."}

    _install_attempted = True
    _set_install("downloading", "Starting the Overwolf download...", 0)
    threading.Thread(target=_install_worker, daemon=True).start()
    return {"success": True, "message": "Installing Overwolf..."}


def ensure_available() -> bool:
    """
    Make live combat stats work, doing whatever that takes on this machine:
    start Overwolf if it's installed, install it first if it isn't.

    Safe to call on every poll - the launch has a cooldown and the install
    only ever fires once per run. Returns True when Overwolf is up.
    """
    if is_installed():
        return ensure_running()
    if not _install_attempted and not INSTALL_STATE["active"]:
        login_logger.info("Overwolf missing - installing it for live combat stats")
        start_install()
    return False


def has_valorant_tracker() -> bool:
    """Whether an Overwolf extension that actually captures VALORANT match
    events is installed.

    The old check just looked for the string "21640" anywhere in any
    manifest - which matched Overwolf's built-in "promotions" extension
    (it lists every game id) and reported a tracker that wasn't there.
    Now: the extension must be the VALORANT Tracker app by UID, or list the
    VALORANT GEP id in its manifest's data.game_events array.
    """
    localapp = os.getenv("LOCALAPPDATA") or ""
    ext_dir = os.path.join(localapp, "Overwolf", "Extensions")
    if not os.path.isdir(ext_dir):
        return False
    try:
        for uid in os.listdir(ext_dir):
            upath = os.path.join(ext_dir, uid)
            if not os.path.isdir(upath):
                continue
            if uid == _TRACKER_UID:
                return True
            for v in os.listdir(upath):
                manifest = os.path.join(upath, v, "manifest.json")
                if not os.path.isfile(manifest):
                    continue
                try:
                    with open(manifest, "r", encoding="utf-8", errors="ignore") as f:
                        data = json.load(f)
                except Exception:
                    continue
                events = (data.get("data") or {}).get("game_events") or []
                try:
                    ids = {int(e) for e in events}
                except (TypeError, ValueError):
                    ids = set()
                # A real provider lists VALORANT in game_events. Exclude the
                # promotions catalogue, which lists dozens of games it does
                # not actually provide events for.
                name = (data.get("meta") or {}).get("name", "")
                if _VALORANT_GEP_ID in ids and len(ids) < 20 and "promotion" not in name.lower():
                    return True
    except Exception:
        pass
    return False


def _tracker_set(stage: str, message: str, percent: int = 0, active: bool = True) -> None:
    TRACKER_INSTALL_STATE.update(
        {"stage": stage, "message": message, "percent": percent, "active": active}
    )


def _tracker_install_worker() -> None:
    tmp = os.path.join(
        os.environ.get("TEMP") or os.getcwd(), "ValorantTrackerSetup-vortex.exe"
    )
    try:
        _tracker_set("downloading", "Downloading Valorant Tracker...", 0)
        with requests.get(_TRACKER_INSTALLER_URL, stream=True, timeout=60) as res:
            if res.status_code != 200:
                _tracker_set("failed", f"Download failed (HTTP {res.status_code}).",
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
                        _tracker_set("downloading", "Downloading Valorant Tracker...",
                                     min(90, int(done / total * 90)))

        with open(tmp, "rb") as f:
            if f.read(2) != b"MZ":
                _tracker_set("failed", "The Tracker installer didn't download cleanly.",
                             0, active=False)
                return

        _tracker_set("installing", "Installing Valorant Tracker...", 92)
        proc = subprocess.Popen(
            [tmp] + _INSTALL_ARGS,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        proc.wait(timeout=600)

        # The stub returns before Overwolf has finished registering the
        # extension, so wait for it to actually appear.
        for _ in range(40):
            if has_valorant_tracker():
                break
            time.sleep(1.5)

        if not has_valorant_tracker():
            _tracker_set(
                "failed",
                "Valorant Tracker didn't finish installing - open Overwolf and add it once.",
                0, active=False,
            )
            return

        ensure_running()
        _tracker_set("done", "Valorant Tracker is installed - live combat stats will work now.",
                     100, active=False)
        login_logger.info("Valorant Tracker installed for live combat stats")
    except Exception as e:
        login_logger.exception("Valorant Tracker install failed")
        _tracker_set("failed", f"Valorant Tracker install failed: {e}", 0, active=False)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def start_tracker_install() -> Dict[str, Any]:
    """Silently install the VALORANT Tracker Overwolf app in the background."""
    global _tracker_install_attempted

    if has_valorant_tracker():
        ensure_running()
        return {"success": True, "message": "Valorant Tracker is already installed."}
    if TRACKER_INSTALL_STATE["active"]:
        return {"success": False, "message": "A Valorant Tracker install is already running."}

    _tracker_install_attempted = True
    _tracker_set("downloading", "Starting the Valorant Tracker download...", 0)
    threading.Thread(target=_tracker_install_worker, daemon=True).start()
    return {"success": True, "message": "Installing Valorant Tracker..."}


# Back-compat alias: the endpoint used to just open the store page.
def open_tracker_store() -> Dict[str, Any]:
    return start_tracker_install()


def ensure_tracker() -> None:
    """Make sure the VALORANT event provider exists, installing it once if not.

    Called alongside ensure_available() from the live-session poll so a fresh
    machine ends up with Overwolf + the Tracker with no user setup. Both
    installs fire at most once per run.
    """
    global _tracker_install_attempted
    if not is_installed():
        return  # Overwolf itself comes first; ensure_available() handles that.
    if has_valorant_tracker():
        return
    if not _tracker_install_attempted and not TRACKER_INSTALL_STATE["active"]:
        login_logger.info("Valorant Tracker missing - installing it for live combat stats")
        start_tracker_install()


def status() -> Dict[str, Any]:
    return {
        "installed": is_installed(),
        "running": is_running(),
        "telemetry": {"setup": "manual", "source_dir": "overwolf/vortex-telemetry"},
        "valorant_tracker": {
            "installed": has_valorant_tracker(),
            "install": dict(TRACKER_INSTALL_STATE),
        },
        "install": dict(INSTALL_STATE),
    }
