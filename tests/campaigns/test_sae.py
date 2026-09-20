"""SAE campaign: gating, commit/confirm pairing, and the pcap save path."""
import struct
from types import SimpleNamespace

import pytest

from airscope.campaigns.sae import SaeCampaign
from airscope.models import AccessPoint
from airscope.persist import save as persist_save

BSSID = "aa:bb:cc:dd:ee:ff"
STA = "11:22:33:44:55:66"


def _raw(dest, src, algo=3, seq=1, status=0):
    f = (bytes([0xB0, 0x00]) + b"\x00\x00"
         + bytes.fromhex(dest.replace(":", "")) + bytes.fromhex(src.replace(":", ""))
         + bytes.fromhex(BSSID.replace(":", "")) + b"\x00\x00")
    return f + struct.pack("<HHH", algo, seq, status) + bytes(64)


def _pkt(dest, src, **kw):
    raw = _raw(dest, src, **kw)
    other = src if src != BSSID else dest
    return SimpleNamespace(type="mgmt_11", bssid=BSSID, client_mac=other, raw=raw)


def _ap(**kw):
    d = dict(bssid=BSSID, ssid="WPA3Net", channel=6, akm_suites=[8])
    d.update(kw)
    return AccessPoint(**{k: v for k, v in d.items()
                          if k in AccessPoint.__dataclass_fields__})


def test_visible_pure_sae_only():
    assert SaeCampaign.visible(_ap()) is True
    assert SaeCampaign.visible(_ap(akm_suites=[8, 2])) is False      # transition: EvilTwin
    assert SaeCampaign.visible(_ap(akm_suites=[2])) is False         # plain PSK
    assert SaeCampaign.visible(_ap(akm_suites=[])) is False          # unconfirmed


def test_ineligible_reasons():
    assert SaeCampaign.ineligible_reason(_ap()) is None
    assert SaeCampaign.ineligible_reason(_ap(ssid=None)) == \
        "hidden SSID: SAE material needs a known ESSID"
    assert SaeCampaign.ineligible_reason(_ap(akm_suites=[2])) == "no SAE AKM confirmed yet"
    assert SaeCampaign.ineligible_reason(_ap(akm_suites=[8, 2])) == \
        "transition mode: use the EvilTwin downgrade"


def test_pairs_commit_and_confirm_per_station():
    camp = SaeCampaign(None, _ap(), log=lambda _m: None)
    camp._on_rx(_pkt(BSSID, STA, seq=1))
    assert camp.pairs == []
    camp._on_rx(_pkt(STA, BSSID, seq=2))
    assert len(camp.pairs) == 1
    assert camp.pairs[0].sta == STA
    assert len(camp.frames_for_pcap()) == 2


def test_ignores_non_sae_and_wrong_bssid():
    camp = SaeCampaign(None, _ap(), log=lambda _m: None)
    camp._on_rx(_pkt(BSSID, STA, algo=0, seq=1))                     # open auth
    other = SimpleNamespace(type="mgmt_11", bssid="00:11:22:33:44:55",
                            client_mac=STA, raw=_raw(BSSID, STA, seq=1))
    camp._on_rx(other)                                              # other AP
    assert camp.pairs == [] and camp.frames_for_pcap() == []


def test_rejected_confirm_not_paired():
    camp = SaeCampaign(None, _ap(), log=lambda _m: None)
    camp._on_rx(_pkt(BSSID, STA, seq=1))
    camp._on_rx(_pkt(STA, BSSID, seq=2, status=1))                   # rejected
    assert camp.pairs == []


class _Iface:
    def __init__(self):
        self.cb = None

    def register_rx_callback(self, cb):
        self.cb = cb

    def unregister_rx_callback(self, cb):
        assert self.cb == cb
        self.cb = None


class _Lease:
    def __init__(self, iface):
        self.iface = iface

    async def __aenter__(self):
        return self.iface

    async def __aexit__(self, *a):
        return False


class _Array:
    def __init__(self, iface):
        self.iface = iface

    def select_iface(self, channel):
        return self.iface

    def lease(self, channel=None, iface=None, **kw):
        return _Lease(iface or self.iface)


@pytest.mark.asyncio
async def test_loop_ends_after_first_pair():
    iface, array = _Iface(), None
    array = _Array(iface)
    camp = SaeCampaign(array, _ap(), log=lambda _m: None)
    assert camp.run() is True
    for _ in range(100):
        if iface.cb is None:
            import asyncio
            await asyncio.sleep(0.01)
            continue
        break
    assert iface.cb is not None
    iface.cb(_pkt(BSSID, STA, seq=1))
    iface.cb(_pkt(STA, BSSID, seq=2))
    await camp.stop()
    assert len(camp.pairs) == 1
    assert iface.cb is None                                  # unregistered in teardown


@pytest.mark.asyncio
async def test_save_round_trip(tmp_path):
    camp = SaeCampaign(None, _ap(), log=lambda _m: None)
    camp._on_rx(_pkt(BSSID, STA, seq=1))
    camp._on_rx(_pkt(STA, BSSID, seq=2))
    ap = _ap()
    result = persist_save.save_sae(ap, camp.frames_for_pcap())
    assert result is not None and result.was_new is True
    assert result.path.name.endswith("_sae.pcap")
    assert persist_save.save_sae(ap, []) is None
