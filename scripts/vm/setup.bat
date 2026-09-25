@echo off
REM airscope Windows setup - one-time installation.
REM Sets up WSL2 + Ubuntu + USB passthrough + airscope.
REM
REM Usage: scripts\vm\setup.bat (double-click or run from cmd)
setlocal enabledelayedexpansion

echo.
echo  ============================================
echo   airscope - Windows Setup
echo  ============================================
echo.

REM --- 1. Check WSL2 ---
echo  [1/5] Checking WSL2...
wsl --list --verbose 2>nul | findstr /i "Ubuntu" >nul 2>&1
if %errorlevel% equ 0 (
    echo        WSL2 Ubuntu found
) else (
    echo        Installing WSL2 + Ubuntu...
    wsl --install --distribution Ubuntu --no-launch
    if %errorlevel% neq 0 (
        echo.
        echo  ERROR: WSL2 installation failed.
        echo  Make sure:
        echo    1. Windows 10 build 19041+ or Windows 11
        echo    2. Run this as Administrator
        echo    3. Enable "Virtual Machine Platform" in Windows Features
        echo.
        pause
        exit /b 1
    )
    echo        WSL2 installed. Restart your PC, then run this script again.
    echo.
    pause
    exit /b 0
)

REM --- 2. Check USBIPd (for USB passthrough) ---
echo  [2/5] Checking USB passthrough (usbipd-win)...
winget list --id usbipd 2>nul | findstr /i "usbipd" >nul 2>&1
if %errorlevel% equ 0 (
    echo        usbipd-win found
) else (
    echo        Installing usbipd-win...
    winget install usbipd --accept-source-agreements --accept-package-agreements
    if %errorlevel% neq 0 (
        echo        usbipd install failed. Install manually from:
        echo        https://github.com/dorssel/usbipd-win/releases
    )
)

REM --- 3. Setup Ubuntu inside WSL2 ---
echo  [3/5] Setting up Ubuntu environment...
wsl -d Ubuntu -e bash -c "echo 'Ubuntu OK'" 2>nul
if %errorlevel% neq 0 (
    echo        Starting Ubuntu for first-time setup...
    wsl -d Ubuntu -e bash -c "sudo apt-get update -qq && sudo apt-get install -y -qq python3 python3-venv python3-pip build-essential libusb-1.0-0-dev git iw > /dev/null 2>&1"
)

REM --- 4. Install airscope inside WSL2 ---
echo  [4/5] Installing airscope in WSL2...
wsl -d Ubuntu -e bash -c "
    set -e
    cd ~
    if [ ! -d airscope ]; then
        # Find airscope source from Windows filesystem
        WIN_DIR=$(ls -d /mnt/c/Users/*/Documents/Default\\ Project/airscope 2>/dev/null | head -1)
        if [ -n \"$WIN_DIR\" ]; then
            ln -sf \"$WIN_DIR\" ~/airscope
        fi
    fi
    if [ -d ~/airscope/src ]; then
        cd ~/airscope
        if [ ! -d .venv ]; then
            python3 -m venv .venv
            .venv/bin/pip install -e \".\" > /dev/null 2>&1
        fi
        echo 'airscope installed'
    else
        echo 'airscope source not found - will clone on first run'
    fi
"

REM --- 5. Done ---
echo  [5/5] Setup complete!
echo.
echo  ============================================
echo   Usage
echo  ============================================
echo.
echo   1. Plug in your WiFi adapter
echo   2. Open WSL2 Ubuntu terminal
echo   3. Run:
echo.
echo      bash ~/airscope/scripts/vm/launch.sh
echo.
echo   Or from Windows PowerShell:
echo      wsl -d Ubuntu -e bash -c "cd ~/airscope && uv run airscope"
echo.
echo   To attach USB adapter to WSL2:
echo      usbipd list
echo      usbipd bind --busid BUS-ID
echo      usbipd attach --wsl --busid BUS-ID
echo.
pause
