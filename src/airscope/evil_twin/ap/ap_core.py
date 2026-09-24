"""Userland 802.11 AP: handles auth, assoc, and client state."""

import time
import struct
import threading
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ClientState:
    mac: bytes
    aid: int
    ip: Optional[str] = None
    ip_bytes: Optional[bytes] = None
    seq_to_client: int = 1
    seq_from_client: int = 1
    associated: bool = False
    authed: bool = False
    connected_at: float = field(default_factory=time.monotonic)


class APStateMachine:
    """Handles 802.11 management frame responses and client tracking."""

    def __init__(self, ap_mac: bytes, ssid: str, channel: int, usb_tx):
        self.ap_mac = ap_mac
        self.ssid = ssid
        self.channel = channel
        self.usb_tx = usb_tx

        self._clients: dict[bytes, ClientState] = {}
        self._tcp_conns: dict = {}
        self._next_aid = 1
        self._mgmt_seq = 1
        self._lock = threading.Lock()

    def _next_mgmt_seq(self) -> int:
        seq = self._mgmt_seq
        self._mgmt_seq = (self._mgmt_seq + 1) & 0xFFF
        return seq

    def handle_rx(self, raw_frame: bytes) -> None:
        """Dispatch an incoming 802.11 frame. Called from USB RX thread."""
        from .frames import parse_frame_control, parse_mgmt_addrs

        frame_type, subtype, to_ds, from_ds = parse_frame_control(raw_frame)

        if frame_type == 0:
            da, sa, bssid = parse_mgmt_addrs(raw_frame)

            if subtype == 0x0B:
                self._handle_auth(raw_frame, da, sa)
            elif subtype == 0x00:
                self._handle_assoc_req(raw_frame, sa)
            elif subtype == 0x04:
                self._handle_probe(raw_frame, sa)

        elif frame_type == 2:
            from .frames import strip_80211_data
            victim_mac, ip_packet = strip_80211_data(raw_frame)
            if victim_mac and ip_packet:
                self._handle_data(victim_mac, ip_packet)

    def _handle_auth(self, frame: bytes, da: bytes, sa: bytes):
        from .frames import craft_auth_response

        victim_mac = sa
        seq = self._next_mgmt_seq()
        response = craft_auth_response(victim_mac, self.ap_mac, seq)
        self.usb_tx(response, priority=0)

        with self._lock:
            if victim_mac not in self._clients:
                self._clients[victim_mac] = ClientState(mac=victim_mac, aid=0)
            self._clients[victim_mac].authed = True

    def _handle_assoc_req(self, frame: bytes, sa: bytes):
        from .frames import craft_assoc_response

        victim_mac = sa
        with self._lock:
            if victim_mac not in self._clients:
                self._clients[victim_mac] = ClientState(mac=victim_mac, aid=0)
            client = self._clients[victim_mac]
            if not client.authed:
                return
            client.aid = self._next_aid
            self._next_aid += 1
            client.associated = True
            aid = client.aid

        seq = self._next_mgmt_seq()
        response = craft_assoc_response(victim_mac, self.ap_mac, aid, seq)
        self.usb_tx(response, priority=0)

    def _handle_probe(self, frame: bytes, sa: bytes):
        body = frame[24:]
        i = 0
        while i < len(body) - 1:
            eid = body[i]
            elen = body[i + 1]
            if eid == 0:
                probe_ssid = body[i + 2:i + 2 + elen].decode('utf-8', errors='ignore')
                if probe_ssid == self.ssid or probe_ssid == '':
                    self._send_probe_response(sa)
                break
            i += 2 + elen

    def _send_probe_response(self, client_mac: bytes):
        pass

    def _handle_data(self, victim_mac: bytes, ip_packet: bytes):
        if len(ip_packet) < 20:
            return

        ip_proto = ip_packet[9]

        if ip_proto == 17:
            from .dhcp import handle_dhcp
            from .dns import handle_dns
            udp = ip_packet[20:]
            if len(udp) < 8:
                return
            dst_port = struct.unpack('>H', udp[2:4])[0]
            if dst_port == 67:
                handle_dhcp(ip_packet, victim_mac, self._send_to_client)
            elif dst_port == 53:
                handle_dns(ip_packet, victim_mac, self._send_to_client)

        elif ip_proto == 6:
            from .tcp import handle_tcp
            handle_tcp(ip_packet, victim_mac, self._send_to_client, self._tcp_conns)

    def _send_to_client(self, victim_mac: bytes, ip_packet: bytes):
        from .frames import wrap_ip_in_data

        with self._lock:
            client = self._clients.get(victim_mac)
            if not client:
                return
            seq = client.seq_to_client
            client.seq_to_client = (client.seq_to_client + 1) & 0xFFF

        frame = wrap_ip_in_data(victim_mac, self.ap_mac, ip_packet, seq)
        self.usb_tx(frame, priority=1)
