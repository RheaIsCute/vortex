"""Keep Overwolf running quietly in the background for Vortex Telemetry.

Live combat stats (see live_combat.py) are supplied by Vortex Telemetry, a
background-only Overwolf companion. Its GEP subscription only works while
Overwolf itself is running. Riot ships no public live-data API for VALORANT,
so this module starts Overwolf itself quietly in the tray:

  * find an existing Overwolf install (registry first, then the usual paths)
  * install it silently if it's missing
  * start it the same way Overwolf's own startup entry does, so it goes
    straight to the tray with no window

The server gates all of it behind the visible "Enable Live Match Features"
setting and the underlying compatibility keys. Install is attempted once per
run: a machine that can't install it (offline, no admin rights) shouldn't
re-download a 200MB installer on every poll.
"""

from __future__ import annotations

import json
import os
import base64
import re
import subprocess
import threading
import time
import winreg
from typing import Any, Dict, List, Optional

import requests

from backend.path_safety import guard_path
from backend import runtime_audit

from backend.client_launcher import _is_process_running_fast, login_logger

# Overwolf's own Run entry is `OverwolfLauncher.exe -overwolfsilent`, which is
# how it starts itself at boot: no window, straight to the tray. Reusing that
# exact invocation means we never show a window the user has to dismiss.
_SILENT_FLAG = "-overwolfsilent"
_LAUNCHER = "OverwolfLauncher.exe"
_PROCS = {"overwolf.exe"}

# These are the process names observed in the current Overwolf runtime.  The
# app-specific ownership check below is intentional: OverwolfBrowser.exe is a
# shared Chromium host, so its name alone is not enough to identify Tracker.
_OVERWOLF_PROCESS_NAMES = {
    "overwolf.exe",
    "overwolflauncher.exe",
    "overwolfbrowser.exe",
    "overwolfhelper.exe",
    "overwolfhelper64.exe",
    "overwolfsetup-vortex.exe",
    "valoranttrackersetup-vortex.exe",
}

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

# A process-local gate protects against a background installer finishing after
# the user turns the feature off. The server also gates every live poll, but a
# worker already in flight needs its own authoritative bit.
_integration_enabled = True
_integration_state_lock = threading.Lock()

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_ONCE_KEY = r"Software\Microsoft\Windows\CurrentVersion\RunOnce"
_STARTUP_APPROVED_RUN_KEY = (
    r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
)

# These app labels are Overwolf's own infrastructure, not user-installed
# third-party apps. Any other --owapp label blocks closing the shared root so
# disabling Vortex cannot take an unrelated Overwolf app down with it.
_OVERWOLF_INTERNAL_APPS = (
    "exclusive mode",
    "launcher events provider",
    "overwolf appstore",
    "overwolf general gameevents provider",
    "overwolf notifications",
    "overwolf promotions",
    "overwolf remote configurations",
    "overwolf support",
    "owobs",
    "settings",
)
_VORTEX_TELEMETRY_MARKER = "vortex telemetry"


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


def _integration_is_enabled() -> bool:
    with _integration_state_lock:
        return _integration_enabled


def enable_live_match_integration() -> None:
    """Allow provider launches again after the user re-enables the feature."""
    global _integration_enabled, _install_attempted, _tracker_install_attempted
    with _integration_state_lock:
        was_disabled = not _integration_enabled
        _integration_enabled = True
    if was_disabled:
        # A failed install from the previous enabled period may be retryable
        # after an explicit off -> on transition. Installed apps are still
        # detected first, so this does not create duplicate installs.
        _install_attempted = False
        _tracker_install_attempted = False


def _process_command(info: Dict[str, Any]) -> str:
    return str(info.get("CommandLine") or info.get("command_line") or "")


def _process_name(info: Dict[str, Any]) -> str:
    return str(info.get("Name") or info.get("name") or "").strip().lower()


def _process_pid(info: Dict[str, Any]) -> int:
    try:
        return int(info.get("ProcessId") or info.get("pid") or 0)
    except (TypeError, ValueError):
        return 0


def _process_parent_pid(info: Dict[str, Any]) -> int:
    try:
        return int(info.get("ParentProcessId") or info.get("parent_pid") or 0)
    except (TypeError, ValueError):
        return 0


def _process_path(info: Dict[str, Any]) -> str:
    return str(info.get("ExecutablePath") or info.get("executable_path") or "").strip()


def _enumerate_processes() -> List[Dict[str, Any]]:
    """Read only the known Overwolf executable names and their command lines."""
    if os.name != "nt":
        return []

    names = ", ".join(f"'{name}'" for name in sorted(_OVERWOLF_PROCESS_NAMES))
    script = (
        f"$names = @({names}); "
        "Get-CimInstance Win32_Process | "
        "Where-Object { $names -contains $_.Name } | "
        "Select-Object Name,ProcessId,ParentProcessId,ExecutablePath,CommandLine | "
        "ConvertTo-Json -Compress"
    )
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            shell=False,
            timeout=4.0,
            check=False,
        )
        if result.returncode != 0:
            login_logger.warning(
                "Could not inspect Overwolf processes for Live Match cleanup (exit code %s)",
                result.returncode,
            )
            return []
        if not (result.stdout or "").strip():
            return []
        data = json.loads(result.stdout)
        if isinstance(data, dict):
            return [data]
        return data if isinstance(data, list) else []
    except (OSError, ValueError, TypeError):
        # A missing/blocked WMI query must never turn into a broad IMAGENAME
        # taskkill fallback; that could close an unrelated Overwolf app.
        login_logger.warning("Could not inspect Overwolf processes for Live Match cleanup")
        return []


def _normal_path(path: str) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(path))) if path else ""


def _path_is_within(path: str, root: str) -> bool:
    if not path or not root:
        return False
    try:
        return os.path.commonpath([_normal_path(path), _normal_path(root)]) == _normal_path(root)
    except ValueError:
        return False


def _overwolf_install_root() -> str:
    path = launcher_path()
    return os.path.dirname(path) if path else ""


def _is_overwolf_root_process(info: Dict[str, Any]) -> bool:
    name = _process_name(info)
    if name not in {"overwolf.exe", "overwolflauncher.exe"}:
        return False
    if name == "overwolf.exe":
        return True
    root = _overwolf_install_root()
    return _path_is_within(_process_path(info), root) or "overwolflauncher.exe" in _process_command(info).lower()


def _overwolf_app_label(info: Dict[str, Any]) -> str:
    match = re.search(r"--owapp=(?:\"([^\"]+)\"|(\S+))", _process_command(info), re.IGNORECASE)
    return (match.group(1) or match.group(2) or "").strip() if match else ""


def _is_tracker_process(info: Dict[str, Any]) -> bool:
    if _process_name(info) != "overwolfbrowser.exe":
        return False
    command = _process_command(info).lower()
    label = _overwolf_app_label(info).lower()
    return (
        f"--uid={_TRACKER_UID.lower()}" in command
        or label in {"valorant tracker", "valorant tracker - background"}
    )


def _is_vortex_telemetry_process(info: Dict[str, Any]) -> bool:
    if _process_name(info) != "overwolfbrowser.exe":
        return False
    text = f"{_process_command(info)} {_overwolf_app_label(info)}".lower()
    return _VORTEX_TELEMETRY_MARKER in text


def _is_vortex_installer_process(info: Dict[str, Any]) -> bool:
    return _process_name(info) in {
        "overwolfsetup-vortex.exe",
        "valoranttrackersetup-vortex.exe",
    }


def _is_internal_overwolf_app(label: str) -> bool:
    label = (label or "").strip().lower()
    return bool(label) and any(
        label == prefix or label.startswith(f"{prefix} -")
        for prefix in _OVERWOLF_INTERNAL_APPS
    )


def _descendant_pids(infos: List[Dict[str, Any]], roots: set[int]) -> set[int]:
    by_parent: Dict[int, List[int]] = {}
    for info in infos:
        pid = _process_pid(info)
        if pid:
            by_parent.setdefault(_process_parent_pid(info), []).append(pid)

    descendants = set(roots)
    pending = list(roots)
    while pending:
        parent = pending.pop()
        for child in by_parent.get(parent, []):
            if child not in descendants:
                descendants.add(child)
                pending.append(child)
    return descendants


def _select_shutdown_targets(infos: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Select exact Tracker/Vortex processes and a safe Overwolf root target."""
    roots = {
        _process_pid(info)
        for info in infos
        if _process_pid(info) and _is_overwolf_root_process(info)
    }
    descendants = _descendant_pids(infos, roots)
    tracker = [
        _process_pid(info) for info in infos
        if _process_pid(info) and _is_tracker_process(info)
    ]
    vortex = [
        _process_pid(info) for info in infos
        if _process_pid(info) and _is_vortex_telemetry_process(info)
    ]
    installers = [
        _process_pid(info) for info in infos
        if _process_pid(info) and _is_vortex_installer_process(info)
    ]

    unrelated_labels = sorted({
        _overwolf_app_label(info)
        for info in infos
        if _process_pid(info) in descendants
        and _overwolf_app_label(info)
        and not _is_tracker_process(info)
        and not _is_vortex_telemetry_process(info)
        and not _is_internal_overwolf_app(_overwolf_app_label(info))
    })
    return {
        "tracker": sorted(set(tracker)),
        "vortex": sorted(set(vortex)),
        "installers": sorted(set(installers)),
        "root_candidates": sorted(roots),
        "roots": sorted(roots) if not unrelated_labels else [],
        "blocked_labels": unrelated_labels,
    }


def _taskkill(pid: int, force: bool = False) -> bool:
    args = ["taskkill", "/PID", str(pid), "/T"]
    if force:
        args.append("/F")
    runtime_audit.process_terminate(f"pid={pid}", "taskkill" + (" /F" if force else ""), "Live Match provider cleanup")
    runtime_audit.child_command(args)
    try:
        result = subprocess.run(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            timeout=3.0,
            check=False,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _pid_is_alive(pid: int) -> bool:
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True,
            text=True,
            shell=False,
            timeout=1.0,
            check=False,
        )
        return bool(re.search(rf"(?<!\d){pid}(?!\d)", result.stdout or ""))
    except (OSError, subprocess.TimeoutExpired):
        return False


def _wait_for_pids_gone(pids: List[int], timeout: float = 2.5) -> List[int]:
    pending = sorted({pid for pid in pids if pid})
    deadline = time.monotonic() + timeout
    while pending and time.monotonic() < deadline:
        pending = [pid for pid in pending if _pid_is_alive(pid)]
        if pending:
            time.sleep(0.15)
    return pending


def _terminate_pids(pids: List[int], label: str) -> List[int]:
    pending = sorted({pid for pid in pids if pid})
    if not pending:
        return []
    for pid in pending:
        _taskkill(pid)
    pending = _wait_for_pids_gone(pending)
    if pending:
        login_logger.warning("%s did not close cleanly; force-closing", label)
        for pid in pending:
            _taskkill(pid, force=True)
        pending = _wait_for_pids_gone(pending, timeout=1.0)
    if pending:
        login_logger.warning("Could not close %s process(es): %s", label, ", ".join(map(str, pending)))
    return pending


def _startup_entry_kind(name: str, command: str) -> str:
    """Return ``overwolf``/``valorant_tracker`` only for clear matches."""
    value_name = str(name or "").strip().lower()
    value_leaf = value_name.rstrip("\\/").rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
    command_text = str(command or "").strip().lower()
    tracker_executable = re.search(
        r"(?:^|[\\/\"])valorant ?tracker\.exe(?:$|[\" ])",
        command_text,
    )
    overwolf_executable = re.search(
        r"(?:^|[\\/\" ])overwolflauncher\.exe(?:$|[\" ])",
        command_text,
    )
    if (
        _TRACKER_UID.lower() in f"{value_name} {command_text}"
        or value_leaf in {"valorant tracker", "valoranttracker"}
        or tracker_executable
    ):
        return "valorant_tracker"
    if value_leaf == "overwolf" or overwolf_executable:
        return "overwolf"
    return ""


def _hive_label(hive: Any) -> str:
    return "HKCU" if hive == winreg.HKEY_CURRENT_USER else "HKLM"


def _registry_views(hive: Any) -> List[int]:
    if hive != winreg.HKEY_LOCAL_MACHINE:
        return [0]
    views = [0]
    for view_name in ("KEY_WOW64_64KEY", "KEY_WOW64_32KEY"):
        view = getattr(winreg, view_name, 0)
        if view and view not in views:
            views.append(view)
    return views


def _registry_values(hive: Any, key_path: str, view: int) -> Optional[List[tuple]]:
    access = getattr(winreg, "KEY_READ", 0x20019) | view
    try:
        with winreg.OpenKey(hive, key_path, 0, access) as key:
            values = []
            index = 0
            while True:
                try:
                    values.append(winreg.EnumValue(key, index))
                    index += 1
                except OSError:
                    break
            return values
    except FileNotFoundError:
        return []
    except OSError as exc:
        login_logger.warning(
            "Could not inspect %s startup key %s: %s",
            _hive_label(hive), key_path, exc,
        )
        return None


def _delete_registry_value(hive: Any, key_path: str, value_name: str, view: int) -> Optional[str]:
    access = getattr(winreg, "KEY_SET_VALUE", 0x0002) | view
    try:
        with winreg.OpenKey(hive, key_path, 0, access) as key:
            winreg.DeleteValue(key, value_name)
        return None
    except FileNotFoundError:
        return None
    except OSError as exc:
        return str(exc)


def _registry_value(hive: Any, key_path: str, value_name: str, view: int) -> Optional[tuple]:
    """Return one value/type pair, or ``None`` when the value is absent."""
    access = getattr(winreg, "KEY_READ", 0x20019) | view
    try:
        with winreg.OpenKey(hive, key_path, 0, access) as key:
            return winreg.QueryValueEx(key, value_name)
    except FileNotFoundError:
        return None
    except OSError as exc:
        login_logger.warning(
            "Could not inspect %s startup value %s: %s",
            _hive_label(hive), value_name, exc,
        )
        return None


def _registry_restore_metadata(command: str, value_type: int, view: int, approval: Optional[tuple]) -> Dict[str, str]:
    """Serialize the precise, matched registration Vortex removed."""
    restore = {
        "command": command,
        "value_type": str(value_type),
        "registry_view": str(view),
    }
    if approval and isinstance(approval[0], bytes):
        restore["startup_approval_b64"] = base64.b64encode(approval[0]).decode("ascii")
        restore["startup_approval_type"] = str(approval[1])
    return restore


def _record_startup_item(
    kind: str,
    mechanism: str,
    name: str,
    location: str,
    command: str = "",
) -> Dict[str, str]:
    # Keep enough non-secret identity to explain/recover what Vortex changed;
    # do not persist arbitrary command lines or user data in the DB metadata.
    return {
        "kind": "VAL Tracker" if kind == "valorant_tracker" else "Overwolf",
        "mechanism": mechanism,
        "name": name,
        "location": location,
        "command_present": "1" if command else "0",
    }


def _cleanup_registry_startup(result: Dict[str, List[Dict[str, str]]]) -> None:
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for key_path in (_RUN_KEY, _RUN_ONCE_KEY):
            for view in _registry_views(hive):
                values = _registry_values(hive, key_path, view)
                if values is None:
                    continue
                for value_name, command, value_type in values:
                    kind = _startup_entry_kind(value_name, str(command or ""))
                    if not kind:
                        continue
                    item = _record_startup_item(
                        kind,
                        "registry",
                        str(value_name),
                        f"{_hive_label(hive)}\\{key_path}",
                        str(command or ""),
                    )
                    approval = None
                    if key_path == _RUN_KEY:
                        approval = _registry_value(
                            winreg.HKEY_CURRENT_USER,
                            _STARTUP_APPROVED_RUN_KEY,
                            value_name,
                            0,
                        )
                    item["restore"] = _registry_restore_metadata(
                        str(command or ""), value_type, view, approval,
                    )
                    error = _delete_registry_value(hive, key_path, value_name, view)
                    if error:
                        result["failed"].append({**item, "reason": error})
                        login_logger.warning(
                            "Could not remove %s startup entry: %s", item["kind"], error
                        )
                        continue

                    result["removed"].append(item)
                    login_logger.info("Removed %s startup entry", item["kind"])

                    # Windows keeps per-user StartupApproved state separately
                    # from Run. Remove only the approval with the same exact
                    # value name; Discord, Steam, Riot, Vanguard, and other
                    # entries are never enumerated for deletion.
                    if key_path == _RUN_KEY:
                        approval_error = _delete_registry_value(
                            winreg.HKEY_CURRENT_USER,
                            _STARTUP_APPROVED_RUN_KEY,
                            value_name,
                            0,
                        )
                        if approval_error:
                            approval_item = _record_startup_item(
                                kind,
                                "registry-startup-approved",
                                str(value_name),
                                f"HKCU\\{_STARTUP_APPROVED_RUN_KEY}",
                            )
                            result["failed"].append({
                                **approval_item,
                                "reason": approval_error,
                            })
                            login_logger.warning(
                                "Could not remove %s startup approval: %s",
                                item["kind"], approval_error,
                            )


def cleanup_startup_entries() -> Dict[str, Any]:
    """Remove only the observed, exactly matched Run/RunOnce registrations."""
    result: Dict[str, Any] = {"removed": [], "disabled": [], "failed": []}
    if os.name != "nt":
        return result
    _cleanup_registry_startup(result)
    return result


def _startup_registry_location(location: str) -> Optional[tuple]:
    """Decode only the exact Run/RunOnce locations Vortex is allowed to restore."""
    text = str(location or "")
    for prefix, hive in (("HKCU\\", winreg.HKEY_CURRENT_USER), ("HKLM\\", winreg.HKEY_LOCAL_MACHINE)):
        if text.startswith(prefix):
            key_path = text[len(prefix):]
            if key_path in {_RUN_KEY, _RUN_ONCE_KEY}:
                return hive, key_path
    return None


def _restore_registry_startup_item(item: Dict[str, Any]) -> Optional[str]:
    location = _startup_registry_location(item.get("location", ""))
    restore = item.get("restore")
    name = str(item.get("name") or "")
    if not location or not isinstance(restore, dict) or not name:
        return "missing or invalid Vortex startup metadata"
    command = str(restore.get("command") or "")
    kind = _startup_entry_kind(name, command)
    expected_kind = "valorant_tracker" if item.get("kind") == "VAL Tracker" else "overwolf"
    if not command or kind != expected_kind:
        return "startup metadata no longer matches a Vortex-supported entry"
    try:
        view = int(restore.get("registry_view", "0"))
        value_type = int(restore.get("value_type", str(getattr(winreg, "REG_SZ", 1))))
    except (TypeError, ValueError):
        return "invalid registry restore metadata"

    hive, key_path = location
    # Do not overwrite a value the user or installer created after Vortex
    # removed its old one. This also avoids restoring over a renamed setup.
    values = _registry_values(hive, key_path, view)
    if values is None:
        return "could not inspect the current startup key"
    if any(str(value_name).lower() == name.lower() for value_name, *_ in values):
        return "startup entry now exists; leaving the current value unchanged"
    access = getattr(winreg, "KEY_SET_VALUE", 0x0002) | view
    try:
        with winreg.CreateKeyEx(hive, key_path, 0, access) as key:
            winreg.SetValueEx(key, name, 0, value_type, command)
        approval = restore.get("startup_approval_b64")
        if approval and hive == winreg.HKEY_CURRENT_USER and key_path == _RUN_KEY:
            try:
                approval_value = base64.b64decode(str(approval), validate=True)
                approval_type = int(restore.get("startup_approval_type", "3"))
                with winreg.CreateKeyEx(
                    winreg.HKEY_CURRENT_USER, _STARTUP_APPROVED_RUN_KEY, 0,
                    getattr(winreg, "KEY_SET_VALUE", 0x0002),
                ) as key:
                    winreg.SetValueEx(key, name, 0, approval_type, approval_value)
            except (OSError, ValueError, TypeError) as exc:
                login_logger.warning("Could not restore Overwolf startup approval: %s", exc)
        return None
    except OSError as exc:
        return str(exc)


def restore_startup_entries(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Restore only exact Run/RunOnce entries previously removed by Vortex.

    The observed integration startup mechanism is a Run value. Other cleanup
    mechanisms are intentionally not recreated from incomplete metadata.
    """
    result: Dict[str, Any] = {"restored": [], "skipped": [], "failed": [], "remaining": []}
    if os.name != "nt":
        return result
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("mechanism") != "registry":
            result["skipped"].append({**item, "reason": "unsupported restoration mechanism"})
            continue
        error = _restore_registry_startup_item(item)
        if error is None:
            result["restored"].append(item)
            login_logger.info("Restored %s startup entry", item.get("kind", "Overwolf"))
        elif error == "startup entry now exists; leaving the current value unchanged":
            result["skipped"].append({**item, "reason": error})
            login_logger.info("Leaving existing %s startup entry unchanged", item.get("kind", "Overwolf"))
        else:
            result["failed"].append({**item, "reason": error})
            result["remaining"].append(item)
            login_logger.warning("Could not restore %s startup entry: %s", item.get("kind", "Overwolf"), error)
    return result


def _stop_external_processes() -> Dict[str, Any]:
    infos = _enumerate_processes()
    if not infos:
        if is_running():
            login_logger.warning(
                "Could not inspect Overwolf process ownership; leaving it running"
            )
        return {
            "tracker": [],
            "vortex_telemetry": [],
            "installers": [],
            "overwolf": [],
            "failed": [],
            "blocked_by_unrelated_apps": [],
        }

    targets = _select_shutdown_targets(infos)
    failed: List[int] = []
    if targets["installers"]:
        login_logger.info("Stopping Live Match provider installer")
        failed.extend(_terminate_pids(targets["installers"], "Live Match provider installer"))
    if targets["tracker"]:
        login_logger.info("Stopping VAL Tracker")
        failed.extend(_terminate_pids(targets["tracker"], "VAL Tracker"))
    if targets["vortex"]:
        login_logger.info("Stopping Vortex Telemetry")
        failed.extend(_terminate_pids(targets["vortex"], "Vortex Telemetry"))

    if targets["roots"]:
        login_logger.info("Stopping Overwolf integration")
        failed.extend(_terminate_pids(targets["roots"], "Overwolf"))
    elif targets["root_candidates"] and targets["blocked_labels"]:
        labels = ", ".join(targets["blocked_labels"])
        login_logger.warning(
            "Could not stop Overwolf without closing unrelated app(s): %s", labels
        )

    return {
        "tracker": targets["tracker"],
        "vortex_telemetry": targets["vortex"],
        "installers": targets["installers"],
        "overwolf": targets["roots"],
        "failed": sorted(set(failed)),
        "blocked_by_unrelated_apps": targets["blocked_labels"],
    }


def disable_live_match_integration() -> Dict[str, Any]:
    """Disable provider launches and perform one immediate cleanup pass."""
    global _integration_enabled
    with _integration_state_lock:
        _integration_enabled = False

    login_logger.info("Live Match Features disabled")
    if INSTALL_STATE.get("active"):
        _set_install("cancelled", "Live Match Features are disabled.", 0, active=False)
    if TRACKER_INSTALL_STATE.get("active"):
        _tracker_set("cancelled", "Live Match Features are disabled.", 0, active=False)

    process_result = _stop_external_processes()
    startup_result = cleanup_startup_entries()
    return {
        "success": not process_result["failed"] and not startup_result["failed"],
        "processes": process_result,
        "startup": startup_result,
    }


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

    if not _integration_is_enabled():
        return False
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
        runtime_audit.live_provider("launch Overwolf", path)
        runtime_audit.process_launch(path, "Overwolf tray (Live Match telemetry)")
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
        if not _integration_is_enabled():
            _set_install("cancelled", "Live Match Features are disabled.", 0, active=False)
            return
        guard_path(tmp, "write")
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

        if not _integration_is_enabled():
            _set_install("cancelled", "Live Match Features are disabled.", 0, active=False)
            return
        _set_install("installing", "Installing Overwolf...", 96)
        runtime_audit.process_launch(tmp, "Overwolf installer (silent)")
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

        if not _integration_is_enabled():
            _set_install("cancelled", "Live Match Features are disabled.", 0, active=False)
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

    if not _integration_is_enabled():
        return {"success": False, "message": "Live Match Features are disabled."}
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
    if not _integration_is_enabled():
        return False
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
        if not _integration_is_enabled():
            _tracker_set("cancelled", "Live Match Features are disabled.", 0, active=False)
            return
        guard_path(tmp, "write")
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

        if not _integration_is_enabled():
            _tracker_set("cancelled", "Live Match Features are disabled.", 0, active=False)
            return
        with open(tmp, "rb") as f:
            if f.read(2) != b"MZ":
                _tracker_set("failed", "The Tracker installer didn't download cleanly.",
                             0, active=False)
                return

        _tracker_set("installing", "Installing Valorant Tracker...", 92)
        runtime_audit.process_launch(tmp, "VALORANT Tracker (Overwolf app) installer (silent)")
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

        if not _integration_is_enabled():
            _tracker_set("cancelled", "Live Match Features are disabled.", 0, active=False)
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

    if not _integration_is_enabled():
        return {"success": False, "message": "Live Match Features are disabled."}
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
    if not _integration_is_enabled():
        return
    if not is_installed():
        return  # Overwolf itself comes first; ensure_available() handles that.
    if has_valorant_tracker():
        return
    if not _tracker_install_attempted and not TRACKER_INSTALL_STATE["active"]:
        login_logger.info("Valorant Tracker missing - installing it for live combat stats")
        start_tracker_install()


def status() -> Dict[str, Any]:
    return {
        "integration_enabled": _integration_is_enabled(),
        "installed": is_installed(),
        "running": is_running(),
        "telemetry": {"setup": "manual", "source_dir": "overwolf/vortex-telemetry"},
        "valorant_tracker": {
            "installed": has_valorant_tracker(),
            "install": dict(TRACKER_INSTALL_STATE),
        },
        "install": dict(INSTALL_STATE),
    }
