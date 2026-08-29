@echo off
setlocal enabledelayedexpansion
title GAURAV Real-Time Market Scanner and Signal Daemon
cd /d "%~dp0"

echo ======================================================================
echo  GAURAV REAL-TIME NSE MARKET SCANNER and SIGNAL DAEMON
echo ======================================================================
echo.
echo  Trading Hours : 09:15 AM - 15:30 PM IST (Mon-Fri)
echo  Active Engine : 16 Quantitative Strategies
echo  Recipients    : Telegram (@gaurav_optionbuying_signal_bot) + Gmail
echo.
echo  Starting continuous background scanning loop...
echo ======================================================================
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

%PYTHON% -m core.market_scanner_daemon --interval 60 --workers 20

pause

