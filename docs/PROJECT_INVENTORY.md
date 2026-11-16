# PROJECT INVENTORY - airscope v0.3.8

## Overview

**Project**: airoscpe  
**Version**: 0.3.8  
**License**: GPL-2.0-only  
**Language**: Python >= 3.11  
**Platform**: Linux, Windows (via WSL2), macOS (Intel native + Lima VM for EvilTwin; Apple Silicon native)  
**Primary Purpose**: Wi-Fi security auditing tool with TUI and web dashboard

### Key Differentiators

- **No kernel drivers required**: Uses libusb to communicate directly with USB Wi-Fi adapters in userspace
- **Pure Python implementation**: 802.11 stack, DHCP server, HTTP captive portal all written in Python
- **Cross-platform**: Single codebase runs on Linux, Windows (WSL2), and macOS
- **No external dependencies**: No hostapd, dnsmasq, reaver, or aircrack-ng subprocesses

---

## Repository Structure

```
airscope/
├── airscope.spec              # PyInstaller config for bundled binaries
├── pyproject.toml             # Project metadata, dependencies, build system (hatchling)
├── uv.lock                    # Deterministic dependency lockfile (uv)
├── LICENSE                    # GPL-2.0 license text
├── README.md                  # Main documentation
├── CONTRIBUTING.md            # Development guidelines
├── assets/                    # UI assets (icons, demo GIF, device card art)
│   ├── airscope.ico
│   └── cardart/               # Device-specific SVGs for TUI
├── docs/                      # Extended documentation
│   ├── ACKS.md
│   ├── CREDITS.md
│   ├── FIRMWARE.md
│   ├── GRADING.md
│   ├── LINUX-PERMISSIONS.md
│   ├── SUPPORTED-HARDWARE.md
│   ├── THEMES.md
│   ├── img/
│   └── releases/              # Release notes per version
├── scripts/                   # Helper scripts for various tasks
│   ├── ack/                   # ACK-related utilities (TX retries, RX auto-ack)
│   ├── ap/                    # AP simulation tools (fake_ap, fake_auth, crack)
│   ├── baseline/              # Performance baselines across OSes
│   ├── capture/
│   │   ├── pcap.py            # PCAP generation helpers
│   │   └── wpcap.py           # WPCAP format writer
│   ├── cracker/               # Cracking utilities (hashcat, hccapx)
│   ├── devices/               # Device enumeration and info tools
│   ├── eapol/
│   │   └── aggregate.py       # EAPOL frame aggregation helper
│   ├── hopper/                # Channel hopping utilities
│   ├── pcap/
│   │   ├── builder.py         # PCAP file builder
│   │   └── parser.py          # PCAP file parser
│   └── wps/                   # WPS-related utilities (pin, pbc)
├── src/airscope/              # Main source code
│   ├── __init__.py            # Package init with version
│   ├── __main__.py            # CLI entry point and main() function
│   ├── diagnose.py            # Diagnostics module
│   ├── doctor.py              # Setup validation / pre-flight checks
│   ├── errors.py              # Custom exception classes
│   ├── exports.py             # Export functions (CSV, netxml, HTML)
│   └── tokens.py              # Token types for UI rendering
├── src/airscope/campaigns/    # Attack orchestration
│   ├── __init__.py
│   └── batch.py               # Batch runner for headless mode
├── src/airscope/chips/        # Device driver packages (discovered dynamically)
│   └── [chipname]_dkms/       # Each chip has its own driver module
│       ├── constants.py
│       ├── transport.py
│       ├── tx.py, rx.py
│       ├── firmware.py
│       ├── driver.py
│       └── ... (per-chip)
├── src/airscope/crack/        # Password cracking utilities
│   ├── __init__.py
│   └── common.py              # Common cracking helpers
├── src/airscope/device/       # Device management layer
│   ├── __init__.py
│   ├── manager.py             # DeviceManager, USB device enumeration
│   ├── watch.py               # DeviceWatch for hotplug detection
│   └── status.py              # DeviceStatus enum and helpers
├── src/airscope/dot11/        # 802.11 frame types and parsers
│   ├── __init__.py
│   ├── frames.py              # Frame structure definitions
│   ├── parser.py              # WlanFrameParser for RX frames
│   └── ... (various frame types)
├── src/airscope/evil_twin/    # Evil Twin / captive portal features
│   ├── __init__.py
│   ├── server.py              # HTTP server for phishing pages
│   └── captive_portal.py      # Captive portal implementation
├── src/airscope/models/       # Data models
│   ├── __init__.py
│   ├── access_point.py        # AccessPoint model
│   ├── client.py              # Client model
│   └── ... (other models)
├── src/airscope/persist/      # Persistence layer (config, vault, logs)
│   ├── __init__.py
│   ├── config.py              # Config class for settings
│   ├── vault.py               # Vault for storing captured credentials
│   └── session.py             # Session logging
├── src/airscope/scripts/      # CLI helper scripts
│   └── capture.py             # Batch capture script (_auto command)
├── src/airscope/setup/        # One-time setup operations
│   ├── __init__.py
│   ├── permissions.py         # udev rules, libusb permissions
│   └── firmware.py            # Firmware loading logic
├── src/airscope/ui/           # Textual TUI implementation
│   ├── __init__.py
│   ├── app.py                 # AirscopeApp main class
│   ├── screens/               # All UI screens (splash, scanner, focus, vault)
│   ├── widgets/               # Custom widgets
│   ├── themes.py              # Theme management
│   └── pref.py                # Preferences modal
├── src/airscope/web/          # Web dashboard (FastAPI-based)
│   ├── __init__.py
│   ├── app.py                 # FastAPI app factory
│   ├── context.py             # HeadlessContext for demo mode
│   └── ... (routes, models)
└── src/airscope/wlan/         # Wireless interface and scanning
    ├── __init__.py
    ├── array.py               # WlanArray for managing multiple interfaces
    ├── interface.py           # WlanInterface per-device interface
    ├── channel_hop.py         # Channel hopping logic
    ├── eapol.py               # EAPOL frame handling
    └── ... (utilities)
├── tests/                     # pytest test suite (~3,008 tests)
│   ├── __init__.py
│   ├── conftest.py            # Test fixtures and mocks
│   ├── scripts/
│   ├── tests/                 # Unit and integration tests
│   └── web/                   # Web UI tests
├── webui/                     # Svelte-based web frontend
│   ├── index.html
│   ├── src/
│   ├── package.json
│   └── vite.config.ts
└── run.bat                    # Windows batch file launcher
```

---

## Entry Points

| Command | Purpose |
|---------|---------|
| `uv run airscope` | Launch TUI (default interactive mode) |
| `python -m airscope` | Same as above |
| `airscope --auto` | Headless batch mode (no TUI) |
| `airscope --web` | Start web dashboard |
| `airscope --doctor` | Run setup validation checks |
| `airscope --smoke` | Self-test (PyInstaller bundle integrity) |
| `airscope --export <format>` | Export captures to files |

---

## Major Modules

### Core System

| Module | Purpose |
|--------|---------|
| `src/airscope/__main__.py` | CLI entry point; platform detection, re-exec logic for Windows/macOS |
| `src/airscope/ui/app.py` | Textual App class; screen management, device watch loop |
| `src/airscope/doctor.py` | Pre-flight checks (udev rules, libusb, permissions) |

### Device Layer

| Module | Purpose |
|--------|---------|
| `src/airscope/device/manager.py` | DeviceManager: USB enumeration via libusb, chip discovery |
| `src/airscope/device/watch.py` | DeviceWatch: polls every 500ms for hotplug events |
| `src/airscope/chips/*/driver.py` | Per-chip driver (lazy-loaded); firmware load, register setup |

### Wireless Layer

| Module | Purpose |
|--------|---------|
| `src/airscope/wlan/array.py` | WlanArray: manages multiple interfaces, channel hopping |
| `src/airscope/wlan/interface.py` | WlanInterface: per-device RX/TX queue, frame parsing |
| `src/airscope/dot11/parser.py` | WlanFrameParser: decodes RX frames into models |

### Attack System

| Module | Purpose |
|--------|---------|
| `src/airscope/campaigns/batch.py` | BatchRunner: orchestrates attacks against multiple APs |
| `src/airscope/scripts/capture.py` | _auto command implementation (headless mode) |
| `src/airscope/evil_twin/server.py` | Evil Twin HTTP server with captive portal |

### Persistence

| Module | Purpose |
|--------|---------|
| `src/airscope/persist/config.py` | Config: stores user preferences, theme, log level |
| `src/airscope/persist/vault.py` | Vault: stores captured credentials (PSKs, PMKIDs) |

### Export & Web

| Module | Purpose |
|--------|---------|
| `src/airscope/exports.py` | Export functions: CSV, netxml, HTML reports |
| `src/airscope/web/app.py` | FastAPI app factory for web dashboard |

---

## Configuration Sources and Defaults

### Config File Location

- **Linux/macOS**: `~/.airscope/config.json`
- **Windows**: `%APPDATA%\airscope\config.json`

### Default Settings

```json
{
  "theme": "midnight",
  "log_level": null,  // null = auto-detect; can be "trace", "debug", "info", "quiet"
  "pbc_enabled": true,
  "channel_hop_interval": 3.0
}
```

### Environment Variables

| Variable | Purpose |
|----------|---------|
| `AIRSCOPE_LOG` | Override log level (trace/debug/info/quiet) |
| `AIRSCOPE_IN_VM` | Internal flag to indicate re-exec in VM (macOS Lima, Windows WSL2) |

---

## Dependencies

### Core Runtime

- `libusb-package>=1.0.26.3` - libusb shared library bundling
- `platformdirs` - Platform-specific config paths
- `pyusb>=1.3.1` - USB communication with adapters
- `rich` - Rich text formatting in console output
- `textual` - TUI framework

### Optional Features

- `fastapi>=0.115`, `uvicorn[standard]>=0.30` - Web dashboard (web group)
- `pillow>=12.3.0` - Image processing for bundle assets
- `pyinstaller>=6.21.0` - Binary packaging
- `pyshark>=0.6`, `httpx>=0.27` - Test-only web helpers

### Dev Dependencies (dev group)

- pytest, pytest-asyncio, pytest-mock
- ruff (linter; formatter disabled)
- textual-dev

---

## Test Suite

| Location | Description |
|----------|-------------|
| `tests/` | ~3008 tests, mostly unit/integration with mocked USB hardware |
| `tests/conftest.py` | Fixtures: mock devices, frame generators, platform detection |
| `tests/web/` | FastAPI endpoint tests |
| `tests/scripts/`, `tests/wlan/`, etc. | Per-module test organization |

**Test command**: `uv run pytest -m 'not slow'` (deselects heavyweight WEP crypto proofs)

---

## External Tools / Binaries Orchestrated

airscope uses **zero external subprocesses** for its attacks. All functionality is implemented in pure Python:

- ✅ No `aireplay-ng`, `aireplay`, or `iw` shell-outs
- ✅ No `hostapd`, `dnsmasq`, `reaver` subprocesses
- ❌ No kernel module loading (`modprobe`/`airmon-ng`)

**Exception**: Web dashboard spawns uvicorn (Python HTTP server) as a library call, not a separate process.

---

## Build & Packaging

| Command | Purpose |
|---------|---------|
| `uv sync --group dev` | Install editable + dev deps |
| `uv run airscope` | Run from source |
| `uv run pytest` | Run tests |
| `uv run ruff check src/` | Lint (formatter disabled) |
| `pyinstaller airscope.spec --noconfirm` | Build binary bundle |

**Note**: PyInstaller builds are platform-specific. Build separately for Linux, Windows, macOS.

---

## Notes

1. **Chip Discovery**: Drivers under `src/airscope/chips/` are discovered dynamically via pkgutil at runtime
2. **Version Source**: `__version__ = "0.3.8"` in `src/airscope/__init__.py` is the single source of truth (read by hatchling at build time)
3. **No `ruff format`**: The project disables formatting to preserve hand-formatted style; use lint-only
4. **Hardware Risk**: Register/firmware writes can brick devices; never touch EFUSE/EEPROM fuses
