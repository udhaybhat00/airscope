"""Batch planner + runner (campaigns.batch) with fakes: no radio, no UI."""
import pytest

from airscope.campaigns.batch import BatchRunner, BatchStep, build_plan
from airscope.models import AccessPoint


def _ap(bssid, ssid="Net", signal=-60, **kw):
    ap = AccessPoint(bssid=bssid, ssid=ssid, **kw)
    ap.signal_by_card = {"card0": signal}
    return ap


def _vault(psk=(), pmkid=(), hs=(), wps=(), sae=()):
    from types import SimpleNamespace
    return SimpleNamespace(
        has_psk=lambda ap: ap.bssid in psk,
        has_pmkid=lambda ap: ap.bssid in pmkid,
        has_handshake=lambda ap: ap.bssid in hs,
        has_wps_psk=lambda ap: ap.bssid in wps,
        has_sae=lambda ap: ap.bssid in sae,
        save_wps_pin=lambda ap, pin, psk_: (_ for _ in ()).throw(AssertionError("no save expected")),
        save_pmkid=lambda ap, mac: (_ for _ in ()).throw(AssertionError("no save expected")),
        save_handshake=lambda ap, mac: (_ for _ in ()).throw(AssertionError("no save expected")),
    )


def test_solved_skipped():
    ap = _ap("aa:bb:cc:dd:ee:01", wps=True)
    steps, skipped = build_plan([ap], _vault(psk={"aa:bb:cc:dd:ee:01"}))
    assert steps == []
    assert [(x.kind, x.outcome) for x in skipped] == [("solved", "skipped")]


def test_chain_order_is_wps_pmkid_handshake():
    ap = _ap("aa:bb:cc:dd:ee:01", wps=True, akm_suites=[2])
    steps, skipped = build_plan([ap], _vault())
    assert [s.kind for s in steps] == ["wps", "pmkid", "handshake"]
    assert skipped == []


def test_have_pmkid_shortens_chain():
    ap = _ap("aa:bb:cc:dd:ee:01", akm_suites=[2])
    steps, _ = build_plan([ap], _vault(pmkid={"aa:bb:cc:dd:ee:01"}))
    assert [s.kind for s in steps] == ["handshake"]


def test_strongest_first():
    weak = _ap("aa:bb:cc:dd:ee:01", ssid="Weak", signal=-80, akm_suites=[2])
    strong = _ap("aa:bb:cc:dd:ee:02", ssid="Strong", signal=-40, akm_suites=[2])
    steps, _ = build_plan([weak, strong], _vault())
    assert steps[0].bssid == "aa:bb:cc:dd:ee:02"


def test_open_network_has_no_attack():
    ap = _ap("aa:bb:cc:dd:ee:01", encryption="OPEN")
    steps, skipped = build_plan([ap], _vault())
    assert steps == []
    assert skipped[0].outcome == "no-attack"


def test_uses_configured_timeouts():
    ap = _ap("aa:bb:cc:dd:ee:01", akm_suites=[2])
    steps, _ = build_plan([ap], _vault())
    assert steps[0].timeout == 120.0


def test_pure_wpa3_plans_sae_only():
    ap = _ap("aa:bb:cc:dd:ee:01", ssid="WPA3Net", akm_suites=[8])
    steps, skipped = build_plan([ap], _vault())
    assert [s.kind for s in steps] == ["sae"]
    assert skipped == []


def test_transition_excludes_sae():
    ap = _ap("aa:bb:cc:dd:ee:01", ssid="Mixed", akm_suites=[2, 8])
    steps, _ = build_plan([ap], _vault())
    kinds = [s.kind for s in steps]
    assert "sae" not in kinds
    assert "pmkid" in kinds and "handshake" in kinds


class _FakeCamp:
    key = "fake"
    done = True

    def __init__(self, array, ap, log=None):
        self.target = ap

    def run(self):
        return True

    async def stop(self):
        pass


class _FakeRunner(BatchRunner):
    def _start_campaign(self, kind, ap):
        return _FakeCamp(self.array, ap)


def _array(aps):
    from types import SimpleNamespace
    return SimpleNamespace(access_points={ap.bssid: ap for ap in aps},
                           forged_macs=set(), clients={})


@pytest.mark.asyncio
async def test_runner_skips_solved_without_starting():
    ap = _ap("aa:bb:cc:dd:ee:01", wps=True)
    runner = _FakeRunner(_array([ap]), _vault(psk={"aa:bb:cc:dd:ee:01"}),
                         timeouts={"wps": 1, "pmkid": 1, "handshake": 1})
    steps, skipped = build_plan([ap], runner.vault)
    summary = await runner.run(steps, [ap])
    assert summary.results == []
    assert skipped[0].outcome == "skipped"


@pytest.mark.asyncio
async def test_runner_timeout_when_nothing_found():
    ap = _ap("aa:bb:cc:dd:ee:01", akm_suites=[2])
    runner = _FakeRunner(_array([ap]), _vault(), timeouts={"pmkid": 0.01, "handshake": 0.01})
    steps, _ = build_plan([ap], runner.vault)
    assert [s.kind for s in steps] == ["pmkid", "handshake"]
    summary = await runner.run(steps, [ap])
    assert [r.outcome for r in summary.results] == ["timeout", "timeout"]
    assert summary.solved == 0


@pytest.mark.asyncio
async def test_runner_records_wps_solve():
    ap = _ap("aa:bb:cc:dd:ee:01", wps=True)
    saved = {}

    def _save(ap_, pin, psk):
        saved["psk"] = psk

    vault = _vault()
    vault.save_wps_pin = _save
    runner = _FakeRunner(_array([ap]), vault, timeouts={"wps": 5})

    class _Solved(_FakeCamp):
        @property
        def done(self):
            return True

    orig = runner._start_campaign

    def _start(kind, ap_):
        camp = orig(kind, ap_)
        camp.state = type("S", (), {"found_pin": "12345670", "found_psk": "secret"})()
        camp.done = True
        return camp

    runner._start_campaign = _start
    steps, _ = build_plan([ap], vault)
    assert [s.kind for s in steps] == ["wps"]
    summary = await runner.run(steps, [ap])
    assert summary.results[0].outcome == "solved"
    assert saved["psk"] == "secret"
    assert summary.solved == 1


@pytest.mark.asyncio
async def test_runner_records_sae_capture():
    ap = _ap("aa:bb:cc:dd:ee:01", ssid="WPA3Net", akm_suites=[8])
    saved = {}

    def _save(ap_, frames):
        saved["frames"] = frames

    vault = _vault()
    vault.save_sae = _save
    runner = _FakeRunner(_array([ap]), vault, timeouts={"sae": 5})

    def _start(kind, ap_):
        camp = _FakeCamp(array=None, ap=ap_)
        camp.pairs = [("sta", b"commit", b"confirm", 1.0)]
        camp.frames_for_pcap = lambda: [(b"commit", 1.0), (b"confirm", 1.0)]
        camp.done = True
        return camp

    runner._start_campaign = _start
    steps, _ = build_plan([ap], vault)
    assert [s.kind for s in steps] == ["sae"]
    summary = await runner.run(steps, [ap])
    assert summary.results[0].outcome == "captured"
    assert saved["frames"] == [(b"commit", 1.0), (b"confirm", 1.0)]
    assert summary.solved == 1


@pytest.mark.asyncio
async def test_run_emits_inventory_event():
    import io
    import json
    ap = _ap("aa:bb:cc:dd:ee:01", ssid="Net", signal=-50, akm_suites=[2])
    buf = io.StringIO()
    runner = _FakeRunner(_array([ap]), _vault(), timeouts={"pmkid": 0.01, "handshake": 0.01})
    runner.session = buf
    await runner.run([], [ap])
    events = [json.loads(ln) for ln in buf.getvalue().splitlines()]
    inv = next(e for e in events if e["event"] == "inventory")
    assert inv["aps"][0]["bssid"] == "aa:bb:cc:dd:ee:01"
    assert inv["aps"][0]["signal"] == -50
    assert any(e["event"] == "summary" for e in events)
