@echo off
REM ============================================
REM  airscope - Windows launcher
REM  Double-click to run (uses WSL2)
REM ============================================

echo.
echo  +--------------------------------------+
echo  ^|  airscope                             ^|
echo  ^|  wireless auditor                    ^|
echo  +--------------------------------------+
echo.

REM Check WSL2
wsl --list --verbose 2>nul | findstr /i "Ubuntu" >nul 2>&1
if %errorlevel% neq 0 (
    echo   [!] WSL2 not found.
    echo.
    echo   To set up airscope on Windows:
    echo     1. Run scripts\vm\setup.bat as Administrator
    echo     2. Then double-click run.bat again
    echo.
    pause
    exit /b 1
)

echo   [OK] WSL2 Ubuntu found
echo.

REM Find airscope source
set SCRIPT_DIR=%~dp0

echo   Starting airscope in Linux...
echo.
wsl -d Ubuntu -e bash -c "cd ~ && if [ -d airscope/src ]; then cd airscope; elif [ -d 'Default Project/airscope/src' ]; then cd 'Default Project/airscope'; else echo 'airscope not found. Run setup first.'; exit 1; fi && if [ ! -d .venv ]; then python3 -m venv .venv && .venv/bin/pip install -e '.' > /dev/null 2>&1; fi && .venv/bin/airscope"
