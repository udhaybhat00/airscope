import re
from types import SimpleNamespace

from airscope.chips.driver import FakeMacSupport
from airscope.ui.screens.focus_v2.eviltwin_modal import _plus_one, _random_bssid, _can_host, _option, _default_bssid_for

_MAC = re.compile(r"^([0-9a-f]{2}:){5}[0-9a-f]{2}$")


def _iface(name="card", fake=FakeMacSupport.SPOOFABLE, ap_mode=True,
           chans=(1, 6, 11), mac="aa:bb:cc:dd:ee:ff"):
    return SimpleNamespace(name=name, mac_address=mac, supports_ap_mode=ap_mode,
                           supported_channels=list(chans),
                           driver=SimpleNamespace(FAKE_MAC=fake, AP_MODE=ap_mode))


def test_host_gate_requires_software_ap_and_ackable_mac():
    assert _can_host(_iface())                                    # spoofable + AP_MODE
    assert _can_host(_iface(fake=FakeMacSupport.FIXED_MAC, mac="aa:bb:cc:dd:ee:ff"))
    assert not _can_host(_iface(ap_mode=False))                   # no software AP
    assert not _can_host(_iface(fake=FakeMacSupport.NONE))
    assert not _can_host(_iface(fake=FakeMacSupport.UNIMPLEMENTED))


def test_default_bssid_spoofs_target_on_spoofable_card():
    target = SimpleNamespace(bssid="94:83:c4:8c:3f:78")
    assert _default_bssid_for(_iface(), target) == "94:83:c4:8c:3f:78"


def test_default_bssid_uses_hard_mac_for_fixed_mac_host():
    target = SimpleNamespace(bssid="94:83:c4:8c:3f:78")
    host = _iface(fake=FakeMacSupport.FIXED_MAC, mac="aa:bb:cc:dd:ee:ff")
    assert _default_bssid_for(host, target) == "aa:bb:cc:dd:ee:ff"


def test_default_bssid_falls_back_to_target_without_host():
    target = SimpleNamespace(bssid="94:83:c4:8c:3f:78")
    assert _default_bssid_for(None, target) == "94:83:c4:8c:3f:78"


def test_option_appends_bands():
    row = _option(_iface(chans=(1, 6, 11)))
    assert row == "card  (2.4 GHz)"
    row5 = _option(_iface(chans=(36, 40, 149)))
    assert "5 GHz" in row5
    assert _option(_iface(chans=())) == "card"


def test_plus_one_bumps_last_nibble():
    assert _plus_one("94:83:c4:8c:3f:78") == "94:83:c4:8c:3f:79"
    assert _plus_one("94:83:c4:8c:3f:7f") == "94:83:c4:8c:3f:70"   # wraps f -> 0


def test_random_bssid_is_locally_administered():
    b = _random_bssid()
    assert _MAC.match(b) and b.startswith("02:")