# airscope — how (and why) I rebuilt Wi-Fi auditing from the USB endpoint up

*A personal write-up: the problem, the build, the platforms, the proof, and the honest
list of things it can't do. Written by the person who wrote the code.*

---

## The night it started

I was on a Kali VM at 2am, fighting `airmon-ng` for the third time that month. The adapter
dropped out of monitor mode. `ioctl SIOCSIWMODE failed: Operation not supported` — a message
that explains nothing, fixes nothing, and teaches nobody anything. I rebooted, pinned a
kernel, rebuilt a DKMS driver, got it working, and then realized I had four terminals open:
one for the scanner, one for the deauth, one for `hostapd`, one for `dnsmasq`. I was copying
BSSIDs between them by hand.

And somewhere in the middle of that, a thought I couldn't shake:

**None of this has to be this way.**

Frame injection is a feature of the radio's firmware, not of the Linux kernel. A captive
portal is DHCP + DNS + TCP + HTTP — protocols I could write in an afternoon. The kernel
module, the five packages, the shell glue: those are *choices*, inherited from 2007-era
tooling, that everyone treats like physics.

So I started writing the other thing. That thing is **airscope**.

---

## What it is, in one breath

airscope is a Wi-Fi security auditor that runs natively on **Linux, Windows, and macOS**,
written entirely in **pure Python**, with **zero kernel drivers** and **zero external tools**.
It scans, captures handshakes and PMKIDs, deauths, breaks WPS, recovers WEP, captures WPA3
SAE material, runs an EvilTwin portal that verifies the victim's password *in real time*,
cracks offline via hashcat, and writes reports — behind a 60fps terminal UI and an optional
web dashboard.

Download one file. Run it. That's the install.

---

## Why

### The problem, honestly stated

Wi-Fi auditing in 2024+ still looks like 2007:

1. **Linux-only.** Nothing in the classic stack cares about Windows or macOS users.
2. **Kernel-dependent.** Monitor mode means out-of-tree drivers that break every time the
   kernel updates — and every distro ships a different kernel.
3. **Glued together.** aircrack-ng, hostapd, dnsmasq, reaver, mdk3: five projects, five
   config dialects, zero shared state. You are the integration layer, copying hex by hand.
4. **Hostile to newcomers.** The error messages are ioctl archaeology. Nobody learns
   anything except how to search Stack Overflow at 2am.

### The insight

The interesting word in that list is **kernel**. Nothing about *auditing* a network requires
running below the operating system. It requires:

- talking to the radio (that's USB — `libusb` does it from userspace, on every OS),
- understanding frames (that's parsing — pure Python does it),
- faking an access point (that's a DHCP server, a DNS sink, and an HTTP page),
- checking passwords (that's PBKDF2 and a MIC comparison).

Every single one of those lives comfortably in userspace. The only reason the old world
reaches for kernel modules is that it *chose* to sit under the network stack instead of
beside it.

So airscope moves the whole stack up. **No `modprobe`. No DKMS. No `airmon-ng`. No
`hostapd` subprocess.** One process, one language, three operating systems.

---

## How it works

I'll tell it the way I think about it — top to bottom.

### The shape of the thing

```text
  TUI (60fps) · Web dashboard · Reports/Vault
                 │
        Attack orchestrator            ← one asyncio graph, one radio mutex
                 │
        WlanInterface + frame parser   ← one representation of a frame, ever
                 │
        USB worker thread              ← bulk IN/OUT, TX priority queue, ACK tally
                 │
        Userland network stack         ← 802.11 craft, DHCP, DNS, TCP, HTTP portal
                 │
        chips/ — one package per chip  ← VID:PID registry, lazy import
                 │
             PyUSB / libusb
```

### The USB part

Everything a kernel radiotap path did, we do on a dedicated worker thread: bulk-IN arrives,
the descriptor is decoded, the frame is dispatched — all *off* the asyncio event loop, so
the UI never stutters and frame timing stays precise. Transmissions go through a priority
queue: management frames first (auth, assoc, deauth), then DHCP, then portal HTTP, then
beacons. That ordering is not cosmetic — an EvilTwin deauth burst and a portal response
will fight for the same radio, and I'd rather decide who wins than find out empirically.

### The frame part

We craft and parse what we need: beacons, probes, auth/assoc, deauth, data, EAPOL. One
parser, one frame model. A frame seen on the wire and a frame written to a pcap are the
same object — there is no "live dialect" and "file dialect" to keep in sync.

### The EvilTwin part (my favorite)

The fake AP is a full userland stack: DHCP leases, DNS blackhole (every name resolves to
us), TCP, and an HTTP portal. The victim connects, gets an IP, gets redirected, submits a
password.

Here's the part I'm proud of: **the password is verified instantly.** The same campaign
already captured the 4-way handshake, so when the portal submits a candidate passphrase we
compute `PMK = PBKDF2(pass, SSID)`, derive the PTK, and compare the MIC against the captured
M2/M4 right there. Match? We're in. Mismatch? Serve the page again. No offline crack, no
handoff to hashcat, no "wait five minutes and check" — a cryptographic verdict in
milliseconds, on any client platform, because nothing about the check is client-specific.

### The ACK part (the bug farm)

Early on I kept losing my mind over one word: **ACK**. It means at least three different
things in this domain:

- did *we hear* the AP acknowledge our frame? (RX tally),
- will *our card* auto-acknowledge a frame sent to a spoofed MAC? (active monitor + the
  chip's own TX retry engine),
- did *our software* retransmit because the tally stayed silent? (software retry).

WPS lives or dies on this; PMKID cares a little; deauth doesn't care at all. So I split it
into three layers with per-chip hooks and a fixed protocol (`set_fake_mac` → arm the tally →
`send_until_ack`). Once it was decomposed, the bugs stopped being mysterious — and the
hardware matrix could give ACKs their own column instead of hiding them inside "TX works".

### The chipset part

There are **20 chipsets across 25 driver packages**, each implementing one small `Driver`
ABC: transport, firmware, MAC/PHY config, RX/TX hooks, channels, and its ACK quirks. Each
package declares its own `VID:PID` list; the registry is built from those declarations only,
and the real driver lazy-imports on first match. Startup stays O(registry), not O(every
driver in the repo).

Above that boundary, nothing knows what a dongle is. Everything speaks 802.11. That
separation is also what makes hardware testing fair (more on that below).

### The boring-but-critical part: platform gates

One function — `campaign_blocked()` — decides what the current OS can do. On macOS it says
*"EvilTwin needs Linux"* and disables the button *with that reason as the tooltip*; every
other attack stays native. The TUI, the web dashboard, and batch mode all ask the same
function, so they can never disagree, and a wrong gate fails CI instead of failing you
mid-engagement.

---

## The platforms (the whole point)

| | Linux | Windows | macOS |
|---|:--:|:--:|:--:|
| Scan / capture / hop | ✅ | ✅ | ✅ |
| Deauth, PMKID, WPS, WEP, SAE capture | ✅ | ✅ | ✅ |
| EvilTwin portal | ✅ | ✅ (via WSL2) | ❌ gated |
| TUI, web, reports | ✅ | ✅ | ✅ |

**Linux** is home turf — everything native.

**Windows** is honest: the adapter is passed into WSL2 with `usbipd` and airscope runs in
the guest where libusb can claim it. Everything works — *including* EvilTwin — but
"Windows support" means "Windows with WSL2", and I say that in the docs instead of implying
a native Win32 monitor path that doesn't exist.

**macOS** is the one people told me was impossible without poking at Apple's closed IO80211
frameworks. It runs natively — because we never touch the system's 802.11 stack at all.
We're below it (at the USB endpoint) and beside it (with our own TCP/IP). The only gap is
the fake-AP interface mode macOS won't give us, so EvilTwin is gated there with a reason
you can read in the tooltip. Everything else just runs.

One codebase. Three OSes. Zero kernel modules. That's the thesis of the whole project.

---

## What people actually use it for

- **Authorized pentests** — recon → target → capture → crack → report, in one tool. The
  reports come out as CSV, Kismet netXML, HTML, and `.hc22000` for whatever you want to
  throw at it next.
- **Defending your own network** — check your PSK strength, your WPS exposure, your
  handshake exposure, on the laptop you already own.
- **Learning** — because it's one readable Python tree, a student can follow a frame from a
  USB descriptor to a rendered row. That's the opposite of `ioctl SIOCSIWMODE failed`.
- **Porting research** — the `Driver` ABC plus the baseline scripts give you a structured
  way to bring up new silicon and *measure* how close your port is to the kernel driver.

---

## How I know it works (and how I sleep at night)

A hardware tool that can only be tested with hardware ships bugs to your adapter. So:

- **3,008 tests over 293 files, and every USB interaction is mocked.** The full suite runs
  in a cloud CI runner in about 77 seconds, on every push. There are even style tests —
  comment policy is asserted by pytest, which sounds insane until you maintain a 256k-line
  tree.
- **A five-axis hardware rubric.** Every card gets measured on RX, TX, ACK behaviour,
  *port fidelity vs. the kernel driver on the same card*, and a 30-minute stress soak —
  then graded A–D. The important trick is keeping two things separate: *port fidelity* (my
  gap, fixable) vs. *hardware ceiling* (the silicon's gap, not fixable). Right now: 13 A,
  3 B, 1 C, 2 D — with the honest cases documented card by card.
- **Tag-gated releases.** The build fails if the git tag doesn't match `__version__`.
  Four binaries (macOS universal2, Linux x64/arm64, Windows x64), smoke-tested before
  publish. Version drift is a build error, not a surprise.

---

## What it can't do

I'd rather write this part carefully than have someone discover it during an engagement.

1. **EvilTwin needs Linux** (or WSL2). macOS gets everything else, gated honestly.
2. **Windows support is WSL2 support.** `usbipd`, WSL2, no native Win32 monitor path.
3. **One radio, one campaign.** A mutex serializes attacks on a single adapter. No
   simultaneous multi-attack yet.
4. **WPA3 can't be outsmarted.** We capture downgrade material and MICs, but SAE is a
   PAKE — it doesn't fall to offline dictionary attack the way a WPA2 handshake does [13].
   If a tool tells you otherwise, it's selling something.
5. **Hardware varies.** On a C- or D-grade card, your day will be worse. No driver fixes
   physics.
6. **2.4 and 5 GHz only.** 6 GHz / Wi-Fi 7 is roadmap, not shipping.
7. **Cracking is orchestrated, not built-in.** Handshakes are parsed, verified, and tracked
   here; GPU hashing happens in hashcat, by design.
8. **Not an SDR.** This is a bulk-USB 802.11 tool, not a spectrum analyzer, and it doesn't
   capture entire 160MHz channels.
9. **Authorization is on you.** Injection and impersonation are restricted or illegal
   without permission in most jurisdictions (FCC Part 15, IT Act 2000, Computer Misuse Act…).
   The tool ships loud legal notices and refuses to attack unattended, but it cannot tell an
   auditor from an attacker — only you can.
10. **The math doesn't care.** Strong passphrases resist PBKDF2 no matter how nice the UI
    is. airscope improves the *workflow*, not entropy.

---

## The part that matters most

Every surface of this project — the README, the landing page, the app itself — says the
same thing: **use it only on networks you own or are explicitly authorized to audit.**

That's not boilerplate. Deauth is disruptive. A fake AP is impersonation. These are serious
powers, and the reason I'm comfortable building them is that they're also how defenders find
out whether their network would survive ten minutes of someone who *isn't* asking nicely.
The dual-use balance leans on the operator. I've tried to build a tool that rewards being
used responsibly: explicit targets, visible skip reasons, no drive-by scanning, legal
notices where you can't miss them.

---

## Where it's going

The next things, in the order I actually intend to do them:

1. **A capture-quality feedback loop** — score every handshake (which EAPOL messages,
   descriptor version, MIC validity), auto-recapture until it's crackable, and stream
   hashcat status live into the TUI.
2. **A defensive security-score mode** — one command against your own network: PMF? WPA3?
   WPS off? Weak PSK? Rogue-AP indicators? → a graded report you can act on.
3. **Multi-adapter** — one radio locked to a channel capturing, another hopping; maybe
   remote sensors feeding one dashboard.
4. **6 GHz / Wi-Fi 7** — the band is coming whether I'm ready or not.
5. **WIDS alerts** — deauth floods and evil twins, pushed to a webhook.
6. **A plugin surface** — entry-point campaigns, so people can extend it without forking
   the orchestrator.

---

## If you read this far

The pitch is short: **Wi-Fi auditing doesn't have to be Linux-only, kernel-dependent, or
glued together with shell scripts — and I can show you 3,008 tests and a binary for your
OS as evidence.**

- Repo: https://github.com/udhaybhat00/airscope
- Downloads: the landing page, or the Releases tab
- Hardware matrix: `docs/SUPPORTED-HARDWARE.md` (grades, per-card notes, all of it)
- The ACK obsession, if you want the deep cut: `docs/ACKS.md`

Take it, run it, break it, tell me where it hurts. And audit something you're allowed to.

— the airscope author
