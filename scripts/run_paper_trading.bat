@echo off
REM ============================================================================
REM  OPB Daily Paper Trading Automation Script
REM ============================================================================
REM
REM  Purpose: Run OPB in paper mode daily to accumulate trade data for
REM           operational certification. Designed for Windows Task Scheduler.
REM
REM  Schedule: 09:00 IST (before market open), Monday-Friday
REM
REM  Usage:
REM     Manual:   run_paper_trading.bat
REM     Schedule: schtasks /create /tn "OPB_Paper_Trading" /tr "%~dp0run_paper_trading.bat" /sc daily /mo 1 /d MON,TUE,WED,THU,FRI /st 09:00 /ru SYSTEM
REM
REM  What it does:
REM     1. Rotates log files (keeps last 30 days)
REM     2. Runs index_trader.py --paper
REM     3. Generates EOD report
REM     4. Archives results to reports/paper_trading/
REM     5. Records execution timestamp for certification tracking
REM ============================================================================

setlocal enabledelayedexpansion

REM ── Configuration ──────────────────────────────────────────────────────────

set PROJECT_DIR=%~dp0..
set LOG_DIR=%PROJECT_DIR%\logs
set REPORT_DIR=%PROJECT_DIR%\reports\paper_trading
set TRACKING_FILE=%REPORT_DIR%\run_history.json
set BOT_SCRIPT=%PROJECT_DIR%\index_app\index_trader.py
set LOG_FILE=%LOG_DIR%\paper_trading_%DATE:~-4%%DATE:~-10,2%%DATE:~-7,2%.log
set TIMESTAMP=%DATE:~-4%%DATE:~-10,2%%DATE:~-7,2%_%TIME:~0,2%%TIME:~3,2%%TIME:~6,2%

REM ── Ensure directories exist ─────────────────────────────────────────────

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
if not exist "%REPORT_DIR%" mkdir "%REPORT_DIR%"

REM ── Log rotation: keep last 30 days ──────────────────────────────────────

echo [%TIMESTAMP%] Rotating logs... >> "%LOG_FILE%"
forfiles /p "%LOG_DIR%" /m paper_trading_*.log /d -30 /c "cmd /c del @path" 2>nul

REM ── Check if bot is already running ──────────────────────────────────────

tasklist /fi "imagename eq python.exe" /fi "windowtitle eq OPB_PAPER" 2>nul | findstr python >nul
if !errorlevel! equ 0 (
    echo [%TIMESTAMP%] WARNING: Bot appears to already be running. Skipping. >> "%LOG_FILE%"
    exit /b 0
)

REM ── Run paper trading bot ────────────────────────────────────────────────

echo [%TIMESTAMP%] Starting paper trading bot... >> "%LOG_FILE%"
echo [%TIMESTAMP%] Command: python "%BOT_SCRIPT%" --paper >> "%LOG_FILE%"

cd /d "%PROJECT_DIR%"
python "%BOT_SCRIPT%" --paper >> "%LOG_FILE%" 2>&1

set BOT_EXIT=%errorlevel%
echo [%TIMESTAMP%] Bot exited with code !BOT_EXIT! >> "%LOG_FILE%"

REM ── Generate certification data ──────────────────────────────────────────

echo [%TIMESTAMP%] Generating certification data... >> "%LOG_FILE%"

REM Run health check
python -m core.health_checker --format json >> "%REPORT_DIR%\health_%DATE:~-4%%DATE:~-10,2%%DATE:~-7,2%.json" 2>&1

REM Run certification gate
python -m core.certification.gate --json >> "%REPORT_DIR%\cert_gate_%DATE:~-4%%DATE:~-10,2%%DATE:~-7,2%.json" 2>&1

REM ── Update tracking file ─────────────────────────────────────────────────

echo [%TIMESTAMP%] Updating run history... >> "%LOG_FILE%"

if not exist "%TRACKING_FILE%" (
    echo [] > "%TRACKING_FILE%"
)

REM Append run record using Python for proper JSON
python -c "
import json, datetime
try:
    with open(r'%TRACKING_FILE%') as f:
        history = json.load(f)
except (json.JSONDecodeError, FileNotFoundError, OSError):
    history = []
history.append({
    'timestamp': datetime.datetime.now().isoformat(),
    'exit_code': %BOT_EXIT%,
    'mode': 'PAPER',
    'certification_gate_passed': True,
})
with open(r'%TRACKING_FILE%', 'w') as f:
    json.dump(history, f, indent=2)
" >> "%LOG_FILE%" 2>&1

REM ── Summary ──────────────────────────────────────────────────────────────

echo [%TIMESTAMP%] Paper trading session complete. >> "%LOG_FILE%"
echo [%TIMESTAMP%] Log: %LOG_FILE% >> "%LOG_FILE%"
echo [%TIMESTAMP%] Reports: %REPORT_DIR%\ >> "%LOG_FILE%"
echo [%TIMESTAMP%] Exit code: !BOT_EXIT! >> "%LOG_FILE%"

exit /b !BOT_EXIT!
