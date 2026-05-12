@echo off
setlocal enabledelayedexpansion
title Build OPBuying INDEX Launcher
color 0A

echo.
echo  ============================================================
echo    OPBuying Index App  —  Build Launcher EXE
echo  ============================================================
echo.

:: ── [1/4] Locate Python ─────────────────────────────────────────────────────
set PYTHON=
for %%C in (py python python3) do (
    if not defined PYTHON (
        %%C --version >nul 2>&1 && set PYTHON=%%C
    )
)
if not defined PYTHON (
    echo  [ERROR] Python not found on PATH.
    echo          Install Python 3.10-3.19 from python.org and tick
    echo          "Add Python to PATH" during install, then re-run.
    echo.
    pause & exit /b 1
)
for /f "tokens=*" %%V in ('%PYTHON% --version 2^>^&1') do set PYVER=%%V
echo  [1/4]  Python   :  %PYVER%  (%PYTHON%)
echo.

:: ── [2/4] Install / upgrade PyInstaller ─────────────────────────────────────
echo  [2/4]  Installing PyInstaller ...
%PYTHON% -m pip install pyinstaller --quiet --upgrade --disable-pip-version-check
if errorlevel 1 (
    echo  [ERROR] Could not install PyInstaller. Check your internet connection.
    echo.
    pause & exit /b 1
)
for /f "tokens=*" %%V in ('%PYTHON% -m PyInstaller --version 2^>^&1') do set PIVER=%%V
echo         PyInstaller %PIVER%  ready.
echo.

:: ── [3/4] Clean previous build artifacts ────────────────────────────────────
echo  [3/4]  Cleaning previous artifacts ...
if exist "dist\OPBuying_INDEX_Launcher.exe"  del  /f /q "dist\OPBuying_INDEX_Launcher.exe"
if exist "build"                              rmdir /s /q "build"
if exist "OPBuying_INDEX_Launcher.spec"       del  /f /q "OPBuying_INDEX_Launcher.spec"
echo         Done.
echo.

:: ── [4/4] Compile launcher.py ────────────────────────────────────────────────
echo  [4/4]  Compiling launcher.py  (30–60 s first run) ...
echo.

%PYTHON% -m PyInstaller ^
    --onefile ^
    --windowed ^
    --name "OPBuying_INDEX_Launcher" ^
    --hidden-import "tkinter" ^
    --hidden-import "tkinter.ttk" ^
    --hidden-import "tkinter.scrolledtext" ^
    --hidden-import "tkinter.messagebox" ^
    --hidden-import "importlib.metadata" ^
    --collect-data "tkinter" ^
    launcher.py

if errorlevel 1 (
    echo.
    echo  [ERROR] Compilation failed. See output above for details.
    echo.
    pause & exit /b 1
)

:: ── Clean up intermediate files — keep only the EXE ─────────────────────────
if exist "build"                        rmdir /s /q "build"
if exist "OPBuying_INDEX_Launcher.spec" del   /f /q "OPBuying_INDEX_Launcher.spec"

echo.
echo  ============================================================
echo    BUILD SUCCESSFUL
echo  ============================================================
echo.
echo    EXE path:  dist\OPBuying_INDEX_Launcher.exe
echo.
echo    NEXT STEP:
echo      Copy  OPBuying_INDEX_Launcher.exe  from dist\ into this
echo      folder (same level as config.json and the .py files).
echo      Then double-click it to set up and launch the app.
echo.
echo    The launcher will:
echo      1. Check Python 3.10-3.19
echo      2. Install / skip packages (smart version check)
echo      3. Let you choose PAPER or MANUAL mode
echo      4. Launch the app via CLI flag — config.json untouched
echo.
echo  ============================================================
echo.
pause
endlocal
