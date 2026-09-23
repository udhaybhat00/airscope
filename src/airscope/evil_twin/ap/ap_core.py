"""Userland AP state machine for the captive-portal fake AP.

Tracks per-client association state and responds to auth/assoc/probe
frames.  Runs entirely in userland via the USB worker thread.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Callable, Optional

log = logging.getLogger(__name__)


class ClientState(IntEnum):
    NONE = 0
    AUTHED = 1
    ASSOCED = 2


@dataclass
class Client:
    mac: str
    state: ClientState = ClientState.NONE
    aid: int = 0
    last_seen: float = 0.0


@dataclass
class ApCore:
    """Minimal AP state machine: auth, assoc, probe response, client tracking.

    ``send_frame`` injects a raw 802.11 frame (auth/assoc response, etc.)
    back through the USB worker.
    """
    ssid: str = ""
    bssid: bytes = b""
    channel: int = 1
    send_frame: Optional[Callable[[bytes], None]] = None
    on_client_assoc: Optional[Callable[[str], None]] = None

    _clients: dict[str, Client] = field(default_factory=dict)
    _next_aid: int = 1

    def handle_auth(self, src_mac: bytes) -> None:
        """Open System Authentication: accept everyone."""
        mac_str = ":".join(f"{b:02x}" for b in src_mac)
        client = self._get_or_create(mac_str)
        client.state = ClientState.AUTHED
        client.last_seen = time.time()
        from airscope.evil_twin.ap.frames import craft_auth_response
        if self.send_frame is not None:
            self.send_frame(craft_auth_response(src_mac, self.bssid))
        log.debug("auth OK %s", mac_str)

    def handle_assoc_req(self, src_mac: bytes) -> None:
        """Association Request: assign AID, send Association Response."""
        mac_str = ":".join(f"{b:02x}" for b in src_mac)
        client = self._get_or_create(mac_str)
        if client.aid == 0:
            client.aid = self._next_aid
            self._next_aid = (self._next_aid % 2007) + 1
        client.state = ClientState.ASSOCED
        client.last_seen = time.time()
        from airscope.evil_twin.ap.frames import craft_assoc_response
        if self.send_frame is not None:
            self.send_frame(craft_assoc_response(src_mac, self.bssid, aid=client.aid))
        log.debug("assoc OK %s aid=%d", mac_str, client.aid)
        if self.on_client_assoc is not None:
            self.on_client_assoc(mac_str)

    def handle_probe_request(self, src_mac: bytes, ssid: str | None) -> None:
        """Probe Request: respond if SSID matches or is wildcard."""
        if ssid and ssid != self.ssid:
            return
        from airscope.evil_twin.ap.frames import craft_probe_response
        if self.send_frame is not None:
            self.send_frame(craft_probe_response(
                self.bssid, self.ssid, self.channel, src_mac))

    def get_client(self, mac: str) -> Client | None:
        return self._clients.get(mac)

    def is_assoced(self, mac: str) -> bool:
        client = self._clients.get(mac)
        return client is not None and client.state == ClientState.ASSOCED

    def cleanup_stale(self, timeout: float = 30.0) -> list[str]:
        """Remove clients not seen within *timeout* seconds."""
        now = time.time()
        stale = [m for m, c in self._clients.items()
                 if now - c.last_seen > timeout]
        for m in stale:
            del self._clients[m]
        return stale

    def _get_or_create(self, mac: str) -> Client:
        if mac not in self._clients:
            self._clients[mac] = Client(mac=mac)
        return self._clients[mac]
