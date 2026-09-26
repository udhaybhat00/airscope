"""The macOS platform gate: on darwin native only the EvilTwin fake-AP
portal is blocked; every other attack keeps its normal campaign gating.
Platform-independent: each test forces sys.platform so results are identical
on Linux CI and a macOS dev box."""
import types

import pytest

from airscope.campaigns.campaign import Campaign
from airscope.campaigns.eviltwin import EvilTwinCampaign
from airscope.ui import focus_model as fm


@pytest.fixture(autouse=True)
def _reset_active():
    Campaign.active = None
    yield
    Campaign.active = None


@pytest.fixture
def macos_native(monkeypatch):
    monkeypatch.setattr(fm.sys, "platform", "darwin")
    monkeypatch.delenv("AIRSCOPE_IN_VM", raising=False)


@pytest.fixture
def linux(monkeypatch):
    monkeypatch.setattr(fm.sys, "platform", "linux")


@pytest.fixture
def macos_vm(monkeypatch):
    monkeypatch.setattr(fm.sys, "platform", "darwin")
    monkeypatch.setenv("AIRSCOPE_IN_VM", "1")


def _ap(**kw):
    """Eligible WPA2-PSK AP (ineligible_reason is None for the common campaigns)."""
    base = dict(encryption="WPA2", akms=["PSK"], akm_suites=[2],
                pairwise_cipher="CCMP", ssid="EvilNet", is_hidden=False,
                last_beacon_frame=b"\x80\x00beacon", wpa3=False,
                transition_mode=False, wep=None, pmf_required=False,
                pmf_capable=False, bssid="aa:bb:cc:dd:ee:ff", wps=False,
                wps_locked=False, wps_version="1.0")
    base.update(kw)
    return types.SimpleNamespace(**base)


@pytest.mark.parametrize("cls", fm.BUTTON_CAMPAIGNS)
def test_macos_native_gates_only_eviltwin(cls, macos_native):
    reason = fm.platform_block_reason(cls.key)
    if cls is EvilTwinCampaign:
        assert reason == "Fake-AP phishing page requires Linux"
    else:
        assert reason is None


@pytest.mark.parametrize("plat", ["linux", "win32"])
@pytest.mark.parametrize("cls", fm.BUTTON_CAMPAIGNS)
def test_other_platforms_gate_nothing(plat, cls, monkeypatch):
    monkeypatch.setattr(fm.sys, "platform", plat)
    assert fm.platform_block_reason(cls.key) is None


@pytest.mark.parametrize("cls", fm.BUTTON_CAMPAIGNS)
def test_vm_environment_gates_nothing(cls, macos_vm):
    assert fm.platform_block_reason(cls.key) is None


def test_campaign_blocked_on_macos_is_pristine(macos_native):
    """On macOS every non-EvilTwin campaign sees exactly its own campaign
    gating (no hidden TX reason); EvilTwin sees the platform reason."""
    ap = _ap()
    for cls in fm.BUTTON_CAMPAIGNS:
        reason = fm.campaign_blocked(cls, ap)
        if cls is EvilTwinCampaign:
            assert reason == "Fake-AP phishing page requires Linux"
        else:
            assert reason == cls.ineligible_reason(ap)


def test_campaign_blocked_linux_has_no_platform_reason(linux):
    ap = _ap()
    for cls in fm.BUTTON_CAMPAIGNS:
        if cls.ineligible_reason(ap) is None:
            assert fm.campaign_blocked(cls, ap) is None
