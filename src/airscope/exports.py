"""Field-tool export formats: airodump-style CSV, Kismet netxml, a cracked-PSK
log, and an HTML session report. Pure functions over plain snapshots (no
vault/array imports); callers collect the data (see ``ap_snaps_from_array``,
``cracks_from_vault``, ``inventory_from_jsonl``). Only the standard library.
"""
from __future__ import annotations

import csv
import html
import io
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from xml.etree.ElementTree import Element, SubElement, tostring


@dataclass
class ClientSnap:
    """One associated station for the reports."""

    mac: str
    signal: int = -100
    packets: int = 0


@dataclass
class ApSnap:
    """One access point: scan columns plus its associated clients."""

    bssid: str
    ssid: Optional[str] = None
    channel: int = 0
    signal: int = -100
    encryption: str = "Unknown"
    akms: List[str] = field(default_factory=list)
    beacons: int = 0
    first_seen: float = 0.0
    last_seen: float = 0.0
    clients: List[ClientSnap] = field(default_factory=list)


@dataclass
class CrackEntry:
    """One recovered credential: AP + PSK, wifite2 cracked-log style."""

    bssid: str
    ssid: Optional[str]
    psk: str
    method: str
    timestamp: float = 0.0


def _when(ts: float) -> str:
    if not ts:
        return ""
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _csv_privacy(ap: ApSnap) -> str:
    enc = (ap.encryption or "").upper()
    if "WPA3" in enc or "SAE" in enc:
        return "WPA3"
    if "WPA2" in enc or "WPA" in enc:
        return "WPA2" if "2" in enc else "WPA"
    if enc == "WEP":
        return "WEP"
    if enc == "OWE":
        return "OWE"
    return "OPN"


def ap_snaps_from_array(array) -> List[ApSnap]:
    """Snapshot every AP in a live array (scanner/vault export, --auto)."""
    clients = getattr(array, "clients", None) or {}
    out: List[ApSnap] = []
    for ap in array.get_access_points():
        owned = [c for c in clients.values()
                 if (getattr(c, "bssid", None) or "").lower() == ap.bssid.lower()]
        out.append(ApSnap(
            bssid=ap.bssid, ssid=getattr(ap, "ssid", None),
            channel=getattr(ap, "channel", 0) or 0,
            signal=getattr(ap, "signal", -100) or -100,
            encryption=getattr(ap, "encryption", None) or "Unknown",
            akms=list(getattr(ap, "akms", None) or []),
            beacons=getattr(ap, "beacons", 0) or 0,
            first_seen=getattr(ap, "first_seen", 0.0) or 0.0,
            last_seen=getattr(ap, "last_seen", 0.0) or 0.0,
            clients=[ClientSnap(mac=c.mac, signal=getattr(c, "signal", -100) or -100,
                                packets=getattr(c, "packets", 0) or 0)
                     for c in owned]))
    return out


def cracks_from_vault(vault) -> List[CrackEntry]:
    """Every recovered credential in VAULT (CRACKED, WEP, WPS PIN/PBC)."""
    from airscope.models import CaptureType
    methods = {CaptureType.CRACKED: "CRACKED", CaptureType.WEP: "WEP",
               CaptureType.WPS_PIN: "WPS PIN", CaptureType.WPS_PBC: "WPS PBC"}
    out: List[CrackEntry] = []
    for cap in vault.all_captures():
        if cap.type in methods and cap.value:
            out.append(CrackEntry(bssid=cap.bssid, ssid=cap.ssid, psk=cap.value,
                                  method=methods[cap.type], timestamp=cap.timestamp))
    out.sort(key=lambda e: e.timestamp)
    return out


def read_jsonl_events(path: Path) -> List[dict]:
    """Batch session events (empty list when missing/unreadable)."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    events: List[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except ValueError:
            continue
    return events


def inventory_from_jsonl(path: Path) -> List[ApSnap]:
    """AP snapshots from batch ``inventory`` events (last one wins)."""
    snaps: List[ApSnap] = []
    for ev in read_jsonl_events(path):
        if ev.get("event") != "inventory":
            continue
        snaps = [ApSnap(
            bssid=a.get("bssid", ""), ssid=a.get("ssid"),
            channel=a.get("channel", 0) or 0, signal=a.get("signal", -100),
            encryption=a.get("encryption") or "Unknown", akms=a.get("akms") or [],
            clients=[ClientSnap(mac=m) for m in a.get("clients") or []]) for a in ev.get("aps", [])]
    return snaps


def steps_from_jsonl(path: Path) -> List[dict]:
    """Finished step results from batch ``step_end`` events."""
    return [ev["result"] for ev in read_jsonl_events(path)
            if ev.get("event") == "step_end" and isinstance(ev.get("result"), dict)]


def latest_session_jsonl(search_dir: Path) -> Optional[Path]:
    """Newest ``airscope_auto_*.jsonl`` in a directory, else None."""
    try:
        cands = sorted(search_dir.glob("airscope_auto_*.jsonl"),
                       key=lambda p: p.stat().st_mtime)
    except OSError:
        return None
    return cands[-1] if cands else None


# ----- writers -------------------------------------------------------------

AP_CSV_HEADER = ["BSSID", "First time seen", "Last time seen", "channel", "Speed",
                 "Privacy", "Cipher", "Authentication", "Power", "# beacons", "# IV",
                 "LAN IP", "ID-length", "ESSID", "Key"]
STATION_CSV_HEADER = ["Station MAC", "First time seen", "Last time seen", "Power",
                      "# packets", "BSSID", "Probed ESSIDs"]


def write_csv(aps: List[ApSnap], path: Path, keys: Optional[Dict[str, str]] = None) -> Path:
    """airodump-ng-style CSV: AP section plus associated-station section."""
    keys = keys or {}
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(AP_CSV_HEADER)
    for ap in aps:
        w.writerow([ap.bssid, _when(ap.first_seen), _when(ap.last_seen), ap.channel, "",
                    _csv_privacy(ap), "", "/".join(ap.akms), ap.signal, ap.beacons, "",
                    "", len(ap.ssid or ""), ap.ssid or "", keys.get(ap.bssid, "")])
    w.writerow([])
    w.writerow(STATION_CSV_HEADER)
    for ap in aps:
        for c in ap.clients:
            w.writerow([c.mac, "", "", c.signal, c.packets, ap.bssid, ""])
    path.write_text(buf.getvalue(), encoding="utf-8")
    return path


def write_netxml(aps: List[ApSnap], path: Path) -> Path:
    """Kismet netxml subset: detection-run with per-AP clients."""
    root = Element("detection-run")
    for i, ap in enumerate(aps, 1):
        net = SubElement(root, "wireless-network", {
            "number": str(i), "type": "infrastructure",
            "first-time": _when(ap.first_seen), "last-time": _when(ap.last_seen)})
        ssid_el = SubElement(net, "SSID", {"first-time": _when(ap.first_seen),
                                           "last-time": _when(ap.last_seen)})
        SubElement(ssid_el, "type").text = "Beacon"
        essid = SubElement(ssid_el, "essid", {"cloaked": "true" if not ap.ssid else "false"})
        essid.text = ap.ssid or ""
        SubElement(net, "BSSID").text = ap.bssid
        SubElement(net, "channel").text = str(ap.channel)
        SubElement(net, "encryption").text = ap.encryption or "Unknown"
        packets = SubElement(net, "packets")
        SubElement(packets, "total").text = str(ap.beacons)
        for j, c in enumerate(ap.clients, 1):
            cli = SubElement(net, "wireless-client", {"number": str(j), "type": "established",
                                                      "first-time": "", "last-time": ""})
            SubElement(cli, "client-mac").text = c.mac
            cpk = SubElement(cli, "packets")
            SubElement(cpk, "total").text = str(c.packets)
    path.write_bytes(b'<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(root, encoding="utf-8"))
    return path


def write_cracked_txt(entries: List[CrackEntry], path: Path) -> Path:
    """wifite2-style cracked log: one AP + PSK per line."""
    lines = ["# airscope cracked log",
             "# BSSID | SSID | PSK | method | cracked-at (UTC)"]
    for e in entries:
        lines.append(f"{e.bssid} | {e.ssid or '<hidden>'} | {e.psk} | "
                     f"{e.method} | {_when(e.timestamp)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _enc_breakdown(aps: List[ApSnap]) -> List[tuple[str, int]]:
    counts: Dict[str, int] = {}
    for ap in aps:
        label = ap.encryption or "Unknown"
        counts[label] = counts.get(label, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def write_html_report(title: str, aps: List[ApSnap], cracks: List[CrackEntry],
                      steps: List[dict], path: Path) -> Path:
    """Self-contained dark HTML session report: scan, captures, cracks, batch."""
    n_clients = sum(len(ap.clients) for ap in aps)
    rows = "\n".join(
        f"<tr><td>{html.escape(ap.ssid or '<hidden>')}</td>"
        f"<td><code>{html.escape(ap.bssid)}</code></td><td>{ap.channel}</td>"
        f"<td>{ap.signal} dBm</td><td>{html.escape(ap.encryption)}</td>"
        f"<td>{len(ap.clients)}</td><td>{ap.beacons}</td></tr>" for ap in aps)
    enc_rows = "\n".join(
        f"<tr><td>{html.escape(label)}</td><td>{n}</td></tr>"
        for label, n in _enc_breakdown(aps))
    crack_rows = "\n".join(
        f"<tr><td>{html.escape(e.ssid or '<hidden>')}</td>"
        f"<td><code>{html.escape(e.bssid)}</code></td>"
        f"<td><code>{html.escape(e.psk)}</code></td><td>{html.escape(e.method)}</td>"
        f"<td>{html.escape(_when(e.timestamp))}</td></tr>" for e in cracks)
    step_rows = "\n".join(
        f"<tr><td><code>{html.escape(str(s.get('bssid', '')))}</code></td>"
        f"<td>{html.escape(str(s.get('kind', '')))}</td>"
        f"<td>{html.escape(str(s.get('outcome', '')))}</td>"
        f"<td>{html.escape(str(s.get('detail', '')))}</td></tr>" for s in steps)
    doc = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>{html.escape(title)}</title>
<style>
body{{background:#0b0f19;color:#e2e8f0;font-family:monospace;max-width:1000px;margin:2em auto;padding:0 1em}}
h1{{color:#60a5fa}}h2{{color:#a78bfa;border-bottom:1px solid #1e293b;padding-bottom:.3em}}
table{{border-collapse:collapse;width:100%;margin:1em 0}}th,td{{border:1px solid #1e293b;padding:.3em .6em;text-align:left}}
th{{background:#131825;color:#60a5fa}}.stat{{color:#f59e0b;font-size:1.2em}}
code{{color:#34d399}}.empty{{color:#64748b}}
</style></head><body>
<h1>{html.escape(title)}</h1>
<h2>Scan summary</h2>
<p><span class="stat">{len(aps)}</span> APs · <span class="stat">{n_clients}</span> clients · """
    doc += f"""<span class="stat">{len(cracks)}</span> credentials cracked</p>
<table><tr><th>Encryption</th><th>Count</th></tr>
{enc_rows if enc_rows else '<tr><td class="empty" colspan="2">no AP data</td></tr>'}</table>
<h2>Access points</h2>
<table><tr><th>SSID</th><th>BSSID</th><th>CH</th><th>Signal</th><th>Encryption</th><th>Clients</th><th>Beacons</th></tr>
{rows if rows else '<tr><td class="empty" colspan="7">no AP data</td></tr>'}</table>
<h2>Cracked credentials</h2>
<table><tr><th>SSID</th><th>BSSID</th><th>PSK</th><th>Method</th><th>When (UTC)</th></tr>
{crack_rows if crack_rows else '<tr><td class="empty" colspan="5">none yet</td></tr>'}</table>
<h2>Batch steps</h2>
<table><tr><th>BSSID</th><th>Attack</th><th>Outcome</th><th>Detail</th></tr>
{step_rows if step_rows else '<tr><td class="empty" colspan="4">no batch log</td></tr>'}</table>
</body></html>
"""
    path.write_text(doc, encoding="utf-8")
    return path


def export_all(outdir: Path, aps: List[ApSnap], cracks: List[CrackEntry],
               steps: List[dict], keys: Optional[Dict[str, str]] = None) -> Dict[str, Path]:
    """Write csv + netxml + cracked.txt + report.html into ``outdir``."""
    outdir.mkdir(parents=True, exist_ok=True)
    return {
        "csv": write_csv(aps, outdir / "airscope.csv", keys),
        "netxml": write_netxml(aps, outdir / "airscope.netxml"),
        "cracked": write_cracked_txt(cracks, outdir / "cracked.txt"),
        "html": write_html_report("airscope session report", aps, cracks, steps,
                                  outdir / "report.html"),
    }
