<p align="center">
  <img src="assets/demo-tour.gif" alt="airscope demo" width="800">
</p>

<h1 align="center">airscope</h1>

<p align="center">
  <strong>Wi-Fi security auditing made simple</strong>
</p>

<p align="center">
  Scan networks. Capture handshakes. Test your defenses. All from one beautiful terminal app.
</p>

<p align="center">
  <a href="https://github.com/udhaybhat00/airscope/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-GPL--2.0-blue" alt="License"></a>
  <img src="https://img.shields.io/badge/python-%3E%3D3.11-blue" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/platform-Linux%20%7C%20Windows%20%7C%20macOS-brightgreen" alt="Platform">
  <a href="https://github.com/udhaybhat00/airscope/actions/workflows/ci.yml"><img src="https://github.com/udhaybhat00/airscope/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <img src="https://img.shields.io/badge/tests-2970+-blue" alt="Tests">
  <img src="https://img.shields.io/badge/pure-Python-orange" alt="Pure Python">
</p>

---

## What is airscope?

airscope is a **Wi-Fi security auditing tool** that runs on your laptop. It connects to a USB Wi-Fi adapter and helps you:

- **See** all nearby Wi-Fi networks in real-time
- **Capture** the "handshake" that proves a password was used
- **Test** if your network is vulnerable to common attacks
- **Generate reports** showing what was found

**Think of it like a stethoscope for your Wi-Fi network** — it listens, analyzes, and tells you what's wrong.

### Who is this for?

| User | What you can do |
|------|----------------|
| **Home user** | Check if your Wi-Fi password is strong enough |
| **IT admin** | Audit office networks for vulnerabilities |
| **Security researcher** | Full attack suite with real-time MIC verification |
| **Student** | Learn 802.11 wireless security hands-on |

---

## Quick Start (3 minutes)

### Step 1: Get the code

```bash
git clone https://github.com/udhaybhat00/airscope.git
cd airscope
```

### Step 2: Install

**Linux** (Ubuntu, Debian, Kali):
```bash
# Install system dependencies
sudo apt install python3 python3-venv libusb-1.0-0-dev iw

# Install Python dependencies
uv sync --group dev

# Run pre-flight check
uv run python -m airscope.doctor
```

**Windows** (10/11):
```powershell
# Option A: One-click setup (recommended)
.\scripts\vm\setup.bat

# Option B: Manual setup
# 1. Install WSL2: wsl --install
# 2. Install usbipd: winget install dorssel.usbipd-win
# 3. In WSL2: git clone + uv sync (same as Linux)
```

**macOS** (Apple Silicon or Intel):
```bash
# Install dependencies
brew install uv libusb

# Install Python dependencies
uv sync --group dev

# Run (scanning works natively)
uv run airscope
```

### Step 3: Plug in your adapter and run

```bash
uv run airscope
```

That's it! The app will guide you through everything else.

---

## What can airscope do?

### Reconnaissance (passive listening)

- **Real-time network scanner** — See all Wi-Fi networks around you, updating live
- **Signal strength meter** — Know which networks are strong vs. weak
- **Client detection** — See which devices are connected to which networks
- **WPS detection** — Identify networks with WPS enabled (potential vulnerability)
- **Hidden network detection** — Find networks that try to hide their name

### Capture attacks

- **WPA/WPA2 handshake capture** — The "proof" that a password was used
- **PMKID harvesting** — Capture without needing any clients connected
- **WPS PushButton capture** — Get the network key via WPS
- **WEP key recovery** — Recover WEP encryption keys

### Active attacks (requires Linux)

- **EvilTwin** — Create a fake version of a network to capture passwords
  - Shows a professional "password required" page to users
  - Verifies passwords in real-time (no offline cracking needed)
  - Works on iOS, Android, Windows, macOS clients
- **Deauthentication** — Disconnect devices from a network
- **WPS PixieDust** — Recover WPS PINs offline
- **WPS PIN brute-force** — Try all possible WPS PINs

### Analysis & reporting

- **Vault** — Organize all your captures in one place
- **Hashcat integration** — Crack captured handshakes
- **Export reports** — CSV, Kismet netXML, HTML
- **Plain English explanations** — No cryptic jargon

---

## Platform Support

| Platform | Scanning | Handshake Capture | EvilTwin / Deauth | How it works |
|----------|:--------:|:-----------------:|:-----------------:|--------------|
| **Linux** | Full | Full | Full | Native — runs directly on your machine |
| **Windows** | Full | Full | Full | Via WSL2 (Windows Subsystem for Linux) — transparent |
| **macOS** | Full | Full | Via Linux | Native scanning; attacks need a Linux machine |

### Linux (recommended)

Everything works natively. No special setup needed beyond installing dependencies.

### Windows

airscope runs inside **WSL2** (Windows Subsystem for Linux), which is a lightweight Linux environment built into Windows. You won't notice the difference — it's all transparent.

**First-time setup:**
1. Run `scripts\vm\setup.bat` as Administrator
2. Plug in your Wi-Fi adapter
3. Run `usbipd wsl attach --busid <BUSID>` (PowerShell as Admin)
4. Run `uv run airscope`

### macOS

airscope runs natively on macOS for **scanning and capture**. For **active attacks** (EvilTwin, deauth), you need a Linux machine because:

> macOS doesn't allow Wi-Fi adapters to transmit arbitrary frames. This is a hardware/OS limitation — no software can fix it.

**What works on macOS:**
- Scan nearby networks
- Capture handshakes (when clients reconnect)
- View the vault and reports
- Run the web dashboard

**What needs Linux:**
- EvilTwin attacks
- Deauthentication
- Any attack that transmits custom frames

**Tip:** Plug the adapter into a Raspberry Pi, old laptop, or cloud VM running Linux, then control it from your Mac.

---

## How it works (for technical users)

airscope talks directly to USB Wi-Fi adapters using **PyUSB** — no kernel drivers needed. This means:

1. **No `airmon-ng`** — no driver versioning hell
2. **No `hostapd`** — we run our own userland AP stack
3. **No `dnsmasq`** — our own DHCP/DNS servers
4. **Pure Python** — everything is in one codebase

### Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│ airscope (Python 3.11+, asyncio)                                   │
│                                                                     │
│  ┌──────────────┐  ┌───────────────┐  ┌─────────────────────────┐  │
│  │ Textual TUI  │  │ Web Dashboard │  │ Report / Vault          │  │
│  └──────┬───────┘  └──────┬────────┘  └────────────┬────────────┘  │
│         │                 │                         │               │
│  ┌──────┴─────────────────┴─────────────────────────┴────────────┐  │
│  │ Attack Orchestrator (asyncio tasks)                           │  │
│  │ - Scanner  - EvilTwin  - WPS  - WEP  - Batch                 │  │
│  └──────────────────────────┬────────────────────────────────────┘  │
│                             │                                       │
│  ┌──────────────────────────┴────────────────────────────────────┐  │
│  │ USB Worker Thread (PyUSB, blocking I/O)                      │  │
│  │ - RX: 802.11 frame dispatch                                   │  │
│  │ - TX: priority queue (mgmt > dhcp > http > beacon > deauth)  │  │
│  │ - Beacon timer (100ms)  - Deauth timer (configurable)        │  │
│  └──────────────────────────┬────────────────────────────────────┘  │
│                             │                                       │
│  ┌──────────────────────────┴────────────────────────────────────┐  │
│  │ Userland 802.11 Stack (pure Python)                          │  │
│  │ - Frame crafting (beacon, auth, assoc, deauth, data)         │  │
│  │ - DHCP server  - DNS blackhole  - TCP/HTTP                   │  │
│  │ - Handshake parser  - PMKID extractor  - WPS parser          │  │
│  └──────────────────────────┬────────────────────────────────────┘  │
│                             │                                       │
│  ┌──────────────────────────┴────────────────────────────────────┐  │
│  │ PyUSB → USB Bulk Endpoints → RTL8812AU / RTL8814AU           │  │
│  │ (userland, no kernel driver)                                  │  │
│  └───────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

### Why no kernel drivers?

Traditional Wi-Fi auditing tools (aircrack-ng, etc.) require putting your adapter into "monitor mode" using kernel drivers. This causes:

- Driver version conflicts
- "Cannot find modprobe" errors
- Different commands for every Linux distribution
- Nothing works on macOS or Windows

airscope talks to the USB device directly. The same code runs on Linux, Windows (via WSL2), and macOS. No driver headaches.

### The EvilTwin flow (simplified)

```
1. CAPTURE    → Listen for the real network's WPA handshake
2. FAKE AP    → Broadcast a convincing copy of the target network
3. DEAUTH     → Kick real clients off the original network
4. PORTAL     → Show "password required" page to disconnected users
5. VERIFY     → Check submitted password against captured handshake
6. RESULT     → Real-time password verification (no offline cracking)
```

---

## Supported Hardware

Any USB Wi-Fi adapter with a supported chipset should work. airscope auto-detects adapters by USB vendor/product ID.

### Recommended adapters

| Adapter | Chipset | Bands | Why it's good |
|---------|---------|-------|---------------|
| **Alfa AWUS036ACH** | RTL8812AU | 2.4 + 5 GHz | Best overall, reliable |
| **Alfa AWUS036ACM** | MT7612U | 2.4 + 5 GHz | Excellent Linux support |
| **TP-Link Archer T3U** | RTL8822BU | 2.4 + 5 GHz | Budget-friendly |
| **Alfa AWUS036ACHM** | RTL8821AU | 2.4 + 5 GHz | Compact, reliable |

### How to check if your adapter works

```bash
# Plug in your adapter, then run:
uv run python -m airscope.doctor --list-usb

# This shows all USB devices and identifies supported ones
```

### Adding custom adapters

If your adapter isn't detected:

```bash
# 1. Find your adapter's USB IDs
uv run python -m airscope.doctor --list-usb

# 2. Add it (example: VID=2357, PID=0138)
uv run python -m airscope.doctor --add-adapter 2357 0138

# 3. Run airscope again
uv run airscope
```

Full hardware documentation: [docs/SUPPORTED-HARDWARE.md](docs/SUPPORTED-HARDWARE.md)

---

## First-time walkthrough

When you first run airscope, it will:

1. **Check your system** — Verify Python, USB access, and adapter
2. **Guide you through setup** — Install any missing dependencies
3. **Show the splash screen** — Select your Wi-Fi adapter
4. **Bring up the adapter** — Set it to the correct mode (first time only)
5. **Start scanning** — See all nearby networks in real-time

### The main screens

**Splash Screen** — Select your adapter and start
```
    * * * * * *
*               *
    * * * * * *
 A I R S C O P E
 ─────────────────
  wireless auditor

 Choose your Wi-Fi adapter to get started

 [RTL8812AU · Alfa AWUS036ACH]
 [Start Scanning] [Uninstall] [Captured Results] [Settings]
```

**Scanner** — Live network table
```
 ┌──────────────────────────────────────────────────────┐
 │ Network          │ Ch │ Signal │ Enc │ Clients │ WPS │
 ├──────────────────┼────┼────────┼─────┼─────────┼─────┤
 │ HomeNetwork      │ 6  │ -42 dBm│ WPA2│ 3       │ No  │
 │ CoffeeShop_Guest │ 11 │ -65 dBm│ Open│ 12      │ Yes │
 │ Hidden_5G        │ 36 │ -58 dBm│ WPA3│ 1       │ No  │
 └──────────────────┴────┴────────┴─────┴─────────┴─────┘
```

**Focus** — Attack options for a selected network
**Vault** — View captured handshakes and cracked passwords

---

## Usage examples

### Basic scanning

```bash
uv run airscope
# 1. Select your adapter
# 2. Press Start
# 3. Watch networks appear in real-time
```

### Headless batch mode

```bash
# Scan for 30 seconds, then attack everything
uv run airscope --auto

# Scan for 60 seconds, attack specific targets
uv run airscope --auto --targets HomeNetwork,OfficeWiFi --scan-secs 60

# Just list what's in range (no attacks)
uv run airscope --auto --list
```

### Web dashboard

```bash
# Open in your browser
uv run airscope --web

# Demo mode (no hardware needed)
uv run airscope --web --demo

# Custom port
uv run airscope --web --port 9000
```

### Export reports

```bash
# Export everything
uv run airscope --export all

# Export just CSV
uv run airscope --export csv --out my-report
```

---

## Configuration

| Setting | Where | Default |
|---------|-------|---------|
| Theme | `Ctrl+P` in the TUI | Signal Noir (dark) |
| Captures folder | `~/airscope/captures/` | Auto-created |
| Adapter list | `~/.airscope/adapters.json` | Auto-populated |
| Web dashboard | `--port` flag | 8765 |
| Log level | `--debug` or `--trace` | WARNING |

---

## Keyboard shortcuts

| Key | Action |
|-----|--------|
| `Enter` | Select / Confirm |
| `Space` | Mark target for batch attack |
| `F` | Freeze scanner (stop re-sorting) |
| `Ctrl+P` | Open preferences |
| `Esc` | Back / Cancel |
| `q` | Quit |

---

## Troubleshooting

### "No adapter found"

**Linux:**
```bash
# Check if adapter is detected
lsusb | grep -i realtek

# Check USB permissions
ls -la /dev/bus/usb/

# Fix permissions (add udev rule)
echo 'SUBSYSTEM=="usb", MODE="0666"' | sudo tee /etc/udev/rules.d/99-airscope.rules
sudo udevadm control --reload
```

**Windows:**
```powershell
# Check WSL2 can see the adapter
wsl -e lsusb

# If not, attach it
usbipd list
usbipd bind --busid <BUSID>
usbipd attach --wsl --busid <BUSID>
```

**macOS:**
```bash
# Check adapter is detected
system_profiler SPUSBDataType | grep -A5 -i realtek

# Grant USB access
# System Settings → Privacy & Security → USB → Allow airscope
```

### "Permission denied" on Linux

```bash
# Option 1: Run with sudo (quick fix)
sudo uv run airscope

# Option 2: Add udev rule (permanent fix)
echo 'SUBSYSTEM=="usb", MODE="0666"' | sudo tee /etc/udev/rules.d/99-airscope.rules
sudo udevadm control --reload
sudo udevadm trigger
```

### Adapter works in Linux but not macOS

This is expected. macOS doesn't support Wi-Fi frame injection. Use airscope on Linux for full features.

### WSL2 not seeing the adapter

```powershell
# Make sure usbipd is installed
winget install dorssel.usbipd-win

# Restart WSL2
wsl --shutdown

# Re-attach the adapter
usbipd attach --wsl --busid <BUSID>
```

---

## Development

### Setup

```bash
git clone https://github.com/udhaybhat00/airscope.git
cd airscope
uv sync --group dev
```

### Run tests

```bash
uv run pytest                    # all tests
uv run pytest tests/campaigns/   # specific module
uv run pytest -k "dhcp"          # keyword filter
uv run pytest -x                 # stop on first failure
```

### Lint

```bash
uv run ruff check src/           # lint only (never format)
```

### Architecture docs

- [docs/SUPPORTED-HARDWARE.md](docs/SUPPORTED-HARDWARE.md) — Hardware compatibility
- [docs/FIRMWARE.md](docs/FIRMWARE.md) — Firmware loading
- [docs/THEMES.md](docs/THEMES.md) — Theme customization
- [AGENTS.md](AGENTS.md) — AI-assisted development conventions

---

## Comparison with other tools

| Feature | airscope | aircrack-ng | airgeddon | Wifite |
|---------|----------|-------------|-----------|--------|
| **Platform** | Linux + Windows + macOS | Linux only | Linux only | Linux only |
| **Kernel driver needed** | No | Yes | Yes | Yes |
| **External tools** | None | Many | Many | Many |
| **User interface** | TUI + Web | CLI | CLI + xterm | CLI |
| **EvilTwin** | Yes (3-step) | No | Yes (bash) | No |
| **WPA3 SAE** | Yes | Partial | No | No |
| **Real-time cracking** | Yes (MIC) | No | No | No |
| **Single binary** | Yes | No | No | No |
| **Language** | Python | C | Bash | Bash |

---

## Roadmap

- [ ] Multi-AP EvilTwin (simultaneous rogue APs)
- [ ] WPA3-SAE full handshake capture (no downgrade)
- [ ] Plugin system for custom attacks
- [ ] BLE / Zigbee sniffing
- [ ] Cloud report sharing
- [ ] Mobile companion app

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup, PR guidelines, and code conventions.

```bash
uv sync --group dev       # install
uv run airscope           # run
uv run pytest             # test
uv run ruff check src/    # lint
```

---

## License & Legal

**Code:** [GNU General Public License v2.0](LICENSE)

**Firmware:** Vendor blobs loaded onto adapters are redistributed verbatim under their manufacturers' licenses (see [docs/FIRMWARE.md](docs/FIRMWARE.md)).

> **Legal Notice:** airscope is intended exclusively for use on networks and equipment you own or are explicitly authorized to audit. Unauthorized access to computer networks is illegal in most jurisdictions. The author accepts no liability for misuse. Use at your own risk.

---

## Acknowledgments

- [PyUSB](https://github.com/pyusb/pyusb) — cross-platform USB access
- [Textual](https://github.com/Textualize/textual) — terminal UI framework
- [Python asyncio](https://docs.python.org/3/library/asyncio.html) — concurrent I/O
- [Realtek RTL8812AU/RTL8814AU](https://www.realtek.com/) — chipset reference
- Attack workflows inspired by [Wifite](https://github.com/derv82/wifite2) and [aircrack-ng](https://www.aircrack-ng.org)

---

<p align="center">
  Built with care for the Wi-Fi security community.<br>
  Star this repo if it helped you! ⭐
</p>
