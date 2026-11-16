# SUBSYSTEM DOCUMENTATION - airscope

## Overview

This document provides detailed breakdowns of each major subsystem in airscope. Each section covers:
- Purpose and responsibility
- Key classes and functions with one-line descriptions
- Inputs, outputs, state, side effects
- External commands/dependencies
- Error handling
- Integration points

---

## 1. CORE SYSTEM SUBSYSTEM

### Location: `src/airscope/__main__.py`, `src/airscope/ui/app.py`

#### Purpose
Entry point orchestration, platform detection, TUI lifecycle management.

#### Key Classes/Functions

| Name | Purpose |
|------|---------|
| `_maybe_reexec_in_wsl()` | Windows: transparently re-exec in WSL2 with USB passthrough |
| `_maybe_reexec_in_vm()` | macOS Intel: re-exec in Lima VM for EvilTwin captive portal |
| `AirscopeApp` | Textual app class; manages screens, device watch, themes |

#### Key Functions

| Name | Purpose |
|------|---------|
| `main()` | CLI argument parsing and dispatch to mode functions |
| `_auto(args)` | Headless batch mode execution |
| `_web(args)` | Web dashboard startup |
| `_export(args)` | Export captures to CSV/netxml/HTML |

#### State Created
- `DeviceManager` instance (USB device tracking)
- `DeviceWatch` polling task (500ms interval)
- `WlanArray` (wireless interface pool)
- `Vault` (credential storage)
- Config state from `~/.airscope/config.json`

#### Side Effects
- Creates/updates `~/.airscope/has_run_before` marker on first run
- Starts USB polling thread
- Launches Textual event loop

#### Error Handling
- Permissions errors → show setup dialog
- Device lost mid-session → toast notification or return to splash (if last card)
- Config parse errors → toast on startup, continue with defaults

#### Integration Points
- Imports all screen modules (`splash`, `scanner`, `focus_v2`, `vault`)
- Calls `_configure_file_logging()` for log file setup
- Registers `DeviceWatch` callbacks for hotplug events

---

## 2. DEVICE MANAGEMENT SUBSYSTEM

### Location: `src/airscope/device/manager.py`

#### Purpose
USB device enumeration, chip discovery, driver loading, interface creation.

#### Key Classes/Functions

| Name | Purpose |
|------|---------|
| `DeviceManager` | USB bus scanning, bring-up orchestration |
| `supported_ids()` | Returns `{(vid, pid): Claim}` for all supported devices |
| `driver_for(vid, pid)` | Returns `(driver_class, setup_key)` for a device |
| `resolve_driver(vid, pid, dev)` | Routes shared vid:pid to correct chip driver |
| `bringup(dev, ...)` | Connects driver, loads firmware, returns `BringupResult` |

#### Key Data Structures

**Claim NamedTuple**
```python
class Claim(NamedTuple):
    entry: DeviceID      # VID/PID metadata from chips/*/__init__.py
    key: str             # Driver package directory name
    import_driver: Callable[[], type[Driver]]  # Lazy driver load function
```

**BringupResult Dataclass**
```python
@dataclass
class BringupResult:
    status: Status       # READY, CANCELLED, FAILED
    message: str = ""
```

#### Key Functions

| Name | Purpose |
|------|---------|
| `supported_ids()` | Pkgutil walk over `chips/` to discover `(vid, pid): Claim` mapping |
| `driver_for(vid, pid)` | Lookup in supported IDs; returns driver class and setup key |
| `resolve_driver(vid, pid, dev)` | Handles shared vid:pid families (e.g., RTL8822CU vs MT76x2U on 0x2357:0x0137) |
| `DeviceManager.bringup(dev, ...)` | Instantiates driver, calls `driver.connect()`, returns interface |

#### State Created
- `supported_ids()` result (cached via `@functools.cache`)
- Driver instances per device (lazy-loaded)
- USB interface handles (`usb.core.Device`)

#### Side Effects
- Reads `/dev/bus/usb/*` on Linux (libusb backend)
- Loads firmware via bulk transfers to USB endpoint
- Registers udev rules on first run (Linux: `pkexec`)

#### External Dependencies
- `libusb_package.get_library_path()` - Bundled libusb shared library path
- `pyusb` - `usb.core.find(find_all=True)` for enumeration

#### Error Handling
- `BringUpError(stage, detail)` - Raised on bring-up failure (permissions, firmware, USB errors)
- `BringUpPermissionsError` - Subclass for fixable access issues (udev rules, WinUSB)

#### Integration Points
- `WlanArray.add()` → calls `DeviceManager.bringup()`
- UI splash screen → calls `supported_ids()` to populate device list

---

## 3. WIRELESS INTERFACE SUBSYSTEM

### Location: `src/airscope/wlan/interface.py`

#### Purpose
Per-device TX/RX queue, channel control, frame injection.

#### Key Classes/Functions

| Name | Purpose |
|------|---------|
| `WlanInterface` | Per-card interface; manages RX callbacks, hopping, frame injection |

#### Key Functions

| Name | Purpose |
|------|---------|
| `connect()` | Calls driver.connect() for hardware bring-up |
| `set_channel(channel)` | Tunes radio to channel via driver |
| `send_no_wait(frame_bytes)` | Fire-and-forget TX (no ACK wait) |
| `send_until_ack(frame_bytes, max_retries)` | Software-retry TX until recipient ACK observed |
| `deauth_broadcast(ap_bssid, count)` | Spray deauth frames to all clients on channel |
| `deauth_client(ap_bssid, client_bssid, rounds)` | Targeted client deauth with ACK tally |

#### State Created
- `_rx_callbacks: List[Callable[[Packet], None]]` - Frame subscribers list
- `_hopping_task: asyncio.Task` - Channel hop loop (if active)
- `current_channel: int` - Last tuned channel

#### Side Effects
- Calls `driver.enable_rx_acks()` to arm ACK tally
- Starts async hopping loop via `_hop_loop()`
- Injects raw 802.11 frames via driver bulk-OUT endpoint

#### External Dependencies
- Driver instance (`self.driver`) with:
  - `set_channel(channel)`
  - `inject_frame(frame_bytes)` / `inject_frame_slow_retry(...)`
  - `enable_rx_acks()` / `disable_rx_acks()`

#### Error Handling
- Device lost → `_on_device_lost()` → calls disconnect callbacks → app notified

#### Integration Points
- `WlanArray.attach(iface)` - Pools interface into shared sink
- Campaigns call TX methods directly on selected interface

---

## 4. WIRELESS ARRAY SUBSYSTEM

### Location: `src/airscope/wlan/array.py`

#### Purpose
Multi-card coordination: deduplication, channel partitioning, card selection for attacks.

#### Key Classes/Functions

| Name | Purpose |
|------|---------|
| `WlanArray` | Pool of interfaces; dedupe RX stream, pick TX interface |
| `WlanSink` | Shared 802.11 state: AP registry, client registry, WEP store |

#### Key Functions

| Name | Purpose |
|------|---------|
| `attach(iface)` | Add interface to pool, register callbacks |
| `select_iface(channel)` | Pick best interface for TX on channel (based on fake_mac support) |
| `start_hopping(channels, interval)` | Start channel hopping across all cards |
| `get_access_points(include_eviltwin=True)` | Return AP registry (optionally exclude twin BSSIDs) |

#### Key Features

**Deduplication**
- Uses `StreamMerger` to merge RX streams from multiple cards
- Drop frames we transmitted (keyed on transmitter MAC)

**Channel Partitioning**
- Splits channels across available cards when hopping
- Re-partitions on membership change (hotplug, unplug)

**Card Selection**
```python
def select_iface(channel) -> Optional[WlanInterface]:
    # 1. Prefer pinned card if it supports channel
    # 2. Otherwise, pick most attack-capable card (SPOOFABLE > FIXED_MAC > NONE)
```

#### State Created
- `self._members: List[WlanInterface]` - Pool of interfaces
- `self._dedupe: StreamMerger` - Deduplication engine
- `self._sink: WlanSink` - Shared state (APs, clients, wep_store)

#### Side Effects
- Starts hopping tasks per member
- Registers TX observer (`on_tx`) to record packet stats

#### Error Handling
- Member lost → `_member_lost()`:
  - Removes from pool
  - Re-partitions channels if hopping
  - Calls disconnect callbacks with remaining count
  - If count == 0: app returns to splash

---

## 5. 802.11 PARSING SUBSYSTEM

### Location: `src/airscope/dot11/parser.py`, `src/airscope/dot11/frames.py`

#### Purpose
Decode raw bytes into structured frame types.

#### Key Classes/Functions

| Name | Purpose |
|------|---------|
| `WlanFrameParser` | Top-level parser; routes to type-specific parsers |
| `Packet` base class | Common fields: bssid, rssi, transmitter, channel |

#### Frame Types Parsed

| Type | Class | Fields |
|------|-------|--------|
| Beacon | `BeaconPacket` | ssid, capabilities, supported_rates, channels, encryption |
| Probe Request | `ProbeRequestPacket` | ssid, rates |
| Probe Response | `ProbeResponsePacket` | ssid, capabilities, rates |
| Association Request | `AssocRequestPacket` | ssid, rates |
| Association Response | `AssocResponsePacket` | status, capability |
| Deauthentication | `DeauthPacket` | reason |
| Authentication | `AuthPacket` | algo, seq, status |
| EAPOL-Key | `EapolKeyPacket` | key_info, replay_counter, MIC |

#### Key Functions

| Name | Purpose |
|------|---------|
| `WlanFrameParser.parse_80211_frame(raw, rssi)` | Parse raw bytes → Packet instance |
| `parse_eapol(frame)` | EAPOL frame parser (M1-M4 handshake frames) |

#### State Created
- None (stateless parsing)

#### Side Effects
- InstantiatesPacket subclasses with parsed fields

---

## 6. ATTACK CAMPAIGNS SUBSYSTEM

### Location: `src/airscope/campaigns/*.py`

#### Purpose
High-level attack orchestration: WPS, PMKID, deauth, SAE.

#### Key Classes

| Class | File | Features |
|-------|------|----------|
| `WpsCampaign` | `wps.py` | Enumerate 8-digit PIN, calculate checksum, extract PSK |
| `PmkidHarvestAttack` | `pmkid.py` | Capture PMKID (RSN IE with PMKID), store for hashcat |
| `DeauthCampaign` | `deauth.py` | Client deauth to force reconnection handshake capture |
| `SaeCampaign` | `sae.py` | Downgrade or direct SAE handshake capture |

#### Campaign Lifecycle

1. **Construction**: `campaign = WpsCampaign(array, ap, log=log)`
2. **Start**: `if campaign.run(): ...` (returns False if radio busy)
3. **Polling**: Check `campaign.done`, call `_check_hit()`
4. **Stop**: `await campaign.stop()` (always called in finally block)

#### Key State

| Attribute | Purpose |
|-----------|---------|
| `target: AccessPoint` | Target AP for the attack |
| `array: WlanArray` | Interface pool for TX |
| `done: bool` | Terminal state reached |
| `log(message)` | Progress logging callback |

#### Error Handling
- Timeout → stop campaign, return "timeout" result
- User interrupt (`request_stop()`) → return "stopped" result

---

## 7. PERSISTENCE SUBSYSTEM

### Location: `src/airscope/persist/config.py`, `vault.py`

#### Purpose
Configuration storage and credential vault.

#### Key Classes

| Class | File | Purpose |
|-------|------|---------|
| `Config` | `config.py` | User preferences (theme, log level) |
| `Vault` | `vault.db` | SQLite store for handshakes/PMKIDs/PSKs |

#### Config Schema

```python
{
    "theme": str,          # e.g., "midnight"
    "log_level": str/null, # trace/debug/info/quiet/null
    "pbc_enabled": bool,
    "silenced_ap_bssids": List[str]
}
```

#### Vault Tables

| Table | Columns |
|-------|---------|
| `access_points` | bssid, ssid, channel, last_seen |
| `handshakes` | bssid, client_mac, frames (BLOB), captured_at |
| `pmkids` | bssid, client_mac, pmkid, captured_at |
| `cracked` | bssid, psk, cracked_at |

#### Key Functions

| Name | Purpose |
|------|---------|
| `Config.load()` | Read `~/.airscope/config.json`, apply defaults |
| `Config.save()` | Persist config to disk |
| `Vault.has_psk(ap)` | Check if PSK already recovered |
| `Vault.save_handshake(ap, client_mac)` | Save handshake frames |
| `Vault.save_pmkid(ap, client_mac)` | Save PMKID capture |

#### Side Effects
- Creates/updates SQLite database on disk
- Writes JSON config file

---

## 8. TUI SUBSYSTEM

### Location: `src/airscope/ui/`

#### Structure
```
ui/
├── app.py           # AirscopeApp main class
├── screens/
│   ├── splash.py       # Adapter selection screen
│   ├── scanner.py      # Real-time AP table with filter/sort
│   ├── focus_v2.py     # AP details + attack buttons
│   └── vault.py        # Credential viewer
├── widgets/         # Reusable UI components
└── themes.py        # Textual theme registration
```

#### Key Screens

| Screen | Purpose |
|--------|---------|
| `SplashView` | Device selection; "Start" → transition to scanner |
| `ScannerView` | AP table with filter/sort/PBC toggle; "Focus" button |
| `FocusViewV2` | Per-AP details + attack buttons (PMKID, deauth, WPS, EvilTwin) |
| `VaultView` | Credential list; export functionality |

#### State Created
- Textual widget tree (header, footer, tables, buttons)
- App-level: `self.target_ap`, `self.vault`

---

## 9. WEB DASHBOARD SUBSYSTEM

### Location: `src/airscope/web/app.py`, `context.py`

#### Purpose
FastAPI-based web interface for monitoring and control.

#### Key Classes/Functions

| Name | Purpose |
|------|---------|
| `HeadlessContext` | Demo vs live mode toggle |
| `create_app(ctx)` | FastAPI app factory with routes |

#### Endpoints

| Route | Method | Purpose |
|-------|--------|---------|
| `/api/status` | GET | System status (interfaces, scanning) |
| `/api/aps` | GET | List of discovered APs |
| `/api/vault` | GET | Captured credentials |
| `/api/cracked` | GET | Cracked PSKs |

#### State Created
- FastAPI app instance
- `uvicorn` HTTP server

---

## 10. CHIP DRIVER CONTRACT

### Location: `src/airscope/chips/driver.py`

#### Purpose
Abstract interface for all chip drivers.

#### Key Contract Methods

| Method | Purpose |
|--------|---------|
| `from_usb_device(dev, id_entry)` | Constructor from USB device handle |
| `connect(progress_cb=None)` | Hardware bring-up: firmware load, register setup |
| `set_channel(channel, scan=False)` | Tune to channel |
| `_inject_frame(frame_bytes)` | Raw frame TX (bulk-OUT) |
| `close()` | Cleanup and release resources |

#### Abstract Properties

```python
SUPPORTED_CHANNELS: ClassVar[List[int]]
FAKE_MAC: ClassVar[FakeMacSupport]
AP_MODE: ClassVar[bool] = False
```

#### Key Features

**ACK Detection**
- `enable_rx_acks()` / `disable_rx_acks()` - Arm/disarm tally
- `record_ack(frame)` - Tally one received ACK
- `acks_seen(mac)` - Query tally for MAC

**Active Monitor (Fake MAC)**
- `enter_active_monitor(mac, bssid)` - Chip emits ACKs for spoofed MAC
- `exit_active_monitor()` - Restore plain monitor mode

#### FakeMacSupport Enum
```python
UNIMPLEMENTED = "unimplemented"   # Not ported yet
NONE = "none"                     # Hardware cannot do it
FIXED_MAC = "fixed_mac"           # Only ACKs own MAC
SPOOFABLE = "spoofable"           # Can ACK any MAC (for EvilTwin)
```

---

## 11. LOGGING SUBSYSTEM

### Location: `src/airscope/chips/log_trace.py`, `ui/app.py`

#### Purpose
Multi-level logging with trace/debug/info/quiet modes.

#### Key Functions

| Name | Purpose |
|------|---------|
| `_configure_file_logging(cli_log_level)` | Set up file logger to `~/.airscope/airscope.log` |
| `_get_log_level(cli_log_level)` | Resolve effective log level |

#### Log Levels
- `TRACE` - Most verbose (chip-level register operations)
- `DEBUG` - Debug messages
- `INFO` - User-facing progress info (default)
- `quiet` - No logging

---

## Summary Matrix

| Subsystem | Core Files | Threading Model | External Dependencies |
|-----------|------------|-----------------|----------------------|
| Device Mgmt | `device/manager.py` | Blocking USB I/O (libusb) | libusb, pyusb |
| Wireless | `wlan/interface.py`, `array.py` | Async (asyncio) | Driver instance |
| Parsing | `dot11/parser.py` | Stateless | None |
| Attacks | `campaigns/batch.py` | Async + ProcessPoolExecutor (WEP) | N/A |
| Persistence | `persist/vault.py` | SQLite sync I/O | SQLite |
| TUI | `ui/app.py`, `screens/*.py` | Textual event loop (async) | textual, rich |
