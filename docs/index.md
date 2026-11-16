# airoscpe Documentation - Complete Index

## Overview

This directory contains the complete technical documentation for **airscope v0.3.8**, a Wi-Fi security auditing tool that runs natively on Linux, Windows (via WSL2), and macOS.

## Quick Reference

| Goal | Read This |
|------|-----------|
| Install airscope | [USAGE.md](./USAGE.md) - Prerequisites and installation steps |
| Learn what it does | [CAPABILITIES.md](./CAPABILITIES.md) - Feature list, CLI flags, TUI controls |
| Understand architecture | [CODEBASE_MAP.md](./CODEBASE_MAP.md) - Master reference for modules, data flow |
| Work on code | [SUBSYSTEMS.md](./SUBSYSTEMS.md) - Detailed subsystem breakdowns |
| Check supported hardware | [SUPPORTED-HARDWARE.md](./SUPPORTED-HARDWARE.md) |

---

## Documentation Files

### Primary Documentation (Required Reading)

#### 1. PROJECT_INVENTORY.md
**Purpose**: Project overview and structure

**Contents**:
- Repository layout (directory tree, key files)
- Entry points and CLI commands
- Major modules and their purposes
- Configuration sources and defaults
- Dependencies (core vs optional)
- Test suite statistics (~3008 tests)
- External tool dependencies (none for attacks)

**Key Sections**:
```
Repository Structure
Entry Points
Major Modules
Configuration Sources
Dependencies
Test Suite
External Tools
Build & Packaging
Notes
```

#### 2. CAPABILITIES.md
**Purpose**: What airscope can do and how to use it

**Contents**:
- CLI commands: `--auto`, `--web`, `--doctor`, `--export`
- TUI screens: Splash, Scanner, FocusV2, Vault
- Attack implementations (PMKID, Handshake, WPS, Deauth, EvilTwin)
- Configuration options (config.json + environment variables)
- Platform-specific capabilities

**Key Tables**:
```
CLI Commands and Flags
TUI Screens and Controls
Attack Implementations
Configuration Options
External Tool Dependencies
Supported Hardware Matrix
Data Formats
Platform-Specific Capabilities
Concurrency Model
Error Handling
```

#### 3. USAGE.md
**Purpose**: Installation, configuration, and operational guide

**Contents**:
- System requirements by platform
- Step-by-step installation (Linux/Windows/macOS)
- Running airscope: TUI mode, batch mode (`--auto`), web dashboard
- TUI keyboard shortcuts
- Attack workflows with examples
- Configuration file format
- Common failure modes and solutions

**Key Examples**:
```bash
# Interactive mode
uv run airscope

# Headless batch mode
uv run airscope --auto --targets "ssid_or_bssid"

# Web dashboard
uv run airscope --web --port 8080

# Export captures
uv run airscope --export csv -o ./reports/
```

### Technical Documentation (For Developers)

#### 4. CODEBASE_MAP.md
**Purpose**: Master architecture reference

**Contents**:
- Startup flow with platform re-exec logic
- Module dependency graph
- Major classes and their relationships
- Process/subprocess calls (none for attacks)
- Networking and I/O interfaces
- State management model
- Data/file formats
- Concurrency model
- Error handling patterns

**Key Diagrams**:
```
Entry Point → [Mode Dispatch] → Mode Handler
Module Dependency Graph
Process/Subprocess Calls
Networking and I/O Interfaces
State Management Model
Control Flow (RX Frame Path, TX Frame Path)
```

#### 5. SUBSYSTEMS.md
**Purpose**: Detailed subsystem breakdowns

**Contents**:
10 major subsystems with:
- Purpose and responsibility
- Key classes/functions (one-line descriptions)
- Inputs/outputs/state/side effects
- External dependencies
- Error handling
- Integration points

**Subsystems Covered**:
1. Core System (`__main__.py`, `ui/app.py`)
2. Device Management (`device/manager.py`)
3. Wireless Interface (`wlan/interface.py`)
4. Wireless Array (`wlan/array.py`)
5. 802.11 Parsing (`dot11/parser.py`)
6. Attack Campaigns (`campaigns/batch.py`)
7. Persistence (`persist/vault.py`, `config.py`)
8. TUI Screens
9. Web Dashboard
10. Chip Driver Contract

### Reference Documentation

#### SUPPORTED-HARDWARE.md
**Purpose**: List of supported USB Wi-Fi adapters

**Contents**:
- Chipset support matrix (chip name, vendor, driver package)
- Feature availability per chipset
- Linux/Windows/macOS platform notes

#### LINUX-PERMISSIONS.md
**Purpose**: Linux-specific setup guide

**Contents**:
- udev rule installation
- libusb permissions
- Common permission errors and solutions

#### THEMES.md
**Purpose**: UI theme customization

**Contents**:
- Available themes (midnight default)
- Theme file structure
- Custom theme creation

#### FIRMWARE.md
**Purpose**: Firmware loading documentation

**Contents**:
- Firmware blob locations
- Loading process
- Provenance tracking

---

## How to Use This Documentation

### For New Users
1. Read [USAGE.md](./USAGE.md) for installation and basic usage
2. Run the doctor to verify setup: `uv run python -m airscope.doctor`
3. Start with interactive mode: `uv run airscope`

### For Developers
1. Read [PROJECT_INVENTORY.md](./PROJECT_INVENTORY.md) for project overview
2. Study [CODEBASE_MAP.md](./CODEBASE_MAP.md) for architecture understanding
3. Dive into specific subsystems in [SUBSYSTEMS.md](./SUBSYSTEMS.md)

### For Contributors
1. Follow the extension workflow from [USAGE.md](./USAGE.md)
2. Update relevant docs as you code:
   - `CODEBASE_MAP.md` for new module relationships
   - `SUBSYSTEMS.md` for component details
3. Run tests: `uv run pytest`

---

## Platform-Specific Notes

### Linux
- Native libusb userspace (no kernel drivers)
- udev rule required for `/dev/bus/usb` access
- Full attack support including EvilTwin captive portal

### Windows
- Re-exec to WSL2 with USB passthrough via usbipd-win
- Adapter must use WinUSB driver
- Full attack support

### macOS
- Intel: Re-exec to Lima VM for EvilTwin portal
- Apple Silicon: Native mode only (USB passthrough impossible)
- All attacks except portal available natively

---

## Quick Command Reference

```bash
# Installation
git clone https://github.com/udhaybhat00/airscope.git
cd airscope
uv sync --group dev      # or: pip install -e .

# Running
uv run airscope                              # Interactive TUI mode
uv run airscope --auto                       # Headless batch mode
uv run airscope --web                        # Web dashboard
uv run airscope --doctor                     # Setup validation

# Debugging
AIRSCOPE_LOG=debug uv run airscope          # Verbose logging

# Exporting
uv run airscope --export csv -o ./reports/  # CSV format
uv run airscope --export all                # All formats
```

---

## Testing

```bash
# Run all tests (excluding slow WEP crypto proofs)
uv run pytest -m 'not slow'

# Run specific test file
uv run pytest tests/wlan/test_interface.py

# Run slow tests (includes WEP proof)
uv run pytest -m slow

# Lint only (no formatting check)
uv run ruff check src/
```

---

## File Locations

| Location | Purpose |
|----------|---------|
| `src/airscope/__main__.py` | CLI entry point |
| `src/airscope/ui/app.py` | TUI app class |
| `src/airscope/device/manager.py` | USB enumeration, driver loading |
| `src/airscope/wlan/interface.py` | Per-card TX/RX control |
| `src/airscope/campaigns/batch.py` | Attack orchestration |
| `~/.airscope/config.json` | User preferences |
| `~/.airscope/vault.db` | SQLite credential store |
| `~/.airscope/airscope.log` | Log file (if enabled) |

---

## Version Information

- **Current version**: 0.3.8
- **Version source**: `src/airscope/__init__.py`
- **License**: GPL-2.0-only
- **Python requirement**: >= 3.11

---

## Summary Statistics

| Metric | Value |
|--------|-------|
| Source files | ~658 Python files |
| Lines of code | ~30K+ |
| Test coverage | 3008+ tests |
| Supported chipsets | 20+ |
| Platforms supported | Linux, Windows (WSL2), macOS |

---

**Last updated**: Generated from source at `/home/toysldr/Projects/airscope`
