"""Plain-English translator for technical log lines.

``plain_english(line)`` maps terse capture/attack output into
human-readable labels that non-expert users can understand at a glance.
The mapping is deterministic and stateless.
"""
from __future__ import annotations

# Each entry: (technical substring → plain-English replacement).
# Order matters: more-specific patterns come first so shorter
# prefixes don't shadow them.
_RULES: list[tuple[str, str]] = [
    # ── handshake / 4-way ──────────────────────────────────────────
    ("Got EAPOL M1", "Handshake step 1 captured"),
    ("Got EAPOL M2", "Handshake step 2 captured"),
    ("Got EAPOL M3", "Handshake step 3 captured"),
    ("Got EAPOL M4", "Handshake step 4 captured"),
    ("Crackable pair confirmed", "Complete handshake — ready to crack"),
    ("Handshake already saved", "Already have a capture for this network"),
    ("HANDSHAKE captured", "Handshake captured — ready to crack"),
    ("✓ HANDSHAKE", "Handshake captured — ready to crack"),
    # ── PMKID ──────────────────────────────────────────────────────
    ("PMKID found", "Key fingerprint captured silently"),
    ("PMKID captured", "Key fingerprint captured silently"),
    ("✓ PMKID", "Key fingerprint captured silently"),
    # ── WEP ────────────────────────────────────────────────────────
    ("WEP KEY captured", "WEP key captured"),
    ("✓ WEP KEY", "WEP key captured"),
    ("Decloaked Hidden Network", "Hidden network revealed"),
    # ── WPS ────────────────────────────────────────────────────────
    ("WPS PIN found", "WPS PIN found"),
    ("✓ WPS PIN", "WPS PIN found"),
    ("WPS PSK (via PushButton)", "Password recovered via WPS button"),
    ("WPS PSK found", "Password recovered via WPS"),
    ("✓ WPS PSK", "Password recovered via WPS"),
    ("WPS locked", "Router has locked WPS — too many attempts"),
    # ── SAE / WPA3 ────────────────────────────────────────────────
    ("SAE captured", "WPA3 login exchange captured"),
    ("✓ SAE", "WPA3 login exchange captured"),
    # ── EvilTwin ───────────────────────────────────────────────────
    ("PSK recovered", "Password found!"),
    ("Password found", "Password found!"),
    # ── deauth / disassoc ──────────────────────────────────────────
    ("Sending deauth to client", "Disconnecting a device from the network"),
    ("Deauth of", "Disconnecting devices from"),
    ("Deauth stopped", "Deauthentication stopped"),
    ("✓ Deauth provoked a crackable handshake",
     "Handshake captured after disconnecting devices"),
    # ── scanning / channel ─────────────────────────────────────────
    ("Channel hopping", "Scanning across all channels"),
    ("Tuned to channel", "Switched to channel"),
    ("Tried to tune to channel", "Attempted to switch to channel"),
    ("Passively listening", "Listening for traffic silently"),
    # ── target / focus ─────────────────────────────────────────────
    ("Target acquired", "Locked onto target network"),
    ("Encryption:", "Encryption:"),
    ("BSSID:", "BSSID:"),
    # ── PMF ────────────────────────────────────────────────────────
    ("PMF Required", "Network requires management frame protection"),
    ("Deauth attacks have been disabled",
     "Disconnect attacks blocked — network uses management protection"),
    # ── WEP attacks ────────────────────────────────────────────────
    ("ChopChop", "Packet forgery attack"),
    ("ARP Replay", "Replaying ARP packets to generate data"),
    # ── EvilTwin campaign ──────────────────────────────────────────
    ("EvilTwin of", "Fake network targeting"),
    ("EvilTwin stopped", "Fake network attack stopped"),
    ("twin live on ch", "Fake network running on channel"),
    # ── WPS attacks ────────────────────────────────────────────────
    ("WPS PIN brute started", "Trying common WPS PINs against the router"),
    ("WPS PushButton", "WPS button-press detection"),
    # ── SAE capture ────────────────────────────────────────────────
    ("SAE capture on", "Capturing WPA3 login from"),
    # ── batch ──────────────────────────────────────────────────────
    ("Batch already running", "An automated attack sequence is already running"),
    ("Nothing to attack", "No targetable networks in the selection"),
    ("Batch done", "Automated attack sequence finished"),
    # ── silence ────────────────────────────────────────────────────
    ("AP Silenced", "Network notifications paused"),
    ("AP UnSilenced", "Network notifications resumed"),
    # ── capture events ─────────────────────────────────────────────
    ("Existing captures in", "Previous captures found in"),
]


def plain_english(line: str) -> str:
    """Translate a technical log line to plain English.

    Scans ``_RULES`` for the first matching substring; returns the
    plain-English replacement. If no rule matches the original line
    is returned unchanged.
    """
    for technical, friendly in _RULES:
        if technical in line:
            return friendly
    return line
