@echo off
setlocal
REM Builds Vortex.exe and the VortexSetup.exe installer from source.
REM Requires Inno Setup 6 installed (ISCC.exe).
cd /d "%~dp0"

for /f "delims=" %%v in ('python -c "import sys; sys.path.insert(0,'.'); from backend.version import APP_VERSION; print(APP_VERSION)"') do set APP_VERSION=%%v
echo Building version %APP_VERSION%

python -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)"
if errorlevel 1 (
    echo.
    echo Build FAILED - release builds require Python 3.12.x.
    python --version
    exit /b 1
)

echo Installing dependencies...
python -m pip install -r requirements.txt -q

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

if not exist dist\Vortex\VortexSmoke.exe (
    echo.
    echo Build FAILED - the frozen smoke-test executable is missing.
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

REM uiautomation imports as Python code from the PYZ, but its native package
REM data is not discovered by import analysis. Both architectures are part of
REM the installed package and their absence previously went unnoticed.
for %%f in (UIAutomationClient_VC140_X64.dll UIAutomationClient_VC140_X86.dll) do (
    if not exist "dist\Vortex\_internal\uiautomation\bin\%%f" (
        echo.
        echo Build FAILED - uiautomation\bin\%%f is missing.
        exit /b 1
    )
)

REM Launch frozen code from the same Analysis/PYZ as Vortex.exe. The smoke twin
REM is console/as-invoker so this gate is unattended despite the production
REM executable's requireAdministrator manifest. Isolate writable app data so a
REM build can never inspect or migrate the user's real database.
set "VORTEX_SMOKE_DIR=%TEMP%\VortexBuildSmoke-%RANDOM%-%RANDOM%"
mkdir "%VORTEX_SMOKE_DIR%"
set "VORTEX_REAL_LOCALAPPDATA=%LOCALAPPDATA%"
set "LOCALAPPDATA=%VORTEX_SMOKE_DIR%\LocalAppData"
set "VORTEX_STARTUP_LOG=%VORTEX_SMOKE_DIR%\startup.log"
echo Running frozen application smoke test...
set "VORTEX_SMOKE_RESULT=0"
for /L %%n in (1,1,3) do (
    echo Frozen smoke pass %%n of 3...
    "dist\Vortex\VortexSmoke.exe" --smoke-test
    if errorlevel 1 set "VORTEX_SMOKE_RESULT=1"
)
set "LOCALAPPDATA=%VORTEX_REAL_LOCALAPPDATA%"
set "VORTEX_STARTUP_LOG="
if not "%VORTEX_SMOKE_RESULT%"=="0" (
    echo.
    echo Build FAILED - the frozen application did not pass its startup/API/UIA smoke test.
    echo Diagnostic log: %VORTEX_SMOKE_DIR%\startup.log
    if exist "%VORTEX_SMOKE_DIR%\startup.log" type "%VORTEX_SMOKE_DIR%\startup.log"
    exit /b 1
)
rmdir /s /q "%VORTEX_SMOKE_DIR%"

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
set "VORTEX_STAGE_DIR=%TEMP%\VortexInstallerStage-%RANDOM%-%RANDOM%"
set "VORTEX_INSTALLER_OUTPUT_DIR=%TEMP%\VortexInstallerOutput-%RANDOM%-%RANDOM%"
set "VORTEX_INSTALLER_PROBE_DIR=%TEMP%\VortexInstallerProbe-%RANDOM%-%RANDOM%"
mkdir "%VORTEX_STAGE_DIR%"
mkdir "%VORTEX_INSTALLER_OUTPUT_DIR%"
robocopy "dist\Vortex" "%VORTEX_STAGE_DIR%" /E /COPY:DAT /DCOPY:DAT /R:2 /W:1 >nul
set "VORTEX_COPY_RESULT=%ERRORLEVEL%"
if %VORTEX_COPY_RESULT% GEQ 8 (
    echo.
    echo Installer build FAILED - staging dist\Vortex returned robocopy code %VORTEX_COPY_RESULT%.
    exit /b 1
)

%ISCC% "/DAppVersion=%APP_VERSION%" "/DBundleDir=%VORTEX_STAGE_DIR%" "/O%VORTEX_INSTALLER_OUTPUT_DIR%" installer\vortex_setup.iss
if errorlevel 1 (
    echo.
    echo Installer build FAILED - Inno Setup returned an error.
    exit /b 1
)

if not exist "%VORTEX_INSTALLER_OUTPUT_DIR%\VortexSetup.exe" (
    echo.
    echo Installer build FAILED - expected output was not created.
    exit /b 1
)

REM Run the exact final installer before exposing it at the release path. Its
REM /VORTEXBUILDSMOKE mode extracts and CRC-checks every payload file into the
REM scratch directory without killing Vortex, creating shortcuts, or writing
REM an uninstall registration.
echo Running installer integrity test...
"%VORTEX_INSTALLER_OUTPUT_DIR%\VortexSetup.exe" /VORTEXBUILDSMOKE /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /NOICONS "/DIR=%VORTEX_INSTALLER_PROBE_DIR%" "/LOG=%VORTEX_INSTALLER_PROBE_DIR%-setup.log"
if errorlevel 1 (
    echo.
    echo Installer build FAILED - SetupLdr or Setup rejected the compiled artifact.
    echo Diagnostic log: %VORTEX_INSTALLER_PROBE_DIR%-setup.log
    exit /b 1
)
if not exist "%VORTEX_INSTALLER_PROBE_DIR%\Vortex.exe" (
    echo.
    echo Installer build FAILED - integrity probe did not extract Vortex.exe.
    exit /b 1
)
set "VORTEX_PROBE_INTERNAL_COUNT=0"
for /f %%c in ('dir /a-d /b /s "%VORTEX_INSTALLER_PROBE_DIR%\_internal" 2^>nul ^| find /c /v ""') do set VORTEX_PROBE_INTERNAL_COUNT=%%c
if not "%VORTEX_PROBE_INTERNAL_COUNT%"=="%_INTERNAL_COUNT%" (
    echo.
    echo Installer build FAILED - payload file count changed during packaging.
    echo Expected %_INTERNAL_COUNT%, extracted %VORTEX_PROBE_INTERNAL_COUNT%.
    exit /b 1
)

if not exist dist_installer mkdir dist_installer
move /y "%VORTEX_INSTALLER_OUTPUT_DIR%\VortexSetup.exe" "dist_installer\VortexSetup.exe" >nul
if errorlevel 1 (
    echo.
    echo Installer build FAILED - verified artifact could not be moved into dist_installer.
    exit /b 1
)
rmdir /s /q "%VORTEX_STAGE_DIR%"
rmdir /s /q "%VORTEX_INSTALLER_OUTPUT_DIR%"
rmdir /s /q "%VORTEX_INSTALLER_PROBE_DIR%"
del /q "%VORTEX_INSTALLER_PROBE_DIR%-setup.log" 2>nul
echo.
echo Installer verified and built atomically: dist_installer\VortexSetup.exe
