r"""Local VALORANT display-mode settings.

VALORANT stores video preferences per account under
``%LOCALAPPDATA%\VALORANT\Saved\Config\<puuid>-<shard>``.  This module only
supports only the optional windowed-borderless preference.
"""

import os
import sys
from typing import Optional


VIDEO_REL = os.path.join("WindowsClient", "GameUserSettings.ini")
VIDEO_SECTION = "[/script/shootergame.shootergameusersettings]"
FULLSCREEN_KEYS = (
    "FullscreenMode",
    "LastConfirmedFullscreenMode",
    "PreferredFullscreenMode",
)
BORDERLESS_VALUE = "1"


def remove_legacy_profile_data() -> None:
    """Delete files left by the removed settings-profile/preset feature."""
    if getattr(sys, "frozen", False):
        base = os.path.join(os.getenv("LOCALAPPDATA") or os.path.expanduser("~"), "Vortex")
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    root = os.path.join(base, "settings_preset")
    known_files = (
        os.path.join(root, "preset.json"),
        os.path.join(root, "Windows", "RiotUserSettings.ini"),
        os.path.join(root, "WindowsClient", "BackupKeybinds.json"),
        os.path.join(root, "WindowsClient", "GameUserSettings.ini"),
    )
    for path in known_files:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        except OSError:
            pass
    for directory in (
        os.path.join(root, "Windows"),
        os.path.join(root, "WindowsClient"),
        root,
    ):
        try:
            os.rmdir(directory)
        except OSError:
            pass


def config_root() -> str:
    local = os.environ.get("LOCALAPPDATA", "")
    return os.path.join(local, "VALORANT", "Saved", "Config")


def account_dir(puuid: str) -> Optional[str]:
    """Return the newest local config directory matching a Riot PUUID."""
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
    directory = account_dir(puuid)
    return bool(directory and os.path.isfile(os.path.join(directory, VIDEO_REL)))


def _read_lines(path: str):
    try:
        with open(path, "r", encoding="utf-8-sig", errors="ignore") as handle:
            return handle.readlines()
    except OSError:
        return None


def _atomic_write(path: str, lines) -> bool:
    temporary = path + ".vortex-tmp"
    try:
        with open(temporary, "w", encoding="utf-8", newline="") as handle:
            handle.writelines(lines)
        os.replace(temporary, path)
        return True
    except OSError:
        try:
            os.remove(temporary)
        except OSError:
            pass
        return False


def force_borderless(puuid: str) -> Optional[bool]:
    """Set one account to Windowed Fullscreen.

    Returns ``True`` when applied/already set, ``False`` on a failed write,
    and ``None`` when that account has no local config yet.
    """
    directory = account_dir(puuid)
    if not directory:
        return None
    path = os.path.join(directory, VIDEO_REL)
    lines = _read_lines(path)
    if lines is None:
        return None

    output = []
    changed = False
    in_section = False
    section_seen_keys = set()

    def flush_missing_keys():
        nonlocal changed
        for key in FULLSCREEN_KEYS:
            if key not in section_seen_keys:
                output.append(f"{key}={BORDERLESS_VALUE}\n")
                changed = True

    for raw in lines:
        stripped = raw.strip()
        if stripped.startswith("["):
            if in_section:
                flush_missing_keys()
            in_section = stripped.lower() == VIDEO_SECTION
            section_seen_keys = set()
            output.append(raw)
            continue

        if in_section:
            matched_key = next(
                (key for key in FULLSCREEN_KEYS
                 if stripped.lower().startswith(key.lower() + "=")),
                None,
            )
            if matched_key:
                section_seen_keys.add(matched_key)
                current = stripped.split("=", 1)[1].strip() if "=" in stripped else ""
                if current != BORDERLESS_VALUE:
                    output.append(f"{matched_key}={BORDERLESS_VALUE}\n")
                    changed = True
                else:
                    output.append(raw)
                continue

        output.append(raw)

    if in_section:
        flush_missing_keys()

    return True if not changed else _atomic_write(path, output)
