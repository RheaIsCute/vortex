# Build and Release

Run from the repository root on Windows:

```powershell
.\build.bat
```

The script reads `backend/version.py`, runs PyInstaller with `build_exe.spec`, stages the executable bundle, and invokes Inno Setup with `installer/vortex_setup.iss` when ISCC is available. Build artifacts are ignored in `build/`, `dist/`, `dist_installer/`, and `installer_output/`.

Before a release, update both `backend/version.py` and root `version.json` consistently. The application updater reads `version.json` from the release repository and launches the installer; test an update over an existing installation, since the installer must handle locked Vortex, WebView2, and Overwolf processes.
