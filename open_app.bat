@echo off
setlocal enabledelayedexpansion
title OPB Super-App - End-User Trading Dashboard Launcher
cd /d "%~dp0"

echo ======================================================================
echo  OPB SUPER-APP - REAL END-USER TRADING DASHBOARD LAUNCHER
echo ======================================================================
echo.
echo  Target URL: http://localhost:8765/
echo  Function  : Live Market Trading, Signal Stream and Real-Time Analytics
echo.

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

:: Check if server is running on port 8765
powershell -NoProfile -ExecutionPolicy Bypass -Command "$c = New-Object System.Net.Sockets.TcpClient; try { $c.Connect('127.0.0.1', 8765); exit 0 } catch { exit 1 } finally { $c.Close() }" >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] Application server is not running. Starting server window...
    start "OPB Trading Server" %PYTHON% index_app/index_trader.py --paper
    echo [INFO] Waiting for the dashboard to come up - startup can take a few seconds...
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\wait_for_dashboard_port.ps1" -Port 8765
)

echo [OK] Opening End-User Trading Dashboard in default browser...
start http://localhost:8765/

echo.
echo ======================================================================
echo  APP LAUNCH COMPLETE - Accessing http://localhost:8765/
echo ======================================================================
ping -n 3 127.0.0.1 >nul 2>&1

