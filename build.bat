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
echo Build succeeded: dist\Vortex\Vortex.exe

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
%ISCC% "/DAppVersion=%APP_VERSION%" installer\vortex_setup.iss

if exist dist_installer\VortexSetup.exe (
    echo.
    echo Installer built: dist_installer\VortexSetup.exe
) else (
    echo.
    echo Installer build FAILED - check the output above.
    exit /b 1
)
