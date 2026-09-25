"""EvilTwinCampaign (reimplemented): Step 1 captures a real crackable handshake first, Step 2 runs
the WPA2-only twin + rapid deauth on the target's channel, Step 3 recovers the PSK online by
MIC-checking the twin's M2 against a candidate feed (rockyou + vault seeds), saving it as an
EVILTWIN_PSK without any external cracker."""
import asyncio
import struct
from types import SimpleNamespace

import pytest

import airscope.campaigns.eviltwin.campaign as camp_mod
from airscope.campaigns import eviltwin as etwin
from airscope.campaigns.eviltwin import (
    EvilTwinCampaign, EvilTwinInput,
)
from airscope.campaigns.eviltwin.campaign import _CandidateFeed
from airscope.crack.external import iter_candidates
from airscope.crack.wpa_psk import mic_for
from airscope.dot11.ap import eapol_m1
from airscope.dot11.eapol import data_header, eapol_key, LLC_SNAP_EAPOL
from airscope.dot11.ie import ssid_ie, rates_ie, ds_param_ie, GENERIC_RSN_IE
from airscope.dot11.parser import WlanFrameParser
from airscope.dot11.packet import BeaconPacket
from airscope.wlan.sink import WlanSink

_BSSID = "94:83:c4:8c:3f:78"
_BSSID_B = bytes.fromhex("9483c48c3f78")
_TWIN = "02:00:00:00:00:01"
_TWIN_B = bytes.fromhex("020000000001")
_CLIENT = "aa:bb:cc:dd:ee:01"
_CLIENT_B = bytes.fromhex("aabbccddee01")
_SNONCE = bytes.fromhex("0f" * 32)
_ANONCE = bytes.fromhex("e7" * 32)
_BROADCAST = b"\xff" * 6
_SSID = "GL-Test"
_PASSWORD = "correct horse"
_FIXED = struct.pack("<Q", 0) + struct.pack("<H", 100) + b"\x11\x04"
_BEACON = (b"\x80\x00\x00\x00" + _BROADCAST + _BSSID_B + _BSSID_B + b"\x00\x00"
           + _FIXED + ssid_ie(_SSID) + rates_ie() + ds_param_ie(11) + GENERIC_RSN_IE)
_TWIN_BEACON = _BEACON[:10] + _TWIN_B + _TWIN_B + _BEACON[22:]


class _FakeDriver:
    async def check_tx_capability(self) -> tuple[bool, str]:
        return True, "TX OK (mock)"


class _FakeIface:
    def __init__(self):
        self.sent: list[bytes] = []
        self.current_channel = 11
        self.fake_mac_arms = 0
        self.fake_mac_clears = 0
        self.deauths: list[tuple] = []
        self.broadcasts = 0
        self.driver = _FakeDriver()

    async def send_no_wait(self, frame: bytes) -> bool:
        self.sent.append(bytes(frame))
        return True

    async def set_channel(self, channel, scan=False) -> bool:
        self.current_channel = channel
        return True

    async def set_fake_mac(self, mac, bssid=None):
        self.fake_mac_arms += 1
        return ":".join(f"{b:02x}" for b in mac)

    async def clear_fake_mac(self) -> None:
        self.fake_mac_clears += 1

    def register_rx_callback(self, cb) -> None:
        pass

    def unregister_rx_callback(self, cb) -> None:
        pass

    async def deauth_client(self, bssid: str, mac, rounds: int) -> None:
        self.deauths.append((bssid, mac, rounds))

    async def deauth_broadcast(self, bssid: str, count: int) -> None:
        self.broadcasts += 1


class _FakeArray:
    def __init__(self):
        self.sink = WlanSink()
        self._stray = {}
        self._twins = set()

    @property
    def access_points(self):
        return self.sink.access_points

    @property
    def clients(self):
        return self.sink.clients

    def record_injected_eapol(self, frame) -> None:
        self.sink.record_injected_eapol(frame)

    def note_own_beacon(self, bssid, channel, beacon) -> None:
        if bssid in self.access_points:
            return
        pkt = WlanFrameParser.parse_80211_frame(beacon, 0)
        if isinstance(pkt, BeaconPacket):
            self.sink.update(pkt, "seed", channel)

    def ignore_stray_beacons(self, bssid, channel) -> None:
        self._stray[bssid] = channel

    def stop_ignoring_stray_beacons(self, bssid) -> None:
        self._stray.pop(bssid, None)

    def mark_evil_twin(self, bssid) -> None:
        self._twins.add(bssid)

    def unmark_evil_twin(self, bssid) -> None:
        self._twins.discard(bssid)


def _target():
    return SimpleNamespace(bssid=_BSSID, ssid=_SSID, channel=11,
                           last_beacon_frame=_BEACON, akm_suites=[2])


def _input(twin, punt, bssid=_BSSID):
    return EvilTwinInput(twin_iface=twin, punt_iface=punt, twin_channel=999,
                         twin_bssid=bssid)


def _seed_single_handshake(array, ap_bssid: str, anonce=_ANONCE, snonce=_SNONCE):
    """A crackable M1+M2 pair under ``ap_bssid`` via the real sink, plus the AP entry."""
    bssid_b = bytes.fromhex(ap_bssid.replace(":", ""))
    beacon = _BEACON if ap_bssid == _BSSID else _TWIN_BEACON
    if ap_bssid not in array.access_points:
        array.note_own_beacon(ap_bssid, 11, beacon)
    array.record_injected_eapol(eapol_m1(bssid_b, _CLIENT_B, anonce, replay=1))
    client_mic = mic_for(_PASSWORD, _SSID, bssid_b, _CLIENT_B, anonce, snonce,
                         eapol_key(key_info=0x010A, key_len=0, replay=1, nonce=snonce,
                                   key_data=GENERIC_RSN_IE, mic=bytes(16)))
    m2 = data_header(to_ds=True, bssid=bssid_b, client=_CLIENT_B) + LLC_SNAP_EAPOL + eapol_key(
        key_info=0x010A, key_len=0, replay=1, nonce=snonce, key_data=GENERIC_RSN_IE,
        mic=client_mic)
    array.sink.update(WlanFrameParser.parse_80211_frame(m2, -40), "seed", 11)


# ----- step 1: a real handshake first ---------------------------------------

def test_visible_requires_psk_akm():
    assert EvilTwinCampaign.visible(_target()) is True
    assert EvilTwinCampaign.visible(SimpleNamespace(ssid="x", akm_suites=[])) is False
    assert EvilTwinCampaign.visible(SimpleNamespace(ssid=None, akm_suites=[2])) is False
    sae = SimpleNamespace(ssid="WPA3", akm_suites=[8])
    assert EvilTwinCampaign.visible(sae) is False                # pure WPA3/SAE: no PSK handshake
    trans = SimpleNamespace(ssid="Mixed", akm_suites=[2, 8])
    assert EvilTwinCampaign.visible(trans) is True               # WPA3-transition keeps PSK


def test_ineligible_reason():
    no_beacon = SimpleNamespace(bssid=_BSSID, ssid=_SSID, channel=11,
                                last_beacon_frame=None, akm_suites=[2])
    assert EvilTwinCampaign.ineligible_reason(no_beacon) == "no beacon captured yet"
    assert EvilTwinCampaign.ineligible_reason(_target()) is None


def test_default_punt_modes_are_empty_now():
    assert etwin.default_punt_modes(SimpleNamespace(pmf_required=True)) == ()
    assert etwin.default_punt_modes(SimpleNamespace(pmf_required=False)) == ()


def test_csa_target_channel_still_valid():
    assert etwin.csa_target_channel(1) == 6
    assert etwin.csa_target_channel(11) == 1
    assert etwin.csa_target_channel(36) == 40
    assert etwin.csa_target_channel(11, 1) == 1
    assert etwin.csa_target_channel(11, 11) == 1


def test_twin_mirrors_target_channel_and_rewrites_bssid():
    array, twin, punt = _FakeArray(), _FakeIface(), _FakeIface()
    camp = EvilTwinCampaign(array, _target(), _input(twin, punt, bssid=_TWIN))
    assert camp.twin_channel == 11                      # input said 999: Step 2 pins the target's
    assert camp.same_bssid is False
    assert camp.twin_bssid == _TWIN
    assert camp.twin_beacon[10:16] == _TWIN_B and camp.twin_beacon[16:22] == _TWIN_B


def test_same_bssid_twin_impersonates_and_keeps_beacon():
    array, twin, punt = _FakeArray(), _FakeIface(), _FakeIface()
    camp = EvilTwinCampaign(array, _target(), _input(twin, punt, bssid=_BSSID))
    assert camp.same_bssid is True
    assert camp.twin_beacon[10:16] == _BSSID_B          # no BSSID rewrite: it is the target's


def test_constructor_requires_beacon_and_ssid():
    array = _FakeArray()
    ap = SimpleNamespace(bssid=_BSSID, ssid=_SSID, channel=11,
                         last_beacon_frame=None, akm_suites=[2])
    with pytest.raises(ValueError):
        EvilTwinCampaign(array, ap, _input(_FakeIface(), _FakeIface(), _BSSID))
    ap = SimpleNamespace(bssid=_BSSID, ssid=None, channel=11,
                         last_beacon_frame=_BEACON, akm_suites=[2])
    with pytest.raises(ValueError):
        EvilTwinCampaign(array, ap, _input(_FakeIface(), _FakeIface(), _BSSID))


def test_first_capture_is_mandatory_before_twin(monkeypatch):
    """Step 1 deauths the target until a crackable real handshake lands; the twin stays unarmed."""
    monkeypatch.setattr(camp_mod, "_REFERENCE_TIMEOUT_SEC", 0.05)
    array, twin, punt = _FakeArray(), _FakeIface(), _FakeIface()
    camp = EvilTwinCampaign(array, _target(), _input(twin, punt, bssid=_TWIN))
    assert asyncio.run(camp._capture_reference()) is False   # timed out, nothing crackable
    assert punt.broadcasts > 0                              # Step 1 is the deauth kick
    assert twin.fake_mac_arms == 0                          # twin not armed yet


def test_step1_ends_immediately_with_existing_real_handshake():
    array, twin, punt = _FakeArray(), _FakeIface(), _FakeIface()
    _seed_single_handshake(array, _BSSID)
    camp = EvilTwinCampaign(array, _target(), _input(twin, punt, bssid=_TWIN))
    assert camp._crackable_instances(_BSSID)            # the real AP already holds M1+M2
    assert asyncio.run(camp._capture_reference()) is True
    assert punt.broadcasts == 0                         # nothing to deauth: step 1 already won


def test_loop_aborts_before_twin_when_reference_proves_impossible(monkeypatch):
    monkeypatch.setattr(camp_mod, "_REFERENCE_TIMEOUT_SEC", 0.05)
    array, twin, punt = _FakeArray(), _FakeIface(), _FakeIface()
    camp = EvilTwinCampaign(array, _target(), _input(twin, punt, bssid=_TWIN))
    assert asyncio.run(camp._loop()) is None
    assert twin.fake_mac_arms == 0                      # Step 1 gate stopped everything


# ----- step 2: twin + rapid deauth ------------------------------------------

async def test_rapid_deauth_cadence(monkeypatch):
    monkeypatch.setattr(camp_mod, "_DEAUTH_PERIOD_SEC", 0.02)
    array, twin, punt = _FakeArray(), _FakeIface(), _FakeIface()
    array.clients[_CLIENT] = SimpleNamespace(mac=_CLIENT, bssid=_BSSID)
    camp = EvilTwinCampaign(array, _target(), _input(twin, punt, bssid=_TWIN))
    task = camp._deauth_loop()
    for _ in range(300):
        await asyncio.sleep(0.01)
        if punt.broadcasts >= 3 and punt.deauths:
            break
    task.cancel()
    assert punt.broadcasts >= 3                         # a disqual round every _DEAUTH_PERIOD_S
    assert punt.deauths                                 # client-targeted deauths too


async def test_step2_arms_twin_seeds_entry_and_hides_twin():
    array, twin, punt = _FakeArray(), _FakeIface(), _FakeIface()
    camp = EvilTwinCampaign(array, _target(), _input(twin, punt, bssid=_TWIN))
    await camp._step2_run_twin()
    assert twin.fake_mac_arms == 1
    assert _TWIN in array._twins                        # hidden from the scanner
    assert _TWIN in array.access_points                 # an AI entry so M2s pair with our M1
    await camp.fakeap.stop()


# ----- step 3: online MIC recovery -------------------------------------------

def _fed(*passwords) -> _CandidateFeed:
    return _CandidateFeed(iter_candidates(None, list(passwords)))


async def test_online_mic_match_recovers_and_saves_eviltwin_psk(monkeypatch):
    saved = []
    monkeypatch.setattr(camp_mod, "save_eviltwin_psk",
                        lambda ap, psk: saved.append((ap.bssid, ap.ssid, psk))
                        or SimpleNamespace(what_captured="EvilTwin PSK"))
    array, twin, punt = _FakeArray(), _FakeIface(), _FakeIface()
    _seed_single_handshake(array, _TWIN)
    camp = EvilTwinCampaign(array, _target(), _input(twin, punt, bssid=_TWIN))
    camp._candidates = _fed("wrong1", "wrong2", _PASSWORD)
    recovered = []
    camp.on_recovered = recovered.append
    await asyncio.wait_for(camp._step3_recover(), timeout=2)
    assert camp.password == _PASSWORD and camp.captured
    assert saved == [(_BSSID, _SSID, _PASSWORD)]        # PRK lands as EVILTWIN_PSK
    assert recovered == [_PASSWORD]                     # the UI toast callback fired
    assert camp._checked_m2 == 1
    assert any(_is_m3(f) for f in twin.sent)            # the 4-way closed with a real M3


def test_online_miss_disconnects_and_reports_exhausted():
    array, twin, punt = _FakeArray(), _FakeIface(), _FakeIface()
    _seed_single_handshake(array, _TWIN)
    camp = EvilTwinCampaign(array, _target(), _input(twin, punt, bssid=_TWIN))
    camp._candidates = _fed("nope1", "nope2")
    assert asyncio.run(camp._step3_recover()) is None
    assert camp.password is None
    assert twin.sent                                  # a disassociate went to the client
    assert camp._candidates.done                       # the single pass is spent (not retried)


async def test_loop_runs_then_tears_down_cleanly():
    array, twin, punt = _FakeArray(), _FakeIface(), _FakeIface()
    _seed_single_handshake(array, _BSSID)              # step 1 wins instantly
    camp = EvilTwinCampaign(array, _target(), _input(twin, punt, bssid=_TWIN))
    task = asyncio.create_task(camp._loop())
    for _ in range(300):
        await asyncio.sleep(0.01)
        if twin.fake_mac_arms and (punt.broadcasts >= 1 or punt.deauths):
            break
    assert twin.fake_mac_arms == 1                     # twin stood up
    assert punt.broadcasts >= 1 or punt.deauths        # deauth loop running
    camp.stopped = True
    await asyncio.wait_for(task, timeout=2)
    await camp.teardown()
    assert twin.fake_mac_clears == 1                   # FakeAP.stop() ran
    assert _TWIN not in array._twins                   # twin un-hidden on teardown


# ----- helpers -----------------------------------------------------------------

def _is_m3(frame: bytes) -> bool:
    pkt = WlanFrameParser.parse_80211_frame(frame, 0)
    return getattr(pkt, "type", None) == "eapol" and getattr(pkt, "msg_num", None) == 3