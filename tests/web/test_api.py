"""Web backend Phase 1: bus, demo context, and the read-only API surface."""
import pytest

try:
    from fastapi.testclient import TestClient
except (ImportError, RuntimeError):
    pytest.skip("web tests require the [web] extra", allow_module_level=True)

from airscope.web import create_app
from airscope.web.bus import Bus
from airscope.web.context import DemoArray, HeadlessContext


def test_bus_fans_out_and_sheds():
    import asyncio

    async def _go():
        bus = Bus()
        a, b = bus.subscribe(), bus.subscribe()
        bus.publish("scan.tick", {"n": 1})
        assert (await a.get())["topic"] == "scan.tick"
        assert (await b.get())["topic"] == "scan.tick"
        bus.unsubscribe(a)
        bus.publish("scan.tick", {"n": 2})
        assert a.empty()
        assert (await b.get())["payload"] == {"n": 2}

    asyncio.run(_go())


def test_demo_array_wanders():
    import asyncio

    async def _go():
        demo = DemoArray()
        assert len(demo.get_access_points()) == 5
        await demo.start_hopping()
        seen_before = {b: a.last_seen for b, a in demo.access_points.items()}
        demo.tick()
        seen_after = {b: a.last_seen for b, a in demo.access_points.items()}
        assert all(after >= before for before, after in
                   zip(seen_before.values(), seen_after.values()))
        await demo.close()

    asyncio.run(_go())


@pytest.fixture()
def demo_client():
    ctx = HeadlessContext(demo=True)
    app = create_app(ctx)
    with TestClient(app) as client:
        yield client


def test_health(demo_client):
    body = demo_client.get("/api/health").json()
    assert body["name"] == "airscope" and body["engine"] == "demo"


def test_devices_never_errors(demo_client, monkeypatch):
    import airscope.device.manager as manager
    monkeypatch.setattr(manager, "devices", lambda: (_ for _ in ()).throw(OSError("no usb")))
    assert demo_client.get("/api/devices").json() == {"devices": []}


def test_aps_shape(demo_client):
    body = demo_client.get("/api/aps").json()
    assert len(body["aps"]) == 5
    first = body["aps"][0]
    assert set(first) >= {"bssid", "ssid", "channel", "signal", "encryption",
                          "akms", "beacons", "clients"}


def test_websocket_hello_then_ticks(demo_client):
    with demo_client.websocket_connect("/api/ws/events") as ws:
        assert ws.receive_json()["topic"] == "hello"
        tick = ws.receive_json()
        assert tick["topic"] == "scan.tick"
        assert len(tick["payload"]["aps"]) == 5


def test_empty_context_serves_empty(demo_client):
    import asyncio

    async def _go():
        ctx = HeadlessContext()
        assert ctx.snapshot_aps() == []
        assert ctx.engine_state() == "idle"
        assert ctx.device_list() == [] or isinstance(ctx.device_list(), list)

    asyncio.run(_go())


# ----- Phase 2: attacks, vault files, crack jobs (demo mode, no hardware) -----

BSSID = "aa:bb:cc:dd:ee:01"


def test_attack_unknown_kind_is_422(demo_client):
    r = demo_client.post("/api/attacks/frobnicate", json={"bssid": BSSID})
    assert r.status_code == 422


def test_attack_unknown_bssid_is_404(demo_client):
    r = demo_client.post("/api/attacks/pmkid", json={"bssid": "00:00:00:00:00:00"})
    assert r.status_code == 404


def test_attack_start_busy_stop(demo_client):
    r = demo_client.post("/api/attacks/pmkid", json={"bssid": BSSID})
    assert r.status_code == 202
    assert r.json()["state"] == "running"
    r2 = demo_client.post("/api/attacks/handshake", json={"bssid": BSSID})
    assert r2.status_code == 409
    assert demo_client.get("/api/attacks/current").json()["attack"]["kind"] == "pmkid"
    assert demo_client.delete("/api/attacks/current").json() == {"stopped": True}


def test_ap_detail_lists_eligible_attacks(demo_client):
    body = demo_client.get(f"/api/aps/{BSSID}").json()
    kinds = {a["kind"] for a in body["attacks"]}
    assert {"pmkid", "handshake"} <= kinds
    assert demo_client.get("/api/aps/00:00:00:00:00:00").status_code == 404


def test_demo_attack_completes_into_vault(demo_client):
    import time
    demo_client.post("/api/attacks/pmkid", json={"bssid": BSSID})
    deadline = time.time() + 20
    while time.time() < deadline:
        tree = demo_client.get("/api/vault").json()
        groups = [g for g in tree["aps"] if g["bssid"] == BSSID]
        if groups and any(c["type"] == "PMKID" for c in groups[0]["captures"]):
            break
        time.sleep(0.5)
    else:
        raise AssertionError("demo attack never saved its capture")
    path = next(c["path"] for c in groups[0]["captures"] if c["type"] == "PMKID")
    dl = demo_client.get("/api/vault/file", params={"path": path})
    assert dl.status_code == 200 and "WPA*01*" in dl.text
    assert demo_client.delete("/api/vault/file", params={"path": path}).json() == {
        "deleted": True}
    assert demo_client.get("/api/vault/file", params={"path": path}).status_code == 404
    assert demo_client.delete("/api/vault/file", params={"path": "/nope.txt"}).status_code == 404


def test_demo_crack_progress_and_save(demo_client):
    import time
    wl = "/tmp/web_phase2_words.txt"
    open(wl, "w").write("secret\n")
    ctx_vault = demo_client  # capture lives in the demo (isolated) vault
    tree = ctx_vault.get("/api/vault").json()
    assert tree["aps"] == []
    # stage a capture by running the demo attack to completion first
    demo_client.post("/api/attacks/pmkid", json={"bssid": BSSID})
    deadline = time.time() + 20
    path = None
    while time.time() < deadline:
        groups = [g for g in demo_client.get("/api/vault").json()["aps"]
                  if g["bssid"] == BSSID]
        hits = [c["path"] for g in groups for c in g["captures"] if c["type"] == "PMKID"]
        if hits:
            path = hits[0]
            break
        time.sleep(0.5)
    assert path is not None
    r = demo_client.post("/api/crack", json={"path": path, "wordlist": wl})
    assert r.status_code == 202
    job_id = r.json()["id"]
    deadline = time.time() + 20
    while time.time() < deadline:
        job = demo_client.get(f"/api/jobs/{job_id}").json()
        if job["state"] == "done":
            break
        time.sleep(0.5)
    else:
        raise AssertionError("demo crack never finished")
    assert demo_client.get("/api/jobs/nope").status_code == 404
    assert demo_client.post("/api/crack", json={"path": path, "wordlist": wl}).status_code == 202
    r = demo_client.post("/api/crack", json={"path": "/nope.hc22000", "wordlist": wl})
    assert r.status_code == 404
    r = demo_client.post("/api/crack", json={"path": path, "wordlist": "/nope.txt"})
    assert r.status_code == 422


def test_ws_attack_state_topic(demo_client):
    demo_client.post("/api/attacks/sae", json={"bssid": "aa:bb:cc:dd:ee:04"})
    with demo_client.websocket_connect("/api/ws/events") as ws:
        ws.receive_json()  # hello
        for _ in range(20):
            ev = ws.receive_json()
            if ev["topic"] == "attack.state":
                assert ev["payload"]["kind"] == "sae"
                break
        else:
            raise AssertionError("no attack.state seen")
    demo_client.delete("/api/attacks/current")


# ----- Phase 3: batch jobs and exports (demo mode, no hardware) -----

def test_batch_start_and_status(demo_client):
    r = demo_client.post("/api/batch", json={"bssids": ["aa:bb:cc:dd:ee:01"]})
    assert r.status_code == 202
    job = r.json()
    assert [s["kind"] for s in job["steps"]] == ["pmkid", "handshake"]
    got = demo_client.get(f"/api/batch/{job['id']}").json()
    assert got["id"] == job["id"] and got["state"] == "running"
    assert demo_client.get("/api/batch/nope").status_code == 404
    assert demo_client.delete(f"/api/batch/{job['id']}").json() == {"stopped": True}
    assert demo_client.delete("/api/batch/nope").json() == {"stopped": False}


def test_batch_unknown_targets_is_422(demo_client):
    r = demo_client.post("/api/batch", json={"bssids": ["00:00:00:00:00:00"]})
    assert r.status_code == 422


def test_batch_completes_with_solved(demo_client):
    import time
    job_id = demo_client.post("/api/batch", json={"bssids": ["aa:bb:cc:dd:ee:01"]}).json()["id"]
    deadline = time.time() + 30
    while time.time() < deadline:
        job = demo_client.get(f"/api/batch/{job_id}").json()
        if job["state"] == "done":
            break
        time.sleep(0.5)
    else:
        raise AssertionError("demo batch never finished")
    assert job["solved"] >= 1
    assert any(r["outcome"] in ("solved", "captured") for r in job["results"])


def test_batch_ws_step_events(demo_client):
    demo_client.post("/api/batch", json={"bssids": ["aa:bb:cc:dd:ee:04"]})
    with demo_client.websocket_connect("/api/ws/events") as ws:
        ws.receive_json()  # hello
        for _ in range(30):
            ev = ws.receive_json()
            if ev["topic"] == "batch.done":
                assert "batch-" in str(ev["payload"].get("id", ""))
                break
        else:
            raise AssertionError("no batch.done seen")


def test_exports_serve_all_kinds(demo_client):
    import xml.etree.ElementTree as ET
    for kind in ("csv", "netxml", "cracked", "html"):
        r = demo_client.get(f"/api/exports/{kind}")
        assert r.status_code == 200, kind
    assert demo_client.get("/api/exports/pdf").status_code == 404
    csv_body = demo_client.get("/api/exports/csv").text
    assert csv_body.startswith("BSSID,First time seen")
    assert "aa:bb:cc:dd:ee:01" in csv_body
    root = ET.fromstring(demo_client.get("/api/exports/netxml").text)
    assert root.tag == "detection-run" and len(root.findall("wireless-network")) == 5
    html = demo_client.get("/api/exports/html").text
    assert "Scan summary" in html and "HomeNet" in html


def test_web_banner_names_url_and_mode():
    from airscope.__main__ import _web_banner
    demo = _web_banner("http://127.0.0.1:8765/", True)
    assert "http://127.0.0.1:8765/" in demo and "DEMO" in demo
    live = _web_banner("http://127.0.0.1:8765/", False)
    assert "http://127.0.0.1:8765/" in live and "LIVE" in live and "DEMO" not in live


def test_scan_stop_start_and_tick_flag(demo_client):
    assert demo_client.post("/api/scan/stop").json() == {"scanning": False}
    assert demo_client.get("/api/health").json()["scanning"] is False
    assert demo_client.post("/api/scan/frobnicate").status_code == 404
    assert demo_client.post("/api/scan/start").json() == {"scanning": True}
    assert demo_client.get("/api/health").json()["scanning"] is True


def test_tick_carries_rates(demo_client):
    with demo_client.websocket_connect("/api/ws/events") as ws:
        ws.receive_json()  # hello
        for _ in range(5):
            ev = ws.receive_json()
            if ev["topic"] == "scan.tick":
                rates = ev["payload"]["rates"]
                assert "aa:bb:cc:dd:ee:01" in rates
                assert set(rates["aa:bb:cc:dd:ee:01"]) == {"beacon", "data", "inject", "deauth"}
                assert ev["payload"]["scanning"] is True
                break
        else:
            raise AssertionError("no scan.tick seen")
