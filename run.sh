#!/bin/bash
# airscope launcher — starts Alpine VM, runs airscope.
set -euo pipefail

VM="airscope"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v limactl &>/dev/null; then
    echo "  Lima not found. Run: bash setup.sh"
    exit 1
fi

if ! limactl list 2>/dev/null | grep -q "^${VM}"; then
    echo "  Creating VM..."
    limactl start --name="$VM" "$SCRIPT_DIR/scripts/vm/airscope.yaml"
fi

STATUS=$(limactl list 2>/dev/null | grep "^${VM}" | awk '{print $2}' || echo "")
if [ "$STATUS" != "Running" ]; then
    echo "  Starting VM..."
    limactl start "$VM"
fi

# Create Linux venv inside VM (separate from macOS .venv)
limactl shell "$VM" ash -c "
    DIR='$SCRIPT_DIR'
    cd \"\$DIR\"
    if [ ! -d .venv-linux ]; then
        python3 -m venv .venv-linux
        .venv-linux/bin/pip install -e '.' > /dev/null 2>&1
    fi
    .venv-linux/bin/airscope $*
"
