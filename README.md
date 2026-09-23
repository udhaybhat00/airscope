<p align="center">
  <img src="assets/demo-tour.gif" alt="airscope demo" width="800">
</p>

<h1 align="center">airscope</h1>

<p align="center">
  <strong>Cross-platform USB Wi-Fi security auditor — pure Python, zero kernel drivers</strong>
</p>

<p align="center">
  <a href="https://github.com/udhaybhat00/airscope/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-GPL--2.0-blue" alt="License"></a>
  <img src="https://img.shields.io/badge/python-%3E%3D3.11-blue" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/platform-Linux%20%7C%20Windows%20%7C%20macOS-brightgreen" alt="Platform">
  <a href="https://github.com/udhaybhat00/airscope/actions/workflows/ci.yml"><img src="https://github.com/udhaybhat00/airscope/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <img src="https://img.shields.io/badge/tests-2982+-blue" alt="Tests">
  <img src="https://img.shields.io/badge/pure-Python-orange" alt="Pure Python">
</p>

<p align="center">
  airscope is a userland 802.11 security auditor that talks directly to USB wireless adapters via PyUSB. No kernel drivers, no monitor mode, no aircrack-ng — just Python, a Textual TUI, and a supported USB adapter.
</p>

---

## Table of Contents

- [Demo](#demo)
- [Why airscope?](#why-airscope)
- [Features](#features)
- [Architecture](#architecture)
- [Supported Hardware](#supported-hardware)
- [Installation](#installation)
- [Usage](#usage)
- [EvilTwin Deep-Dive](#eviltwin-deep-dive)
- [Project Structure](#project-structure)
- [Testing](#testing)
- [Configuration](#configuration)
- [Troubleshooting](#troubleshooting)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [License & Legal](#license--legal)
- [Acknowledgments](#acknowledgments)

---

## Demo

<p align="center">
  <img src="assets/demo-tour.gif" alt="airscope: live scanner, WPA handshake capture, WPS attack, hashcat cracking, and HTML report" width="800">
</p>

<p align="center"><em>Scanner → Focus → Attack → Vault — all in the terminal</em></p>

> Watch the TUI in action: [Video demo coming soon](#)

---

## Why airscope?

- **No kernel drivers** — pure userland PyUSB; no `airmon-ng`, no driver versioning hell
- **No external tool dependencies** — no aircrack-ng, no hostapd, no dnsmasq, no mdk3. Everything is Python
- **True cross-platform** — identical codebase on Linux/Windows/macOS; no "only works on Kali" limitation
- **Single binary** — PyInstaller produces a standalone executable per OS
- **Textual TUI + Web dashboard** — terminal-native UI with optional browser view
- **EvilTwin with real-time MIC verification** — WPA3 SAE downgrade that recovers plaintext password without offline cracking

### Comparison

| Feature | airscope | aircrack-ng | airgeddon |
|---------|----------|-------------|-----------|
| OS | Linux + Windows + macOS | Linux only | Linux only |
| Kernel driver required | No | Yes (monitor mode) | Yes |
| External tools | None | Many (hostapd, dnsmasq, etc.) | Many |
| TUI | Textual (asyncio) | CLI | CLI + xterm |
| Web dashboard | Yes | No | No |
| EvilTwin | Yes (3-step, MIC verify) | Manual | Yes (bash) |
| WPA3 SAE | Yes (downgrade + MIC) | Partial | No |
| WPS PixieDust | Yes | Yes (reaver) | No |
| Single binary | Yes (PyInstaller) | No | No |
| Python | 3.11+ | C | Bash |

---

## Features

### Reconnaissance

- **Real-time scanner** — 2.4 + 5 GHz channel hopping across multiple cards
- **Multi-card aggregation** — dedicated capture card + injection card
- **AP & client identification** — vendor fingerprinting, WPS beacon parsing
- **VAP decloaking** — hidden SSID detection via BSSID correlation
- **Signal strength metering** — tiered: Excellent / Good / Fair / Weak

### Captures

- **WPA/WPA2 4-way handshake** — passive sniffing + deauth-triggered
- **PMKID harvesting** — active + passive collection
- **WPS PushButton PSK capture**
- **Export formats** — `.pcap`, `.pcapng`, `.hc22000`, `.hccapx`

### Attacks

- **EvilTwin** (3-step: handshake → fake AP + deauth → MIC verification)
  - Handshake detection prompt (use existing / custom path / capture new)
  - Userland 802.11 AP (auth, assoc, DHCP, DNS blackhole, TCP/HTTP)
  - Captive portal (fake router firmware upgrade page)
  - Cross-platform (macOS / Windows / Linux)
- **WPS PixieDust** — offline PIN recovery from beacon
- **WPS PIN brute-force** — resumable
- **WEP suite** — ARP replay, ChopChop, fake auth, PTW key recovery
- **Batch "Auto Attack"** — sequential campaigns across multiple targets

### Analysis & Output

- **Vault** — capture manager, crack progress tracking
- **Hashcat integration** — offline cracking of captured handshakes
- **Real-time MIC verification** — WPA3 SAE → plaintext, no offline step
- **Report export** — CSV, Kismet netXML, cracked.txt, HTML
- **Log translation** — technical events → plain English, 15+ mappings

### UI / UX

- **Textual TUI** — asyncio-based, 60fps render
- **Web dashboard** — optional, same data as TUI (`--web`)
- **Signal Noir theme family** — dark + high-contrast variants
- **Animated startup banner**
- **Plain-English attack cards** with descriptions
- **3-step progress indicator** for EvilTwin
- **Scanner freeze mode** (`F` key)
- **Keyboard-first navigation** (all actions bindable)

---

## Architecture

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

### Design Decisions

- **PyUSB over kernel drivers** — cross-platform, no versioning hell, no `modprobe` blacklists
- **asyncio + dedicated USB thread** — non-blocking TUI, precise frame timing
- **Textual over curses/rich** — asyncio-native, CSS-like styling, widget tree
- **Userland AP stack** — no hostapd dependency, full control over 802.11 frames

---

## Supported Hardware

| Adapter | Chipset | 2.4 GHz | 5 GHz | Monitor | AP Mode | Notes |
|---------|---------|:-------:|:-----:|:-------:|:-------:|-------|
| Alfa AWUS036ACH | RTL8812AU | ✅ | ✅ | ✅ | ✅ | Recommended |
| Alfa AWUS036ACM | MT7612U | ✅ | ✅ | ✅ | ✅ | Grade A |
| Alfa AWUS036ACHM | RTL8821AU | ✅ | ✅ | ✅ | ✅ | Grade A |
| Alfa AWUS036AXML | MT7921AU | ✅ | ✅ | ✅ | ✅ | Wi-Fi 6 |
| TP-Link Archer T4U | RTL8812AU | ✅ | ✅ | ✅ | ✅ | Grade A |
| TP-Link Archer T3U | RTL8821AU | ✅ | ✅ | ✅ | ✅ | Grade A |
| ASUS BE93 | RTL8922AU | ✅ | ✅ | ✅ | ✅ | Wi-Fi 7 |
| Netgear A9000 | RTL8814AU | ✅ | ✅ | ⚠️ | ✅ | TX broken |
| MediaTek MT7925AU | MT7925AU | ✅ | ✅ | ✅ | ✅ | Wi-Fi 6E |

Any RTL8812AU or RTL8814AU-based USB dongle should work. The tool auto-detects by USB VID/PID. Full grading table: [docs/SUPPORTED-HARDWARE.md](docs/SUPPORTED-HARDWARE.md).

---

## Installation

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- Supported USB Wi-Fi adapter (see table above)

### Quick Start

```bash
git clone https://github.com/udhaybhat00/airscope.git
cd airscope
uv sync --group dev && uv run airscope
```

### Standalone Binary (no Python needed at runtime)

```bash
uv run pyinstaller airscope.spec --noconfirm --clean
# Output: dist/airscope (Linux), dist/airscope.exe (Windows), dist/airscope (macOS)
```

### One-Time Driver Setup (handled in-app)

| OS | What happens | User action |
|----|-------------|-------------|
| Linux | udev rule + modprobe blocklist via pkexec | One sudo prompt |
| macOS | IOKit authorization | Click "Allow" in dialog |
| Windows | WinUSB driver install via UAC | One UAC prompt |

Undo anytime from Splash → Uninstall, then re-plug the adapter.

---

## Usage

### Step-by-step walkthrough

1. **Launch** → Animated startup banner → Splash screen
2. **Select adapter** → Pick from detected cards (band badges shown: `2G`/`5G`)
3. **Press START** → Driver setup (first time only) → Scanner
4. **Scan** → Live network table (signal, encryption, WPS, clients)
5. **Select target** → Focus screen (attack cards appear)
6. **Choose attack** → e.g., EvilTwin
7. **Step 1:** Handshake capture (or use existing)
8. **Step 2:** Fake AP + deauth (captive portal active)
9. **Step 3:** MIC verification → plaintext password
10. **Review results** → Vault (captures, credentials, reports)

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `F` | Freeze/unfreeze scanner |
| `Ctrl+P` | Toggle theme |
| `Esc` | Back / Cancel / Stop |
| `Enter` | Select / Confirm |
| `Space` | Mark target for batch |
| `B` | Batch-attack marked targets |

### Headless Batch Mode

```bash
uv run airscope --auto                                    # scan, then attack everything
uv run airscope --auto --targets HomeNet,aa:bb:cc:dd:ee:ff --scan-secs 15
uv run airscope --auto --list                             # print APs in range and exit
uv run airscope --auto --session night1.jsonl --pmkid-timeout 180
```

### Web Dashboard

```bash
uv run airscope --web                    # live dashboard at http://127.0.0.1:8765/
uv run airscope --web --demo             # simulated scan, no hardware needed
uv run airscope --web --port 9000 --no-browser
```

Needs the web extras once: `uv sync --extra web`.

### CLI Flags

| Flag | Description |
|------|-------------|
| `--version` | Print version and exit |
| `--auto` | Headless batch mode |
| `--list` | Print APs in range and exit |
| `--targets` | Comma-separated BSSIDs or SSID substrings |
| `--scan-secs` | Seconds to scan before attacking (default 30) |
| `--web` | Serve web dashboard |
| `--port` | Dashboard port (default 8765) |
| `--demo` | Simulated scan, no hardware |
| `--session` | JSONL session log path |
| `--export` | `csv`, `netxml`, `cracked`, `html`, or `all` |
| `--quiet` | No logs |
| `--debug` / `--trace` | Verbose logging |

---

## EvilTwin Deep-Dive

The EvilTwin is airscope's flagship attack. It creates a rogue access point that mimics a target network, captures the WPA handshake, and verifies the password in real-time.

### 3-Step Flow

```
┌──────────────────────────────────────────────────────────┐
│ Step 1: Handshake Capture                                │
│   Passive sniff + deauth → client reauths → 4-wayHS     │
│   OR: use existing .pcap from ~/airscope/captures/       │
└──────────────────────┬───────────────────────────────────┘
                       │
┌──────────────────────▼───────────────────────────────────┐
│ Step 2: Fake AP + Deauth                                 │
│   Userland 802.11 AP (OPEN mode)                         │
│   Auth → Assoc → DHCP (10.0.0.x) → DNS blackhole        │
│   Captive portal: "Wi-Fi Password Required" page         │
│   Deauth loop kicks real clients off original AP          │
└──────────────────────┬───────────────────────────────────┘
                       │
┌──────────────────────▼───────────────────────────────────┐
│ Step 3: MIC Verification                                 │
│   Password submitted on portal → MIC check against HS   │
│   If match: plaintext password recovered (no offline)    │
└──────────────────────────────────────────────────────────┘
```

### How the Userland AP Works

1. **Beacon frames** broadcast the rogue SSID every 100ms
2. **Authentication** — clients authenticate against the OPEN AP
3. **Association** — AP tracks per-client state (seq numbers, AID)
4. **DHCP** — userland DHCP server assigns `10.0.0.x` IPs
5. **DNS** — all queries resolve to `10.0.0.1` (blackhole)
6. **HTTP** — captive portal detection triggers OS-specific dialogs:
   - iOS/macOS: `/hotspot-detect.html` → system dialog
   - Android: `/generate_204` → notification
   - Windows: `/connecttest.htm` → captive portal UI
7. **Password capture** — form submission logged to `~/airscope/logs/captured_passwords.log`

### Handshake Detection Prompt

When an existing `.pcap` file is found in `~/airscope/captures/`, a modal dialog offers three options:

1. **Use existing** — skip Step 1, go straight to fake AP
2. **Custom path** — enter a path to a different handshake file
3. **Capture new** — run Step 1 as normal

### Cross-Platform

The entire flow works identically on:
- macOS 14+ (Apple Silicon + Intel)
- Windows 10/11 (with WinUSB driver via Zadig)
- Linux (Ubuntu 22.04+, with udev rule or sudo)

### No Offline Cracking Needed

MIC verification gives the plaintext password directly — no need to export to hashcat or aircrack-ng.

---

## Project Structure

```
airscope/
├── src/airscope/
│   ├── __init__.py
│   ├── __main__.py            # Entry point, CLI flags
│   ├── tokens.py              # Theme palette (Signal Noir)
│   ├── ui/
│   │   ├── app.py             # Main Textual App
│   │   ├── themes.py          # Theme registration
│   │   └── screens/           # Splash, Scanner, Focus, Vault, EvilTwin
│   ├── evil_twin/             # EvilTwin module (3-step)
│   │   ├── orchestration.py   # Flow control, handshake prompt
│   │   ├── ap/                # Userland AP (frames, dhcp, dns, tcp, http)
│   │   ├── screens/           # HandshakePrompt, PathInput modals
│   │   └── usb/               # USB worker thread, device layer
│   ├── campaigns/             # Attack campaigns (WPS, PMKID, WEP, SAE, batch)
│   ├── scanner/               # Channel hopping, AP/client tracking
│   ├── vault/                 # Capture storage, report export
│   ├── crack/                 # Handshake parsing, hashcat integration
│   ├── web/                   # Web dashboard (optional)
│   └── chips/                 # Driver implementations (AR9271, RTL8812AU, etc.)
├── tests/                     # 2982+ tests
├── docs/                      # THEMES.md, FIRMWARE.md, HARDWARE.md
├── assets/                    # Screenshots, GIFs, card art
├── scripts/                   # Build helpers
├── pyproject.toml
├── airscope.spec              # PyInstaller config
├── AGENTS.md                  # AI-assisted development conventions
├── CONTRIBUTING.md            # Dev setup, PR guidelines
└── README.md
```

---

## Testing

**2982 tests** — all tests run without hardware (USB interactions are mocked via pytest-mock).

```bash
uv run pytest                    # all tests
uv run pytest tests/evil_twin/   # module-specific
uv run pytest -k "dhcp"          # keyword filter
uv run pytest -x                 # stop on first failure
```

**Lint:**

```bash
uv run ruff check src/           # lint only (never format)
```

**CI:** [`.github/workflows/ci.yml`](.github/workflows/ci.yml) — lint + tests + import smoke on every push/PR.

---

## Configuration

| Setting | Location | Default |
|---------|----------|---------|
| Theme | `Ctrl+P` → theme | `airscope-noir` |
| Web dashboard port | `--port` flag | `8765` |
| Captures | `~/airscope/captures/` | Auto-created |
| Password log | `~/airscope/logs/captured_passwords.log` | Auto-created |
| Exports | `--out` flag | `airscope_exports/` |
| Log level | `--debug` / `--trace` | WARNING |

---

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| "No adapter found" | Wrong driver (Windows) | Run Zadig → WinUSB |
| "Permission denied" (Linux) | No udev rule | Press START → allow pkexec |
| Adapter not showing on macOS | IOKit authorization denied | System Settings → Privacy → allow |
| EvilTwin: clients don't associate | Firmware data-frame RX not enabled | Check adapter firmware version |
| EvilTwin: portal doesn't appear | DNS blackhole not responding | Check logs for DNS query handling |
| TUI lag on macOS | USB I/O on event loop | Ensure USB worker thread is active |
| PyInstaller binary crashes | Missing USB libs | Install libusb (Linux) / WinUSB (Windows) |

---

## Roadmap

- [ ] Multi-AP EvilTwin (simultaneous rogue APs on different channels)
- [ ] WPA3-SAE full handshake capture (no downgrade)
- [ ] Plugin system for custom attacks
- [ ] BLE / Zigbee sniffing
- [ ] Cloud report sharing

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup, PR guidelines, and code conventions.

```bash
uv sync --group dev       # install
uv run airscope           # run
uv run pytest             # test
uv run ruff check src/    # lint
```

Read [AGENTS.md](AGENTS.md) for AI-assisted development conventions.

---

## License & Legal

**Code:** [GNU General Public License v2.0](LICENSE)

**Firmware:** Vendor blobs loaded onto adapters are redistributed verbatim under their manufacturers' licenses (see [docs/FIRMWARE.md](docs/FIRMWARE.md)).

> **⚠️ Legal Notice:** airscope is intended exclusively for use on networks and equipment you own or are explicitly authorized to audit. Unauthorized access to computer networks is illegal in most jurisdictions (e.g., CFAA in the US, IT Act 2000 in India, Computer Misuse Act in the UK). The author accepts no liability for misuse. Use at your own risk.

---

## Acknowledgments

- [PyUSB](https://github.com/pyusb/pyusb) — cross-platform USB access
- [Textual](https://github.com/Textualize/textual) — terminal UI framework
- [Python asyncio](https://docs.python.org/3/library/asyncio.html) — concurrent I/O
- [Realtek RTL8812AU/RTL8814AU](https://www.realtek.com/) — chipset driver reference
- Attack workflows follow the playbook established by [Wifite](https://github.com/derv82/wifite2) and the [aircrack-ng](https://www.aircrack-ng.org) suite

---

<p align="center">
  Built with ❤️ and too much coffee<br>
  Star the repo if it helped: <a href="https://github.com/udhaybhat00/airscope">github.com/udhaybhat00/airscope</a>
</p>
