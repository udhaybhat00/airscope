# airscope: Kernel-Independent Wi-Fi Security Auditing in Pure Python

**A technical report on the design, evaluation, and limitations of a cross-platform framework for authorized Wi-Fi reconnaissance, capture, and attack simulation.**

| | |
|---|---|
| **Project** | airscope — wireless auditor |
| **Version** | v0.3.8 (September 2026) |
| **License** | GPL-2.0 |
| **Runtime** | Python 3.11+ · asyncio · PyUSB/libusb |
| **Platforms** | Linux (native) · Windows 10/11 (WSL2) · macOS (native) |
| **Availability** | https://github.com/udhaybhat00/airscope |

---

## Abstract

Wi-Fi security auditing today is dominated by a toolchain that is Linux-only, kernel-dependent,
and assembled from five or more loosely coupled programs. Practitioners must install
monitor-mode drivers that break on kernel updates, chain `airmon-ng` with `aircrack-ng`,
`hostapd`, `dnsmasq`, `reaver` and `mdk3`, and shuttle results between terminals by hand.
This paper presents **airscope**, a framework that reinvents that stack from the USB endpoint
up in pure Python: a userspace 802.11 implementation that talks directly to Wi-Fi adapters
through PyUSB, a complete userland access-point stack (frame crafting, DHCP, DNS, HTTP captive
portal), and a three-layer acknowledgement-reliability subsystem — with no kernel modules, no
external daemons, and a single codebase that runs on Linux, Windows, and macOS.

airscope integrates reconnaissance, handshake and PMKID capture, deauthentication, WPS
(PixieDust and PIN), WEP recovery, WPA3 SAE downgrade capture, EvilTwin with real-time MIC
verification, offline cracking orchestration, and report generation behind a 60 fps Textual TUI
and an optional web dashboard. The implementation comprises 256k lines of Python across 658
modules, drives 20 chipsets through 25 driver packages, and is validated by 3,008 tests in
which all hardware is mocked, plus a five-axis hardware verification rubric that grades each
adapter card on measured behaviour rather than anecdote.

We report the architecture, the portability model, the evaluation methodology, and — with equal
weight — the limitations: the EvilTwin portal requires Linux, Windows support rides on USB
passthrough into WSL2, campaigns serialize on a single radio, WPA3 attacks cannot exceed what
the protocol's downgrade surface permits, and adapter performance varies measurably across
silicon. airscope is released as single-file binaries for four platforms and is intended
exclusively for use on networks you own or are explicitly authorized to audit.

**Keywords:** Wi-Fi security, 802.11, userspace drivers, cross-platform, EvilTwin, PMKID,
WPA/WPA2, WPS, security auditing, Textual, pure Python.

---

## 1. Introduction

### 1.1 The problem

Wi-Fi auditing in 2024+ still looks like this: install Kali Linux, run `airmon-ng`, fight
driver versions, pray `modprobe` does not break your kernel, pipe five different tools
together, and copy-paste output between terminals. That workflow is:

1. **Linux-only.** Nothing in the classic stack works on Windows or macOS.
2. **Kernel-dependent.** Monitor mode requires out-of-tree drivers (or mac80211's monitor
   path) that break on every kernel update and every distro upgrade.
3. **Glued together.** aircrack-ng, hostapd, dnsmasq, reaver and mdk3 are separate projects
   with separate configuration dialects that barely talk to each other.
4. **Hostile to newcomers.** An error like `ioctl SIOCSIWMODE failed: Operation not supported`
   teaches nobody anything — it is a wall, not a diagnostic.

Each of these is an engineering choice that someone made once and everyone else inherited.
They are not properties of 802.11 itself. Frame injection is a property of the radio's
firmware and MAC; nothing in that path requires a kernel module. A captive-portal access
point needs DHCP, DNS, TCP and HTTP — protocols whose smallest correct implementations fit in
a few thousand lines. The monitor-mode ioctl exists because tools chose to live below the
network stack rather than beside it.

### 1.2 The airscope answer

airscope moves the entire stack into userspace, in one language, in one process:

- **No kernel drivers.** Adapters are driven directly from userspace via PyUSB/libusb. The
  radio never needs `airmon-ng`, `modprobe`, or a DKMS build on the machine running the audit.
- **No external tools.** The 802.11 frame stack, DHCP server, DNS blackhole, HTTP captive
  portal, handshake parser, PMKID extractor, and WPS machinery are all pure Python in this
  repository. There is no `hostapd` subprocess, no `dnsmasq` config, no shell-out to `reaver`.
- **One codebase, three OSes.** The same Python runs on Linux, Windows (via WSL2), and macOS.
  Platform differences are detected at runtime in a single choke point (`campaign_blocked()`)
  and communicated to the user as a reason, not as a crash.
- **A real interface.** A 60 fps Textual TUI plus an optional web dashboard, instead of a wall
  of terminal output and five scrollback panes.

### 1.3 Contributions

This report makes the following claims:

- **C1 — Userspace 802.11 over USB.** A practical architecture for driving Wi-Fi adapters
  entirely from userspace: a dedicated USB worker thread with a priority TX queue, descriptor
  decoding on bulk-IN, and no kernel involvement, presented in §4.1.
- **C2 — A complete userland AP.** An EvilTwin implementation that verifies the candidate PSK
  against a captured handshake *in real time* via MIC computation, eliminating the offline
  cracking step, presented in §4.2.
- **C3 — A three-layer ACK reliability model.** A decomposition of the overloaded word "ACK"
  (heard ACKs, emitted ACKs, hardware retry, software retry) into independently testable
  mechanisms with per-chip hooks, presented in §4.3.
- **C4 — The platform-gate model.** Runtime capability detection as a model-layer predicate so
  the UI can never offer an attack that cannot run on the current OS, presented in §4.5.
- **C5 — A reproducible hardware rubric.** A five-axis verification methodology (RX, TX, ACKs,
  Port fidelity, Stress) with a letter-grade rubric that separates *port quality* from
  *silicon capability*, presented in §6.2.
- **C6 — Hardware-free CI at scale.** 3,008 tests over 293 files in which every USB interaction
  is mocked, making a hardware-dependent tool fully testable in a cloud runner, presented in
  §6.1.

---

## 2. Background and Related Work

### 2.1 The incumbent toolchain

The de facto audit stack is the aircrack-ng suite plus its satellites. `airmon-ng` moves an
interface into monitor mode via kernel ioctls; `airodump-ng` captures; `aireplay-ng`
injects deauthentication; `hostapd` and `dnsmasq` together fake an access point; `reaver`
brute-forces WPS; `mdk3` floods. Each tool is competent; the *system* is not: state lives in
shell variables, target selection is retyped per tool, and output formats disagree.

**airgeddon** wraps that stack in a unified menu-driven TUI — an improvement in ergonomics
that leaves the underlying dependencies untouched: it still requires monitor-mode kernel
support, hostapd, and the same Linux-only base. **Wifite2** automates target selection and
chaining with the same constraint. **Kismet** is a well-engineered wireless sniffer and
detector, but it is a passive observer: it does not drive attacks, and it too sits on the
kernel's monitor path.

### 2.2 Positioning

| | **airscope** | aircrack-ng stack | airgeddon | Kismet |
|---|---|---|---|---|
| Install | `uv sync` / single binary | Kernel modules + 5 packages | Bash + many packages | Packages |
| Kernel changes | **None** | Monitor-mode drivers | Same as aircrack-ng | Monitor mode |
| OS support | **Linux + Windows + macOS** | Linux only | Linux only | Mostly Linux |
| External processes | **Zero** | hostapd, dnsmasq, reaver, ... | All of them | External detectors |
| EvilTwin password check | **Real-time MIC verify** | Manual export to hashcat | Manual | N/A |
| WPA3 SAE handling | Downgrade + MIC capture | Partial | No | Passive |
| Interface | **60 fps TUI + web** | CLI | CLI + xterm | CLI + web |
| Test coverage | **3,008 tests, hardware mocked** | C unit tests | None | Moderate |
| Distribution | **Single binary per OS** | Package per distro | Script | Package per distro |

The claim is not that airscope's individual attacks are novel — the attacks are published
techniques [11–13] — but that the *integration* is: one process, one state model, one target
selection, three operating systems, and no shared mutable global state between tools.

---

## 3. System Architecture

### 3.1 The stack

```text
┌─────────────────────────────────────────────────────────────────────┐
│ airscope (Python 3.11+, asyncio)                                   │
│                                                                     │
│  ┌──────────────┐  ┌───────────────┐  ┌─────────────────────────┐  │
│  │ Textual TUI  │  │ Web Dashboard │  │ Report / Vault          │  │
│  │ 60fps, CSS   │  │ optional      │  │ pcap/hc22000/CSV/HTML   │  │
│  └──────┬───────┘  └──────┬────────┘  └────────────┬────────────┘  │
│         │                 │                         │               │
│  ┌──────┴─────────────────┴─────────────────────────┴────────────┐  │
│  │ Attack Orchestrator (asyncio tasks, one radio mutex)          │  │
│  │ Scanner · EvilTwin · WPS PIN/PBC · WEP · PMKID · SAE · Batch │  │
│  └──────────────────────────┬────────────────────────────────────┘  │
│                             │                                       │
│  ┌──────────────────────────┴────────────────────────────────────┐  │
│  │ WlanInterface (802.11 abstraction: hopping, AP/client state)  │  │
│  │ WlanFrameParser (pure-Python 802.11 frame parser)             │  │
│  └──────────────────────────┬────────────────────────────────────┘  │
│                             │                                       │
│  ┌──────────────────────────┴────────────────────────────────────┐  │
│  │ USB Worker Thread (PyUSB, blocking I/O off the event loop)   │  │
│  │ RX: bulk-IN  → descriptor decode → frame dispatch            │  │
│  │ TX: priority queue (mgmt > dhcp > http > beacon > deauth)    │  │
│  │ ACK tracking: RX tally + chip HW retry + software retry      │  │
│  └──────────────────────────┬────────────────────────────────────┘  │
│                             │                                       │
│  ┌──────────────────────────┴────────────────────────────────────┐  │
│  │ Userland 802.11 + network stack (pure Python)                │  │
│  │ Frame craft: beacon/auth/assoc/deauth/data/EAPOL             │  │
│  │ EvilTwin AP: DHCP server · DNS blackhole · TCP · HTTP portal │  │
│  │ Crack: handshake parser · PMKID · MIC verify · WPA-PSK       │  │
│  └──────────────────────────┬────────────────────────────────────┘  │
│                             │                                       │
│  ┌──────────────────────────┴────────────────────────────────────┐  │
│  │ chips/ — one driver package per chipset (20 supported)       │  │
│  │ transport (bulk + control) · firmware · MAC/PHY/RX/TX        │  │
│  │ Auto-discovered by VID:PID, lazy import                      │  │
│  └──────────────────────────┬────────────────────────────────────┘  │
│                             │                                       │
│              PyUSB / libusb → USB bulk endpoints                    │
└─────────────────────────────────────────────────────────────────────┘
```

Reading downward: presentation (TUI/web/report), orchestration (one asyncio task graph, one
radio mutex), the 802.11 abstraction, the USB worker, the userland network stack, and the
per-chipset drivers. Reading upward: every received frame is decoded at the bulk endpoint and
promoted through the same parser the attack logic consumes — there is exactly one
representation of a frame in the system, not a capture-file dialect and a live dialect.

### 3.2 Key design decisions

| Decision | Why |
|----------|-----|
| **PyUSB over kernel drivers** | Cross-platform, no versioning hell, no `modprobe` blacklists |
| **asyncio + dedicated USB thread** | Non-blocking TUI with precise frame timing; USB I/O never stalls the render loop |
| **Textual over curses/raw rich** | Asyncio-native, CSS-like styling, real widget tree, keyboard bindings |
| **One radio mutex per campaign** | Two attacks can never fight over the same adapter; the UI disables conflicting buttons automatically |
| **Lazy chip imports** | The VID:PID registry is built from each chip's light `__init__` only; drivers load on first match, keeping startup fast |
| **Userland AP stack** | Full control over every 802.11 frame, no hostapd/dnsmasq config drift |
| **Platform gates in the model layer** | A single `campaign_blocked()` choke point decides what each OS can do, so the UI can never offer an attack that cannot run |

---

## 4. Methodology and Design

### 4.1 Userspace USB driver model

Each adapter is owned by a **USB worker thread** that performs all blocking PyUSB transfers
off the asyncio event loop. The receive path is `bulk-IN → descriptor decode → frame
dispatch`; the transmit path is a **priority queue** ordered so that time-critical management
frames (auth/assoc/deauth) precede best-effort traffic (DHCP leases, HTTP portal responses,
beacon maintenance):

```text
priority(TX) = mgmt > dhcp > http > beacon > deauth-burst
```

This ordering matters in practice: a captive portal serving a client while a deauth burst is
in flight must not starve the handshake it was launched to complete, and vice versa — the
queue makes the trade-off explicit and testable instead of emergent.

Because the transport is bulk USB rather than a kernel radiotap path, **frame timing is under
our control** and the same code path runs identically on all three operating systems (modulo
libusb backend selection). The cost of this decision is that we own everything the kernel used
to do: descriptor formats, firmware handshakes, and retry policy. That cost is per-chipset and
is where the 25 driver packages live.

### 4.2 Pure-Python 802.11 and network stack

airscope crafts and parses the frames it needs (`beacon`, `probe`, `auth`, `assoc`,
`deauth/disassoc`, `data`, `EAPOL`) and implements the small network stack an evil-twin
victim expects:

- **DHCP server** — leases to associated clients;
- **DNS blackhole** — every query resolves to the portal host, so navigation "just works";
- **TCP + HTTP server** — serves the credential-capture portal;
- **Real-time MIC verification** — the captured 4-way handshake from the same campaign is
  used to verify each submitted PSK *as it arrives*: candidate `PMK = PBKDF2(passphrase,
  SSID)` → `PTK` → compare MIC against `M2`/`M4`. No offline cracking step, no file handoff:

$$P_{\text{accept}} = \left[\mathrm{HMAC\text{-}SHA1}(K, \dots)_{\text{MIC}} = \text{MIC}_{\text{captured}}\right]$$

The portal verdict is therefore instant and cryptographically grounded, which is also why the
attack works against iOS, Android, Windows, and macOS clients alike: nothing about the check
is client-specific.

### 4.3 The three-layer ACK model

"Ambiguity around the word ACK" is the single largest source of bugs in injection tooling,
because two unrelated phenomena travel under one name [17]:

1. **Heard ACKs (RX tally)** — did *we receive* the recipient's ACK frame? (`record_ack`
   hooks on incoming frames.)
2. **Emitted ACKs (active monitor + chip HW-retry)** — will *our radio* ACK a frame addressed
   to a spoofed MAC, and will the chip's own TX engine retry our forged frame?
3. **Software retry** — did `send_until_ack()` retransmit because the tally stayed silent?

A campaign (WPS, PMKID, WEP) drives them in a fixed protocol: `set_fake_mac()` so the AP's
unicast reaches us (and the chip auto-ACKs, or the AP abandons the session) →
`enable_rx_acks()` → `send_until_ack()` / `acks_seen()`. Deauthentication needs none of this
— it only *reports* endpoint ACKs. The result is that each mechanism is independently
observable, and the hardware matrix (§6.2) can grade "ACKs" as its own column instead of
folding it into a vague "TX works".

### 4.4 Concurrency model

One event loop; one **radio mutex per campaign**. Because a single adapter cannot sensibly
simultaneously hop channels for reconnaissance and hold a fixed channel for a portal, the
mutex serializes campaigns and the model layer reports *why* a button is disabled in plain
English. The UI never presents an action the model will refuse — the reverse of the usual
pattern where a GUI learns about impossibility by crashing.

### 4.5 Platform gates

`campaign_blocked()` is the single choke point where OS capability is decided. On macOS
native, for example, EvilTwin is blocked with the reason *"Fake-AP phishing page requires
Linux"* while deauth, WPS, PMKID, WEP, and SAE capture all run natively. Consequences of
putting the gate in the model rather than the view:

- the TUI and web dashboard cannot diverge in what they offer;
- batch/auto-attack mode inherits the same decisions;
- tests assert the matrix directly (a wrong gate fails CI, not a user's engagement).

### 4.6 Chipset driver model

Each chipset is a package implementing the `Driver` ABC (`chips/driver.py`): transport
(bulk + control), firmware load, MAC/PHY configuration, RX/TX hooks, `SUPPORTED_CHANNELS`,
and the chip-specific pieces of the ACK model. Registration is data-driven: each package's
`__init__.py` declares `SUPPORTED_IDS = [DeviceID(vid, pid), ...]`, the registry is built by
reading those declarations only, and the first VID:PID match lazily imports the driver —
startup cost is O(registry), not O(all drivers).

The driver boundary is deliberately narrow. It is the only layer allowed to know that a given
dongle is, say, an RTL8812AU; everything above it speaks 802.11. This is what makes the port
fidelity column of §6.2 meaningful: a driver either delivers the frames or it does not, and
the measurement happens above the driver, where users feel it.

---

## 5. Platforms

### 5.1 Support matrix

| Capability | Linux | Windows | macOS |
|---|:--:|:--:|:--:|
| Passive scan / hop / capture | ✅ native | ✅ WSL2 | ✅ native |
| Deauth injection | ✅ | ✅ WSL2 | ✅ native |
| PMKID extraction | ✅ | ✅ WSL2 | ✅ native |
| WPS PixieDust / PIN / PBC | ✅ | ✅ WSL2 | ✅ native |
| WEP suite | ✅ | ✅ WSL2 | ✅ native |
| WPA3 SAE downgrade capture | ✅ | ✅ WSL2 | ✅ native |
| EvilTwin (userland AP + portal) | ✅ | ✅ WSL2 | ❌ gated (needs Linux net stack path) |
| TUI + web dashboard + reports | ✅ | ✅ | ✅ |
| Single-binary distribution | ✅ | ✅ (.exe) | ✅ (universal2) |

### 5.2 Windows

Windows support is honest about its mechanism: the adapter is passed into WSL2 with
`usbipd`, and airscope runs inside the WSL2 guest where libusb can claim the device
directly. Everything — including EvilTwin — therefore works, but "Windows support" means
"Windows with WSL2", and the docs and download page say so rather than implying a native
Win32 monitor path that does not exist.

### 5.3 macOS

macOS runs the tool natively (no VM) for everything except the EvilTwin portal, which is
blocked by the platform gate with a visible reason. Native operation on macOS is the part of
the matrix most people said was impossible without closed IO80211 frameworks; the userspace
USB approach is precisely what makes it possible: we never touch the system's 802.11 stack,
because we are below it at the USB endpoint and beside it at the network stack.

---

## 6. Evaluation

### 6.1 Software quality: 3,008 tests without hardware

A hardware tool that can only be tested with hardware ships bugs to every user's adapter.
airscope inverts that: **all USB interactions are mocked** (`pytest-mock`), so the full suite
runs in a cloud runner:

| Metric | Value |
|---|---|
| Tests | **3,008** passing, 11 xfailed (documented expected failures) |
| Test files | 293 |
| Source modules | 658 (256,364 LOC) + 39,977 LOC of tests |
| Runtime | ~77 s locally; runs in CI on every push |
| Lint | `ruff check` on `src/` and `tests/`; the formatter is deliberately disabled (hand-formatted ~99-col tree) |
| Style guards as tests | Comment policy and even an em-dash ban in core sources are *asserted by tests*, so style drift fails the build |

CI runs lint + tests on every push; a separate release workflow builds PyInstaller binaries
for macOS (universal2), Linux (x64, arm64) and Windows, smoke-tests them, and publishes only
when the pushed tag matches `__version__` — version drift is a build failure, not a surprise.

### 6.2 Hardware verification: a five-axis rubric

Benchmarks for Wi-Fi tools are usually anecdotal ("works with my adapter"). airscope
maintains `docs/SUPPORTED-HARDWARE.md` as a measured matrix; `docs/GRADING.md` defines the
process. Two axes are kept deliberately separate:

- **Port fidelity** — airscope vs. the Linux kernel driver *on the same card*. A gap here is
  our port leaving performance on the table (fixable by us).
- **Hardware ceiling** — how good the card is at all, even under the best driver. If Linux
  itself is weak on this silicon, no port can save it (not fixable, and should not be
  misreported as our bug).

| Column | What is measured |
|---|---|
| **RX** | Reception breadth/quality, channel tune — passive captures depend on it |
| **TX** | Frame injection — deauth, WPS, WEP, PMKID extraction depend on it |
| **ACKs** | Does the radio auto-ACK a forged MAC; does the AP ACK us — WPS leans on this heavily |
| **Port** | airscope vs. kernel driver on the same card |
| **Stress** | 30-minute channel-hopping soak; tracks RX degradation over time |
| **Grade** | Rubric rollup of the above |

Each card is baselined with scripts in `scripts/baseline/` (kernel driver vs. airscope,
diffed), so grades are reproducible rather than editorial. Current distribution across the
19 fully graded cards: **13 A, 3 B, 1 C, 2 D** — including the honest cases: a faithful port
of a weak card scores `Port ✅` with a low grade; a lower-fidelity port of a capable card
gets `Port ⚠️`.

### 6.3 Performance characteristics

- **UI:** 60 fps Textual rendering, driven off the same event loop as attack orchestration;
  USB blocking calls never run on that loop.
- **Startup:** lazy driver import keeps boot O(registry) rather than O(chipsets).
- **Sustained capture:** the RX path is descriptor-decode-and-dispatch with a dedupe layer
  (`wlan/dedupe.py`); the stress soak exists specifically to catch RX degradation that only
  appears over 30 minutes of hopping.

### 6.4 Distribution

Four release binaries (macOS universal2, Linux x64, Linux arm64, Windows x64) are built from
a single source of truth (`__version__`), gated on the tag, and smoke-tested before publish.
There is no installer, no kernel module, and no post-install step: download, mark executable,
run.

---

## 7. Use Cases

1. **Authorized penetration testing.** Full engagement lifecycle in one tool: recon → target
   selection → capture → crack orchestration → client-ready reports (CSV, Kismet netXML,
   HTML, `.hc22000` for external cracking).
2. **Defensive self-audit.** Organizations can audit their own PSK strength, WPS exposure,
   PMF configuration and handshake exposure with equipment they already own, on any desktop
   OS they already run.
3. **Education and training.** Because the whole stack is one readable Python tree, a student
   can follow a received frame from a USB descriptor to a rendered row — the pedagogical
   opposite of `ioctl SIOCSIWMODE failed`.
4. **Driver/porting research.** The `Driver` ABC plus the baseline scripts give a structured
   way to bring up new silicon and quantify fidelity against the kernel driver.
5. **Cross-platform demonstrations.** The same demo runs on a conference laptop regardless of
   its OS — there is no "run it in a VM" asterisk.

---

## 8. Limitations

A research claim that ignores its counter-evidence is marketing. The following are the
tool's real boundaries as of v0.3.8:

1. **EvilTwin requires Linux** (native or WSL2). The userland AP itself is portable Python,
   but the platform gate blocks it on macOS because the fake-AP path needs an interface
   configuration mode macOS does not expose to this userspace approach. Every other attack
   runs natively there.
2. **Windows support is WSL2 support.** It requires `usbipd` passthrough and WSL2. It is not
   a native Win32 monitor-mode implementation, and the project does not claim one.
3. **One radio, one campaign.** The radio mutex means no simultaneous multi-attack on one
   adapter. Multi-adapter parallelism is future work (§10).
4. **WPA3 is bounded by the protocol.** We implement downgrade capture and MIC recording;
   SAE's PAKE construction does not yield to offline dictionary attack the way a captured
   WPA2-PSK handshake does [13]. The tool cannot crack what the protocol refuses to expose —
   reporting otherwise would be dishonest.
5. **Hardware variance is real.** Grades C and D cards in the matrix have measured RX/TX
   weaknesses; users on that silicon will have a worse day than users on an A-grade card,
   and no software fix changes the hardware ceiling.
6. **Frequency coverage:** 2.4 and 5 GHz today. 6 GHz / Wi-Fi 7 (802.11be, MLO) support is
   roadmap, not present. OFDMA-era frame handling is unimplemented.
7. **Cracking is orchestrated, not built-in.** Offline brute-force delegates to hashcat;
   airscope parses, verifies (real-time MIC in EvilTwin), and tracks progress, but GPU
   hashing is external by design.
8. **Throughput ceiling.** A userspace bulk-USB path is ample for 802.11 control/management
   frames and the legacy/mcs rates involved in auditing, but this is not a wideband SDR:
   it is not a spectrum analyzer and does not capture entire 160 MHz channels.
9. **Regulatory and legal exposure.** Injection, deauthentication and impersonation are
   restricted or illegal without authorization in most jurisdictions (e.g. FCC Part 15,
   IT Act 2000, Computer Misuse Act). airscope ships in-product legal notices and
   authorization framing, but a tool cannot technically distinguish an authorized auditor
   from an attacker — the operator's authorization is the real control.
10. **Scale of attacks.** Effectiveness against strong PSKs is bounded by passphrase entropy,
    not by tooling: airscope improves the *workflow*, not the mathematics of PBKDF2.

---

## 9. Ethics, Safety, and Legal Considerations

- **Authorization is a precondition, not a feature.** Every distribution surface (README,
  landing page, in-app notice) states that airscope is for networks you own or are
  explicitly authorized to audit, with jurisdiction-specific warnings (CFAA, IT Act 2000,
  Computer Misuse Act).
- **No unattended mischief.** Attacks require explicit target selection; batch mode runs
  only what was chosen, with plain-English skip reasons; nothing scans-and-attacks
  autonomously.
- **Evidence hygiene.** Captures and reports live in user-controlled directories with
  timestamped artifacts suitable for engagement documentation.
- **The defensive mirror.** The same mechanics that capture handshakes let owners verify
  their own exposure; the project's long-term direction (§10) leans further into that
  dual-use balance.

---

## 10. Conclusion and Future Work

airscope demonstrates that the Linux-only, kernel-dependent, multi-process Wi-Fi audit
workflow is contingent rather than necessary: with a userspace USB transport, a pure-Python
802.11 and network stack, and a disciplined platform-gate model, the same tool runs on three
operating systems with zero kernel modifications, zero external daemons, and 3,008 tests
proving its behaviour without hardware present.

Future work, in rough priority order:

1. **Capture-quality feedback loop** — score every handshake (EAPOL message coverage,
   descriptor version, MIC validity), auto-recapture until crackable, and stream hashcat
   status into the TUI.
2. **Defensive security-score mode** — a graded self-audit (PMF, WPA3, WPS exposure, weak
   PSK, rogue-AP indicators) producing a report an organization can act on.
3. **Multi-adapter operation** — one radio locked to a channel capturing, another hopping;
   remote sensors feeding one dashboard.
4. **6 GHz / Wi-Fi 7** — band expansion and MLO-aware frame handling.
5. **WIDS alerting** — deauth-flood and evil-twin detection with webhook notifications.
6. **Plugin surface** — entry-point attack modules so the community can extend campaigns
   without forking the orchestrator.

---

## References

1. aircrack-ng suite. https://www.aircrack-ng.org
2. airgeddon — multi-attack wireless auditing tool. https://github.com/v1s1t0r1sh3r3/airgeddon
3. Wifite2. https://github.com/derv82/wifite2
4. Kismet wireless sniffer/detector. https://www.kismetwireless.net
5. hashcat password recovery. https://hashcat.net
6. hostapd / IEEE 802.11 access-point implementation. https://w1.fi/hostapd/
7. PyUSB — Python USB access library. https://pyusb.github.io
8. Textual — Python TUI framework. https://textual.textualize.io
9. IEEE Std 802.11-2020, *IEEE Standard for Information Technology — Telecommunications and
   information exchange between systems — Local and metropolitan area networks — Specific
   requirements — Part 11: Wireless LAN Medium Access Control (MAC) and Physical Layer (PHY)
   Specifications*.
10. Wi-Fi Alliance, WPA3 Specification. https://www.wi-fi.org/discover-wi-fi/security
11. M. Vanhoef and F. Piessens, "Key Reinstallation Attacks: Forcing Nonce Reuse in WPA2"
    (KRACK), NDSS 2017.
12. M. Vanhoef, "Fragment and Forge: Breaking Wi-Fi Using Frame Aggregation and Fragmentation"
    (FragAttacks), USENIX Security 2021.
13. D. Drahoš, M. Vanhoef, and P. Řezník, "Dragonblood: Breaking the WPA3 Standard" (SAE
    attacks), IEEE S&P 2019.
14. PEP 3156 / Python `asyncio` — https://docs.python.org/3/library/asyncio.html
15. PyInstaller. https://pyinstaller.org
16. Microsoft, WSL2 USB/IP support — usbipd-win. https://github.com/dorssel/usbipd-win
17. airscope, *ACKs: diagnosing hardware auto-ACK and retry* — docs/ACKS.md.
18. airscope, *Hardware Testing & Verification* — docs/SUPPORTED-HARDWARE.md; and
    *Grading* — docs/GRADING.md.
19. WiGLE — wireless network mapping. https://wigle.net

---

*airscope is released under the GNU General Public License v2.0. This document describes
software intended exclusively for use on networks and equipment you own or are explicitly
authorized to audit.*
