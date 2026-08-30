"""
Auto-update checker for Vortex Valorant Account Manager.
Checks the version.json manifest committed at the root of the vortex repo,
and if a newer version is available, downloads the Windows installer from the
matching GitHub release and launches it so it can replace the running app.

Manifest format (version.json in RheaIsCute/vortex):
    { "version": "5.5.15", "download_url": "...", "changelog": "..." }
where download_url points at the VortexSetup.exe asset of that release, e.g.
    https://github.com/RheaIsCute/vortex/releases/latest/download/VortexSetup.exe
"""

import os
import sys
import subprocess
import tempfile
from typing import Optional, Dict, Any

import requests
from packaging.version import parse as parse_version, InvalidVersion

from backend.version import APP_VERSION

import json
import time

# The manifest lives at the repo root on the default branch. jsdelivr is listed
# first because GitHub Raw is CDN-cached for minutes after a push and can serve
# a stale manifest; both are consulted and the highest advertised version wins.
VERSION_CHECK_URLS = [
    "https://cdn.jsdelivr.net/gh/RheaIsCute/vortex@master/version.json",
    "https://raw.githubusercontent.com/RheaIsCute/vortex/master/version.json",
]
REQUEST_TIMEOUT = 6.0

# Environment variables the PyInstaller onefile bootloader uses to talk to the
# child process it spawns. They MUST NOT leak into anything we launch during an
# update: the bootloader treats a process that inherits _PYI_PARENT_PROCESS_LEVEL
# as its own re-executed child and then verifies that its parent process runs the
# same executable. When the new Vortex.exe is started by setup.exe/powershell.exe
# that check fails and the app dies with
#   "Security validation failure: parent process has different executable!"
# The names below cover PyInstaller 5.x (_MEIPASS*) and 6.x (_PYI_*).
# Handshake files. The background updater arms itself and writes READY_FLAG,
# and then refuses to touch a single thing until the app writes GO_FLAG on its
# way out. That ordering is what stops an update from killing an app that is
# still running, or from exiting an app into an update that never started.
_TMP = tempfile.gettempdir()
READY_FLAG = os.path.join(_TMP, "vortex_update_ready.flag")
GO_FLAG = os.path.join(_TMP, "vortex_update_go.flag")
LOG_FILE = os.path.join(_TMP, "vortex_updater.log")
INNO_LOG = os.path.join(_TMP, "vortex_inno_install.log")
HANDOFF_TIMEOUT = 12.0

PYI_ENV_VARS = (
    "_MEIPASS",
    "_MEIPASS2",
    "_PYI_ARCHIVE_FILE",
    "_PYI_APPLICATION_HOME_DIR",
    "_PYI_PARENT_PROCESS_LEVEL",
    "_PYI_SPLASH_IPC",
    "_PYI_LINUX_PROCESS_NAME",
)


def check_for_update() -> Optional[Dict[str, Any]]:
    """
    Queries the version.json manifest from the vortex repo (jsdelivr / GitHub Raw).
    Returns a dict with 'version', 'url', and optional 'notes' if a newer
    version is available, otherwise None.
    Never raises - any network/parsing failure is treated as "no update".
    """
    headers = {
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache"
    }

    best: Optional[Dict[str, Any]] = None
    best_parsed = None

    # Every source is consulted rather than stopping at the first reachable
    # one: GitHub Raw is CDN-cached for minutes after a release, so the first
    # source can answer successfully with a stale manifest. Whichever source
    # advertises the highest version wins.
    for base_url in VERSION_CHECK_URLS:
        try:
            url = f"{base_url}?_t={int(time.time())}"
            res = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
            if res.status_code != 200:
                continue

            raw_text = res.text.strip()
            # Handle potential literal escaped newlines from shell formatting
            if "\\r\\n" in raw_text or "\\n" in raw_text:
                raw_text = raw_text.replace("\\r\\n", "\n").replace("\\n", "\n")

            data = json.loads(raw_text)
            remote_version = str(data.get("version", "")).strip()
            download_url = str(data.get("download_url", "")).strip()

            if not remote_version or not download_url:
                continue

            try:
                parsed = parse_version(remote_version)
            except InvalidVersion:
                continue

            if best_parsed is None or parsed > best_parsed:
                best_parsed = parsed
                best = {
                    "version": remote_version,
                    "url": download_url,
                    "notes": data.get("changelog", "")
                }
        except Exception:
            continue

    if best is None or best_parsed is None:
        return None

    try:
        if best_parsed <= parse_version(APP_VERSION):
            return None
    except InvalidVersion:
        return None

    return best


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

        # Always pull a fresh copy from the site. A leftover file from an
        # interrupted attempt would otherwise be re-used (or block the write)
        # and the silent install would fail for no visible reason.
        try:
            if os.path.exists(installer_path):
                os.remove(installer_path)
        except OSError:
            installer_path = os.path.join(
                tmp_dir, f"VortexUpdateSetup{suffix}-{int(time.time())}.exe"
            )

        cache_bust = "&" if "?" in download_url else "?"
        download_url = f"{download_url}{cache_bust}_t={int(time.time())}"

        with requests.get(
            download_url,
            stream=True,
            timeout=30,
            headers={"Cache-Control": "no-cache, no-store", "Pragma": "no-cache"},
        ) as res:
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

        if not os.path.exists(installer_path) or os.path.getsize(installer_path) < 1024 * 100:
            return None

        # Guard against a redirect/error page being saved as "the installer":
        # a real Windows executable always starts with the "MZ" DOS signature.
        with open(installer_path, "rb") as f:
            if f.read(2) != b"MZ":
                try:
                    os.remove(installer_path)
                except OSError:
                    pass
                return None

        return installer_path
    except Exception:
        return None


def reveal_installer(installer_path: str) -> bool:
    """
    Opens Explorer with the downloaded installer selected, so the user can
    run it manually if needed.
    """
    try:
        subprocess.Popen(["explorer.exe", "/select,", os.path.normpath(installer_path)])
        return True
    except Exception:
        try:
            os.startfile(os.path.dirname(installer_path))
            return True
        except Exception:
            return False


def install_dir() -> str:
    """
    Where this copy of Vortex actually lives. Handed to the installer as /DIR
    so an update lands on top of the existing installation instead of laying
    a second copy down somewhere else - which is how people ended up with
    several Vortex installs and had to keep reinstalling by hand.
    """
    if getattr(sys, "frozen", False):
        return os.path.normpath(os.path.dirname(sys.executable))
    return ""


def commit_update() -> None:
    """
    Green-lights the waiting background updater. It refuses to touch anything
    until this file exists, so an app that decided *not* to exit (the handoff
    never confirmed, the user cancelled) is never killed out from under itself.
    Call this immediately before exiting, and nowhere else.
    """
    try:
        with open(GO_FLAG, "w", encoding="utf-8") as f:
            f.write(str(int(time.time())))
    except OSError:
        pass


def apply_and_relaunch(installer_path: str, target_version: str = "") -> bool:
    """
    Spawns a detached background updater that waits for this process to exit,
    installs the new build over the current one, and brings Vortex back up.

    Returns True only once that script has confirmed it is running and armed.
    A False here means nothing has been started and the app must stay open -
    exiting on a spawn that never took hold is what left people with no Vortex
    and a manual reinstall to do.

    The script does nothing at all until commit_update() writes the go flag,
    so a False return can never strand a still-running app.

    target_version, when given, is checked against the version marker the
    installer writes on a real completed install (see vortex_setup.iss). A
    /VERYSILENT run can report exit code 0 while genuinely changing nothing -
    an AV quarantining or blocking the freshly-downloaded, unsigned installer
    mid-run is the usual cause - so the exit code alone was never proof the
    files actually changed. A version mismatch is treated exactly like a
    failed silent install and falls through to a visible retry.
    """
    try:
        tmp_dir = tempfile.gettempdir()
        updater_ps1 = os.path.join(tmp_dir, "vortex_updater.ps1")
        updater_vbs = os.path.join(tmp_dir, "vortex_updater.vbs")

        for stale in (READY_FLAG, GO_FLAG):
            try:
                if os.path.exists(stale):
                    os.remove(stale)
            except OSError:
                pass

        current_pid = os.getpid()
        exe_path = os.path.normpath(sys.executable) if getattr(sys, "frozen", False) else ""
        current_dir = install_dir()
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        program_files = os.environ.get("ProgramFiles", "")
        program_files_x86 = os.environ.get("ProgramFiles(x86)", "")

        default_target = os.path.normpath(os.path.join(local_app_data, "Programs", "Vortex", "Vortex.exe"))
        local_target = os.path.normpath(os.path.join(local_app_data, "Vortex", "Vortex.exe"))
        alt_target = os.path.normpath(os.path.join(program_files, "Vortex", "Vortex.exe"))
        x86_target = os.path.normpath(os.path.join(program_files_x86, "Vortex", "Vortex.exe"))

        norm_installer = os.path.normpath(installer_path)
        ps_var_list = ", ".join(f"'{v}'" for v in PYI_ENV_VARS)
        dir_arg = f' /DIR=\"{current_dir}\"' if current_dir else ""

        ps1_content = f"""# Vortex Automated Background Updater
$logFile = "{LOG_FILE}"
$readyFlag = "{READY_FLAG}"
$goFlag = "{GO_FLAG}"
$ErrorActionPreference = "SilentlyContinue"

function Write-Log($msg) {{
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "[$ts] $msg" | Out-File -FilePath $logFile -Append -Encoding utf8
}}

"=== Vortex Automated Background Updater Started ===" | Out-File -FilePath $logFile -Encoding utf8
Write-Log "Installer:      '{norm_installer}'"
Write-Log "Install dir:    '{current_dir}'"
Write-Log "Target version: '{target_version}'"
Write-Log "Parent PID:     {current_pid}"

# Step 0: Scrub PyInstaller bootloader variables from this process. Everything
# launched from here inherits this environment, and a stray
# _PYI_PARENT_PROCESS_LEVEL makes a freshly started Vortex.exe believe it is a
# bootloader child, check its parent, and abort with
# "Security validation failure: parent process has different executable!".
foreach ($v in @({ps_var_list})) {{
    if (Test-Path "env:$v") {{ Remove-Item "env:$v" -Force -ErrorAction SilentlyContinue }}
    [System.Environment]::SetEnvironmentVariable($v, $null, 'Process')
}}

# Step 1: Tell Vortex we are armed, then wait for its explicit go-ahead.
# Without the go flag nothing below runs, so an app that changed its mind
# about updating is never killed and never left uninstalled.
New-Item -Path $readyFlag -ItemType File -Force | Out-Null
Write-Log "Armed - waiting for the go flag."

$go = $false
for ($i = 0; $i -lt 120; $i++) {{
    if (Test-Path $goFlag) {{ $go = $true; break }}
    Start-Sleep -Milliseconds 500
}}
if (-not $go) {{
    Write-Log "No go flag after 60s - Vortex is still running. Aborting without changes."
    Remove-Item -Path $readyFlag -Force -ErrorAction SilentlyContinue
    exit 0
}}
Write-Log "Go flag received."

# Step 2: Wait for the parent to actually exit, then clear any stragglers so
# the installer isn't fighting a locked Vortex.exe.
for ($i = 0; $i -lt 40; $i++) {{
    if (-not (Get-Process -Id {current_pid} -ErrorAction SilentlyContinue)) {{ break }}
    Start-Sleep -Milliseconds 500
}}
Get-Process -Name "Vortex" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 700

# Step 3: Install over the existing copy. /DIR pins it to where Vortex already
# lives so the update replaces the install instead of adding another one.
Write-Log "Running the installer silently..."
# Built as one string rather than an array: PowerShell 5.1 re-quotes array
# elements that contain spaces, which mangles a quoted /DIR under Program Files.
$installArgs = '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /NOCANCEL /LOG="{INNO_LOG}"{dir_arg}'
$installProc = Start-Process -FilePath '{norm_installer}' -ArgumentList $installArgs -Wait -PassThru -ErrorAction SilentlyContinue
$exitCode = if ($installProc) {{ $installProc.ExitCode }} else {{ -1 }}
Write-Log "Installer exit code: $exitCode"
Start-Sleep -Seconds 1

# Step 4: Work out what to start. The copy we were launched from is the first
# guess - the whole point of /DIR is that it is still the right path.
$candidates = @(
    '{exe_path}',
    '{default_target}',
    "$env:LOCALAPPDATA\\Programs\\Vortex\\Vortex.exe",
    '{local_target}',
    '{alt_target}',
    '{x86_target}'
)

# Inno records DisplayName as "<AppName> version <AppVersion>", so an exact
# match on "Vortex" never hits - hence the wildcard.
$reg = Get-ItemProperty "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*" -ErrorAction SilentlyContinue |
       Where-Object {{ $_.DisplayName -like "Vortex*" -and $_.InstallLocation }}
foreach ($r in $reg) {{
    $candidates = @((Join-Path $r.InstallLocation "Vortex.exe")) + $candidates
}}

function Find-Vortex {{
    foreach ($c in $candidates) {{
        if ($c -and (Test-Path $c)) {{ return $c }}
    }}
    return ""
}}

$targetExe = Find-Vortex

# Step 4.5: A clean exit code is not proof the install actually did anything -
# Defender or another AV silently blocking/quarantining the unsigned installer
# mid-run is the usual way a /VERYSILENT run reports success while changing
# nothing. The version marker Inno writes on a real completed install is the
# actual check.
$verified = $true
$expectedVersion = '{target_version}'
if ($exitCode -eq 0 -and $targetExe -and $expectedVersion) {{
    $verified = $false
    $marker = Join-Path (Split-Path -Parent $targetExe) "installed_version.txt"
    $installedVersion = ""
    for ($i = 0; $i -lt 6; $i++) {{
        if (Test-Path $marker) {{
            $installedVersion = (Get-Content $marker -Raw -ErrorAction SilentlyContinue).Trim()
            if ($installedVersion -eq $expectedVersion) {{ $verified = $true; break }}
        }}
        Start-Sleep -Milliseconds 500
    }}
    Write-Log "Post-install version check: expected '$expectedVersion', found '$installedVersion', verified=$verified"
}}

# Step 5: A failed or unverified silent install gets one visible run so the
# user can see and answer whatever actually went wrong (elevation, antivirus,
# a locked file) instead of the update silently no-op-ing.
if ($exitCode -ne 0 -or -not $verified) {{
    Write-Log "Silent install failed or unverified - showing the installer."
    Start-Process -FilePath '{norm_installer}' -ArgumentList '/SP-' -Wait -ErrorAction SilentlyContinue
    $targetExe = Find-Vortex
}}

# Step 6: Bring Vortex back, and confirm it actually came back. This is the
# step that used to fail silently and leave nothing running at all.
function Start-Vortex($path) {{
    if (-not $path) {{ return $false }}
    Write-Log "Launching: $path"
    Start-Process -FilePath "$path" -WorkingDirectory (Split-Path -Parent "$path")
    for ($i = 0; $i -lt 30; $i++) {{
        Start-Sleep -Milliseconds 500
        if (Get-Process -Name "Vortex" -ErrorAction SilentlyContinue) {{ return $true }}
    }}
    return $false
}}

$running = Start-Vortex $targetExe
if (-not $running) {{
    Write-Log "First launch attempt produced no process - retrying."
    $running = Start-Vortex (Find-Vortex)
}}

# Step 7: Last resort. Whatever happened to the install, the user gets their
# app back rather than an empty desktop and a manual reinstall.
if (-not $running -and (Test-Path '{exe_path}')) {{
    Write-Log "Falling back to the copy that was already installed."
    $running = Start-Vortex '{exe_path}'
}}
if (-not $running) {{
    Write-Log "ERROR: Vortex could not be started. Opening the installer for the user."
    Start-Process -FilePath 'explorer.exe' -ArgumentList '/select,', '{norm_installer}'
}}

# Step 8: Clean up.
Start-Sleep -Seconds 3
Remove-Item -Path $readyFlag -Force -ErrorAction SilentlyContinue
Remove-Item -Path $goFlag -Force -ErrorAction SilentlyContinue
if ($running) {{ Remove-Item -Path '{norm_installer}' -Force -ErrorAction SilentlyContinue }}
Write-Log "Update cycle complete (relaunched: $running)."
"""
        with open(updater_ps1, "w", encoding="utf-8") as f:
            f.write(ps1_content)

        vbs_content = (
            'CreateObject("Wscript.Shell").Run '
            '"powershell.exe -NonInteractive -NoProfile -ExecutionPolicy Bypass '
            f'-File ""{updater_ps1}""", 0, False\n'
        )
        with open(updater_vbs, "w", encoding="utf-8") as f:
            f.write(vbs_content)

        # Clean the environment handed to the updater of every PyInstaller
        # bootloader variable, so the poisoned values never reach the installer
        # or the relaunched Vortex.exe further down the process chain.
        clean_env = os.environ.copy()
        for var in PYI_ENV_VARS:
            clean_env.pop(var, None)
            os.environ.pop(var, None)

        try:
            subprocess.Popen(["wscript.exe", updater_vbs], env=clean_env)
        except Exception:
            # Fallback to a direct powershell spawn if wscript is unavailable.
            subprocess.Popen(
                [
                    "powershell.exe",
                    "-NonInteractive",
                    "-NoProfile",
                    "-ExecutionPolicy", "Bypass",
                    "-File", updater_ps1
                ],
                creationflags=0x08000000,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=clean_env
            )

        # Wait for the script to say it is alive. Everything after this point
        # is safe; without it, the app would be exiting on faith.
        deadline = time.time() + HANDOFF_TIMEOUT
        while time.time() < deadline:
            if os.path.exists(READY_FLAG):
                return True
            time.sleep(0.1)
        return False
    except Exception:
        return False
