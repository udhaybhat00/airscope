#!/bin/bash
# airscope setup — one command, ~80MB total.
set -euo pipefail

echo ""
echo "  airscope setup"
echo ""

# Lima
if ! command -v limactl &>/dev/null; then
    echo "  Installing Lima..."
    brew install lima
fi
echo "  [ok] Lima"

# VM
if ! limactl list 2>/dev/null | grep -q "^airscope"; then
    echo "  Creating Alpine VM (~80MB)..."
    limactl start --name=airscope "$(dirname "$0")/scripts/vm/airscope.yaml"
fi
echo "  [ok] VM ready"

# Python venv inside VM
DIR="$(cd "$(dirname "$0")" && pwd)"
echo "  Setting up Python inside VM..."
limactl shell airscope ash -c "
    cd '$DIR'
    if [ ! -d .venv-linux ]; then
        python3 -m venv .venv-linux
        .venv-linux/bin/pip install -e '.' > /dev/null 2>&1
    fi
"
echo "  [ok] Python ready"

echo ""
echo "  Done! Run: bash run.sh"
echo ""
