#!/usr/bin/env bash
# airscope setup -- run this once after cloning
set -e

echo "airscope setup"
echo ""

# Check uv
if command -v uv &>/dev/null; then
    echo "  [ok] uv found"
else
    echo "  [!] uv not found, installing..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

# OS-specific
OS=$(uname -s)
case "$OS" in
    Darwin)
        if ! brew list libusb &>/dev/null; then
            echo "  Installing libusb (macOS)..."
            brew install libusb
        else
            echo "  [ok] libusb already installed"
        fi
        ;;
    Linux)
        if ! ldconfig -p 2>/dev/null | grep -q libusb-1.0; then
            echo "  Installing libusb (Linux)..."
            if command -v apt &>/dev/null; then
                sudo apt install -y libusb-1.0-0
            elif command -v dnf &>/dev/null; then
                sudo dnf install -y libusb1
            elif command -v pacman &>/dev/null; then
                sudo pacman -S --noconfirm libusb
            fi
        else
            echo "  [ok] libusb already installed"
        fi
        ;;
    MINGW*|MSYS*|CYGWIN*)
        echo "  [!] Windows: If adapter not found, install WinUSB driver via Zadig"
        echo "      https://zadig.akeo.ie/"
        ;;
esac

# Install Python deps
echo "  Syncing dependencies..."
uv sync --group dev

# Run doctor
echo ""
uv run python -m airscope.doctor

echo ""
echo "Setup complete. Run: uv run airscope"
