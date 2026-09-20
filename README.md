# airscope

![build](https://github.com/udhaybhat00/airscope/actions/workflows/ci.yml/badge.svg)
![version](https://img.shields.io/github/v/release/udhaybhat00/airscope)
![license](https://img.shields.io/badge/license-GPL--2.0-blue)
![python](https://img.shields.io/badge/python-%3E%3D3.11-blue)

> A standalone USB Wi-Fi auditor for Linux, Windows, and macOS.

> Wireless penetration testing toolkit: WPA/WPA2 handshake and PMKID capture, WPS PixieDust and PIN attacks, WPA3 SAE capture, EvilTwin downgrade, and hashcat-powered password cracking — in a terminal UI and a local web dashboard.

<p align="center">
  <img src="assets/demo-tour.gif" alt="airscope Wi-Fi security auditor demo: live wireless network scanner, WPA handshake capture, WPS attack, hashcat password cracking, and HTML security report" width="800">
</p>

> *At least* one of the [supported USB adapters](docs/SUPPORTED-HARDWARE.md) is **required** for live captures — but you can tour the whole UI with no hardware (below).

## Getting started (no experience needed)

The easiest way needs **no installs and no terminal knowledge**. Download one file, open it, and you're looking at the app in under a minute.

There are **two ways to use it** — pick one:
- **Terminal app** (default): just run the file. Menus and tables right inside your terminal.
- **Browser dashboard**: run the file with `--web --demo` after it. A webpage opens automatically.

> **What's a Terminal?** It's the app on your computer where you type text commands instead of clicking buttons — called Terminal on Mac, Command Prompt or PowerShell on Windows. You only need it for two copy-paste steps on Mac/Linux below; Windows needs none at all.

### Windows (no terminal needed)

1. Go to the [**Releases page**](https://github.com/udhaybhat00/airscope/releases/latest) and download **`airscope-windows-x64.exe`**.
2. **Double-click** the downloaded file. This opens the **terminal app**.
3. Windows will likely show a blue box saying *"Windows protected your PC"*. This appears because the app is **unsigned** (signing certificates cost hundreds of dollars a year — the code itself is open for anyone to inspect). Click **More info**, then **Run anyway**.
4. A black window opens and stays open — that's the app running. Leave it alone.

> First launch takes ~30 seconds while the app unpacks itself — be patient, the window looks frozen meanwhile. Later launches are instant.

> If double-clicking seemingly does nothing: check the taskbar for the blue SmartScreen prompt hiding behind your browser window. It's almost always waiting there for the *More info → Run anyway* clicks.

> Want the browser dashboard on Windows instead? Open Command Prompt in the download folder and run `airscope-windows-x64.exe --web --demo`.

### macOS (two copy-paste commands)

Apple requires apps to be registered with them ("Gatekeeper") or your Mac refuses to open them — same unsigned-app situation as Windows, but Apple doesn't offer a click-through, so there are two commands to paste. Nothing gets installed; they just tell your Mac "I trust this file, run it".

1. Go to the [**Releases page**](https://github.com/udhaybhat00/airscope/releases/latest) and download **`airscope-macos-universal2`**. Remember which folder it landed in (usually Downloads).
2. Open **Terminal** (press `Cmd + Space`, type `Terminal`, press Enter) and paste these lines one at a time, pressing Enter after each. If your file isn't in Downloads, replace `~/Downloads` with its folder. The **last line is a choice** — plain terminal app, or browser dashboard:

```bash
xattr -d com.apple.quarantine ~/Downloads/airscope-macos-universal2
chmod +x ~/Downloads/airscope-macos-universal2
~/Downloads/airscope-macos-universal2
```

or, for the browser dashboard instead:

```bash
~/Downloads/airscope-macos-universal2 --web --demo
```

The first line removes Apple's quarantine flag (the "unidentified developer" block), the second makes the file runnable, the third starts it.

> If your Mac says *"can't be opened because it is from an unidentified developer"*: it means step 1's first command didn't run (or ran in the wrong folder). Re-open Terminal and run the `xattr` line again carefully — watch for typos in the file path.

### Linux (two copy-paste commands)

1. Go to the [**Releases page**](https://github.com/udhaybhat00/airscope/releases/latest) and download **`airscope-linux-x64`** (or `airscope-linux-arm64` on Raspberry Pi / ARM machines).
2. Open a terminal in the download folder and paste. The **last line is a choice** — plain terminal app, or browser dashboard:

```bash
chmod +x ./airscope-linux-x64
./airscope-linux-x64
```

or, for the browser dashboard instead:

```bash
./airscope-linux-x64 --web --demo
```

The first line makes the file runnable, the second starts it.

### After launch (all systems)

**Terminal app** (no flags): you get menus and tables inside your terminal. Plug in a [supported USB adapter](docs/SUPPORTED-HARDWARE.md) and press START to scan for real.

**Browser dashboard** (`--web --demo` flags): a webpage **opens in your browser automatically** — that's the whole interface. If no browser tab appears, go to **http://127.0.0.1:8765/** yourself.

You'll see an amber **DEMO MODE** banner across the top: you're looking at a **simulation**. Nothing on your network is being touched, scanned, or attacked — it's there so you can click through every screen safely. A real scan needs a [supported USB adapter](docs/SUPPORTED-HARDWARE.md) plugged in.

### For developers (from source)

This path needs [`uv`](https://docs.astral.sh/uv/) (a Python installer/manager) — install it first, then **close and reopen your terminal** so it takes effect:

- **macOS / Linux:** `curl -LsSf https://astral.sh/uv/install.sh | sh`
- **Windows:** `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`

Then:

```bash
git clone https://github.com/udhaybhat00/airscope
cd airscope
uv sync --group dev --extra web   # install (editable + dev + web deps)
uv run airscope --web --demo      # dashboard at http://127.0.0.1:8765/
```

Got a supported adapter? Plug it in and run `uv run airscope` (terminal UI) or drop `--demo` for the live dashboard.

## Why?

* **Cross-Platform:** Runs identically on Linux, macOS, and Windows.
* **Driver Heaven:** Ships its own userland wireless stack, so there is no kernel driver versioning hell and no Windows NDIS wall.
* **Zero Runtime Dependencies:** No external auditor tools — pure Python over PyUSB with a Textual TUI.

## Features

### Reconnaissance & Analysis

- **Multi-Card Aggregation:** Capture across multiple adapters at once; pick a dedicated card to inject.
- **Real-time Scanner:** 2.4 GHz & 5 GHz channel-hopping (split across cards); signal, encryption suites, WPA3/SAE transition modes.
- **AP & Client Identification:** Vendor fingerprinting; router make/model from WPS beacons.
- **VAP Decloaking:** Finds hidden networks via BSSID correlation with visible siblings.
- **Packet Dashboard:** Live beacon, data, injection, and deauth rates.

### Attacks & Captures

- **WPA/WPA2 Handshakes:** Passive sniffing + targeted deauth; validated pairs exported as `.pcap` / `.hc22000`.
- **PMKID Harvesting:** Active + passive collection for WPA/WPA2 key material.
- **EvilTwin WPA3 Downgrade:** Clones the AP and evicts clients to capture handshakes.
- **WPS Recovery Suite:** PixieDust (offline PIN recovery), PushButton PSK capture, resumable PIN brute-force.
- **WEP Suite:** ARP replay, ChopChop, fake auth, and PTW key recovery.
- **Vault Cracking:** Dictionary attacks on captures via hashcat (aircrack-ng fallback), cracked PSKs saved back per AP.
- **Batch & Headless:** Multi-target queues in the TUI (`Space`/`B`), or `airscope --auto` with JSONL session logs.
- **Dashboard & Exports:** Local Svelte web UI (scanner, target attacks, vault, batch, reports) plus CSV / Kismet netXML / cracked.txt / HTML reports.

### Screens

- **Splash:** Adapter picker with band badges (`2G`/`5G`), START / Uninstall / Vault / Prefs.
- **Scanner:** Live AP table with tiered signal meter and icon-coded encryption column.
  `Space` marks targets, `B` batch-attacks the marked set (WPS → PMKID → handshake,
  strongest first, solved APs skipped), `Shift+B` stops after the current step.
- **Focus:** Single-target view — packet dashboard, clients, campaign controls, log.
- **Vault:** Loot manager for captures and recovered credentials. No card needed.

### Headless batch mode

```bash
uv run airscope --auto                                   # scan, then attack everything
uv run airscope --auto --targets HomeNet,aa:bb:cc:dd:ee:ff --scan-secs 15
uv run airscope --auto --list                            # print APs in range and exit
uv run airscope --auto --session night1.jsonl --pmkid-timeout 180
```

Progress prints to stdout; structured step events land in the JSONL session file.
Cards needing one-time driver setup must go through the TUI once first.

### Web dashboard

```bash
uv run airscope --web                    # live dashboard at http://127.0.0.1:8765/
uv run airscope --web --demo             # simulated scan, no hardware needed
uv run airscope --web --port 9000 --no-browser
```

Needs the web extras once: `uv sync --extra web` (or `pip install 'fastapi>=0.115' 'uvicorn[standard]>=0.30'`).
Scanner, target attacks, vault + cracking, batch queue, and reports — the same
Signal Noir theme as the TUI. Demo mode is bannered in the terminal and across
the top of every page, so it can't be mistaken for a real scan.

## How it compares

| Capability | airscope | aircrack-ng | wifite2 | reaver | bully |
|---|---|---|---|---|---|
| WPA/WPA2 handshake capture | ✓ | ✓ | ✓ | — | — |
| PMKID capture | ✓ | via hcxdumptool | ✓ | — | — |
| WPA offline crack (built-in path) | ✓ vault+hashcat | ✓ | ✓ | — | — |
| WPS PixieDust | ✓ (subset of modes) | via reaver/bully | ✓ (via tools) | ✓ | ✓ |
| WPS online PIN brute-force | ✓ | — | ✓ (via tools) | ✓ | ✓ |
| WEP attacks | replay/chopchop/PTW (no caffe-latte/hirte) | full set | full set | — | — |
| WPA3 SAE capture | ✓ passive | via hcxdumptool | fork-only | — | — |
| EvilTwin | WPA2 downgrade | fake AP primitives | fork: portal | — | — |
| Enterprise/EAP attacks | ✗ | partial (airbase) | ✗ | — | — |
| Batch multi-target + headless | ✓ | scripts | ✓ core value | — | — |
| Windows/macOS support | ✓ | Linux-first | Linux-only | Linux | Linux |
| Web dashboard | ✓ | ✗ | ✗ | ✗ | ✗ |
| No monitor-mode setup (userland USB) | ✓ | ✗ | ✗ | ✗ | ✗ |
| Hardware scope | ~20 USB chipsets | any monitor card | any monitor card | any | any |
| Reports (CSV/netXML/HTML) | ✓ | csv/netxml | cracked log | ✗ | ✗ |

## Install & Run

Requires Python 3.11+ and [`uv`](https://docs.astral.sh/uv/). Works on Kali Linux and any modern distro alongside tools like aircrack-ng, hashcat, and Wireshark (capture files are standard `.pcap` / `.hc22000`).

```bash
uv sync --group dev   # install (editable + dev deps)
uv run airscope       # run
```

Build a standalone binary (per-OS, no cross-compile):

```bash
uv run pyinstaller airscope.spec --noconfirm --clean   # -> dist/
```

## One-Time Driver Setup

Handled in-app after pressing `START`:

- **Linux:** One `pkexec`/`sudo` prompt for udev permissions and blocklists in `/etc/modprobe.d/`.
- **macOS:** Plug in and press *Allow* in the authorization dialog. Nothing to install.
- **Windows:** One UAC prompt installs WinUSB for the device.

Undo it anytime from the splash screen with `Uninstall`, then re-plug the adapter.

## Themes

Ships the **Signal Noir** theme family (`airscope-noir` default, `airscope-noir-contrast` for bright rooms) alongside Textual's built-ins. Switch with `ctrl+p` → theme. Details in [docs/THEMES.md](docs/THEMES.md).

## Docs

- [Supported hardware](docs/SUPPORTED-HARDWARE.md) — cards, bands, grading.
- [Linux permissions](docs/LINUX-PERMISSIONS.md) — udev / modprobe notes.
- [Firmware](docs/FIRMWARE.md) — vendored blob provenance and licenses.
- [Driver credits](docs/CREDITS.md) — upstream sources.
- [Contributing](CONTRIBUTING.md) — dev setup, tests, PR conventions.

## Attribution

airscope's attack workflows — WPS PixieDust/PIN, PMKID harvesting, deauth-assisted handshake capture, and the WEP replay suite — follow the playbook established by the original [Wifite](https://github.com/derv82/wifite2) project and the [aircrack-ng](https://www.aircrack-ng.org) suite. Its userland drivers are Python ports of GPLv2 Linux kernel and vendor DKMS drivers; the full upstream credit list is in [docs/CREDITS.md](docs/CREDITS.md).

airscope is an independent implementation: no wifite2 or aircrack-ng code is vendored. It drives USB hardware directly and shells out to hashcat/aircrack-ng only as external cracking tools.

## License & Disclaimer

**Code:** [GNU General Public License v2.0](LICENSE).

**Firmware:** Vendor blobs loaded onto adapters are redistributed verbatim under their manufacturers' licenses (see [docs/FIRMWARE.md](docs/FIRMWARE.md)).

**⚠️ Notice & Disclaimer:** For use only on networks and equipment you own or are explicitly authorized to audit. Airscope drives USB hardware registers directly without kernel guardrails; use at your own risk.
