"""Minimal userland TCP state machine for the captive-portal AP.

Handles the TCP handshake (SYN/SYN-ACK/ACK), data transfer (HTTP request/response),
and connection teardown (FIN/ACK).  Operates over raw IP packets - no kernel sockets.

Only supports a single server port (8080) and one connection per client at a time.
"""
from __future__ import annotations

import logging
import os
import struct
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Callable, Optional

log = logging.getLogger(__name__)

# TCP flags
FIN = 0x01
SYN = 0x02
RST = 0x04
PSH = 0x08
ACK = 0x10
URG = 0x20

_HDR_LEN = 20


class TcpState(IntEnum):
    LISTEN = 0
    SYN_RECEIVED = 1
    ESTABLISHED = 2
    CLOSE_WAIT = 3
    LAST_ACK = 4
    CLOSED = 5


def _checksum(data: bytes, src_ip: str, dst_ip: str, proto: int = 6) -> int:
    """IP pseudo-header + TCP checksum."""
    def _ip(s: str) -> bytes:
        return bytes(int(o) for o in s.split("."))
    pseudo = _ip(src_ip) + _ip(dst_ip) + struct.pack(">BBH", 0, proto, len(data))
    full = pseudo + data
    if len(full) % 2:
        full += b"\x00"
    s = 0
    for i in range(0, len(full), 2):
        s += (full[i] << 8) | full[i + 1]
    while s >> 16:
        s = (s & 0xFFFF) + (s >> 16)
    return ~s & 0xFFFF


def _tcp_checksum(src_ip: str, dst_ip: str, segment: bytes) -> int:
    return _checksum(segment, src_ip, dst_ip, 6)


@dataclass
class TcpConnection:
    state: TcpState = TcpState.LISTEN
    client_ip: str = ""
    client_port: int = 0
    server_port: int = 8080
    seq: int = 0  # server ISN
    ack: int = 0  # next expected from client
    recv_buf: bytearray = field(default_factory= bytearray)
    send_buf: bytearray = field(default_factory= bytearray)
    last_activity: float = 0.0
    on_data: Optional[Callable[[bytes], None]] = None  # called when full HTTP request received


@dataclass
class TcpStack:
    """Minimal TCP stack: one server port, per-client connections."""
    server_ip: str = "192.168.4.1"
    server_port: int = 8080
    send_ip: Optional[Callable[[bytes], None]] = None  # raw IP packet
    on_http_request: Optional[Callable[[str, str, bytes], bytes]] = None  # (method, path, body) -> response

    _conns: dict[tuple[str, int], TcpConnection] = field(default_factory=dict)

    def handle_ip_packet(self, ip_raw: bytes) -> None:
        """Process an incoming IPv4 packet, dispatch TCP segments."""
        if len(ip_raw) < 20:
            return
        ihl = (ip_raw[0] & 0x0F) * 4
        proto = ip_raw[9]
        if proto != 6:
            return
        src_ip = ".".join(str(b) for b in ip_raw[12:16])
        tcp = ip_raw[ihl:]
        if len(tcp) < _HDR_LEN:
            return

        dst_port = struct.unpack(">H", tcp[2:4])[0]
        if dst_port != self.server_port:
            return

        src_port = struct.unpack(">H", tcp[0:2])[0]
        seq = struct.unpack(">I", tcp[4:8])[0]
        flags = tcp[13]
        data = tcp[_HDR_LEN:]

        key = (src_ip, src_port)
        conn = self._conns.get(key)

        if flags & SYN and not (flags & ACK):
            self._handle_syn(key, src_ip, src_port, seq)
        elif conn and flags & RST:
            self._close(conn, key)
        elif conn and flags & FIN:
            self._handle_fin(conn, key, seq)
        elif conn and data:
            self._handle_data(conn, key, seq, data, flags)

    # ----- handlers ----------------------------------------------------------

    def _handle_syn(self, key: tuple[str, int], src_ip: str, src_port: int,
                    client_seq: int) -> None:
        conn = TcpConnection(
            state=TcpState.SYN_RECEIVED,
            client_ip=src_ip,
            client_port=src_port,
            server_port=self.server_port,
            seq=int.from_bytes(os.urandom(4)),
            ack=client_seq + 1,
            last_activity=time.time(),
        )
        self._conns[key] = conn
        self._send_syn_ack(conn)
        log.debug("TCP SYN from %s:%d", src_ip, src_port)

    def _handle_fin(self, conn: TcpConnection, key: tuple[str, int], seq: int) -> None:
        conn.ack = seq + 1
        self._send_ack(conn)
        self._close(conn, key)

    def _handle_data(self, conn: TcpConnection, key: tuple[str, int],
                     seq: int, data: bytes, flags: int) -> None:
        if seq != conn.ack:
            return
        conn.recv_buf.extend(data)
        conn.ack = seq + len(data)
        conn.last_activity = time.time()
        if flags & PSH or self._is_http_complete(conn.recv_buf):
            self._process_request(conn, key)

    def _process_request(self, conn: TcpConnection, key: tuple[str, int]) -> None:
        raw = bytes(conn.recv_buf)
        conn.recv_buf.clear()
        method, path, body = self._parse_http(raw)
        log.debug("HTTP %s %s from %s", method, path, conn.client_ip)

        if self.on_http_request:
            response = self.on_http_request(method, path, body)
        else:
            response = self._default_response()

        conn.send_buf.extend(response)
        self._send_data(conn)
        conn.state = TcpState.CLOSE_WAIT
        self._send_fin(conn)
        self._close(conn, key)

    # ----- frame builders ----------------------------------------------------

    def _send_syn_ack(self, conn: TcpConnection) -> None:
        tcp = self._build_tcp(conn.client_port, conn.server_port,
                              conn.seq, conn.ack, SYN | ACK)
        conn.seq = (conn.seq + 1) & 0xFFFFFFFF
        self._send_raw(conn.client_ip, tcp)

    def _send_ack(self, conn: TcpConnection) -> None:
        tcp = self._build_tcp(conn.client_port, conn.server_port,
                              conn.seq, conn.ack, ACK)
        self._send_raw(conn.client_ip, tcp)

    def _send_data(self, conn: TcpConnection) -> None:
        payload = bytes(conn.send_buf)
        conn.send_buf.clear()
        tcp = self._build_tcp(conn.client_port, conn.server_port,
                              conn.seq, conn.ack, ACK | PSH, payload)
        conn.seq = (conn.seq + len(payload)) & 0xFFFFFFFF
        self._send_raw(conn.client_ip, tcp)

    def _send_fin(self, conn: TcpConnection) -> None:
        tcp = self._build_tcp(conn.client_port, conn.server_port,
                              conn.seq, conn.ack, FIN | ACK)
        conn.seq = (conn.seq + 1) & 0xFFFFFFFF
        self._send_raw(conn.client_ip, tcp)

    def _send_raw(self, dst_ip: str, tcp_segment: bytes) -> None:
        if self.send_ip is None:
            return
        ihl_ver = 0x45
        total_len = 20 + len(tcp_segment)
        ip = struct.pack(">BBHHHBBH", ihl_ver, 0, total_len,
                         0x1234, 0, 64, 6, 0)
        src = self.server_ip
        src_bytes = bytes(int(o) for o in src.split("."))
        dst_bytes = bytes(int(o) for o in dst_ip.split("."))
        ip = ip[:12] + src_bytes + dst_bytes
        cs = _checksum(ip, src, dst_ip, 6)
        ip = ip[:10] + struct.pack(">H", cs) + ip[12:]
        self.send_ip(ip + tcp_segment)

    def _build_tcp(self, sport: int, dport: int, seq: int, ack: int,
                   flags: int, payload: bytes = b"") -> bytes:
        tcp = struct.pack(">HHII", sport, dport, seq, ack)
        tcp += bytes([(5 << 4), flags])
        tcp += struct.pack(">H", 65535)  # window
        tcp += b"\x00\x00"  # checksum (placeholder)
        tcp += b"\x00\x00"  # urgent pointer
        cs = _tcp_checksum(self.server_ip, "", tcp + payload)
        tcp = tcp[:16] + struct.pack(">H", cs) + tcp[18:]
        return tcp + payload

    def _close(self, conn: TcpConnection, key: tuple[str, int]) -> None:
        conn.state = TcpState.CLOSED
        self._conns.pop(key, None)

    # ----- HTTP parsing ------------------------------------------------------

    @staticmethod
    def _parse_http(raw: bytes) -> tuple[str, str, bytes]:
        try:
            header_end = raw.find(b"\r\n\r\n")
            if header_end < 0:
                return "GET", "/", b""
            header = raw[:header_end].decode("utf-8", errors="replace")
            lines = header.split("\r\n")
            parts = lines[0].split(" ")
            method = parts[0] if parts else "GET"
            path = parts[1] if len(parts) > 1 else "/"
            body = raw[header_end + 4:]
            return method, path, body
        except Exception:
            return "GET", "/", b""

    @staticmethod
    def _is_http_complete(buf: bytearray) -> bool:
        return b"\r\n\r\n" in buf

    @staticmethod
    def _default_response() -> bytes:
        body = b"<html><body><h1>Portal</h1></body></html>"
        return (
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: text/html\r\n"
            b"Content-Length: " + str(len(body)).encode() + b"\r\n"
            b"Connection: close\r\n"
            b"\r\n" + body
        )
