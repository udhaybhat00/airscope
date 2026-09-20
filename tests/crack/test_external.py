"""External dictionary crackers (crack.external): command building and output parsing."""
from pathlib import Path

from airscope.crack import external as ext


def test_hashcat_progress_parses_machine_readable():
    prog = ext.parse_progress_line("STATUS\t2\tSPEED\t999\t100\tPROGRESS\t500\t1024", "hashcat")
    assert prog is not None
    assert (prog.tested, prog.total) == (500, 1024)
    assert prog.fraction == 500 / 1024


def test_hashcat_non_status_line_is_none():
    assert ext.parse_progress_line("Session..........: hashcat", "hashcat") is None
    assert ext.parse_progress_line("", "hashcat") is None


def test_aircrack_progress_parses_tested_and_speed():
    prog = ext.parse_progress_line("[00:00:03] 500/1024 keys tested (12.34 k/s)", "aircrack")
    assert prog is not None
    assert (prog.tested, prog.total) == (500, 1024)
    assert prog.speed == "12.34 k/s"


def test_aircrack_line_without_count_is_none():
    assert ext.parse_progress_line("Opening capture file...", "aircrack") is None


def test_fraction_zero_without_total():
    assert ext.CrackProgress(tested=10, total=0).fraction == 0.0


def test_hashcat_show_handles_colon_in_psk():
    line = "WPA*02*abc*def:pass:word:1"
    assert ext.parse_hashcat_show(line, ["WPA*02*abc*def"]) == "pass:word:1"


def test_hashcat_show_ignores_unknown_lines():
    assert ext.parse_hashcat_show("garbage without separator", ["WPA*02*abc"]) is None
    assert ext.parse_hashcat_show("", ["WPA*02*abc"]) is None


def test_aircrack_key_from_stdout():
    assert ext.parse_aircrack_key("blah\nKEY FOUND! [ secret123 ]\n") == "secret123"


def test_aircrack_key_from_keyfile(tmp_path):
    keyfile = tmp_path / "key.txt"
    keyfile.write_text("secret123\n", encoding="utf-8")
    assert ext.parse_aircrack_key("no key here", keyfile) == "secret123"


def test_aircrack_key_missing_everywhere(tmp_path):
    assert ext.parse_aircrack_key("nothing", tmp_path / "absent.txt") is None
    assert ext.parse_aircrack_key("nothing") is None


def test_hashcat_cmd_uses_mode_22000_and_potfile():
    cmd = ext.build_hashcat_cmd("hashcat", Path("h.hc22000"), Path("w.txt"), Path("p.pot"))
    assert cmd[:3] == ["hashcat", "-m", "22000"]
    assert "h.hc22000" in cmd and "w.txt" in cmd and "p.pot" in cmd


def test_aircrack_cmd_writes_keyfile():
    cmd = ext.build_aircrack_cmd("aircrack-ng", Path("c.pcap"), Path("w.txt"), Path("k.txt"))
    assert cmd == ["aircrack-ng", "-w", "w.txt", "-l", "k.txt", "c.pcap"]


def test_sibling_pcap_found_and_missing(tmp_path):
    hc = tmp_path / "Net_aa-bb-cc-dd-ee-ff.hc22000"
    hc.write_text("x", encoding="utf-8")
    assert ext.sibling_pcap(hc, "aa-bb-cc-dd-ee-ff") is None
    pcap = tmp_path / "Net_aa-bb-cc-dd-ee-ff_1700000000_handshake.pcap"
    pcap.write_text("x", encoding="utf-8")
    assert ext.sibling_pcap(hc, "aa-bb-cc-dd-ee-ff") == pcap


def test_hash_lines_filters_to_wpa_records(tmp_path):
    hc = tmp_path / "a.hc22000"
    hc.write_text("junk\nWPA*01*abc\nWPA*02*def\n\n", encoding="utf-8")
    assert ext.hash_lines(hc) == ["WPA*01*abc", "WPA*02*def"]
    assert ext.hash_lines(tmp_path / "missing.hc22000") == []


def test_detect_prefers_hashcat(monkeypatch):
    monkeypatch.setattr(ext.shutil, "which", lambda name: f"/bin/{name}")
    tools = ext.detect_tools()
    assert tools.preferred == "hashcat"


def test_detect_falls_back_to_aircrack(monkeypatch):
    monkeypatch.setattr(ext.shutil, "which", lambda name: "/bin/aircrack-ng" if name == "aircrack-ng" else None)
    tools = ext.detect_tools()
    assert tools.preferred == "aircrack"


def test_detect_none_when_missing(monkeypatch):
    monkeypatch.setattr(ext.shutil, "which", lambda name: None)
    assert ext.detect_tools().preferred is None


def test_hashcat_show_parses_normalized_handshake_hit():
    out = "07f8a762aa8bda2644355066febf0f1d0a3ad59abac86712fc52e6f5074b6f11*5465737431:test1234"
    assert ext.parse_hashcat_show(out, ["WPA*02*unrelated"]) is None  # star form never occurs
    real = ("4fbe218ba6216f4a0611e14d621684f0:aabbccddeeff:112233445566"
            ":TestNet:test1234")
    assert ext.parse_hashcat_show(real, ["WPA*02*unrelated"], ssid="TestNet") == "test1234"
    assert ext.parse_hashcat_show(real, ["WPA*02*unrelated"], ssid="Other") is None
    colon_psk = ("4fbe218ba6216f4a0611e14d621684f0:aabbccddeeff:112233445566"
                 ":TestNet:pass:word:1")
    assert ext.parse_hashcat_show(colon_psk, [], ssid="TestNet") == "pass:word:1"


def test_extract_records_splits_by_kind(tmp_path):
    hc = tmp_path / "a.hc22000"
    hc.write_text("WPA*01*pm\nWPA*02*hs\n", encoding="utf-8")
    assert ext.extract_records(hc, "HS") == ["WPA*02*hs"]
    assert ext.extract_records(hc, "PMKID") == ["WPA*01*pm"]


def test_potfile_lives_beside_captures(tmp_path):
    assert ext.potfile_path(tmp_path) == tmp_path / ".airscope.potfile"


def test_write_temp_hashfile_round_trips(tmp_path):
    path = ext.write_temp_hashfile(tmp_path, "aa-bb-cc-dd-ee-ff", ["WPA*02*hs"])
    assert path.name == ".airscope-crack-aa-bb-cc-dd-ee-ff.hc22000"
    assert path.read_text(encoding="utf-8").splitlines() == ["WPA*02*hs"]
    assert ext.potfile_path(tmp_path) == tmp_path / ".airscope.potfile"


def test_install_hint_names_a_tool():
    assert "hashcat" in ext.install_hint()
