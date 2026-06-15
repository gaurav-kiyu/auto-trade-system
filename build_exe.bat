@echo off
setlocal enabledelayedexpansion

:: Version: 2.53.0 — Read VERSION from file
if not exist VERSION (
    echo  [ERROR] VERSION file not found
    pause & exit /b 1
)
set /p VERSION=<VERSION
if "%VERSION%"=="" (
    echo  [ERROR] VERSION file is empty
    pause & exit /b 1
)
title Build OPBuying INDEX Launcher - v%VERSION%
color 0A

echo.
echo  ============================================================
echo    OPBuying Index Options Bot v%VERSION%
echo    Build Launcher EXE
echo  ============================================================
echo  VERSION: v%VERSION% (Production Ready)
echo  STATUS: Limited Live Pilot (7/10 confidence)
echo.

:: [1/4] Locate Python
set PYTHON=
for %%C in (py python python3) do (
    if not defined PYTHON (
        %%C --version >nul 2>&1 && set PYTHON=%%C
    )
)
if not defined PYTHON (
    echo  [ERROR] Python not found. Install Python 3.10-3.14 from python.org
    pause & exit /b 1
)
for /f "tokens=*" %%V in ('%PYTHON% --version 2^>^&1') do set PYVER=%%V
echo  [OK] Python: %PYVER%
echo.

:: [2/4] Install/Upgrade PyInstaller
echo  [2/4] Installing PyInstaller ...
%PYTHON% -m pip install pyinstaller --quiet --upgrade --disable-pip-version-check
for /f "tokens=*" %%V in ('%PYTHON% -m PyInstaller --version 2^>^&1') do set PIVER=%%V
echo         PyInstaller %PIVER% ready
echo.

:: [3/4] Clean previous build
echo  [3/4] Cleaning previous build ...
if exist "dist\OPBuying_INDEX_Launcher.exe"  del /f /q "dist\OPBuying_INDEX_Launcher.exe"
if exist "build" rmdir /s /q "build"
if exist "OPBuying_INDEX_Launcher.spec" del /f /q "OPBuying_INDEX_Launcher.spec"
echo         Done
echo.

:: [4/4] Compile
echo  [4/4] Compiling launcher.py (30-60 seconds first run) ...
echo.
%PYTHON% -m PyInstaller --onefile --windowed --name "OPBuying_INDEX_Launcher" --hidden-import "tkinter" --hidden-import "tkinter.ttk" --hidden-import "tkinter.scrolledtext" --hidden-import "tkinter.messagebox" --hidden-import "importlib.metadata" --collect-data "tkinter" launcher.py

if errorlevel 1 (
    echo  [ERROR] Compilation failed
    pause & exit /b 1
)

:: Cleanup
if exist "build" rmdir /s /q "build"
if exist "OPBuying_INDEX_Launcher.spec" del /f /q "OPBuying_INDEX_Launcher.spec"

echo.
echo  ============================================================
echo    BUILD SUCCESSFUL - v%VERSION%
echo  ============================================================
echo.
echo    Output: dist\OPBuying_INDEX_Launcher.exe
echo.
echo    NEXT STEPS:
echo      1. Copy EXE to project root (same as config.json)
echo      2. Double-click to run GUI launcher
echo      3. Select PAPER or MANUAL mode
echo.
echo    v%VERSION% Features:
echo      - DataEngine recursion bug FIXED (3 recursive lambdas)
echo      - VIX data type error FIXED (MultiIndex columns)
echo      - Race condition FIXED (Thread-safe A/B tester)
echo      - 10 silent exception blocks now LOGGED
echo      - Enterprise auth RBAC with brute-force protection
echo      - Data governance with automated retention cleanup
echo      - Environment isolation (DEV/QA/PAPER/SHADOW/PRODUCTION)
echo.
echo  ============================================================
pause
endlocal
