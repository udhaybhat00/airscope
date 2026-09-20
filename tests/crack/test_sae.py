"""SAE auth frame decoding (crack.sae): fixed-header parsing only."""
import struct

from airscope.crack.sae import SEQ_COMMIT, SEQ_CONFIRM, parse_sae_auth

BSSID = "aa:bb:cc:dd:ee:ff"
STA = "11:22:33:44:55:66"


def _frame(dest, src, algo=3, seq=1, status=0, body_len=64):
    f = (bytes([0xB0, 0x00]) + b"\x00\x00"
         + bytes.fromhex(dest.replace(":", "")) + bytes.fromhex(src.replace(":", ""))
         + bytes.fromhex(BSSID.replace(":", "")) + b"\x00\x00")
    f += struct.pack("<HHH", algo, seq, status) + bytes(body_len)
    return f


def test_commit_decodes():
    sae = parse_sae_auth(_frame(BSSID, STA, seq=SEQ_COMMIT))
    assert sae is not None
    assert (sae.seq, sae.status, sae.source, sae.bssid) == (1, 0, STA, BSSID)


def test_confirm_decodes():
    sae = parse_sae_auth(_frame(STA, BSSID, seq=SEQ_CONFIRM))
    assert sae is not None and sae.seq == 2


def test_open_auth_rejected():
    assert parse_sae_auth(_frame(BSSID, STA, algo=0)) is None


def test_non_auth_subtype_rejected():
    f = bytearray(_frame(BSSID, STA))
    f[0] = 0x80  # beacon
    assert parse_sae_auth(bytes(f)) is None


def test_truncated_rejected():
    assert parse_sae_auth(b"\xb0\x00" + b"\x00" * 10) is None
