"""802.11 frame crafting and parsing for the userland AP stack.

Pure bytes, no I/O. All frame builders return raw bytes ready for USB injection.
Frame Control encoding matches the existing dot11.mac module format:
  FC[0] = subtype(4 bits) | type(2 bits) | more_data(1) | retry(1)
  FC[1] = power_mgmt(1) | more_frag(1) | protected(1) | order(1) | from_ds(1) | to_ds(1)
"""
from __future__ import annotations

import struct
import time
import zlib

# ----- Frame Control types ---------------------------------------------------
FC_TYPE_MGMT = 0
FC_TYPE_CTRL = 1
FC_TYPE_DATA = 2

# Management subtypes (upper nibble of FC[0])
SUBTYPE_AUTH = 0x0B
SUBTYPE_ASSOC_REQ = 0x00
SUBTYPE_ASSOC_RESP = 0x01
SUBTYPE_DEAUTH = 0x0C
SUBTYPE_DISASSOC = 0x0A
SUBTYPE_PROBE_REQ = 0x04
SUBTYPE_PROBE_RESP = 0x05
SUBTYPE_BEACON = 0x08
SUBTYPE_ACTION = 0x0D

# Data subtypes
SUBTYPE_DATA = 0x00
SUBTYPE_NULL = 0x04
SUBTYPE_QOS_DATA = 0x08

# FC bit positions (in FC[1])
FC1_TODS = 0x01
FC1_FROMDS = 0x02
FC1_PROTECTED = 0x08

# Address indices in the MAC header
_ADDR1 = slice(4, 10)
_ADDR2 = slice(10, 16)
_ADDR3 = slice(16, 22)

# Minimum header sizes
_HDR_LEN = 24
_HDR_LEN_QOS = 26


def _fc(subtype: int, fc_type: int = FC_TYPE_MGMT, *, to_ds: bool = False,
        from_ds: bool = False, protected: bool = False) -> bytes:
    """Build the 2-byte Frame Control field."""
    fc0 = (subtype << 4) | (fc_type << 2)
    fc1 = 0
    if to_ds:
        fc1 |= FC1_TODS
    if from_ds:
        fc1 |= FC1_FROMDS
    if protected:
        fc1 |= FC1_PROTECTED
    return bytes([fc0, fc1])


def _header(fc_bytes: bytes, addr1: bytes, addr2: bytes, addr3: bytes,
            seq: int = 0) -> bytes:
    """Build a 24-byte 802.11 MAC header with sequence control."""
    duration = b"\x00\x00"
    seq_ctrl = (seq & 0x0FFF) << 4
    return fc_bytes + duration + addr1 + addr2 + addr3 + struct.pack("<H", seq_ctrl)


def _fcs(frame: bytes) -> bytes:
    """Append the 4-byte FCS (CRC-32)."""
    return frame + struct.pack("<I", zlib.crc32(frame) & 0xFFFFFFFF)


# ----- Management frame builders ---------------------------------------------

def craft_auth_response(victim_mac: bytes, ap_mac: bytes, seq: int = 0) -> bytes:
    """Open System Authentication Response (algorithm=0, seq=2, status=0)."""
    fc = _fc(SUBTYPE_AUTH)
    body = struct.pack("<HHH", 0, 2, 0)  # algo=Open, seq=2, status=Success
    return _fcs(_header(fc, victim_mac, ap_mac, ap_mac, seq) + body)


def craft_assoc_response(victim_mac: bytes, ap_mac: bytes, aid: int = 1,
                         seq: int = 0) -> bytes:
    """Association Response (status=0, AID assigned, basic rate set)."""
    fc = _fc(SUBTYPE_ASSOC_RESP)
    # Capability: ESS + Short Preamble
    cap = struct.pack("<H", 0x0431)
    status = struct.pack("<H", 0)  # success
    aid_field = struct.pack("<H", (aid & 0x3FFF) | 0xC000)
    # Supported rates: 1, 2, 5.5, 11, 6, 9, 12, 18, 24, 36, 48, 54 Mbps
    rates = bytes([0x82, 0x84, 0x8B, 0x96, 0x0C, 0x12, 0x18, 0x24, 0x30, 0x48, 0x60, 0x6C])
    rate_ie = bytes([0x01, len(rates)]) + rates
    body = cap + status + aid_field + rate_ie
    return _fcs(_header(fc, victim_mac, ap_mac, ap_mac, seq) + body)


def craft_deauth(victim_mac: bytes, ap_mac: bytes, reason: int = 4,
                 seq: int = 0) -> bytes:
    """Deauthentication frame."""
    fc = _fc(SUBTYPE_DEAUTH)
    body = struct.pack("<H", reason)
    return _fcs(_header(fc, victim_mac, ap_mac, ap_mac, seq) + body)


def craft_disassoc(victim_mac: bytes, ap_mac: bytes, reason: int = 4,
                   seq: int = 0) -> bytes:
    """Disassociation frame."""
    fc = _fc(SUBTYPE_DISASSOC)
    body = struct.pack("<H", reason)
    return _fcs(_header(fc, victim_mac, ap_mac, ap_mac, seq) + body)


def craft_beacon(ap_mac: bytes, ssid: str, channel: int, seq: int = 0,
                 *, bssid: bytes | None = None, cap_ess: bool = True,
                 cap_privacy: bool = False) -> bytes:
    """Beacon frame with SSID, supported rates, DS parameter set, and HT capabilities."""
    fc = _fc(SUBTYPE_BEACON)
    beacon_bssid = bssid or ap_mac

    # Fixed parameters: Timestamp(8) + Beacon Interval(2) + Capability(2)
    ts = struct.pack("<Q", int(time.time() * 1_000_000))
    interval = struct.pack("<H", 100)  # 100 TU = 102.4 ms
    cap = 0x0001 if cap_ess else 0x0000
    if cap_privacy:
        cap |= 0x0010
    cap_bytes = struct.pack("<H", cap)

    # Information Elements
    ies = _ssid_ie(ssid) + _rates_ie(channel) + _ds_param_ie(channel) + _ht_caps_ie()

    body = ts + interval + cap_bytes + ies
    return _fcs(_header(fc, b"\xff" * 6, ap_mac, beacon_bssid, seq) + body)


def craft_probe_response(ap_mac: bytes, ssid: str, channel: int,
                         dest_mac: bytes, seq: int = 0) -> bytes:
    """Probe Response (same body as beacon, addressed to the requester)."""
    fc = _fc(SUBTYPE_PROBE_RESP)
    ts = struct.pack("<Q", int(time.time() * 1_000_000))
    interval = struct.pack("<H", 100)
    cap = struct.pack("<H", 0x0001)
    ies = _ssid_ie(ssid) + _rates_ie(channel) + _ds_param_ie(channel) + _ht_caps_ie()
    body = ts + interval + cap + ies
    return _fcs(_header(fc, dest_mac, ap_mac, ap_mac, seq) + body)


# ----- Data frame builders ---------------------------------------------------

def wrap_ip_in_data(client_mac: bytes, ap_mac: bytes, ip_packet: bytes,
                    seq: int = 0) -> bytes:
    """Wrap an IP packet in an 802.11 Data frame (ToDS=1, FromDS=0).
    Includes LLC/SNAP header for IPv4."""
    fc = _fc(SUBTYPE_DATA, FC_TYPE_DATA, to_ds=True)
    llc_snap = b"\xAA\xAA\x03\x00\x00\x00\x08\x00"
    payload = llc_snap + ip_packet
    return _fcs(_header(fc, ap_mac, client_mac, ap_mac, seq) + payload)


# ----- IE builders -----------------------------------------------------------

def _ssid_ie(ssid: str) -> bytes:
    s = ssid.encode("utf-8", "ignore")[:32]
    return bytes([0x00, len(s)]) + s


def _rates_ie(channel: int) -> bytes:
    if channel > 14:
        rates = bytes([0x8C, 0x12, 0x98, 0x24, 0xB0, 0x48, 0x60, 0x6C])
    else:
        rates = bytes([0x82, 0x84, 0x8B, 0x96, 0x0C, 0x12, 0x18, 0x24])
    return bytes([0x01, len(rates)]) + rates


def _ds_param_ie(channel: int) -> bytes:
    return bytes([0x03, 0x01, channel & 0xFF])


def _ht_caps_ie() -> bytes:
    """Minimal HT Capabilities IE (no actual HT, just to be present)."""
    ht = bytes([
        0x19, 0x00,  # HT capability info (LDPC=0, SM Pwr Save=3, HT-GF=0)
        0x17,        # A-MPDU params (max length = 65535)
        0x00, 0x00, 0x00, 0x00,  # Supported MCS set (first 4 bytes)
        0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00,
        0x00, 0x00,
    ])
    return bytes([0x2D, len(ht)]) + ht


# ----- Frame parsing ---------------------------------------------------------

def parse_fc(raw: bytes) -> tuple[int, int, bool, bool]:
    """Parse Frame Control. Returns (type, subtype, to_ds, from_ds)."""
    if len(raw) < 2:
        return -1, -1, False, False
    fc0, fc1 = raw[0], raw[1]
    fc_type = (fc0 >> 2) & 0x03
    subtype = (fc0 >> 4) & 0x0F
    to_ds = bool(fc1 & FC1_TODS)
    from_ds = bool(fc1 & FC1_FROMDS)
    return fc_type, subtype, to_ds, from_ds


def parse_addrs_mgmt(raw: bytes) -> tuple[bytes, bytes, bytes]:
    """Parse DA, SA, BSSID from a management frame."""
    return raw[_ADDR1], raw[_ADDR2], raw[_ADDR3]


def parse_addrs_data(raw: bytes, to_ds: bool, from_ds: bool) -> tuple[bytes, bytes, bytes]:
    """Parse (ra, ta, bssid) from a data frame."""
    if to_ds and not from_ds:
        return raw[_ADDR1], raw[_ADDR2], raw[_ADDR3]
    if from_ds and not to_ds:
        return raw[_ADDR2], raw[_ADDR1], raw[_ADDR3]
    raise ValueError("4-address frames not supported")


def extract_ssid_from_probe(raw: bytes) -> str | None:
    """Extract SSID from a Probe Request body (after 24-byte header)."""
    body = raw[24:]
    i = 0
    while i + 1 < len(body):
        eid = body[i]
        elen = body[i + 1]
        if eid == 0:  # SSID
            return body[i + 2: i + 2 + elen].decode("utf-8", errors="replace")
        i += 2 + elen
    return None


def strip_data_payload(raw: bytes) -> tuple[bytes, bytes] | None:
    """Strip 802.11 header + LLC/SNAP from a received data frame.
    Returns (src_mac, ip_packet) or None."""
    fc_type, subtype, to_ds, from_ds = parse_fc(raw)
    if fc_type != FC_TYPE_DATA:
        return None
    if to_ds:
        src_mac = raw[_ADDR2]  # SA = client
    elif from_ds:
        src_mac = raw[_ADDR1]  # SA = client (from AP perspective)
    else:
        return None

    # Find LLC/SNAP or QoS header
    hdr_len = _HDR_LEN
    if subtype >= SUBTYPE_QOS_DATA:
        hdr_len = _HDR_LEN_QOS

    payload = raw[hdr_len:]
    # Strip LLC/SNAP (8 bytes: AA AA 03 00 00 00 08 00 for IPv4)
    if len(payload) > 8 and payload[:6] == b"\xAA\xAA\x03\x00\x00\x00":
        ethertype = struct.unpack(">H", payload[6:8])[0]
        if ethertype == 0x0800:  # IPv4
            return src_mac, payload[8:]
    return None
