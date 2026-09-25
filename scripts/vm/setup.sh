#!/bin/bash
# airscope Linux VM setup for macOS.
# Installs Lima, creates a Linux VM with USB passthrough, and sets up airscope inside it.
#
# Usage: bash scripts/vm/setup.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VM_NAME="airscope"
CONFIG="$SCRIPT_DIR/airscope.yaml"

info()  { printf "\033[1;34m==>\033[0m %s\n" "$*"; }
ok()    { printf "\033[1;32m  ✓\033[0m %s\n" "$*"; }
warn()  { printf "\033[1;33m  !\033[0m %s\n" "$*"; }
err()   { printf "\033[1;31m  ✗\033[0m %s\n" "$*"; }

# --- 1. Check / install Lima ---
if command -v limactl &>/dev/null; then
    ok "limactl found: $(limactl --version 2>&1 | head -1)"
else
    info "Installing Lima (lightweight Linux VMs for macOS)..."
    if command -v brew &>/dev/null; then
        brew install lima
        ok "Lima installed via Homebrew"
    else
        err "Homebrew not found. Install it first: https://brew.sh"
        exit 1
    fi
fi

# --- 2. Check if VM already exists ---
if limactl list 2>/dev/null | grep -q "^${VM_NAME}"; then
    STATUS=$(limactl list 2>/dev/null | grep "^${VM_NAME}" | awk '{print $2}')
    if [ "$STATUS" = "Running" ]; then
        ok "VM '$VM_NAME' is already running"
    else
        info "Starting existing VM '$VM_NAME'..."
        limactl start "$VM_NAME"
        ok "VM started"
    fi
else
    info "Creating Linux VM '$VM_NAME' (this takes a few minutes)..."
    limactl start --name="$VM_NAME" "$CONFIG"
    ok "VM created and started"
fi

# --- 3. Install airscope inside the VM ---
info "Installing airscope dependencies inside the VM..."
limactl shell "$VM_NAME" bash -c '
    set -euo pipefail
    cd ~/

    # Find the airscope source (shared via mount or clone)
    if [ -d airscope/src ]; then
        cd airscope
    elif [ -d "Default Project/airscope/src" ]; then
        cd "Default Project/airscope"
    else
        echo "airscope source not found in home directory"
        echo "Make sure the project is in your home folder or ~/Default Project/"
        exit 1
    fi

    if [ ! -d .venv ]; then
        python3 -m venv .venv
        .venv/bin/pip install -e "." > /dev/null 2>&1
    fi
    echo "airscope installed in VM"
'
ok "airscope ready inside VM"

# --- 4. USB adapter check ---
info "Checking USB adapters in VM..."
USB_DEVS=$(limactl shell "$VM_NAME" lsusb 2>/dev/null || echo "(lsusb not available)")
if echo "$USB_DEVS" | grep -qi "realtek\|2357\|0bda\|8812\|8822"; then
    ok "WiFi adapter detected in VM"
else
    warn "No Realtek WiFi adapter detected in VM"
    warn "Plug in your adapter, then run:"
    warn "  limactl shell $VM_NAME lsusb"
    warn ""
    warn "If not visible, add your adapter's VID:PID to $CONFIG"
fi

# --- 5. Print usage ---
echo ""
info "Setup complete! Usage:"
echo ""
echo "  Start airscope in Linux VM:"
echo "    limactl shell $VM_NAME bash -c \"cd ~/airscope && uv run airscope\""
echo ""
echo "  Or use the shortcut script:"
echo "    bash $SCRIPT_DIR/launch.sh"
echo ""
echo "  Stop the VM:"
echo "    limactl stop $VM_NAME"
echo ""
echo "  Delete the VM:"
echo "    limactl delete $VM_NAME"
echo ""
