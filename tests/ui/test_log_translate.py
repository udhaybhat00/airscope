"""Snapshot tests for plain_english() log-line translator."""
import pytest

from airscope.ui.log_translate import plain_english


# ── full-line examples (input → expected) ────────────────────────────
_CASES: list[tuple[str, str]] = [
    # handshake
    ("Got EAPOL M1 from aa:bb:cc:dd:ee:ff", "Handshake step 1 captured"),
    ("Got EAPOL M2 from aa:bb:cc:dd:ee:ff", "Handshake step 2 captured"),
    ("Got EAPOL M3 from aa:bb:cc:dd:ee:ff", "Handshake step 3 captured"),
    ("Got EAPOL M4 from aa:bb:cc:dd:ee:ff", "Handshake step 4 captured"),
    ("Crackable pair confirmed for 94:83:c4:8c:3f:78",
     "Complete handshake - ready to crack"),
    ("Handshake already saved for 94:83:c4:8c:3f:78",
     "Already have a capture for this network"),
    # PMKID
    ("PMKID found on aa:bb:cc:dd:ee:ff",
     "Key fingerprint captured silently"),
    # WEP
    ("WEP KEY captured for aa:bb:cc:dd:ee:ff", "WEP key captured"),
    ("Decloaked Hidden Network SSID=SecretNet", "Hidden network revealed"),
    # WPS
    ("WPS PIN found for aa:bb:cc:dd:ee:ff PIN=12345670",
     "WPS PIN found"),
    ("WPS PSK found for aa:bb:cc:dd:ee:ff PSK=secret",
     "Password recovered via WPS"),
    ("WPS PSK (via PushButton) found PSK=secret",
     "Password recovered via WPS button"),
    ("WPS locked on aa:bb:cc:dd:ee:ff",
     "Router has locked WPS - too many attempts"),
    # deauth
    ("Sending deauth to client aa:bb:cc:dd:ee:01 on ch6",
     "Disconnecting a device from the network"),
    ("Deauth of MyRouter: forcing a re-handshake",
     "Disconnecting devices from"),
    ("Deauth stopped", "Deauthentication stopped"),
    # scanning
    ("Channel hopping started on 1,6,11",
     "Scanning across all channels"),
    ("Tuned to channel 6", "Switched to channel"),
    ("Passively listening for WEP IVs",
     "Listening for traffic silently"),
    # target
    ("Target acquired: Intel AX200",
     "Locked onto target network"),
    # EvilTwin
    ("EvilTwin of MyNetwork on ch 6",
     "Fake network targeting"),
    ("EvilTwin stopped", "Fake network attack stopped"),
    ("twin live on ch 6 (WPA2-only RSN)",
     "Fake network running on channel"),
    # WPS attacks
    ("WPS PIN brute started on MyRouter",
     "Trying common WPS PINs against the router"),
    ("WPS PushButton: Window Open",
     "WPS button-press detection"),
    # batch
    ("Batch already running (Shift+B stops it)",
     "An automated attack sequence is already running"),
    ("Nothing to attack in the marked set",
     "No targetable networks in the selection"),
    ("Batch done: 3/5 APs yielded captures",
     "Automated attack sequence finished"),
    # silence
    ("AP Silenced ✗S", "Network notifications paused"),
    ("AP UnSilenced ✓", "Network notifications resumed"),
    # no-match passthrough
    ("random garbage log line", "random garbage log line"),
]


@pytest.mark.parametrize("input_line, expected", _CASES, ids=[c[0][:40] for c in _CASES])
def test_plain_english(input_line: str, expected: str) -> None:
    assert plain_english(input_line) == expected


def test_plain_english_returns_string() -> None:
    result = plain_english("anything")
    assert isinstance(result, str)
