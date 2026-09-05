# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Vortex | Valorant Account Manager.
Builds a windowed one-DIRECTORY bundle. Run via:
    pyinstaller build_exe.spec --clean
Output: dist/Vortex/  (Vortex.exe + _internal/)

Deliberately NOT --onefile. The onefile bootloader re-executes itself as a
child process and passes _PYI_ARCHIVE_FILE / _PYI_PARENT_PROCESS_LEVEL to it
through the environment. Those variables are inherited by everything the app
launches, so during an auto-update they travelled
    Vortex.exe -> wscript -> powershell -> VortexSetup.exe -> new Vortex.exe
and the freshly installed Vortex.exe - sitting at the exact path recorded in
_PYI_ARCHIVE_FILE - concluded it was a bootloader child, checked its parent
process, found powershell.exe instead of itself, and aborted with
    "Security validation failure: parent process has different executable!"
The onedir bootloader performs no such re-exec and no parent verification, so
it starts correctly even from a process whose environment still carries those
variables. That is what makes one-click updating work for copies of Vortex
that are already installed and still carry the old updater.
"""

from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
    copy_metadata,
)

block_cipher = None

_UIAUTOMATION_BINARIES = collect_dynamic_libs("uiautomation")
_UIAUTOMATION_BIN_DIRS = sorted(
    {str(Path(source).parent) for source, _destination in _UIAUTOMATION_BINARIES}
)
_UIAUTOMATION_DATA = [
    item
    for item in collect_data_files("uiautomation")
    if not item[0].lower().endswith(".dll")
]

# `logo-source.png` is design-source artwork with no runtime reference.  The
# map URLs below are served by the frontend alias table in app.js; each file
# is byte-for-byte identical to its retained counterpart.  Keep source-cache
# inputs intact for cache-maintenance tooling, but omit these unnecessary
# copies from the packaged frontend.
_EXCLUDED_FRONTEND_DATA = {
    "assets/logo-source.png",
    "assets/valorant-api/maps/4490f1d6-4818-bf5f-9b3a-9c9a8dbb52ed/listviewicon.png",
    "assets/valorant-api/maps/4490f1d6-4818-bf5f-9b3a-9c9a8dbb52ed/splash.png",
    "assets/valorant-api/maps/a264de0f-4a04-9c78-c97a-a6b192ce6e86/listviewicon.png",
    "assets/valorant-api/maps/a264de0f-4a04-9c78-c97a-a6b192ce6e86/splash.png",
    "assets/valorant-api/maps/a38a3f9a-4042-844c-8970-a3ac2f7ce93d/listviewicon.png",
    "assets/valorant-api/maps/a38a3f9a-4042-844c-8970-a3ac2f7ce93d/splash.png",
    "assets/valorant-api/maps/a9009649-421f-d5d5-f80c-0cbe02c125bb/listviewicon.png",
    "assets/valorant-api/maps/a9009649-421f-d5d5-f80c-0cbe02c125bb/splash.png",
    "assets/valorant-api/maps/1f10dab3-4294-3827-fa35-c2aa00213cf3/listviewicon.png",
    "assets/valorant-api/maps/1f10dab3-4294-3827-fa35-c2aa00213cf3/splash.png",
}

# `get_weapon_data()` uses weapon ids only to resolve display names. The
# Inventory UI renders equipped skin art and tier icons, never the cached
# weapon display/killstream images. Excluding this whole media-only directory
# therefore cannot remove an image URL produced by the application.
_EXCLUDED_FRONTEND_PREFIXES = (
    "assets/valorant-api/weapons/",
)


def frontend_datas():
    """Return every static frontend file except proven local-URL aliases."""
    root = Path("frontend")
    datas = []
    for source in root.rglob("*"):
        if not source.is_file():
            continue
        relative = source.relative_to(root).as_posix()
        if (relative in _EXCLUDED_FRONTEND_DATA
                or any(relative.startswith(prefix) for prefix in _EXCLUDED_FRONTEND_PREFIXES)):
            continue
        datas.append((str(source), str(Path("frontend") / source.relative_to(root).parent)))
    return datas

hidden_imports = [
    # multiprocessing's frozen bootstrap imports socket dynamically; keep
    # the stdlib module in the bundle so packaged startup cannot fail with
    # "No module named 'socket'" before the WebView is created.
    "socket",
    "win32timezone",
    # UI Automation is how the Riot Client's "Stay signed in" checkbox is
    # found and set. comtypes generates its typelib wrappers at runtime, so
    # the generated package has to be collected explicitly or the frozen
    # build can't talk to UIA at all.
    "uiautomation",
    "comtypes",
    "comtypes.stream",
] + collect_submodules("uiautomation") + collect_submodules("comtypes.gen") \
    + collect_submodules("uvicorn") + collect_submodules("websockets") \
    + collect_submodules("wsproto") + collect_submodules("webview")

a = Analysis(
    ["app.py"],
    # Also expose the UIA bin directory to PyInstaller's ctypes scanner. The
    # files are already explicit binaries above; this lets the scanner resolve
    # their basename loads instead of emitting a false "not found" warning.
    pathex=_UIAUTOMATION_BIN_DIRS,
    binaries=_UIAUTOMATION_BINARIES,
    datas=(
        frontend_datas()
        # PyInstaller sees uiautomation's Python imports but not its package
        # data.  The two native helper DLLs live under uiautomation/bin and
        # must be collected explicitly for a complete login-automation install.
        + _UIAUTOMATION_DATA
        + copy_metadata("uiautomation")
        + copy_metadata("pywebview")
        + copy_metadata("pythonnet")
        + copy_metadata("clr_loader")
    ),
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Vortex",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="frontend/assets/logo.ico",
    manifest="vortex.manifest",
    # PyInstaller rewrites requestedExecutionLevel from these flags even when
    # a custom manifest is supplied. Keep this in sync with vortex.manifest.
    uac_admin=True,
    uac_uiaccess=False,
)

# A console/as-invoker twin built from the exact same Analysis and PYZ lets an
# unattended build launch the frozen code without a UAC prompt. build.bat runs
# it with --smoke-test and the installer deliberately does not ship this file.
smoke_exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VortexSmoke",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="frontend/assets/logo.ico",
    uac_admin=False,
    uac_uiaccess=False,
)

coll = COLLECT(
    exe,
    smoke_exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Vortex",
)
