r"""Local VALORANT config housekeeping.

The only thing left here is cleanup of files written by the long-removed
settings-profile/preset feature; :func:`remove_legacy_profile_data` is called
once on server start.
"""

import os
import sys


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
