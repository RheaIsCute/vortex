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

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

hidden_imports = [
    "win32timezone",
    # UI Automation is how the Riot Client's "Stay signed in" checkbox is
    # found and set. comtypes generates its typelib wrappers at runtime, so
    # the generated package has to be collected explicitly or the frozen
    # build can't talk to UIA at all.
    "uiautomation",
    "comtypes",
    "comtypes.stream",
] + collect_submodules("comtypes.gen") + [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
] + collect_submodules("webview")

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("frontend", "frontend"),
        # Intel's open-source PresentMon (MIT license) - the ETW capture
        # engine behind the FPS counter. See vendor/PresentMon/NOTICE.txt.
        ("vendor/PresentMon/PresentMon-x64.exe", "vendor/PresentMon"),
        ("vendor/PresentMon/NOTICE.txt", "vendor/PresentMon"),
    ],
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
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Vortex",
)
