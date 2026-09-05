@echo off
REM Builds Vortex.exe and the VortexSetup.exe installer from source.
REM Requires Inno Setup 6 installed (ISCC.exe).
cd /d "%~dp0"

for /f "delims=" %%v in ('python -c "import sys; sys.path.insert(0,'.'); from backend.version import APP_VERSION; print(APP_VERSION)"') do set APP_VERSION=%%v
echo Building version %APP_VERSION%

echo Installing dependencies...
pip install -r requirements.txt -q
pip install pyinstaller -q

echo.
echo Building dist\Vortex\ (this can take a minute)...

REM Wipe the previous output first. Without this PyInstaller refuses to write
REM into a non-empty dist\Vortex ("output directory is not empty") and stops at
REM the COLLECT step - and because the PREVIOUS build's Vortex.exe was still
REM sitting there, the old existence check below passed and Inno went on to
REM package a stale build under a new version number. Deleting it up front also
REM means that if Vortex.exe exists afterwards, it is necessarily fresh.
if exist dist\Vortex rmdir /s /q dist\Vortex

REM --noconfirm so a leftover directory can never turn into an interactive
REM prompt (or the refusal above) on a machine where dist wasn't cleared.
python -m PyInstaller build_exe.spec --clean --noconfirm
if errorlevel 1 (
    echo.
    echo Build FAILED - PyInstaller exited with an error.
    exit /b 1
)

if not exist dist\Vortex\Vortex.exe (
    echo.
    echo Build FAILED - check the output above.
    exit /b 1
)

REM The source manifest is not enough: fail the build unless the PE resource
REM that Windows will actually read requests elevation.
python tools\verify_executable_manifest.py dist\Vortex\Vortex.exe
if errorlevel 1 (
    echo.
    echo Build FAILED - Vortex.exe does not contain the required elevation manifest.
    exit /b 1
)

REM Vortex.exe existing is not proof the bundle is complete. A PyInstaller run
REM that dies partway through COLLECT can still leave Vortex.exe plus a handful
REM of _internal files - that is exactly how a ~44-file installer for 5.5.14 got
REM built and shipped, gutting every machine that auto-updated to it. A healthy
REM one-dir build has well over a thousand files under _internal\; anything
REM close to empty means the build is truncated and must NOT be packaged.
set _INTERNAL_COUNT=0
for /f %%c in ('dir /a-d /b /s "dist\Vortex\_internal" 2^>nul ^| find /c /v ""') do set _INTERNAL_COUNT=%%c
echo _internal file count: %_INTERNAL_COUNT%
if %_INTERNAL_COUNT% LSS 500 (
    echo.
    echo Build FAILED - dist\Vortex\_internal has only %_INTERNAL_COUNT% files.
    echo The PyInstaller bundle is truncated. Refusing to build the installer
    echo from an incomplete build. Re-run and check the PyInstaller output.
    exit /b 1
)

REM Spot-check a few binary deps that have gone missing from bad builds before:
REM the stdlib C extensions and pydantic_core's compiled module.
for %%f in (_ctypes.pyd _ssl.pyd _socket.pyd _sqlite3.pyd) do (
    if not exist "dist\Vortex\_internal\%%f" (
        echo.
        echo Build FAILED - dist\Vortex\_internal\%%f is missing.
        echo A stdlib C extension did not get bundled. See build_exe.spec.
        exit /b 1
    )
)

echo Build succeeded: dist\Vortex\Vortex.exe (%_INTERNAL_COUNT% files in _internal)

set ISCC="%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not exist %ISCC% set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist %ISCC% (
    echo.
    echo Inno Setup ^(ISCC.exe^) not found - skipping installer build.
    echo Install it from https://jrsoftware.org/isinfo.php and re-run to build VortexSetup.exe.
    exit /b 0
)

echo.
echo Building VortexSetup.exe installer...

REM Inno Setup still has legacy source-path handling in a few compiler paths.
REM This repository's nested location plus the bundled Valorant asset tree can
REM exceed MAX_PATH, causing it to silently omit hundreds of runtime assets.
REM Stage the completed bundle under the short temp path before compiling so
REM the installer always receives every file that PyInstaller produced.
set "VORTEX_STAGE_DIR=%TEMP%\VortexInstallerStage"
if exist "%VORTEX_STAGE_DIR%" rmdir /s /q "%VORTEX_STAGE_DIR%"
mkdir "%VORTEX_STAGE_DIR%"
robocopy "dist\Vortex" "%VORTEX_STAGE_DIR%" /E /COPY:DAT /DCOPY:DAT /R:2 /W:1 >nul
set "VORTEX_COPY_RESULT=%ERRORLEVEL%"
if %VORTEX_COPY_RESULT% GEQ 8 (
    echo.
    echo Installer build FAILED - staging dist\Vortex returned robocopy code %VORTEX_COPY_RESULT%.
    exit /b 1
)

%ISCC% "/DAppVersion=%APP_VERSION%" "/DBundleDir=%VORTEX_STAGE_DIR%" installer\vortex_setup.iss

if exist dist_installer\VortexSetup.exe (
    rmdir /s /q "%VORTEX_STAGE_DIR%"
    echo.
    echo Installer built: dist_installer\VortexSetup.exe
) else (
    echo.
    echo Installer build FAILED - check the output above.
    exit /b 1
)
