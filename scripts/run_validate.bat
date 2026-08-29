@echo off
REM Version: 2.58.0
echo ========================================
echo AUDIT VALIDATION SCRIPT
echo ========================================
echo.
echo [1/5] Checking Python version...
setlocal enabledelayedexpansion
set PYTHON=
for %%C in (py python python3) do (
    if not defined PYTHON (
        %%C --version >nul 2>&1 && set PYTHON=%%C
    )
)
if not defined PYTHON (
    echo [ERROR] Neither "py" nor "python" was found in PATH.
    pause
    exit /b 1
)
%PYTHON% --version
echo.
echo [2/5] Testing now_ist() import...
%PYTHON% -c "from core.datetime_ist import now_ist; t = now_ist(); print(f'now_ist() OK: {t}')"
echo.
echo [3/5] Running smoke tests...
%PYTHON% -m pytest tests/test_smoke.py -v --tb=short
echo.
echo [4/5] Checking coverage threshold...
findstr "fail_under" .coveragerc
echo.
echo [5/5] Checking deliverable files...
dir docs\deliverables\*.md /b | find /c /v ""
echo.
echo ========================================
echo VALIDATION COMPLETE
echo ========================================
pause
