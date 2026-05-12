@echo off
setlocal enabledelayedexpansion
title OPBuying — Low Capital Launcher (Rs.5,000)
color 0A

echo.
echo  ============================================================
echo    OPBuying Index App  —  Rs.5,000 LOW CAPITAL Mode
echo    PAPER TRADING ONLY — No Real Orders
echo  ============================================================
echo.

:: ── Detect Python ────────────────────────────────────────────────
set PYTHON=
for %%C in (py python python3) do (
    if not defined PYTHON (
        %%C --version >nul 2>&1 && set PYTHON=%%C
    )
)
if not defined PYTHON (
    echo  [ERROR] Python not found. Install Python 3.10-3.19.
    pause & exit /b 1
)

:: ── Check if deps are installed ───────────────────────────────────
%PYTHON% -c "import yfinance" >nul 2>&1
if errorlevel 1 (
    echo  Installing dependencies ...
    %PYTHON% -m pip install -r requirements.txt --quiet --disable-pip-version-check
    echo.
)

:: ── Check capital config ──────────────────────────────────────────
echo.
echo  CURRENT LOW-CAPITAL SETTINGS:
echo    Base Capital    : Rs.5,000
echo    Daily Loss Stop : Rs.300  (-6%%)
echo    Max Trades/Day  : 1
echo    Max Lot Capital : 50%%
echo    Execution Mode  : PAPER  ^<-- No real orders
echo.
echo  Edit  config.lowcap.json  to change capital or settings.
echo.

:: ── Ask user to confirm ───────────────────────────────────────────
set /p CONFIRM="Start PAPER trading with Rs.5,000? (Y/N): "
if /i not "%CONFIRM%"=="Y" (
    echo  Cancelled.
    pause & exit /b 0
)

:: ── Run the bot in PAPER mode with low-cap config ─────────────────
echo.
echo  Starting PAPER trading ...
echo  -------------------------------
%PYTHON% -m index_app.index_trader --paper
set EXIT_CODE=!errorlevel!

echo.
echo  ============================================================
echo    SESSION ENDED  (exit code: !EXIT_CODE!)
echo  ============================================================
echo.
pause
endlocal
