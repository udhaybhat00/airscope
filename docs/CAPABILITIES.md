# CAPABILITIES - airscope

## Feature Overview

airscope is a Wi-Fi security auditing tool that provides the following capabilities:

1. **Real-time Scanning** - See all nearby Wi-Fi networks with signal strength, channel, encryption type
2. **Handshake Capture** - Capture WPA/WPA2/WPA3-PSK handshakes and PMKIDs for offline cracking
3. **WPS Attack** - Test against Wi-Fi Protected Setup vulnerabilities
4. **Evil Twin / Captive Portal** - Simulate APs to capture credentials in real-time with MIC verification
5. **Deauthentication Attacks** - Force clients to reconnect, capturing handshakes
6. **WEP Cracking** - Capture and crack WEP encryption via statistical attacks
7. **SAE Handshake Capture** - Capture WPA3-PSK SAE handshakes including downgrade attempts
8. **Batch Operations** - Headless mode for automated scanning and attacking multiple targets
9. **Export Reports** - Generate CSV, netxml, HTML reports of findings
10. **Web Dashboard** - Optional web interface for monitoring and control

---

## CLI Commands and Flags

### Main Entry Point: `uv run airscope`

#### Interactive Mode (TUI)
- **Command**: `uv run airscope` or `airscope`
- **Behavior**: Launches Textual-based terminal UI with scanner, focus, and vault screens
- **Keyboard Shortcuts**:
  - `Ctrl+P` - Preferences modal

#### Headless Batch Mode (`--auto`)
- **Command**: `uv run airscope --auto [OPTIONS]`
- **Purpose**: Fully automated scanning and attacking without TUI
- **Options**:
  - `--scan-secs N` - Scan duration in seconds (default: 15)
  - `--targets "bssid,ssid"` - Filter to specific targets (comma-separated BSSID or SSID partial match)
  - `--list` - List all discovered APs with channel/signal/SSID info
  - `--session PATH` - Session log file path (default: `airscope_auto_<timestamp>.jsonl`)
  - `--wps-timeout N` - WPS attack timeout in seconds (default: 60)
  - `--pmkid-timeout N` - PMKID capture timeout in seconds (default: 30)
  - `--hs-timeout N` - Handshake capture timeout in seconds (default: 30)
  - `--sae-timeout N` - SAE handshake timeout in seconds (default: 30)

#### Web Dashboard Mode (`--web`)
- **Command**: `uv run airscope --web [OPTIONS]`
- **Purpose**: Start FastAPI web dashboard
- **Options**:
  - `--host HOST` - Bind host (default: `127.0.0.1`)
  - `--port PORT` - Port number (default: `8000`)
  - `--demo` - Run in demo mode with simulated data
  - `--no-browser` - Suppress automatic browser opening

#### Diagnostic Mode (`--doctor`)
- **Command**: `uv run airscope --doctor`
- **Purpose**: Run setup validation checks
- **Options**:
  - `--list-usb` - List all USB devices (find adapter VID:PID)
  - `--add-adapter V PID` - Add custom adapter (e.g., `--add-adapter 13b1 011b`)

#### Self-Test Mode (`--smoke`)
- **Command**: `uv run airscope --smoke`
- **Purpose**: Verify PyInstaller bundle integrity
- **Behavior**: Tests libusb loading, TUI widget mounting, and chip discovery

#### Export Mode (`--export`)
- **Command**: `uv run airscope --export <FORMAT> [OPTIONS]`
- **Purpose**: Generate reports from captures
- **Options**:
  - `-o DIR` - Output directory (default: `airscope_exports/`)
  - `--session PATH` - Batch session log file for additional context

#### Global Flags
- `--debug` - Enable debug-level logging
- `--trace` - Enable trace-level logging (verbose)
- `--quiet` - Suppress logging output

---

## TUI Screens and Controls

### Splash Screen
**Purpose**: Initial adapter selection screen
**Controls**:
- Arrow keys to navigate device list
- Enter/Space to select adapter
- "Start" button to begin session

### Scanner Screen
**Purpose**: Real-time display of discovered networks
**Features**:
- Table view of APs with columns: BSSID, Channel, Signal, Encryption, SSID
- Filter by signal strength, encryption type
- Sort by channel, signal, BSSID
- PBC (Push Button Configuration) toggle
- "Focus" button to inspect selected AP

### Focus Screen (V2)
**Purpose**: Detailed view of a single AP with attack options
**Features**:
- AP information: BSSID, Channel, Signal, Encryption, SSID
- Client list table (if visible)
- Attack buttons:
  - **PMKID Capture** - Capture PMKID for offline cracking
  - **Handshake Capture** - Deauth clients to capture full handshake
  - **WPS Pin Attack** - Test against WPS PIN vulnerabilities
  - **WPS PBC Attack** - Push button configuration attack
  - **Evil Twin** - Create fake AP with captive portal (Linux-only)
  - **Deauth Broadcast** - Deauthenticate all clients on channel
- "Back" to return to scanner

### Vault Screen
**Purpose**: View captured credentials and cracked passwords
**Features**:
- List of captured handshakes/PMKIDs with AP details
- Cracked PSKs displayed in plaintext
- Export functionality to CSV/netxml formats
- Clear vault action

### Preferences Modal
**Purpose**: User configuration
**Options**:
- Theme selection (midnight default)
- Log level (trace/debug/info/quiet)
- PBC toggle

---

## Attack Implementations

### PMKID Capture
- **File**: `src/airscope/campaigns/batch.py` - `PMKIDCaptureStep`
- **How it works**:
  1. Send RSNE with PMKID to AP (4-way handshake start)
  2. Capture the first ANonce frame from AP containing PMKID
  3. Store for offline cracking (hashcat mode 16800)
- **Dependencies**: Chip supports raw 802.11 injection

### Handshake Capture
- **File**: `src/airscope/wlan/interface.py` - `deauth_client()`, `WlanSink`
- **How it works**:
  1. Deauth both AP and client (AP→Client, Client→AP frames)
  2. Monitor for reconnection 4-way handshake
  3. Capture M1-M4 frames with ANonce/SNonce/ MICs
  4. Store in hashcat format (mode 22000 for WPA-PWKI)
- **Dependencies**: Chip supports RX monitoring and frame injection

### WPS Pin Attack
- **File**: `scripts/ap/crack.py` - `WpsCrack`
- **How it works**:
  1. Send EAPOL start to AP
  2. Enumerate 8-digit PIN using divide-and-conquer (first 4 digits, then last 3, checksum)
  3. Calculate final digit from checksum algorithm
  4. If successful, extract PSK from AP response
- **Dependencies**: AP must have WPS enabled with default PIN or pin-enabled

### Evil Twin / Captive Portal
- **File**: `src/airscope/evil_twin/server.py` - HTTP server + captive portal logic
- **How it works**:
  1. Create fake AP with same SSID as target
  2. Start DHCP server and DNS blackhole
  3. Serve captive portal page on port 80
  4. Capture credentials submitted to login form
  5. Verify against real network via MIC check (if possible)
- **Dependencies**: Linux host network interface required (for dnsmasq)
- **Platform notes**: Disabled on macOS Apple Silicon; marked as "Linux-only" on other platforms

### Deauthentication
- **File**: `src/airscope/wlan/interface.py` - `deauth_broadcast()`, `deauth_client()`
- **How it works**:
  1. Build deauth frame with reason code 7 (class_2_frame_from_non_ap)
  2. Inject via driver's `inject_frame()` or `inject_frame_slow_retry()`
  3. For client-specific: monitor for ACKs to verify effectiveness
- **Dependencies**: Chip supports raw frame injection

### WEP Cracking
- **File**: `src/airscope/crack/common.py` - WEP attack logic
- **How it works**:
  1. Capture ARP packets (packet injection trick)
  2. Build statistical model of keystream bytes
  3. Recover plaintext via FMS attack or PTW
  4. Use ProcessPoolExecutor for parallel processing
- **Dependencies**: WEP network must be active with traffic

### SAE Handshake Capture
- **File**: `src/airscope/wlan/interface.py` - SAE-specific deauth
- **How it works**:
  1. Downgrade attack: force WPA3 → WPA2 transition
  2. Or capture WPA3-only handshake frames
  3. Store in hashcat format (mode 22000)
- **Dependencies**: Chip supports raw injection; AP must support downgrade

---

## Configuration Options

### Config File: `~/.airscope/config.json`

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `theme` | string | `"midnight"` | UI theme name |
| `log_level` | string/null | `null` | Log verbosity: trace/debug/info/quiet/null |
| `pbc_enabled` | bool | `true` | Enable PBC toggle in scanner |
| `channel_hop_interval` | float | `3.0` | Seconds between channel hops |

### Environment Variables

| Variable | Purpose |
|----------|---------|
| `AIRSCOPE_LOG` | Override log level (trace/debug/info/quiet) |
| `AIRSCOPE_IN_VM` | Internal: indicates re-exec in VM context |
| `AIRSCOPE_RTL8188` | For RTL8188eus: "mainline" to use mainline driver |
| `AIRSCOPE_RTL8812` | For RTL8812AU: "mainline" to use mainline driver |
| `AIRSCOPE_RTL8821` | For RTL8821AU: "mainline" to use mainline driver |
| `AIRSCOPE_RTL8814` | For RTL8814AU: "mainline" to use mainline driver |
| `AIRSCOPE_RTL8822` | For RTL8822BU: "mainline" to use mainline driver |

---

## External Tool Dependencies

airscope uses **zero external subprocesses** for core attacks. All implementation is pure Python:

- ✅ No shell-outs to aircrack-ng, aireplay-ng, hostapd, dnsmasq, reaver
- ✅ No kernel module loading (modprobe/airmon-ng)
- ❌ No external binary dependencies

**Exception**: Web dashboard uses uvicorn HTTP server library call.

---

## Supported Hardware

See [docs/SUPPORTED-HARDWARE.md](../../docs/SUPPORTED-HARDWARE.md) for complete list.

### Chipset Support Matrix

| Chipset | Vendor | Driver Package | Features |
|---------|--------|----------------|----------|
| RTL8812AU | Realtek | rtl8812au_dkms | Full (scan, capture, deauth, evil twin) |
| RTL8814AU | Realtek | rtl8814au_dkms | Full |
| RTL8821AU | Realtek | rtl8821au_dkms | Full |
| RTL8822BU | Realtek | rtl8822bu_dkms | Full |
| RTL8822CU | Realtek | rtl8822cu | Full |
| MT76x2U | Mediatek | mt76x2u | Full |
| AR9271 | Atheros | ar9271_v2 | Full (WEP, PMKID, deauth) |

---

## Data Formats

### Capture Storage: `~/.airscope/vault.db`
SQLite database with tables:
- `access_points` - BSSID, channel, encryption, last seen
- `handshakes` - M1-M4 frames, ANonce/SNonce, MICs
- `pmkids` - PMKID captures
- `cracked` - PSKs that were recovered

### Session Logs: `airscope_auto_<timestamp>.jsonl`
JSON Lines format with events:
```json
{"time": "2024-01-01T12:00:00Z", "event": "ap_found", "bssid": "...", "ssid": "..."}
{"time": "...", "event": "handshake_captured", "bssid": "...", "status": "success"}
```

### Export Formats

| Format | File | Description |
|--------|------|-------------|
| CSV | `airscope_exports/aps.csv` | AP list: BSSID, channel, signal, encryption, SSID |
| netxml | `airscope_exports/networks.netxml` | Wireshark-compatible XML |
| Cracked | `airscope_exports/cracked.txt` | PSKs in hashcat format |
| HTML | `airscope_exports/index.html` | Interactive dashboard |

---

## Platform-Specific Capabilities

### Linux (Native)
- ✅ Full feature set including EvilTwin captive portal
- ✅ No re-exec required
- ✅ Direct libusb access after udev rule installed

### Windows
- ✅ Full feature set via WSL2 transparent re-exec
- ⚠️ Requires usbipd-win for USB passthrough
- ❌ Native mode falls back to limited functionality

### macOS (Intel)
- ✅ Full features via Lima VM for EvilTwin portal
- ✅ Native: all attacks except captive portal
- ⚠️ First run prompts for USB access permission

### macOS (Apple Silicon)
- ✅ Full attacks natively (no USB passthrough to VMs possible)
- ⚠️ EvilTwin portal unavailable (requires Linux network interface)
- ❌ Lima VM not supported on ARM64

---

## Concurrency Model

| Component | Threading/Async | Purpose |
|-----------|-----------------|---------|
| Textual app | Main thread, async event loop | UI rendering, user input |
| DeviceWatch | Async interval timer (every 500ms) | Hotplug detection |
| RX reader | USB worker thread (blocking I/O) | Bulk-IN reads, frame parsing |
| Channel hopper | asyncio task per interface | Channel hopping loop |
| TX injection | asyncio async/await | Frame queuing and retry logic |
| Batch runner | asyncio tasks + ProcessPoolExecutor | Parallel WEP cracking |

---

## Error Handling

| Error Type | Handling |
|------------|----------|
| `BringUpPermissionsError` | Show setup dialog with one-time fixes (udev, WinUSB) |
| `AirscopeDeviceLostError` | Toast notification; if last card, return to splash |
| `USBError` (device gone) | Disconnect callback chain → app recovery modal |
| `ConfigError` | Show toast on startup, don't block launch |

---

## Summary of Implementation Files

| Feature | Primary Files |
|---------|---------------|
| CLI entry point | `src/airscope/__main__.py` |
| Device management | `src/airscope/device/manager.py`, `src/airscope/device/watch.py` |
| Wireless interface | `src/airscope/wlan/interface.py`, `src/airscope/wlan/array.py` |
| 802.11 parsing | `src/airscope/dot11/parser.py`, `src/airscope/dot11/frames.py` |
| Attacks | `src/airscope/campaigns/batch.py` |
| TUI screens | `src/airscope/ui/screens/*.py` |
| EvilTwin | `src/airscope/evil_twin/server.py`, `captive_portal.py` |
| Persistence | `src/airscope/persist/config.py`, `vault.py` |
| Web dashboard | `src/airscope/web/app.py`, `context.py` |
