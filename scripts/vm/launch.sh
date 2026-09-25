#!/bin/bash
# Launch airscope in a Linux VM on macOS.
# Starts the VM if needed, then runs airscope with full TX support.
#
# Usage: bash scripts/vm/launch.sh [extra args for airscope]
set -euo pipefail

VM_NAME="airscope"

info()  { printf "\033[1;34m==>\033[0m %s\n" "$*"; }
ok()    { printf "\033[1;32m  ✓\033[0m %s\n" "$*"; }
err()   { printf "\033[1;31m  ✗\033[0m %s\n" "$*"; }

# Check limactl
if ! command -v limactl &>/dev/null; then
    err "limactl not found. Run: bash scripts/vm/setup.sh"
    exit 1
fi

# Start VM if not running
STATUS=$(limactl list 2>/dev/null | grep "^${VM_NAME}" | awk '{print $2}' || echo "")
if [ "$STATUS" != "Running" ]; then
    info "Starting Linux VM..."
    limactl start "$VM_NAME" 2>/dev/null || {
        err "VM start failed. Try: limactl delete $VM_NAME && bash scripts/vm/setup.sh"
        exit 1
    }
    ok "VM started"
fi

# Find airscope source inside the VM
AIRSCOPE_DIR=$(limactl shell "$VM_NAME" bash -c '
    for d in ~/airscope ~/Default\ Project/airscope /tmp/airscope-vm/airscope; do
        if [ -d "$d/src" ]; then echo "$d"; exit 0; fi
    done
    echo ~/airscope
' 2>/dev/null | tr -d '\r')

info "Running airscope in Linux VM..."
echo ""

# Run airscope inside the VM, forwarding all args
# Use stdin/stdout/stderr directly for the TUI
exec limactl shell "$VM_NAME" bash -c "cd '$AIRSCOPE_DIR' && uv run airscope $*"
