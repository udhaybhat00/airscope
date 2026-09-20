"""SAE (WPA3 Dragonfly) authentication frame decoding.

SAE runs as 802.11 Authentication frames (management subtype 11) with
algorithm 3: seq 1 = commit (group + scalar + element), seq 2 = confirm.
Only the fixed header is decoded here (the finite-field blobs ride along
untouched in ``raw``); pairing commit+confirm per station happens in the
SAE campaign. Pure data, no radio.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Optional

from airscope.dot11.mac import mac_to_str

AUTH_ALGO_SAE = 3
SEQ_COMMIT = 1
SEQ_CONFIRM = 2


@dataclass(slots=True)
class SaeAuth:
    """One SAE commit/confirm frame: endpoints plus the raw MPDU."""

    seq: int
    status: int
    dest: str
    source: str
    bssid: str
    raw: bytes


def parse_sae_auth(raw: bytes) -> Optional[SaeAuth]:
    """Decode an MPDU as SAE auth, or None (not auth / not SAE / truncated)."""
    if len(raw) < 30:
        return None
    if raw[0] & 0xFC != 0xB0:      # type 0 (mgmt), subtype 11 (auth)
        return None
    algo, seq, status = struct.unpack("<HHH", raw[24:30])
    if algo != AUTH_ALGO_SAE:
        return None
    return SaeAuth(seq=seq, status=status, dest=mac_to_str(raw[4:10]),
                   source=mac_to_str(raw[10:16]), bssid=mac_to_str(raw[16:22]),
                   raw=bytes(raw))
