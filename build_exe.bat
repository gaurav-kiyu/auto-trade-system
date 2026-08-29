@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

:: Version: 2.58.0 — Read VERSION from file dynamically
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
echo    GAURAV CAPITAL - OPBuying Super-App v%VERSION%
echo    Build Standalone Launcher EXE
echo  ============================================================
echo  VERSION: v%VERSION%
echo  STATUS: Paper/Manual-signal mode by default - see live_readiness_checker
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
%PYTHON% -m pip install pyinstaller --quiet --upgrade --disable-pip-version-check --no-warn-script-location
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

:: Cleanup build artifacts and move EXE to project root
if exist "build" rmdir /s /q "build"
if exist "OPBuying_INDEX_Launcher.spec" del /f /q "OPBuying_INDEX_Launcher.spec"

echo  [OK] Moving standalone executable to project root ...
if exist "dist\OPBuying_INDEX_Launcher.exe" (
    move /y "dist\OPBuying_INDEX_Launcher.exe" "OPBuying_INDEX_Launcher.exe" >nul
    if exist "dist" rmdir /s /q "dist"
)

echo.
echo  ============================================================
echo    BUILD SUCCESSFUL - v%VERSION% (GAURAV)
echo  ============================================================
echo.
echo    Output: OPBuying_INDEX_Launcher.exe
echo.
echo    Double-click OPBuying_INDEX_Launcher.exe in the project folder to run.
echo.
echo    v%VERSION% Features:
echo      - Multi-Asset signal generation (NIFTY/BANKNIFTY/FINNIFTY options,
echo        NSE equities, ETFs/REITs, IPOs)
echo      - Paper / Manual-signal / Live execution modes, live-locked by
echo        default until a real paper track record is proven
echo      - Broker abstraction layer (Zerodha, Angel, others)
echo      - Enterprise dashboard with RBAC, audit trail, and governance tooling
echo.
echo  ============================================================
pause
endlocal
