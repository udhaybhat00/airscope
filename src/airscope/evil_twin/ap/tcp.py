"""Minimal TCP implementation for serving the captive portal.
Handles: SYN -> SYN-ACK -> ACK -> data -> FIN
No retransmission, no window scaling, no MSS negotiation (fixed 1460).
"""

import struct
import time
from dataclasses import dataclass, field
from typing import Callable


SYN = 0x02
ACK = 0x10
PSH = 0x08
FIN = 0x01
RST = 0x04


@dataclass
class TcpConn:
    client_mac: bytes
    client_ip: bytes
    client_port: int
    server_port: int = 80
    our_seq: int = 0
    their_seq: int = 0
    state: str = 'SYN_SENT'
    recv_buf: bytearray = field(default_factory=bytearray)
    created: float = field(default_factory=time.monotonic)
    last_activity: float = field(default_factory=time.monotonic)


def handle_tcp(ip_packet: bytes, victim_mac: bytes, send_fn: Callable,
               conns: dict):
    """Process an incoming TCP segment."""
    tcp = ip_packet[20:]
    if len(tcp) < 20:
        return

    src_port = struct.unpack('>H', tcp[0:2])[0]
    dst_port = struct.unpack('>H', tcp[2:4])[0]
    seq = struct.unpack('>I', tcp[4:8])[0]
    ack = struct.unpack('>I', tcp[8:12])[0]
    data_offset = (tcp[12] >> 4) * 4
    flags = tcp[12]
    payload = tcp[data_offset:]

    if dst_port != 80:
        return

    key = (victim_mac, src_port)

    if flags & SYN and not (flags & ACK):
        conn = TcpConn(
            client_mac=victim_mac,
            client_ip=ip_packet[12:16],
            client_port=src_port,
            our_seq=int(time.time() * 1000) & 0x7FFFFFFF,
            their_seq=seq + 1,
            state='ESTABLISHED'
        )
        conns[key] = conn
        _send_tcp_segment(send_fn, victim_mac, conn, flags=SYN | ACK, payload=b'')
        return

    if flags & RST:
        conns.pop(key, None)
        return

    conn = conns.get(key)
    if conn is None:
        _send_tcp_segment(send_fn, victim_mac, None, flags=RST,
                          seq=ack, payload=b'')
        return

    conn.last_activity = time.monotonic()

    if flags & FIN:
        conn.their_seq += 1
        _send_tcp_segment(send_fn, victim_mac, conn, flags=ACK, payload=b'')
        conn.state = 'FIN_WAIT'
        return

    if flags & ACK and payload:
        conn.recv_buf.extend(payload)
        conn.their_seq = seq + len(payload)

        if b'\r\n\r\n' in conn.recv_buf:
            request = conn.recv_buf.decode('utf-8', errors='ignore')
            conn.recv_buf.clear()

            from .http import handle_http_request
            response_bytes = handle_http_request(request, victim_mac)

            if response_bytes:
                _send_tcp_segment(send_fn, victim_mac, conn,
                                  flags=PSH | ACK, payload=response_bytes)

    elif flags & ACK and not payload:
        pass


def _send_tcp_segment(send_fn: Callable, victim_mac: bytes,
                      conn: TcpConn | None, flags: int, payload: bytes):
    """Build and send a TCP segment."""
    from .dhcp import _build_ipv4_packet

    if conn:
        seq = conn.our_seq
        ack = conn.their_seq
        dst_port = conn.client_port
        src_port = conn.server_port
        client_ip = conn.client_ip
    else:
        seq = 0
        ack = 0
        dst_port = 0
        src_port = 80
        client_ip = b'\x0A\x00\x00\x64'

    window = 65535
    tcp_header = struct.pack(
        '!HHIIBBHHH',
        src_port, dst_port,
        seq, ack,
        (5 << 4),
        flags,
        window,
        0,
        0
    )

    pseudo = struct.pack('!4s4sBBH', b'\x0A\x00\x00\x01', client_ip, 0, 6,
                         20 + len(payload))
    checksum_data = pseudo + tcp_header + payload
    if len(checksum_data) % 2:
        checksum_data += b'\x00'
    total = sum(struct.unpack('!%dH' % (len(checksum_data) // 2), checksum_data))
    total = (total >> 16) + (total & 0xFFFF)
    total += total >> 16
    checksum = ~total & 0xFFFF

    tcp_header = struct.pack(
        '!HHIIBBHHH',
        src_port, dst_port, seq, ack,
        (5 << 4), flags, window, checksum, 0
    )

    tcp_segment = tcp_header + payload

    if conn and payload:
        conn.our_seq += len(payload)

    ip_packet = _build_ipv4_packet(
        src=b'\x0A\x00\x00\x01',
        dst=client_ip,
        proto=6,
        payload=tcp_segment
    )

    send_fn(victim_mac, ip_packet)
