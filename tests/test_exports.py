"""Export formats (exports): csv/netxml/cracked/html writers plus JSONL readers."""
import json
import xml.etree.ElementTree as ET

import pytest

from airscope import exports as e
from airscope.models import CaptureType, PersistedCapture


def _snaps():
    return [e.ApSnap(bssid="aa:bb:cc:dd:ee:ff", ssid="HomeNet", channel=6, signal=-50,
                     encryption="WPA2", akms=["PSK"], beacons=42,
                     first_seen=1700000000.0, last_seen=1700000100.0,
                     clients=[e.ClientSnap(mac="11:22:33:44:55:66", signal=-60, packets=7)]),
            e.ApSnap(bssid="aa:bb:cc:dd:ee:00", ssid=None, channel=11, signal=-80,
                     encryption="OPEN")]


def _cracks():
    return [e.CrackEntry("aa:bb:cc:dd:ee:ff", "HomeNet", "secret123", "CRACKED", 1700000200.0)]


def _steps():
    return [{"bssid": "aa:bb:cc:dd:ee:ff", "kind": "pmkid",
             "outcome": "captured", "detail": "PMKID"}]


def test_csv_has_airodump_sections(tmp_path):
    p = e.write_csv(_snaps(), tmp_path / "a.csv", {"aa:bb:cc:dd:ee:ff": "secret123"})
    lines = p.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("BSSID,First time seen")
    assert "aa:bb:cc:dd:ee:ff" in lines[1] and "HomeNet" in lines[1]
    assert "secret123" in lines[1]                       # known key lands in Key column
    assert lines[4].startswith("Station MAC")
    assert "11:22:33:44:55:66" in lines[5]


def test_netxml_parses_with_ap_and_client(tmp_path):
    p = e.write_netxml(_snaps(), tmp_path / "a.netxml")
    root = ET.parse(str(p)).getroot()
    assert root.tag == "detection-run"
    nets = root.findall("wireless-network")
    assert len(nets) == 2
    assert nets[0].find("BSSID").text == "aa:bb:cc:dd:ee:ff"
    assert nets[0].find("SSID/essid").text == "HomeNet"
    assert nets[0].find("wireless-client/client-mac").text == "11:22:33:44:55:66"


def test_cracked_txt_lists_ap_and_psk(tmp_path):
    p = e.write_cracked_txt(_cracks(), tmp_path / "cracked.txt")
    body = p.read_text(encoding="utf-8")
    assert "aa:bb:cc:dd:ee:ff | HomeNet | secret123 | CRACKED" in body


def test_html_has_all_sections(tmp_path):
    p = e.write_html_report("t", _snaps(), _cracks(), _steps(), tmp_path / "r.html")
    body = p.read_text(encoding="utf-8")
    for section in ("Scan summary", "Access points", "Cracked credentials", "Batch steps",
                    "HomeNet", "secret123", "pmkid", "WPA2"):
        assert section in body


def test_html_escapes_markup(tmp_path):
    snaps = [e.ApSnap(bssid="aa", ssid="<b>evil</b>", encryption="WPA2")]
    body = e.write_html_report("t", snaps, [], [], tmp_path / "r.html").read_text(encoding="utf-8")
    assert "<b>evil</b>" not in body and "&lt;b&gt;evil&lt;/b&gt;" in body


def test_jsonl_round_trip(tmp_path):
    p = tmp_path / "airscope_auto_1.jsonl"
    inv = {"event": "inventory", "aps": [{"bssid": "aa:bb:cc:dd:ee:ff", "ssid": "N",
                                          "channel": 6, "signal": -50, "encryption": "WPA2",
                                          "akms": ["PSK"], "clients": ["11:22:33:44:55:66"]}]}
    p.write_text("\n".join([json.dumps(inv),
                            json.dumps({"event": "step_end", "result": {"bssid": "x"}}),
                            "not json"]) + "\n", encoding="utf-8")
    aps = e.inventory_from_jsonl(p)
    assert len(aps) == 1 and aps[0].clients[0].mac == "11:22:33:44:55:66"
    assert e.steps_from_jsonl(p) == [{"bssid": "x"}]
    assert e.inventory_from_jsonl(tmp_path / "missing.jsonl") == []


def test_latest_session_discovery(tmp_path):
    assert e.latest_session_jsonl(tmp_path) is None
    a = tmp_path / "airscope_auto_1.jsonl"
    b = tmp_path / "airscope_auto_2.jsonl"
    a.write_text("{}\n", encoding="utf-8")
    b.write_text("{}\n", encoding="utf-8")
    import os
    os.utime(b, (b.stat().st_mtime + 5, b.stat().st_mtime + 5))
    assert e.latest_session_jsonl(tmp_path) == b


def test_export_all_writes_four(tmp_path):
    made = e.export_all(tmp_path / "out", _snaps(), _cracks(), _steps())
    assert set(made) == {"csv", "netxml", "cracked", "html"}
    assert all(p.is_file() for p in made.values())


def test_cracks_from_vault_collects_credentials():
    from types import SimpleNamespace
    caps = [PersistedCapture(type=CaptureType.CRACKED, timestamp=3, path="c",
                             bssid="b1", ssid="N", value="psk1"),
            PersistedCapture(type=CaptureType.WEP, timestamp=1, path="w",
                             bssid="b1", value="aabb"),
            PersistedCapture(type=CaptureType.HS, timestamp=2, path="h", bssid="b1")]
    vault = SimpleNamespace(all_captures=lambda: caps)
    out = e.cracks_from_vault(vault)
    assert [(c.psk, c.method) for c in out] == [("aabb", "WEP"), ("psk1", "CRACKED")]


def test_ap_snaps_from_array_counts_clients():
    from types import SimpleNamespace
    ap = SimpleNamespace(bssid="aa:bb:cc:dd:ee:ff", ssid="N", channel=1, signal=-70,
                         encryption="WPA2", akms=[], beacons=5, first_seen=1.0, last_seen=2.0)
    mine = SimpleNamespace(mac="m1", bssid="aa:bb:cc:dd:ee:ff", signal=-60, packets=3)
    other = SimpleNamespace(mac="m2", bssid="ff:ee:dd:cc:bb:aa", signal=-60, packets=3)
    arr = SimpleNamespace(get_access_points=lambda: [ap], clients={"a": mine, "b": other})
    snaps = e.ap_snaps_from_array(arr)
    assert [c.mac for c in snaps[0].clients] == ["m1"]


def test_cli_export_all(tmp_path, monkeypatch):
    import sys
    from airscope.persist.config import Config
    (tmp_path / "Net_aa-bb-cc-dd-ee-ff_1000_handshake.hc22000").write_text(
        "WPA*02*" + "0" * 32 + "*aabbccddeeff*112233445566*5465737431***2\n", encoding="utf-8")
    monkeypatch.setattr(Config, "captures_dir", str(tmp_path))
    monkeypatch.setattr("airscope.persist.config._PATH", tmp_path / "config.toml")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["airscope", "--export", "all", "--out", "out"])
    from airscope.__main__ import main
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0
    assert {p.name for p in (tmp_path / "out").iterdir()} == \
        {"airscope.csv", "airscope.netxml", "cracked.txt", "report.html"}
