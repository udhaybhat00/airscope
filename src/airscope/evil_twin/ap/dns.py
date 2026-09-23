"""DNS server: responds to ALL queries with 10.0.0.1 (blackhole)."""

import struct
from typing import Callable


def handle_dns(ip_packet: bytes, victim_mac: bytes, send_fn: Callable):
    """Handle a DNS query by responding with A record -> 10.0.0.1."""
    udp = ip_packet[20:]
    if len(udp) < 12:
        return

    src_port = struct.unpack('>H', udp[0:2])[0]
    dns_query = udp[8:]

    if len(dns_query) < 12:
        return

    txid = dns_query[0:2]
    qdcount = struct.unpack('>H', dns_query[4:6])[0]

    resp_header = txid + struct.pack('>HHHHH', 0x8580, qdcount, qdcount, 0, 0)

    question = dns_query[12:]

    answer = (
        b'\xC0\x0C'
        + struct.pack('>H', 1)
        + struct.pack('>H', 1)
        + struct.pack('>I', 60)
        + struct.pack('>H', 4)
        + b'\x0A\x00\x00\x01'
    )

    dns_response = resp_header + question + answer

    udp_resp = struct.pack('>HHHH', 53, src_port, 8 + len(dns_response), 0) + dns_response

    from .dhcp import _dhcp_state
    client_ip = _dhcp_state.get_ip(victim_mac) or b'\x0A\x00\x00\x64'

    from .dhcp import _build_ipv4_packet
    ip_resp = _build_ipv4_packet(
        src=b'\x0A\x00\x00\x01',
        dst=client_ip,
        proto=17,
        payload=udp_resp
    )

    send_fn(victim_mac, ip_resp)
