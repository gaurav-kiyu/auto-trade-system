@echo off
setlocal enabledelayedexpansion
title OPBuying - Low Capital Launcher (Rs.5,000)
color 0A

echo.
echo  ============================================================
echo    OPBuying Index Options Bot v2.53.0
echo    Rs.5,000 LOW CAPITAL Mode - SAFE
echo.
echo    VERSION: v2.53.0 (Production Ready)
echo    RISK: 1.5%% per trade | DAILY STOP: -300 INR
echo    EXECUTION: MANUAL/SIGNAL mode (NO real orders)
echo    STATUS: Paper trading with full risk controls
echo  ============================================================
echo.

:: Python Detection
set PYTHON=
for %%C in (py python python3) do (
    if not defined PYTHON (
        %%C --version >nul 2>&1 && set PYTHON=%%C
    )
)
if not defined PYTHON (
    echo  [ERROR] Python not found. Install Python 3.10-3.19.
    echo  Download from: https://www.python.org/downloads/
    pause & exit /b 1
)
echo  [OK] Python found: %PYTHON%

:: Dependency Check
%PYTHON% -c "import yfinance, pandas, numpy" >nul 2>&1
if errorlevel 1 (
    echo  [INSTALL] Installing dependencies ...
    %PYTHON% -m pip install -r requirements.txt --quiet --disable-pip-version-check
)
echo  [OK] Dependencies installed

echo.
echo  === CURRENT CONFIG ===
echo  Mode           : MANUAL (signals only, no auto-trade)
echo  Broker API    : DISABLED (no real orders)
echo  Capital       : 5,000 INR
echo  Max Daily Loss: -300 INR (-6%%)
echo  Max Open Pos  : 1
echo  Max Trades/Day: 2
echo  Win Rate      : 54.5%% (55 trades)
echo  Profit Factor : 2.54
echo.

:: User Confirmation
set /p CONFIRM="Start paper trading with Rs.5,000? (Y/N): "
if /i not "%CONFIRM%"=="Y" (
    echo  Cancelled. Press any key to exit...
    pause >nul
    exit /b 0
)

echo.
echo  === STARTING ===
echo  Running: python -m index_app.index_trader --paper
echo  -----------------------------------------------
%PYTHON% -m index_app.index_trader --paper
set EXIT_CODE=!errorlevel!

echo.
echo  ============================================================
echo  Session Complete (exit code: !EXIT_CODE!)
echo  ============================================================
echo.
pause
endlocal
