"""
Auto-update checker for Vortex Valorant Account Manager.
Checks a small static JSON version manifest hosted on Vercel (asarii.xyz),
and if a newer version is available, downloads the Windows installer and
launches it so it can replace the running app.

Manifest format matches the existing precedent in the RheaIsCute/asa repo
(see public/autovgc/version.json):
    { "version": "3.1.0", "download_url": "...", "changelog": "..." }
"""

import os
import subprocess
import tempfile
from typing import Optional, Dict, Any

import requests
from packaging.version import parse as parse_version, InvalidVersion

from backend.version import APP_VERSION

VERSION_CHECK_URL = "https://asarii.xyz/vortex/version.json"
REQUEST_TIMEOUT = 6.0


def check_for_update() -> Optional[Dict[str, Any]]:
    """
    Queries the version manifest. Returns a dict with 'version', 'url', and
    optional 'notes' if a newer version is available, otherwise None.
    Never raises - any network/parsing failure is treated as "no update".
    """
    try:
        res = requests.get(VERSION_CHECK_URL, timeout=REQUEST_TIMEOUT)
        if res.status_code != 200:
            return None

        data = res.json()
        remote_version = str(data.get("version", "")).strip()
        download_url = str(data.get("download_url", "")).strip()

        if not remote_version or not download_url:
            return None

        try:
            is_newer = parse_version(remote_version) > parse_version(APP_VERSION)
        except InvalidVersion:
            return None

        if not is_newer:
            return None

        return {
            "version": remote_version,
            "url": download_url,
            "notes": data.get("changelog", "")
        }
    except Exception:
        return None


def download_installer(download_url: str, version: str = "", progress_cb=None) -> Optional[str]:
    """
    Downloads the installer .exe to a temp file. Returns the local path on
    success, or None on failure. progress_cb(bytes_downloaded, total_bytes)
    is called periodically if provided (total_bytes may be 0 if unknown).

    The filename includes the target version (e.g. VortexUpdateSetup-3.1.3.exe)
    rather than a fixed name. Windows Explorer/Shell caches an extracted icon
    bitmap per file path, so re-downloading a differently-updated .exe to the
    exact same path can keep showing a stale icon from a previous version
    even though the file's bytes (and embedded icon) actually changed. A
    version-suffixed filename means every update lands on a fresh path the
    shell has never cached an icon for.
    """
    try:
        tmp_dir = tempfile.gettempdir()
        suffix = f"-{version}" if version else ""
        installer_path = os.path.join(tmp_dir, f"VortexUpdateSetup{suffix}.exe")

        with requests.get(download_url, stream=True, timeout=30) as res:
            if res.status_code != 200:
                return None

            total = int(res.headers.get("Content-Length", 0))
            downloaded = 0

            with open(installer_path, "wb") as f:
                for chunk in res.iter_content(chunk_size=1024 * 256):
                    if not chunk:
                        continue
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_cb:
                        try:
                            progress_cb(downloaded, total)
                        except Exception:
                            pass

        if not os.path.exists(installer_path) or os.path.getsize(installer_path) == 0:
            return None

        return installer_path
    except Exception:
        return None


def reveal_installer(installer_path: str) -> bool:
    """
    Opens Explorer with the downloaded installer selected, so the user can
    run it themselves.

    We deliberately do NOT launch the installer from this process. Some
    security software (Avira's self-protection, for one) blocks one
    executable spawning an installer and shows a scary dialog like
    "Security validation failure: parent process has different executable!"
    - that message comes from the AV, not from us or Inno Setup (the string
    appears nowhere in Inno Setup's source or in our binaries). A user
    double-clicking the file themselves isn't blocked, so handing off to
    Explorer is the approach that works regardless of what AV is installed.
    """
    try:
        subprocess.Popen(["explorer.exe", "/select,", os.path.normpath(installer_path)])
        return True
    except Exception:
        # Fall back to just opening the containing folder.
        try:
            os.startfile(os.path.dirname(installer_path))
            return True
        except Exception:
            return False
