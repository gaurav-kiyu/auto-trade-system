@echo off
TITLE GAURAV - OPB Super-App Master Launcher
COLOR 0A
CLS
cd /d "%~dp0"

echo ==============================================================================
echo   GAURAV - OPB SUPER-APP AUTONOMOUS ENGINE ^& WEB SERVER
echo ==============================================================================
echo.
setlocal enabledelayedexpansion
set PYTHON=
for %%C in (py python python3) do (
    if not defined PYTHON (
        %%C --version >nul 2>&1 && set PYTHON=%%C
    )
)
if not defined PYTHON (
    echo [ERROR] Neither "py" nor "python" was found in PATH.
    echo Install Python 3.11+ from https://www.python.org/downloads/ and make
    echo sure "Add python.exe to PATH" is checked during install.
    pause
    exit /b 1
)

if not exist json\config.json (
    if exist json\config.template.json (
        echo [INFO] json\config.json not found - bootstrapping it from json\config.template.json...
        copy /y json\config.template.json json\config.json >nul
    )
)

echo [1/3] Running pre-flight governance and DB integrity checks...
%PYTHON% scripts\pre_implementation_check.py --verify-analysis
%PYTHON% scripts\check_db_integrity.py

echo [2/3] Scheduling browser launch once the web server is actually ready...
start /b powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0scripts\wait_for_dashboard_port.ps1" -Port 8765 -OpenUrl "http://localhost:8765/"

echo [3/3] Starting the trading bot + Enterprise Dashboard on http://localhost:8765 ...
echo       (paper/signal-only mode - no real orders are ever placed)
echo       Press Ctrl+C or close this window to stop the bot.
%PYTHON% index_app\index_trader.py --paper

pause

