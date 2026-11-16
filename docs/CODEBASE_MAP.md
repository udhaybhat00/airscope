# CODEBASE MAP - airscope

## Overview

This document is the master reference for understanding how airoscpe works. It supersedes all other documentation as the single source of truth.

**Version**: 0.3.8  
**License**: GPL-2.0-only  
**Primary Language**: Python >= 3.11  
**Platform**: Linux (native), Windows (via WSL2), macOS (Intel via Lima VM, Apple Silicon native)

---

## STARTUP FLOW

### Entry Point: `src/airscope/__main__.py`

```
CLI invocation → main() → [mode dispatch] → mode-specific handler
```

**Mode Selection Logic**:
```python
def main():
    args = parse_args()
    
    if args.smoke:
        _smoke()  # PyInstaller bundle integrity test
    
    elif args.auto:
        _auto(args)  # Headless batch mode (no TUI)
    
    elif args.web:
        _web(args)  # Web dashboard mode
    
    elif args.export:
        _export(args)  # Export captures to files
    
    elif args.doctor:
        _doctor()  # Setup validation
    
    else:
        AirscopeApp().run()  # Interactive TUI mode
```

### TUI Startup Sequence

1. **`AirscopeApp.__init__()`**
   - Load `~/.airscope/config.json` (theme, log_level)
   - Create `DeviceManager(self)`
   - Create `DeviceWatch(device_manager=...)`
   - Initialize `WlanArray()`, `Vault()`

2. **`on_mount()`** (Textual lifecycle callback)
   - Install screens: `splash`, `scanner`, `focus_v2`, `vault`
   - Push `SplashView` to stack
   - Start `DeviceWatch` polling interval (500ms)

3. **DeviceWatch Loop**
   - Poll USB bus every 500ms via `device_manager.devices()`
   - On device change → `_on_devices_changed(current, arrived, departed)`
   - If splash visible: refresh device list
   - If mid-session and new devices: prompt to bring up

### Platform Re-exec (Windows/macOS)

**Windows**:
```
main() → _maybe_reexec_in_wsl()
  └─ Check WSL2 availability
  └─ If WSL2 + adapter visible: re-exec in WSL2 with USB passthrough
  └─ Else: fall back to native (limited functionality)
```

**macOS Intel**:
```
main() → _maybe_reexec_in_vm()
  └─ Check Lima VM status
  └─ If VM running: re-exec in VM for EvilTwin captive portal
  └─ Else: run native (EvilTwin portal disabled with message)
```

**macOS Apple Silicon**:
- USB passthrough to VMs is impossible (IOKit limitation)
- Skip re-exec; run native mode only

---

## MODULE DEPENDENCY GRAPH

```
┌─────────────────────────────────────────────────────────────────────┐
│                      src/airscope/__main__.py                        │
│  (CLI entry point, platform re-exec)                                │
└────────────────┬────────────────────────────────────────────────────┘
                 │
   ┌─────────────┼─────────────┐
   ▼             ▼             ▼
┌────────┐  ┌──────────┐  ┌──────────┐
│ Device │  │   UI     │  │  Web     │
│ Manager│  │  (Textual)│  │ (FastAPI)│
└────┬───┘  └────┬─────┘  └────┬─────┘
     │           ▼            ▼
     │      ┌────────┐    ┌────────┐
     │      │Screens │    │Routes  │
     │      └────────┘    └────────┘
     │
   ┌─┴───┐
   ▼     ▼
┌────────────┐  ┌────────────┐
│ WlanArray  │  │Chip Drivers│
│ (pool)     │  │(per-chip)  │
└────┬───────┘  └────┬───────┘
     │               │
   ┌─┴───┐         ┌─┴───┐
   ▼     ▼         ▼     ▼
┌──────────┐  ┌──────────┐  ┌──────────┐
│ WlanSink │  │ Campaigns│  │ Persistence│
│ (state)  │  │(attacks) │  │(config/db) │
└──────────┘  └──────────┘  └──────────┘
```

### Core Module Dependencies

| From | To | Purpose |
|------|-----|---------|
| `__main__.py` | `ui/app.py` | TUI app initialization |
| `__main__.py` | `device/manager.py` | USB device enumeration |
| `__main__.py` | `device/watch.py` | Hotplug detection |
| `ui/app.py` | `wlan/array.py` | Wireless interface pool |
| `ui/app.py` | `persist/vault.py` | Credential storage |
| `device/manager.py` | `chips/*/driver.py` | Driver instantiation (lazy) |
| `wlan/array.py` | `wlan/sink.py` | Shared state aggregation |
| `campaigns/*.py` | `wlan/interface.py` | TX frame injection |
| `persist/config.py` | `~/.airscope/config.json` | User preferences |

---

## MAJOR CLASSES AND RELATIONSHIPS

### 1. AirscopeApp (TUI Main)

**File**: `src/airscope/ui/app.py`

```python
class AirscopeApp(App):
    - device_manager: DeviceManager
    - device_watch: DeviceWatch
    - array: Optional[WlanArray]      # None on splash screen
    - target_ap: Optional[AccessPoint]
    - vault: Vault
```

**Key Methods**:
- `on_mount()` → Push splash, start device watch
- `_on_devices_changed()` → Hotplug handling
- `_prompt_hotplug(fresh)` → Ask user to bring up new devices
- `action_preferences()` → Show preferences modal

### 2. DeviceManager (USB Enumeration)

**File**: `src/airscope/device/manager.py`

```python
class DeviceManager:
    - _app: AirscopeApp              # Back-reference for UI calls
    
def supported_ids() -> dict[(vid, pid): Claim]
def driver_for(vid, pid) -> Optional[(DriverClass, setup_key)]
def devices() -> List[Device]       # USB bus scan
def bringup(dev) → BringupResult   # Hardware bring-up + interface creation
```

**Claim Structure**:
```python
class Claim(NamedTuple):
    entry: DeviceID          # Metadata from chips/*/__init__.py
    key: str                 # Driver package directory name
    import_driver: Callable  # Lazy load driver class
```

### 3. WlanInterface (Per-Card Interface)

**File**: `src/airscope/wlan/interface.py`

```python
class WlanInterface:
    - driver: Driver              # Chip-specific implementation
    - current_channel: int
    - _rx_callbacks: List[Callable[[Packet], None]]
    
async def connect() → bool                    # Hardware bring-up
async def set_channel(channel) → bool         # Tune radio
async def send_no_wait(frame_bytes) → bool    # Fire-and-forget TX
async def send_until_ack(frame, max_retries)  # Software-retry TX
async def deauth_broadcast(ap_bssid, count)   # Broadcast deauth
async def deauth_client(ap, client, rounds)   # Targeted deauth with ACK tally
```

### 4. WlanArray (Interface Pool)

**File**: `src/airscope/wlan/array.py`

```python
class WlanArray:
    - _members: List[WlanInterface]
    - _sink: WlanSink              # Shared state
    - _dedupe: StreamMerger        # RX deduplication
    
def attach(iface) → iface       # Add interface to pool
def select_iface(channel) → Optional[iface]  # Pick best TX card for channel
async def start_hopping(channels, interval)  # Start channel hopper
async def close()               # Close all interfaces
```

### 5. WlanSink (Shared State)

**File**: `src/airscope/wlan/sink.py`

```python
class WlanSink:
    - access_points: Dict[bssid, AccessPoint]
    - clients: Dict[mac, Client]
    - wep_store: WepCaptureStore
    - packet_stats: PacketStats
    
def update(pkt, card_id) → None     # Fold parsed frame into state
def get_access_points() → List[AP]  # Return AP list (optionally filter eviltwin)
```

### 6. Campaigns (Attack Orchestration)

**File**: `src/airscope/campaigns/batch.py`

```python
class BatchRunner:
    - array: WlanArray
    - vault: Vault
    
def build_plan(aps, vault) → (steps, skipped)
async def run(steps, aps) → BatchSummary

@dataclass
class BatchStep:
    bssid: str
    ssid: Optional[str]
    kind: str          # "wps", "pmkid", "handshake", "sae"
    timeout: float
```

---

## PROCESS AND SUBPROCESS CALLS

### Process Model

**airscope uses ZERO external subprocesses for attacks**. All functionality is implemented in pure Python.

| Action | Implementation |
|--------|----------------|
| USB enumeration | `pyusb` via libusb (userspace) |
| Frame injection | Bulk-OUT transfer to USB endpoint |
| Channel tuning | Chip-specific register writes via bulk transfers |
| DHCP server | Pure Python TCP/UDP server |
| HTTP captive portal | Pure Python HTTP server (FastAPI or simple) |
| Packet parsing | Byte-level parsing in Python |

**Exception**: Web dashboard spawns uvicorn HTTP server library call.

---

## NETWORKING AND I/O INTERFACES

### USB Interface
- **Backend**: `libusb_package` (bundled libusb shared library)
- **Protocol**: Bulk transfers (bulk-IN for RX, bulk-OUT for TX)
- **Endpoints**: Chip-specific (driver determines endpoint numbers)

### File I/O
| File | Purpose |
|------|---------|
| `~/.airscope/config.json` | User preferences (theme, log_level) |
| `~/.airscore/vault.db` | SQLite: handshakes/PMKIDs/cracked PSKs |
| `~/.airscope/airscope.log` | Log file (if logging enabled) |
| `~/.airscope/adapters.json` | Custom adapter VID/PIDs |

### Network I/O
| Interface | Purpose |
|-----------|---------|
| TCP port 8000 (default) | Web dashboard HTTP server |
| UDP/DHCP | Fake AP DHCP server for EvilTwin |
| ICMP | Captive portal detection |

---

## STATE MANAGEMENT MODEL

### Session State

| State | Location | Lifetime |
|-------|----------|----------|
| Device list | `DeviceManager.devices()` | Per-session, refreshed every 500ms |
| Interface pool | `WlanArray._members` | From first attach to close |
| Channel hopper | `asyncio.Task` per interface | As long as hopping active |
| AP registry | `WlanSink.access_points` | Entire session |
| Client registry | `WlanSink.clients` | Entire session |
| WEP capture | `WlanSink.wep_store` | Entire session |

### Transient State

| State | Location | Purpose |
|-------|----------|---------|
| RX frame buffer | Driver's bulk-IN ring buffer | Raw incoming bytes |
| TX queue | Interface's send method | Pending frames to inject |
| ACK tally | `Driver._ack_counts` | During active TX with retry |

---

## DATA AND FILE FORMATS

### Capture Data Format

**AccessPoint** (Python dataclass):
```python
@dataclass
class AccessPoint:
    bssid: str
    ssid: Optional[str]
    channel: int
    signal: int                    # dBm, smoothed across cards
    encryption: str                # "WEP", "WPA2-PSK", "WPA3-SAE", etc.
    beacons: int                   # Count received
    last_seen: float               # timestamp.time()
    handshakes: Dict[client_mac, Handshake]
```

**Handshake** (Python dataclass):
```python
@dataclass
class Handshake:
    bssid: str
    client_mac: str
    mic: Optional[str]             # First 16 bytes of MIC
    frames: List[bytes]            # M1-M4 raw frames
```

### Export Formats

| Format | File | Description |
|--------|------|-------------|
| CSV | `aps.csv` | BSSID, channel, signal, encryption, SSID |
| netxml | `networks.netxml` | Wireshark-compatible XML format |
| HTML | `index.html` | Interactive dashboard |
| hashcat | `cracked.txt` | PSKs in `$SSID$:$PMKID$` or `$SSID$:*$...` format |

---

## EXTERNAL UTILITIES ORCHESTRATED

airscope orchestrates **no external utilities** for attacks. All implementation is pure Python:

| Action | Traditional Tool | airoscpe Implementation |
|--------|------------------|------------------------|
| USB enumeration | `lsusb`, udevadm | `pyusb` (libusb backend) |
| Monitor mode | `airmon-ng start wlan0` | Chip firmware configuration via registers |
| Frame injection | `aireplay-ng -0` | Bulk-OUT endpoint write |
| Channel hop | `iw dev wlan0 set channel N` | Chip register writes |
| DHCP server | `dnsmasq` | Pure Python TCP/UDP server |
| HTTP captive portal | `nginx`, `lighttpd` | FastAPI or simple HTTP server |

---

## CONCURRENCY MODEL

### Threading Model

| Component | Concurrency Model | Purpose |
|-----------|-------------------|---------|
| Textual app | Async event loop (asyncio) | UI rendering, user input handling |
| DeviceWatch | Timer-based polling (every 500ms async interval) | USB hotplug detection |
| RX reader | Dedicated thread (blocking libusb read) | Bulk-IN reads from USB device |
| TX injection | Async (coroutine) via interface methods | Frame transmission |
| Channel hopper | Per-interface asyncio task | Periodic channel switching |
| Batch runner | Sequential with async/await + ProcessPoolExecutor | Attack orchestration |

### Parallelism

**ProcessPoolExecutor**: Used only for WEP cracking (statistical analysis parallelization).

**No shared mutable state across processes** - each worker receives copies of data.

---

## CONTROL FLOW

### RX Frame Path
```
USB bulk-IN → Driver RX reader thread 
  └─> Parse raw bytes to Packet 
      └─> WlanInterface._on_frame_parsed(pkt)
          └─> WlanArray._ingest(iface, pkt)
              ├─> Drop if WE transmitted (TA in own_macs)
              ├─> Dedupe via StreamMerger
              ├─> novel_globally? → WlanSink.update(pkt, card_id)
              │   ├─> AP registry update (beacon, probe_resp)
              │   ├─> Client tracking (assoc, data, eapol)
              │   └─> EAPOL handshake detection
              └─> Dispatch RX to subscribers (campaigns)
```

### TX Frame Path
```
Campaign.send_no_wait(frame_bytes) or send_until_ack(...)
  └─> WlanInterface.send_*()
      └─> Driver.inject_frame() or inject_frame_slow_retry()
          ├─> Add sequence number (_stamp_tx_seq)
          ├─> Register MAC for ACK tally (if enabled)
          └─> Bulk-OUT to USB endpoint
```

### Channel Hopping Path
```
WlanInterface.start_hopping(channels, interval)
  └─> asyncio.create_task(_hop_loop(channels, interval))
      └─> Loop: set_channel(next_channel), sleep(interval)
```

---

## ERROR HANDLING

### Error Types

| Error | Location | Handling |
|-------|----------|----------|
| `BringUpError(stage, detail)` | Driver.connect() | Show setup dialog if permissions, else fatal |
| `AirscopeDeviceLostError` | RX reader thread | Toast notification or splash re-entry |
| `ConfigError` | Config.load() | Toast on startup, use defaults |

### Recovery Flow

**Device lost mid-session**:
```
RX reader catches USB error
  └─> Driver._on_device_lost(exc)
      └─> WlanInterface._on_device_lost(exc)
          └─> WlanArray._member_lost(iface, exc)
              ├─> Remove from _members
              ├─> Re-partition channels if hopping
              ├─> Call disconnect callbacks with remaining count
              └─> If count == 0: push RecoverableErrorModal → user can quit
                  If count > 0: toast notification, continue running
```

---

## SUMMARY OF KEY FILES

### Entry Point & Core
| File | Purpose |
|------|---------|
| `src/airscope/__main__.py` | CLI entry point, mode dispatch |
| `src/airscope/ui/app.py` | Textual app class |
| `src/airscope/doctor.py` | Setup validation checks |

### Device & Driver
| File | Purpose |
|------|---------|
| `src/airscope/device/manager.py` | USB enumeration, driver loading |
| `src/airscope/device/watch.py` | Hotplug detection (DeviceWatch) |
| `src/airscope/chips/driver.py` | Chip driver abstract interface |

### Wireless Layer
| File | Purpose |
|------|---------|
| `src/airscope/wlan/interface.py` | Per-card TX/RX, channel control |
| `src/airscope/wlan/array.py` | Multi-card pool, deduplication |
| `src/airscope/wlan/sink.py` | Shared 802.11 state (AP/client registry) |

### Attack System
| File | Purpose |
|------|---------|
| `src/airscope/campaigns/batch.py` | Batch runner, step orchestration |
| `src/airscope/campaigns/deauth.py` | Deauthentication campaign |
| `src/airscope/campaigns/pmkid.py` | PMKID capture |
| `src/airscope/campaigns/wps.py` | WPS PIN enumeration |

### Persistence
| File | Purpose |
|------|---------|
| `src/airscope/persist/config.py` | User preferences (theme, log_level) |
| `src/airscope/persist/vault.py` | SQLite credential storage |

---

## RECOMMENDED READING ORDER

1. **Start here**: `src/airscope/__main__.py` - understand entry points
2. **UI flow**: `src/airscope/ui/app.py`, then screens in order (splash, scanner)
3. **Device layer**: `src/airscope/device/manager.py`
4. **Wireless interface**: `src/airscope/wlan/interface.py`, `array.py`
5. **Attack system**: `src/airscope/campaigns/batch.py`
6. **Driver contract**: `src/airscope/chips/driver.py`

## NOTES

- **Chip discovery** is dynamic via pkgutil walk over `chips/` at runtime
- **No external subprocesses** - all attacks implemented in pure Python
- **Async-first design** - Textual event loop, asyncio for I/O
- **State is centralized** in `WlanSink`, interfaces are pure per-card radio
