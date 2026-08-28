# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Vortex | Valorant Account Manager.
Builds a single-file, windowed .exe. Run via:
    pyinstaller build_exe.spec --clean
Output: dist/Vortex.exe
"""

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

hidden_imports = [
    "win32timezone",
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
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="Vortex",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="frontend/assets/logo.ico",
)
