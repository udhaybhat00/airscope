@echo off
REM Launch airscope in WSL2 on Windows.
REM
REM Usage: scripts\vm\launch.bat (double-click or run from cmd)
setlocal enabledelayedexpansion

echo.
echo  ============================================
echo   airscope - Starting in WSL2 Linux...
echo  ============================================
echo.

REM --- Check WSL2 ---
wsl --list --verbose 2>nul | findstr /i "Ubuntu" >nul 2>&1
if %errorlevel% neq 0 (
    echo  ERROR: WSL2 Ubuntu not found.
    echo  Run scripts\vm\setup.bat first.
    pause
    exit /b 1
)

REM --- List USB adapters ---
echo  Checking USB adapters...
wsl -d Ubuntu -e bash -c "lsusb 2>/dev/null | grep -i 'realtek\|2357\|0bda' || echo '  No Realtek adapter found in WSL2'"
echo.

REM --- USB attach helper ---
echo  To attach your WiFi adapter to WSL2:
echo    1. Plug in the adapter
echo    2. Run: usbipd list
echo    3. Run: usbipd bind --busid X-X
echo    4. Run: usbipd attach --wsl --busid X-X
echo.
echo  Or run airscope now (adapter may already be attached):
echo.

REM --- Launch airscope ---
wsl -d Ubuntu -e bash -c "
    cd ~
    if [ -d airscope/src ]; then
        cd airscope
    elif [ -d 'Default Project/airscope/src' ]; then
        cd 'Default Project/airscope'
    else
        echo 'airscope not found. Run setup first.'
        exit 1
    fi
    if [ ! -d .venv ]; then
        python3 -m venv .venv
        .venv/bin/pip install -e '.' > /dev/null 2>&1
    fi
    .venv/bin/airscope
"

if %errorlevel% neq 0 (
    echo.
    echo  airscope exited with an error.
    echo  Try: usbipd attach --wsl --busid BUS-ID
    pause
)
