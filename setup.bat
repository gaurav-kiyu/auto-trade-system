@echo off
TITLE OPB Trading Super-App Setup
COLOR 0B
CLS
cd /d "%~dp0"

echo ==============================================================================
echo   OPB TRADING SUPER-APP - ENVIRONMENT SETUP AND INTEGRITY BOOTSTRAP
echo ==============================================================================
echo.

echo [1/3] Checking Python 3.11+ environment...
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
echo [OK] Python found: %PYTHON%

if not exist json\config.json (
    if exist json\config.template.json (
        echo [INFO] json\config.json not found - bootstrapping it from json\config.template.json...
        copy /y json\config.template.json json\config.json >nul
    )
)

echo [2/3] Verifying database integrity and pre-implementation governance...
%PYTHON% scripts\pre_implementation_check.py --verify-analysis
%PYTHON% scripts\check_db_integrity.py

echo [3/3] Environment bootstrap complete. You can now run start.bat to launch.
echo.
pause
