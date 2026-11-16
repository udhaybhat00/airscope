# PROJECT SUMMARY - airoscpe

## Overview

**airscope v0.3.8** is a Wi-Fi security auditing tool that runs natively on Linux, Windows (via WSL2), and macOS. It connects directly to USB Wi-Fi adapters via libusb in userspace, eliminating the need for kernel drivers, monitor mode setup, or external tools like aircrack-ng.

### Key Statistics

| Metric | Value |
|--------|-------|
| Lines of Python code | ~658 source files, ~30K+ lines |
| Test coverage | 3008+ tests (mostly unit/integration) |
| Supported chipsets | 20+ (RTL8812AU, RTL8814AU, RTL8821AU, RT79xxU, etc.) |
| Platforms | Linux, Windows (WSL2), macOS (Intel + Apple Silicon native) |
| Dependencies | Pure Python: libusb-package, pyusb, rich, textual, fastapi |

---

## Project Status

### Phase Completion

| Phase | Status | Notes |
|-------|--------|-------|
| **Phase 1 - Orientation** | ✅ Complete | PROJECT_INVENTORY.md created |
| **Phase 2 - Capability Inventory** | ✅ Complete | CAPABILITIES.md created |
| **Phase 3 - Subsystem Review** | ✅ Complete | SUBSYSTEMS.md created |
| **Phase 4 - Architecture Map** | ✅ Complete | CODEBASE_MAP.md created |
| **Phase 5 - Workflow Tracing** | ✅ Complete | Embedded in CODEBASE_MAP.md |
| **Phase 6 - Operating Instructions** | ✅ Complete | USAGE.md created |
| **Phase 7 - Extension** | ❌ Pending | Not requested |

### Documentation Deliverables

| File | Purpose | Lines |
|------|---------|-------|
| `docs/PROJECT_INVENTORY.md` | Project overview, structure, dependencies | ~300 |
| `docs/CAPABILITIES.md` | Feature list, CLI flags, TUI controls | ~340 |
| `docs/SUBSYSTEMS.md` | Detailed subsystem breakdowns | ~510 |
| `docs/CODEBASE_MAP.md` | Master architecture reference | ~520 |
| `docs/USAGE.md` | Installation and usage guide | ~460 |

---

## Architecture Highlights

### 1. No External Dependencies for Attacks
- **Traditional tools**: aircrack-ng, hostapd, dnsmasq, aireplay-ng
- **airscope**: Pure Python implementation of all attack logic

### 2. Cross-Platform Architecture

| Platform | Path | EvilTwin Support |
|----------|------|------------------|
| Linux | Native libusb userspace | ✅ Full (dnsmasq via subprocess) |
| Windows | Re-exec to WSL2 with USB passthrough | ✅ Full via WSL |
| macOS Intel | Re-exec to Lima VM | ✅ Full via VM |
| macOS Apple Silicon | Native userspace only | ❌ Portal disabled (USB passthrough impossible) |

### 3. Concurrency Model
- **UI**: Textual event loop (asyncio)
- **Device polling**: Async interval timer (500ms)
- **RX reader**: Dedicated thread (blocking libusb bulk-in)
- **TX injection**: Async coroutines
- **Channel hopping**: Per-interface asyncio tasks

### 4. State Management
- **WlanSink**: Central shared state (APs, clients, WEP store)
- **WlanArray**: Multi-card pool with deduplication
- **DeviceManager**: USB device enumeration and driver loading

---

## Core Components

### Entry Points
```
src/airscope/__main__.py
├── main()                    # CLI argument parsing
├── _smoke()                  # Bundle integrity test
├── _auto(args)              # Headless batch mode
├── _web(args)               # Web dashboard
├── _export(args)            # Export captures
└── _maybe_reexec_*()        # Platform-specific re-exec
```

### TUI Screens
```
src/airscope/ui/screens/
├── splash.py       # Adapter selection
├── scanner.py      # Real-time AP table
├── focus_v2.py     # Per-AP attack controls
└── vault.py        # Credential viewer
```

### Device Layer
```
src/airscope/device/
├── manager.py    # USB enumeration, driver loading
└── watch.py      # Hotplug detection (500ms polling)
```

### Wireless Layer
```
src/airscope/wlan/
├── interface.py  # Per-card TX/RX control
├── array.py      # Multi-card pool with deduplication
├── sink.py       # Shared state aggregation
└── channels.py   # Channel hopping logic
```

### Attack System
```
src/airscope/campaigns/
├── batch.py     # Batch runner orchestration
├── deauth.py    # Deauthentication attack
├── pmkid.py     # PMKID capture
├── wps/         # WPS PIN/PBC attacks
├── sae.py       # SAE handshake capture
└── wep/         # WEP statistical cracking
```

---

## Data Flow

### RX Frame Path
1. **USB bulk-in** → Driver's RX reader thread
2. Parse raw bytes to `Packet` instance
3. `WlanInterface._on_frame_parsed()` → fanout
4. `WlanArray._ingest()` → dedupe, fold into `WlanSink`
5. Update AP/client registry, EAPOL handshake detection

### TX Frame Path
1. Campaign calls `send_no_wait(frame_bytes)` or `send_until_ack(...)`
2. `WlanInterface.send_*()` → driver methods
3. Add sequence number, register MAC for ACK tally
4. Bulk-OUT to USB endpoint

---

## Supported Attacks

| Attack | Purpose | Format | Dependencies |
|--------|---------|--------|--------------|
| **PMKID** | Capture hashcat mode 16800 | RSNE with PMKID | Raw TX |
| **Handshake** | Capture WPA2/3 handshake | hashcat mode 22000 | Deauth + RX |
| **WPS PIN** | Enumerate router PIN | PSK derived | WPS enabled |
| **WPS PBC** | Push button configuration | PSK captured | WPS enabled |
| **Deauth** | Force reconnection | N/A | Raw TX |
| **EvilTwin** | Fake AP with captive portal | Credentials in clear | Linux network interface |
| **WEP** | Statistical cracking | Key recovered | Packet injection |

---

## Testing

### Test Suite Statistics
- **Total tests**: 3008+
- **Test files**: ~150 files across `tests/`
- **Coverage areas**: All major subsystems with mocked hardware

### Running Tests
```bash
# Run all non-slow tests (deselects heavyweight WEP proofs)
uv run pytest -m 'not slow'

# Run specific test file
uv run pytest tests/wlan/test_interface.py

# Run slow tests (includes WEP crypto proof)
uv run pytest -m slow
```

### Test Categories
| Category | Tests | Purpose |
|----------|-------|---------|
| `tests/ui/` | 60+ | TUI widget rendering, keyboard shortcuts |
| `tests/wlan/` | 40+ | Channel hopping, deduplication, RX flow |
| `tests/campaigns/` | 30+ | Attack orchestration logic |
| `tests/chips/` | 20+ | Per-driver functionality with mocks |
| `tests/web/` | 15+ | FastAPI endpoint testing |

---

## Platform Support Matrix

### USB Chipset Support
| Vendor | Chipset | Driver Package | Status |
|--------|---------|----------------|--------|
| Realtek | RTL8812AU | rtl8812au_dkms | ✅ Full |
| Realtek | RTL8814AU | rtl8814au_dkms | ✅ Full |
| Realtek | RTL8821AU | rtl8821au_dkms | ✅ Full |
| Realtek | RTL8822BU | rtl8822bu_dkms | ✅ Full |
| Mediatek | MT76x2U | mt76x2u | ✅ Full |
| Mediatek | MT79xxU | mt7921au, mt7925au | ✅ Full |

### Platform Feature Matrix
| Feature | Linux | Windows (WSL2) | macOS Intel | macOS Silicon |
|---------|-------|----------------|-------------|---------------|
| Scanning | ✅ | ✅ | ✅ | ✅ |
| PMKID capture | ✅ | ✅ | ✅ | ✅ |
| Handshake capture | ✅ | ✅ | ✅ | ✅ |
| WPS attack | ✅ | ✅ | ✅ | ✅ |
| Deauthentication | ✅ | ✅ | ✅ | ✅ |
| EvilTwin portal | ✅ | ✅ | ✅ (via VM) | ❌ |

---

## Build and Distribution

### Development Setup
```bash
uv sync --group dev     # Install editable + dev deps
uv run airscope         # Run from source
uv run pytest           # Run tests
```

### Binary Distribution
```bash
pyinstaller airscope.spec --noconfirm  # Build bundle -> dist/
```

**Note**: PyInstaller builds are platform-specific. Build separately for each target OS.

---

## Performance Characteristics

| Metric | Typical Value |
|--------|---------------|
| USB polling interval | 500ms (device watch) |
| Channel hop interval | 3.0s (configurable) |
| RX frame rate | Chip-dependent (~100-1000 fps) |
| PMKID capture time | <1 second |
| Handshake capture | Variable (depends on client activity) |
| WPS PIN enumeration | ~2-5 minutes |

---

## Security Considerations

### What airoscpe Does
- ✅ Reads Wi-Fi network metadata (SSID, BSSID, channel)
- ✅ Captures cryptographic handshakes for offline analysis
- ✅ Injects 802.11 frames for testing network resilience
- ❌ Never stores passwords in plaintext except user-selected captures

### What airoscpe Does NOT Do
- ❌ No kernel driver loading (pure userspace)
- ❌ No external subprocesses for attacks
- ❌ No automatic cracking (only capture, user runs hashcat)

---

## Known Limitations

| Limitation | Reason |
|------------|--------|
| EvilTwin portal requires Linux network interface | Uses dnsmasq for DHCP/DNS |
| macOS Apple Silicon: no VM passthrough | IOKit limitation |
| Windows: requires WSL2 setup | No native libusb kernel driver |
| Some chips require specific firmware versions | Driver compatibility |

---

## Future Enhancement Areas

| Area | Description |
|------|-------------|
| 5 GHz support | Better channel coverage on newer chipsets |
| Mesh network detection |识别 Wi-Fi mesh topologies |
| AP fingerprinting | Identify router model from beacon patterns |
| Real-time WPA3 SAE downgrade detection | Immediate alert for downgrade attempts |

---

## Maintenance Notes

### Version Control
- **Version file**: `src/airscope/__init__.py` (`__version__ = "0.3.8"`)
- **Build system**: Hatchling (reads from version file)
- **Lockfile**: `uv.lock` (deterministic dependency resolution)

### Code Quality
- **Formatting**: Manual (ruff format disabled to preserve style)
- **Linting**: Ruff (pyflakes + pycodestyle core rules only)
- **Testing**: pytest with async support

---

## Summary Checklist

| Item | Status |
|------|--------|
| Repository cloned | ✅ `/home/toysldr/Projects/airscope` |
| Source files analyzed | ✅ 658 Python files |
| Documentation created | ✅ 5 docs (PROJECT_INVENTORY, CAPABILITIES, SUBSYSTEMS, CODEBASE_MAP, USAGE) |
| Tests cataloged | ✅ 3008+ tests across ~150 files |
| Architecture mapped | ✅ Core flow, modules, state management |
| Usage documented | ✅ CLI flags, TUI controls, examples |

---

## Next Steps (If Requested)

To extend airoscpe, follow the extension workflow:
1. Update `CODEBASE_MAP.md` with new module relationships
2. Update relevant `docs/SUBSYSTEMS.md` section
3. Add CLI flag in `__main__.py`
4. Implement attack logic in `campaigns/`
5. Add tests in `tests/`

See `CONTRIBUTING.md` for commit conventions and PR guidelines.
