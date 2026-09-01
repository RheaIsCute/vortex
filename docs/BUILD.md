# Build and Release

Run from the repository root on Windows:

```powershell
.\build.bat
```

The script reads `backend/version.py`, runs PyInstaller with `build_exe.spec`, stages the executable bundle, and invokes Inno Setup with `installer/vortex_setup.iss` when ISCC is available. Build artifacts are ignored in `build/`, `dist/`, `dist_installer/`, and `installer_output/`.

Before a release, update both `backend/version.py` and root `version.json` consistently. The application updater checks GitHub’s latest stable release API first, then the version manifest mirrors on jsDelivr/GitHub Raw, and launches the release’s `VortexSetup.exe`; test an update over an existing installation, since the installer must handle locked Vortex, WebView2, and Overwolf processes.

Release checklist:

1. Finish changes and run tests/compile checks.
2. Bump `backend/version.py`, `version.json`, and the installer fallback version.
3. Run `build.bat` and confirm `dist_installer/VortexSetup.exe` exists.
4. Commit and push source/version changes to `master`.
5. Create a new tag and GitHub Release (for example, `v5.5.34`) and attach exactly `VortexSetup.exe`.
6. Verify the manifest’s version and download URL, then test an older installed build detecting, downloading, and launching the new release.
