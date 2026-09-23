"""Userland DHCP server for the captive-portal AP.

Operates over raw 802.11 data frames (no kernel sockets).  The server
assigns IPs from a configurable pool and responds to Discover/Request
with Offer/Ack, pointing clients at the portal IP for gateway and DNS.
"""
from __future__ import annotations

import logging
import struct
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

log = logging.getLogger(__name__)

# DHCP constants
_BOOTREQUEST = 1
_BOOTREPLY = 2
_MAGIC_COOKIE = bytes([0x63, 0x82, 0x53, 0x63])

# DHCP options
OPT_SUBNET_MASK = 1
OPT_ROUTER = 3
OPT_DNS_SERVER = 6
OPT_REQUESTED_IP = 50
OPT_MESSAGE_TYPE = 53
OPT_SERVER_ID = 54
OPT_LEASE_TIME = 51
OPT_END = 255

# DHCP message types
DHCPDISCOVER = 1
DHCPOFFER = 2
DHCPREQUEST = 3
DHCPACK = 5
DHCPNAK = 6


@dataclass
class Lease:
    mac: str
    ip: str
    expires: float


@dataclass
class DhcpServer:
    """Minimal stateful DHCP server running over raw frames.

    The ``send_ip`` callback wraps the reply into an 802.11 data frame
    and injects it.  ``handle_dhcp`` is called from the data-frame RX
    path with the UDP payload already extracted.
    """
    gateway_ip: str = "192.168.4.1"
    subnet_mask: str = "255.255.255.0"
    ip_start: str = "192.168.4.10"
    ip_end: str = "192.168.4.200"
    lease_sec: int = 3600
    send_ip: Optional[Callable[[str, bytes], None]] = None  # (client_ip, udp_payload)

    _leases: dict[str, Lease] = field(default_factory=dict)
    _next_ip_counter: int = 0

    def __post_init__(self) -> None:
        self._ip_pool_start = self._ip_to_int(self.ip_start)
        self._ip_pool_end = self._ip_to_int(self.ip_end)

    # ----- public API --------------------------------------------------------

    def handle_dhcp(self, raw_udp: bytes, src_mac: str) -> Optional[bytes]:
        """Process a DHCP payload (UDP data, no IP/UDP headers).  Returns the
        DHCP reply payload, or None if nothing to send."""
        if len(raw_udp) < 240:
            return None
        msg_type_opt = self._get_option(raw_udp, OPT_MESSAGE_TYPE)
        if msg_type_opt is None:
            return None
        msg_type = msg_type_opt[0]

        client_mac_raw = raw_udp[28:34]
        client_mac_str = ":".join(f"{b:02x}" for b in client_mac_raw)

        if msg_type == DHCPDISCOVER:
            return self._handle_discover(raw_udp, client_mac_str)
        if msg_type == DHCPREQUEST:
            return self._handle_request(raw_udp, client_mac_str)
        return None

    def get_lease_ip(self, mac: str) -> Optional[str]:
        """Return the currently-leased IP for *mac*, or None."""
        lease = self._leases.get(mac)
        if lease and lease.expires > time.time():
            return lease.ip
        return None

    # ----- internals ---------------------------------------------------------

    def _handle_discover(self, pkt: bytes, mac: str) -> bytes:
        ip = self._assign_ip(mac)
        if ip is None:
            log.warning("DHCP pool exhausted")
            return self._nak(pkt, mac)
        return self._build_offer(pkt, mac, ip)

    def _handle_request(self, pkt: bytes, mac: str) -> bytes:
        req_ip_opt = self._get_option(pkt, OPT_REQUESTED_IP)
        if req_ip_opt:
            req_ip = ".".join(str(b) for b in req_ip_opt)
        else:
            req_ip = self._assign_ip(mac)
            if req_ip is None:
                return self._nak(pkt, mac)

        self._leases[mac] = Lease(mac=mac, ip=req_ip,
                                  expires=time.time() + self.lease_sec)
        return self._build_ack(pkt, mac, req_ip)

    def _assign_ip(self, mac: str) -> Optional[str]:
        existing = self._leases.get(mac)
        if existing and existing.expires > time.time():
            return existing.ip
        for _ in range(self._ip_pool_end - self._ip_pool_start + 1):
            candidate = self._int_to_ip(self._ip_pool_start + self._next_ip_counter)
            self._next_ip_counter = (self._next_ip_counter + 1) % (
                self._ip_pool_end - self._ip_pool_start + 1)
            taken = any(lease.ip == candidate and lease.expires > time.time()
                        for lease in self._leases.values())
            if not taken:
                return candidate
        return None

    def _build_offer(self, pkt: bytes, mac: str, ip: str) -> bytes:
        xid = pkt[4:8]
        return self._build_bootp(pkt, mac, ip, xid, DHCPOFFER)

    def _build_ack(self, pkt: bytes, mac: str, ip: str) -> bytes:
        xid = pkt[4:8]
        return self._build_bootp(pkt, mac, ip, xid, DHCPACK)

    def _nak(self, pkt: bytes, mac: str) -> bytes:
        xid = pkt[4:8]
        return self._build_bootp(pkt, mac, "0.0.0.0", xid, DHCPNAK)

    def _build_bootp(self, pkt: bytes, mac: str, ip: str,
                     xid: bytes, msg_type: int) -> bytes:
        """Build a DHCP reply (BOOTP packet + options)."""
        client_mac_raw = bytes(int(o, 16) for o in mac.split(":"))
        # Fixed BOOTP fields
        reply = bytearray(240)
        reply[0] = _BOOTREPLY
        reply[1] = 1  # htype (Ethernet)
        reply[2] = 6  # hlen
        reply[3] = 0  # hops
        reply[4:8] = xid  # xid (echo from request)
        reply[8:10] = b"\x00\x00"  # secs
        reply[10:12] = b"\x00\x00"  # flags
        reply[12:16] = b"\x00\x00\x00\x00"  # ciaddr
        ip_bytes = self._ip_to_bytes(ip)
        reply[16:20] = ip_bytes  # yiaddr
        reply[20:24] = ip_bytes  # siaddr (server)
        reply[24:28] = self._ip_to_bytes(self.gateway_ip)  # giaddr
        reply[28:34] = client_mac_raw
        # Pad to 240 bytes, then magic cookie
        reply_bytes = bytes(reply)
        options = self._build_options(msg_type, ip)
        return reply_bytes + _MAGIC_COOKIE + options

    def _build_options(self, msg_type: int, client_ip: str) -> bytes:
        opts = bytearray()
        opts += bytes([OPT_MESSAGE_TYPE, 1, msg_type])
        opts += bytes([OPT_SUBNET_MASK, 4]) + self._ip_to_bytes(self.subnet_mask)
        opts += bytes([OPT_ROUTER, 4]) + self._ip_to_bytes(self.gateway_ip)
        opts += bytes([OPT_DNS_SERVER, 4]) + self._ip_to_bytes(self.gateway_ip)
        opts += bytes([OPT_LEASE_TIME, 4]) + struct.pack(">I", self.lease_sec)
        opts += bytes([OPT_SERVER_ID, 4]) + self._ip_to_bytes(self.gateway_ip)
        opts += bytes([OPT_END])
        return bytes(opts)

    # ----- helpers ------------------------------------------------------------

    @staticmethod
    def _get_option(pkt: bytes, opt_id: int) -> Optional[bytes]:
        i = 240 + 4  # skip BOOTP fixed + magic cookie
        while i < len(pkt):
            if pkt[i] == OPT_END:
                break
            if pkt[i] == 0:  # padding
                i += 1
                continue
            oid = pkt[i]
            olen = pkt[i + 1]
            if oid == opt_id:
                return pkt[i + 2: i + 2 + olen]
            i += 2 + olen
        return None

    @staticmethod
    def _ip_to_int(ip: str) -> int:
        parts = ip.split(".")
        return (int(parts[0]) << 24 | int(parts[1]) << 16 |
                int(parts[2]) << 8 | int(parts[3]))

    @staticmethod
    def _int_to_ip(n: int) -> str:
        return f"{(n >> 24) & 0xFF}.{(n >> 16) & 0xFF}.{(n >> 8) & 0xFF}.{n & 0xFF}"

    @staticmethod
    def _ip_to_bytes(ip: str) -> bytes:
        return bytes(int(o) for o in ip.split("."))
