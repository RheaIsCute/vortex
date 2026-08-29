"""
Local VALORANT display and gameplay settings.

Riot doesn't expose crosshair, sensitivity, keybinds, or video settings
through any API - they live entirely in per-account config files that the
game itself reads at startup:

    %LOCALAPPDATA%\\VALORANT\\Saved\\Config\\<puuid>-<shard>\\
        Windows\\RiotUserSettings.ini        - crosshair, audio, mouse
                                                sensitivity, keybinds, HUD
        WindowsClient\\GameUserSettings.ini   - display mode, resolution,
                                                graphics quality

The folder only exists once that account has actually signed into VALORANT
on this PC - Riot creates it on first launch, not on Riot Client login. Every
function here is best-effort and returns False/None rather than raising when
that folder isn't there yet, since "hasn't logged in here before" is a
routine, expected case rather than an error.
"""

import os
import sys
import json
import time
import shutil
from datetime import datetime
from typing import Any, Dict, Optional

GAMEPLAY_REL = os.path.join("Windows", "RiotUserSettings.ini")
VIDEO_REL = os.path.join("WindowsClient", "GameUserSettings.ini")
# The keybind table lives in its own file next to the video settings, so
# copying only the two .ini files left keybinds behind - "copy my settings"
# is not much use if the binds don't come with them.
KEYBINDS_REL = os.path.join("WindowsClient", "BackupKeybinds.json")

# The section header Unreal writes display-mode keys under, and the keys
# that all have to agree or the game silently reverts to windowed/fullscreen
# on the next launch (LastConfirmedFullscreenMode exists specifically to
# undo a mode the game couldn't confirm actually displayed correctly).
VIDEO_SECTION = "[/script/shootergame.shootergameusersettings]"
FULLSCREEN_KEYS = ("FullscreenMode", "LastConfirmedFullscreenMode", "PreferredFullscreenMode")
BORDERLESS_VALUE = "1"  # Unreal's WindowedFullscreen enum value


def config_root() -> str:
    local = os.environ.get("LOCALAPPDATA", "")
    return os.path.join(local, "VALORANT", "Saved", "Config")


def account_dir(puuid: str) -> Optional[str]:
    """
    The config folder for one puuid, or None if this account has never
    signed into VALORANT on this PC. Folder names are "<puuid>-<shard>" -
    matched by prefix rather than assuming the shard suffix, since that
    format isn't documented anywhere. If more than one somehow matches
    (a shard change after a region move), the most recently touched wins.
    """
    if not puuid:
        return None
    root = config_root()
    if not os.path.isdir(root):
        return None

    prefix = puuid.lower() + "-"
    best, best_mtime = None, -1.0
    try:
        for name in os.listdir(root):
            if not name.lower().startswith(prefix):
                continue
            path = os.path.join(root, name)
            if not os.path.isdir(path):
                continue
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                mtime = 0.0
            if mtime > best_mtime:
                best, best_mtime = path, mtime
    except OSError:
        return None
    return best


def has_config(puuid: str) -> bool:
    d = account_dir(puuid)
    return bool(d and os.path.isfile(os.path.join(d, VIDEO_REL)))


def wait_for_account(puuid: str, timeout: float = 90.0) -> bool:
    """
    Blocks until this account's config folder shows up, for a first-ever
    login on this PC. Riot creates it within the first few seconds of the
    game actually starting (not the Riot Client login), so this is only
    worth calling from a background thread after a launch has been kicked
    off - never inline on a request.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if has_config(puuid):
            return True
        time.sleep(1.5)
    return False


def _read_lines(path: str):
    try:
        with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
            return f.readlines()
    except OSError:
        return None


def _atomic_write(path: str, lines) -> bool:
    tmp = path + ".vortex-tmp"
    try:
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.writelines(lines)
        os.replace(tmp, path)
        return True
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


def force_borderless(puuid: str) -> Optional[bool]:
    """
    Sets Display Mode to Windowed Fullscreen (borderless) for this account.
    Returns True if it's now (or already was) set, False if the write
    failed, or None if the account has no config folder yet - the caller
    decides whether that's worth watching for.
    """
    d = account_dir(puuid)
    if not d:
        return None
    path = os.path.join(d, VIDEO_REL)
    lines = _read_lines(path)
    if lines is None:
        return None

    out = []
    changed = False
    in_section = False
    section_seen_keys = set()

    def flush_missing_keys():
        nonlocal changed
        for key in FULLSCREEN_KEYS:
            if key not in section_seen_keys:
                out.append(f"{key}={BORDERLESS_VALUE}\n")
                changed = True

    for raw in lines:
        stripped = raw.strip()
        if stripped.startswith("["):
            if in_section:
                flush_missing_keys()
            in_section = stripped.lower() == VIDEO_SECTION
            section_seen_keys = set()
            out.append(raw)
            continue

        if in_section:
            matched_key = next(
                (k for k in FULLSCREEN_KEYS if stripped.lower().startswith(k.lower() + "=")), None
            )
            if matched_key:
                section_seen_keys.add(matched_key)
                current_val = stripped.split("=", 1)[1].strip() if "=" in stripped else ""
                if current_val != BORDERLESS_VALUE:
                    out.append(f"{matched_key}={BORDERLESS_VALUE}\n")
                    changed = True
                else:
                    out.append(raw)
                continue

        out.append(raw)

    if in_section:
        flush_missing_keys()

    if not changed:
        return True
    return _atomic_write(path, out)


def copy_settings(src_puuid: str, dst_puuid: str,
                  gameplay: bool = True, video: bool = True) -> Dict[str, Any]:
    """
    Copies crosshair/sensitivity/keybinds and/or video/graphics wholesale
    from one account's local config to another's, on this same PC. Both
    accounts need to have signed into VALORANT here at least once - Riot
    only creates the folder on first game launch, and there's nothing to
    seed a brand-new one from until then.
    """
    if src_puuid == dst_puuid:
        return {"success": False, "message": "Source and target are the same account."}

    src_dir = account_dir(src_puuid)
    if not src_dir:
        return {"success": False, "message":
                "The source account hasn't signed into VALORANT on this PC yet, "
                "so there's nothing to copy from."}

    dst_dir = account_dir(dst_puuid)
    if not dst_dir:
        return {"success": False, "message":
                "This account hasn't signed into VALORANT on this PC yet. "
                "Log it in and let the game reach the main menu once, then copy again."}

    plan = []
    if gameplay:
        plan.append((GAMEPLAY_REL, "crosshair, sensitivity & HUD"))
        plan.append((KEYBINDS_REL, "keybinds"))
    if video:
        plan.append((VIDEO_REL, "video & graphics"))

    copied = []
    missing = []
    for rel, label in plan:
        src_f = os.path.join(src_dir, rel)
        if not os.path.isfile(src_f):
            missing.append(label)
            continue
        dst_f = os.path.join(dst_dir, rel)
        try:
            os.makedirs(os.path.dirname(dst_f), exist_ok=True)
            shutil.copyfile(src_f, dst_f)
            copied.append(label)
        except OSError:
            missing.append(label)
            continue

    if not copied:
        return {"success": False, "message": "Nothing to copy - the source account's settings files weren't found."}

    message = f"Copied {_join(copied)}."
    if missing:
        message += f" ({_join(missing)} not found on the source account.)"
    return {"success": True, "message": message, "copied": copied, "missing": missing}


def _join(items) -> str:
    """'a', 'a and b', 'a, b and c'."""
    items = list(items)
    if len(items) <= 1:
        return items[0] if items else ""
    return f"{', '.join(items[:-1])} and {items[-1]}"


def describe(puuid: str) -> Dict[str, Any]:
    """
    What an account actually has stored on this PC - used to tell the user
    exactly what a copy would carry across, rather than making them guess.
    """
    d = account_dir(puuid)
    if not d:
        return {"found": False, "files": []}
    files = []
    for rel, label in ((GAMEPLAY_REL, "Crosshair, sensitivity & HUD"),
                       (KEYBINDS_REL, "Keybinds"),
                       (VIDEO_REL, "Video & graphics")):
        path = os.path.join(d, rel)
        files.append({"label": label, "present": os.path.isfile(path)})
    return {"found": True, "path": d, "files": files}


# --------------------------------------------------------------------------
# SETTINGS PRESET
#
# A copy of one account's local VALORANT settings, kept in Vortex's own data
# directory rather than being read out of the source account's folder every
# time it's needed.
#
# Snapshotting matters because a source account's folder is not stable:
# VALORANT rewrites it whenever that account plays, and it can only be read
# at all while Vortex knows which puuid the account has. Capturing from
# whichever account is signed in right now needs no stored identity at all -
# the live session supplies the puuid - which is what makes a preset possible
# for accounts Vortex has never seen before.
# --------------------------------------------------------------------------

FILE_SPECS = (
    (GAMEPLAY_REL, "Crosshair, sensitivity & HUD", "RiotUserSettings.ini"),
    (KEYBINDS_REL, "Keybinds", "BackupKeybinds.json"),
    (VIDEO_REL, "Video & graphics", "GameUserSettings.ini"),
)


def preset_dir() -> str:
    if getattr(sys, "frozen", False):
        base = os.path.join(os.getenv("LOCALAPPDATA") or os.path.expanduser("~"), "Vortex")
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "settings_preset")


def _ini_value(text: str, key: str) -> str:
    """Value of `key=` from an ini/settings body, or ''."""
    needle = key.lower() + "="
    for line in text.splitlines():
        s = line.strip()
        if s.lower().startswith(needle):
            return s.split("=", 1)[1].strip()
    return ""


FULLSCREEN_LABELS = {"0": "Fullscreen", "1": "Windowed Fullscreen (borderless)", "2": "Windowed"}


def summarize_files(folder: str) -> Dict[str, Any]:
    """
    A human-readable account of what a settings folder actually contains.

    This is what the UI shows after a copy, so that "it copied" can be checked
    against real values - a crosshair name, a sensitivity, a keybind count -
    rather than taken on trust.
    """
    files = []
    details: Dict[str, Any] = {}

    for rel, label, filename in FILE_SPECS:
        path = os.path.join(folder, rel)
        present = os.path.isfile(path)
        size = os.path.getsize(path) if present else 0
        entry = {"label": label, "file": filename, "present": present, "size": size}

        if present and rel == GAMEPLAY_REL:
            try:
                with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
                    text = f.read()
                details["crosshair_profile"] = _ini_value(text, "EAresStringSettingName::CrosshairProfileName")
                details["sensitivity"] = _ini_value(text, "EAresFloatSettingName::MouseSensitivity")
                details["scoped_sensitivity"] = _ini_value(text, "EAresFloatSettingName::MouseSensitivityZoomed")
                details["settings_lines"] = len([l for l in text.splitlines() if "=" in l])
            except OSError:
                pass

        if present and rel == KEYBINDS_REL:
            try:
                with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
                    data = json.load(f)
                mappings = data.get("actionMappings") or []
                details["keybind_count"] = len(mappings)
                details["agent_keybinds"] = len(
                    [m for m in mappings if (m.get("characterName") or "None") != "None"]
                )
            except (OSError, ValueError):
                pass

        if present and rel == VIDEO_REL:
            try:
                with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
                    text = f.read()
                mode = _ini_value(text, "FullscreenMode")
                details["display_mode"] = FULLSCREEN_LABELS.get(mode, f"Unknown ({mode})") if mode else ""
                w = _ini_value(text, "ResolutionSizeX")
                h = _ini_value(text, "ResolutionSizeY")
                details["resolution"] = f"{w} x {h}" if w and h else ""
            except OSError:
                pass

        files.append(entry)

    return {"files": files, "details": details}


def capture_preset(puuid: str, label: str = "") -> Dict[str, Any]:
    """
    Snapshots one account's settings into Vortex's own storage and reports
    exactly what was taken, file by file.
    """
    if not puuid:
        return {"success": False, "message": "No account is signed in, so there's nothing to capture."}

    src = account_dir(puuid)
    if not src:
        return {"success": False, "message":
                "This account has no VALORANT settings on this PC yet. "
                "Play one match on it, then capture again."}

    dest = preset_dir()
    try:
        os.makedirs(dest, exist_ok=True)
    except OSError as e:
        return {"success": False, "message": f"Couldn't create the preset folder: {e}"}

    copied, missing = [], []
    for rel, lbl, filename in FILE_SPECS:
        src_f = os.path.join(src, rel)
        if not os.path.isfile(src_f):
            missing.append(lbl)
            continue
        try:
            dst_f = os.path.join(dest, rel)
            os.makedirs(os.path.dirname(dst_f), exist_ok=True)
            shutil.copyfile(src_f, dst_f)
            copied.append(lbl)
        except OSError:
            missing.append(lbl)

    if not copied:
        return {"success": False, "message":
                "None of this account's settings files could be read."}

    summary = summarize_files(dest)
    meta = {
        "puuid": puuid,
        "label": label,
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "copied": copied,
        "missing": missing,
    }
    try:
        with open(os.path.join(dest, "preset.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
    except OSError:
        pass

    return {
        "success": True,
        "message": f"Saved {_join(copied)} from {label or 'the signed-in account'}.",
        "meta": meta,
        **summary,
    }


def describe_preset() -> Dict[str, Any]:
    """What's currently stored as the preset, if anything."""
    dest = preset_dir()
    meta = {}
    try:
        with open(os.path.join(dest, "preset.json"), "r", encoding="utf-8") as f:
            meta = json.load(f)
    except (OSError, ValueError):
        pass

    if not any(os.path.isfile(os.path.join(dest, rel)) for rel, _, _ in FILE_SPECS):
        return {"exists": False, "meta": meta, "files": [], "details": {}}

    return {"exists": True, "meta": meta, **summarize_files(dest)}


def apply_preset(puuid: str, label: str = "") -> Dict[str, Any]:
    """
    Writes the stored preset onto one account, and reports what landed.

    Each file is verified by size after the write rather than trusting that
    copyfile returning meant the game will see it - the target folder is one
    VALORANT also writes to.
    """
    dest = preset_dir()
    if not any(os.path.isfile(os.path.join(dest, rel)) for rel, _, _ in FILE_SPECS):
        return {"success": False, "message":
                "No preset saved yet - capture one from a signed-in account first."}

    if not puuid:
        return {"success": False, "message": "No account is signed in to apply the preset to."}

    target = account_dir(puuid)
    if not target:
        return {"success": False, "message":
                "This account has no VALORANT settings folder on this PC yet. "
                "Play one match on it, then apply again."}

    applied, failed = [], []
    for rel, lbl, filename in FILE_SPECS:
        src_f = os.path.join(dest, rel)
        if not os.path.isfile(src_f):
            continue
        dst_f = os.path.join(target, rel)
        try:
            os.makedirs(os.path.dirname(dst_f), exist_ok=True)
            shutil.copyfile(src_f, dst_f)
            if os.path.getsize(dst_f) == os.path.getsize(src_f):
                applied.append(lbl)
            else:
                failed.append(lbl)
        except OSError as e:
            failed.append(f"{lbl} ({e.strerror or e})")

    if not applied:
        return {"success": False, "message": "Nothing could be written to this account.",
                "applied": [], "failed": failed}

    message = f"Applied {_join(applied)} to {label or 'this account'}."
    if failed:
        message += f" Couldn't write {_join(failed)}."
    return {
        "success": True,
        "message": message,
        "applied": applied,
        "failed": failed,
        **summarize_files(target),
    }
