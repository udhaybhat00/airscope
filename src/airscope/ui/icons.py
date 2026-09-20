"""Signal Noir iconography: single source for encryption, signal, and status glyphs.

Base Unicode only (blocks + geometric shapes); no Nerd Font / emoji dependency.
Colors live in ``encryption_format.py`` / ``signal_bar.py``; this module owns shapes.
"""
from __future__ import annotations


# Encryption icons, keyed by EncryptionType value.
ENC_OPEN = "○"
ENC_WEP = "◐"
ENC_WPA1 = "⬢"
ENC_WPA2 = "⬣"
ENC_WPA3 = "◆"
ENC_WPA3_TRANSITION = "⬣→2"
ENC_OWE = "◇"
ENC_UNKNOWN = "?"

# WPS / client / identity extras.
WPS_OPEN = "◉"
WPS_LOCKED = "◎"
CLIENT = "●"
HIDDEN_SSID = "◌"

# Signal tiers by dBm (coarse, for the prefix glyph; the bar shows fine detail).
TIER_1 = "▁"  # < -80
TIER_2 = "▂"  # -80..-70
TIER_3 = "▃"  # -70..-60
TIER_4 = "▅"  # -60..-50
TIER_5 = "▇"  # > -50
TIER_DEAD = "╳"
TIER_WARMING = "…"


def signal_tier(dbm: float | None) -> str:
    """Coarse tier glyph for a dBm value; ``None`` → warming."""
    if dbm is None:
        return TIER_WARMING
    if dbm < -80:
        return TIER_1
    if dbm < -70:
        return TIER_2
    if dbm < -60:
        return TIER_3
    if dbm < -50:
        return TIER_4
    return TIER_5
