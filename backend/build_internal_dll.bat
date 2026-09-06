@echo off
REM Build script for VALORANT Internal DLL
REM Requires Visual Studio or MinGW-w64

echo ========================================
echo  VALORANT Internal DLL Builder
echo ========================================
echo.
echo WARNING: This DLL will be injected into VALORANT
echo and is EXTREMELY detectable by Vanguard.
echo.
echo Use at your own risk. Account bans are likely.
echo.
pause

REM Try to find Visual Studio compiler
where cl.exe >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo Found Visual Studio compiler
    echo Compiling with MSVC...
    cl /LD /O2 /EHsc valorant_internal.cpp /link /OUT:valorant_internal.dll user32.lib psapi.lib
    if %ERRORLEVEL% EQU 0 (
        echo.
        echo SUCCESS: valorant_internal.dll built successfully!
        echo.
        goto :end
    ) else (
        echo ERROR: Compilation failed
        goto :error
    )
)

REM Try MinGW
where g++.exe >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo Found MinGW compiler
    echo Compiling with MinGW...
    g++ -shared -o valorant_internal.dll valorant_internal.cpp -std=c++17 -O2 -lpsapi -luser32
    if %ERRORLEVEL% EQU 0 (
        echo.
        echo SUCCESS: valorant_internal.dll built successfully!
        echo.
        goto :end
    ) else (
        echo ERROR: Compilation failed
        goto :error
    )
)

echo ERROR: No C++ compiler found!
echo.
echo Please install one of:
echo   - Visual Studio (with C++ tools)
echo   - MinGW-w64
echo.
goto :error

:end
echo DLL location: %CD%\valorant_internal.dll
echo.
echo To use:
echo 1. Enable memory reading in Vortex settings
echo 2. Select "Internal" mode
echo 3. Start VALORANT
echo 4. Enable memory reading
echo.
pause
exit /b 0

:error
echo.
echo Build failed. Check errors above.
echo.
pause
exit /b 1
