"""Demo-mode attack simulation: scripted log lines plus real vault artifacts.

No radio, no subprocesses. Each simulated attack writes the same files the
real path would produce (parsed back through the normal index), so the Vault,
counts, and crack flows behave identically. Demo only.
"""
from __future__ import annotations

import asyncio
import struct
import time
from pathlib import Path
from typing import List, Optional

SCRIPT_LINES = {
    "wps": ["probing WPS registrar…", "M1/M2 exchanged, running PixieDust…",
            "PIN recovered offline, verifying…"],
    "pmkid": ["associating with forged MAC…", "EAPOL M1 requested…", "PMKID captured"],
    "handshake": ["deauthenticating clients…", "listening for 4-way handshake…",
                  "handshake captured"],
    "sae": ["listening for SAE commit (passive)…", "commit seen, waiting confirm…",
            "SAE pair complete"],
    "eviltwin": ["twin beaconing on target channel…", "punting clients…",
                 "handshake captured on twin"],
}

_HS_LINE = "WPA*02*" + "0" * 32 + "*aabbccddeeff*112233445566*5465737431***2\n"
_PMKID_LINE = "WPA*01*" + "0" * 32 + "*aabbccddeeff*112233445566*5465737431***\n"


def _sae_frame(dest: str, src: str, bssid: str, seq: int) -> bytes:
    f = (bytes([0xB0, 0x00]) + b"\x00\x00"
         + bytes.fromhex(dest.replace(":", "")) + bytes.fromhex(src.replace(":", ""))
         + bytes.fromhex(bssid.replace(":", "")) + b"\x00\x00")
    return f + struct.pack("<HHH", 3, seq, 0) + bytes(64)


class DemoAttack:
    """A scripted stand-in for a campaign: lines, then artifacts, then done."""

    def __init__(self, kind: str, ap, captures_dir: Path,
                 log=None, step_s: float = 2.0) -> None:
        self.kind = kind
        self.ap = ap
        self.captures_dir = captures_dir
        self.log = log or (lambda _m: None)
        self.step_s = step_s
        self.stopped = False
        self.done = False
        self._task: Optional[asyncio.Task] = None

    def run(self) -> bool:
        """Mirror Campaign.run: claim and schedule (always succeeds solo)."""
        self._task = asyncio.create_task(self._drive())
        return True

    async def stop(self) -> None:
        self.stopped = True
        if self._task is not None:
            await self._task

    def request_stop(self) -> None:
        self.stopped = True

    async def _drive(self) -> None:
        try:
            for line in SCRIPT_LINES.get(self.kind, ["working…"]):
                if self.stopped:
                    return
                self.log(line)
                await asyncio.sleep(self.step_s)
            if not self.stopped:
                self._write_artifacts()
        finally:
            self.done = True

    def _write_artifacts(self) -> None:
        from airscope.persist.common import bssid_to_dashed, safe_ssid
        import time as _time
        dashed = bssid_to_dashed(self.ap.bssid)
        ssid = safe_ssid(self.ap.ssid)
        epoch = int(_time.time())
        base = self.captures_dir / f"{ssid}_{dashed}_{epoch}"
        if self.kind == "wps":
            (base.with_name(base.name + "_wps_pin.txt")).write_text(
                f"SSID: {self.ap.ssid or ''}\nBSSID: {self.ap.bssid}\n"
                f"PSK: demodemo\nPIN: 12345670\n", encoding="utf-8")
        elif self.kind == "pmkid":
            (base.with_name(base.name + "_pmkid.hc22000")).write_text(
                _PMKID_LINE, encoding="utf-8")
        elif self.kind in ("handshake", "eviltwin"):
            (base.with_name(base.name + "_handshake.hc22000")).write_text(
                _HS_LINE, encoding="utf-8")
        elif self.kind == "sae":
            from airscope.persist.pcap import write_pcap
            sta = "11:22:33:44:55:66"
            now = _time.time()
            write_pcap(base.with_name(base.name + "_sae.pcap"),
                       [(_sae_frame(self.ap.bssid, sta, self.ap.bssid, 1), now),
                        (_sae_frame(sta, self.ap.bssid, self.ap.bssid, 2), now + 0.1)])

    def frames_for_pcap(self) -> List[tuple[bytes, float]]:
        """BatchRunner SAE compat (unused: demo saves its own files)."""
        return []
