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
import time
import shutil
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
