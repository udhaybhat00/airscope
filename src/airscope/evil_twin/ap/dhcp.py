"""Minimal DHCP server for the rogue AP. All in userland, no dnsmasq."""

import struct
import time
import threading
from typing import Callable


GATEWAY = "10.0.0.1"
SUBNET = "255.255.255.0"
DNS_SERVER = "10.0.0.1"
LEASE_TIME = 3600
IP_POOL_START = 100
IP_POOL_END = 200


class DHCPState:
    def __init__(self):
        self._leases: dict[bytes, tuple[bytes, float]] = {}
        self._next_ip = IP_POOL_START
        self._lock = threading.Lock()

    def assign_ip(self, mac: bytes) -> bytes:
        with self._lock:
            if mac in self._leases:
                ip, expiry = self._leases[mac]
                if time.time() < expiry:
                    return ip

            while self._next_ip <= IP_POOL_END:
                ip = bytes([10, 0, 0, self._next_ip])
                conflict = False
                for m, (i, e) in self._leases.items():
                    if i == ip and time.time() < e:
                        conflict = True
                        break
                if not conflict:
                    self._leases[mac] = (ip, time.time() + LEASE_TIME)
                    self._next_ip += 1
                    return ip

            oldest_mac, (oldest_ip, _) = min(
                self._leases.items(), key=lambda x: x[1][1]
            )
            self._leases[mac] = (oldest_ip, time.time() + LEASE_TIME)
            return oldest_ip

    def get_ip(self, mac: bytes) -> bytes | None:
        with self._lock:
            if mac in self._leases:
                ip, expiry = self._leases[mac]
                if time.time() < expiry:
                    return ip
        return None


_dhcp_state = DHCPState()


def handle_dhcp(ip_packet: bytes, victim_mac: bytes, send_fn: Callable):
    """Parse DHCP message and send appropriate response."""
    udp = ip_packet[20:]
    if len(udp) < 236 + 8:
        return
    dhcp_msg = udp[8:]

    xid = dhcp_msg[4:8]
    chaddr = dhcp_msg[28:34]

    msg_type = None
    i = 236
    while i < len(dhcp_msg):
        opt = dhcp_msg[i]
        if opt == 0:
            break
        if opt == 255:
            i += 1
            continue
        length = dhcp_msg[i + 1]
        if opt == 53 and length >= 1:
            msg_type = dhcp_msg[i + 2]
        i += 2 + length

    if msg_type == 1:
        client_ip = _dhcp_state.assign_ip(chaddr)
        response = _build_dhcp_reply(
            xid=xid,
            chaddr=chaddr,
            yiaddr=client_ip,
            msg_type=2,
            options={
                1: bytes([255, 255, 255, 0]),
                3: bytes([10, 0, 0, 1]),
                6: bytes([10, 0, 0, 1]),
                51: struct.pack('>I', LEASE_TIME),
                54: bytes([10, 0, 0, 1]),
            }
        )
        _send_dhcp(victim_mac, response, send_fn, broadcast=True)

    elif msg_type == 3:
        client_ip = _dhcp_state.get_ip(chaddr) or bytes([10, 0, 0, IP_POOL_START])
        response = _build_dhcp_reply(
            xid=xid,
            chaddr=chaddr,
            yiaddr=client_ip,
            msg_type=5,
            options={
                1: bytes([255, 255, 255, 0]),
                3: bytes([10, 0, 0, 1]),
                6: bytes([10, 0, 0, 1]),
                51: struct.pack('>I', LEASE_TIME),
                54: bytes([10, 0, 0, 1]),
            }
        )
        _send_dhcp(victim_mac, response, send_fn, broadcast=True)

    elif msg_type == 7:
        with _dhcp_state._lock:
            _dhcp_state._leases.pop(chaddr, None)


def _build_dhcp_reply(xid: bytes, chaddr: bytes, yiaddr: bytes, msg_type: int,
                      options: dict) -> bytes:
    """Build a complete DHCP reply (BootReply)."""
    header = struct.pack(
        '<BBBBIHHIIIIII',
        2,
        1,
        6,
        0,
        struct.unpack('>I', xid)[0],
        0,
        0,
        0,
        struct.unpack('>I', yiaddr)[0] if isinstance(yiaddr, bytes) else 0,
        0,
        0,
    )
    header += chaddr + b'\x00' * (16 - len(chaddr))
    header += b'\x00' * 64 + b'\x00' * 128

    opts = b''
    for opt_num, value in options.items():
        opts += bytes([opt_num, len(value)]) + value
    opts += b'\xFF'

    return header + opts


def _send_dhcp(victim_mac: bytes, dhcp_payload: bytes, send_fn: Callable,
               broadcast: bool = True):
    """Wrap DHCP in UDP then IP then send via 802.11."""
    dst_ip = b'\xff\xff\xff\xff' if broadcast else _dhcp_state.get_ip(victim_mac)

    udp_len = 8 + len(dhcp_payload)
    udp = struct.pack('>HHHH', 67, 68, udp_len, 0) + dhcp_payload

    ip = _build_ipv4_packet(
        src=b'\x0a\x00\x00\x01',
        dst=dst_ip,
        proto=17,
        payload=udp
    )

    send_fn(victim_mac, ip)


def _build_ipv4_packet(src: bytes, dst: bytes, proto: int, payload: bytes) -> bytes:
    """Build a minimal IPv4 packet with correct checksum."""
    total_len = 20 + len(payload)
    ip_id = int(time.time() * 1000) & 0xFFFF
    header = struct.pack(
        '!BBHHHBBH4s4s',
        0x45,
        0,
        total_len,
        ip_id,
        0,
        64,
        proto,
        0,
        src,
        dst
    )
    checksum = _ipv4_checksum(header)
    header = struct.pack(
        '!BBHHHBBH4s4s',
        0x45, 0, total_len, ip_id, 0, 64, proto, checksum, src, dst
    )
    return header + payload


def _ipv4_checksum(header: bytes) -> int:
    """Calculate IPv4 header checksum."""
    if len(header) % 2:
        header += b'\x00'
    total = sum(struct.unpack('!%dH' % (len(header) // 2), header))
    total = (total >> 16) + (total & 0xFFFF)
    total += total >> 16
    return ~total & 0xFFFF
