"""Load previously-saved captures from captures/ back into per-AP history, so a
recovered key or captured handshake/PMKID re-surfaces as a badge + Focus summary
on the next scan. Classification is by filename; both .hc22000 and .pcap files are
indexed (a handshake may have either or both). Counterpart: persist.save."""
from __future__ import annotations

import logging
import struct
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

from airscope.models import CaptureType, PersistedCapture
from airscope.persist.common import (
    AGGREGATED_HC22000_RE,
    LEGACY_CAPTURE_RE,
    V14_AGGREGATED_HC22000_RE,
    V14_CAPTURE_RE,
    WEP_KEY_HEX_RE,
    WPS_PIN_RE,
    WPS_PSK_RE,
    _v14_bssid_to_colon,
    bssid_to_colon,
)
from airscope.persist.config import Config

logger = logging.getLogger(__name__)


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        logger.debug("capture_history: unreadable %s: %s", path.name, e)
        return None


def _read_wep_key(path: Path) -> str | None:
    """Extract the hex WEP key from a ``_wep_key.txt`` file, or None."""
    text = _read_text(path)
    if text is None:
        return None
    m = WEP_KEY_HEX_RE.search(text)
    return m.group(1).lower() if m else None


def _read_wps_psk(path: Path) -> str | None:
    """Extract the PSK from a ``_wps_pin.txt`` or ``_wps_pbc.txt`` file, or None."""
    text = _read_text(path)
    if text is None:
        return None
    m = WPS_PSK_RE.search(text)
    return m.group(1).strip() if m else None


def _read_wps_pin(path: Path) -> str | None:
    """Extract the PIN from a ``_wps_pin.txt`` file, or None."""
    text = _read_text(path)
    if text is None:
        return None
    m = WPS_PIN_RE.search(text)
    return m.group(1).strip() if m else None


def _count_hashlines(path: Path, prefix: str) -> int:
    """Number of ``WPA*01*`` / ``WPA*02*`` records in a .hc22000 file (0 if unreadable)."""
    text = _read_text(path)
    if text is None:
        return 0
    return sum(1 for ln in text.splitlines() if ln.strip().startswith(prefix))


def _count_sae_pairs(path: Path, bssid: str) -> int:
    """Completed SAE commit+confirm pairs per station in a bare-MPDU pcap."""
    bssid = bssid.lower()
    try:
        blob = path.read_bytes()
    except OSError:
        return 0
    if len(blob) < 24:
        return 0
    seen: dict[str, set[int]] = {}
    off = 24
    while off + 16 <= len(blob):
        _ts_sec, _ts_usec, incl, _orig = struct.unpack("<IIII", blob[off:off + 16])
        off += 16
        frame, off = blob[off:off + incl], off + incl
        if len(frame) < 30 or frame[0] & 0xFC != 0xB0:
            continue
        algo, seq, status = struct.unpack("<HHH", frame[24:30])
        if algo != 3 or status != 0 or seq not in (1, 2):
            continue
        src, dst = frame[10:16].hex(":"), frame[4:10].hex(":")
        sta = src if src != bssid else dst
        if sta in (bssid, "ff:ff:ff:ff:ff:ff"):
            continue
        seen.setdefault(sta, set()).add(seq)
    return sum(1 for seqs in seen.values() if seqs == {1, 2})


def _parse_aggregate_hc(path: Path, bssid: str) -> List[PersistedCapture]:
    text = _read_text(path)
    if text is None:
        return []
    try:
        mtime = int(path.stat().st_mtime)
    except OSError:
        mtime = 0
    m = AGGREGATED_HC22000_RE.match(path.name)
    ssid = m.group("ssid") if m else None
    pmkid = hs = 0
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("WPA*01*"):
            pmkid += 1
        elif line.startswith("WPA*02*"):
            hs += 1
    out: List[PersistedCapture] = []
    if pmkid:
        out.append(PersistedCapture(type=CaptureType.PMKID, timestamp=mtime, path=str(path),
                                    bssid=bssid, ssid=ssid, record_count=pmkid))
    if hs:
        out.append(PersistedCapture(type=CaptureType.HS, timestamp=mtime, path=str(path),
                                    bssid=bssid, ssid=ssid, record_count=hs))
    return out


def _parse_aggregate_hc_v14(path: Path, bssid: str) -> List[PersistedCapture]:
    """Parse a v14.py aggregated hc22000 file (BSSID as 12 hex chars without dashes)."""
    text = _read_text(path)
    if text is None:
        return []
    try:
        mtime = int(path.stat().st_mtime)
    except OSError:
        mtime = 0
    m = V14_AGGREGATED_HC22000_RE.match(path.name)
    ssid = m.group("ssid") if m else None
    pmkid = hs = 0
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("WPA*01*"):
            pmkid += 1
        elif line.startswith("WPA*02*"):
            hs += 1
    out: List[PersistedCapture] = []
    if pmkid:
        out.append(PersistedCapture(type=CaptureType.PMKID, timestamp=mtime, path=str(path),
                                    bssid=bssid, ssid=ssid, record_count=pmkid))
    if hs:
        out.append(PersistedCapture(type=CaptureType.HS, timestamp=mtime, path=str(path),
                                    bssid=bssid, ssid=ssid, record_count=hs))
    return out


def _parse_file(path: Path, bssid: str) -> List[PersistedCapture]:
    """Parse one captures/ file into zero or more PersistedCapture entries."""
    # airscope aggregated hc22000 (dashed BSSID)
    if AGGREGATED_HC22000_RE.match(path.name):
        return _parse_aggregate_hc(path, bssid)

    m = LEGACY_CAPTURE_RE.match(path.name)
    if not m:
        # v14.py format (BSSID as 12 hex chars without dashes + timestamp.seq)
        m_v14 = V14_CAPTURE_RE.match(path.name)
        if m_v14:
            ssid_raw = path.name[:m_v14.start("bssid") - 1]  # strip trailing _
            return [PersistedCapture(type=CaptureType.HS, timestamp=0,
                                     path=str(path), bssid=bssid, ssid=ssid_raw or None,
                                     record_count=0)]
        # v14.py aggregated hc22000 (BSSID as 12 hex chars without dashes)
        if V14_AGGREGATED_HC22000_RE.match(path.name):
            return _parse_aggregate_hc_v14(path, bssid)
        # Fallback: no filename pattern matched but we have a valid BSSID
        # (typically resolved from the parent directory name by load_capture_index's
        # _bssid_from_parent fallback). Create a minimal entry so the capture is
        # still visible in airscope instead of being silently dropped.
        if bssid:
            return [PersistedCapture(type=CaptureType.HS, timestamp=0,
                                     path=str(path), bssid=bssid, ssid=None,
                                     record_count=0)]
        return []
    epoch = int(m.group("epoch"))
    kind = m.group("kind")
    ext = m.group("ext")
    ssid = m.group("ssid")

    if kind == "wep_key" and ext == "txt":
        key = _read_wep_key(path)
        if key is None:
            return []
        return [PersistedCapture(type=CaptureType.WEP, timestamp=epoch, path=str(path),
                                 bssid=bssid, value=key, ssid=ssid)]
    if kind == "wps_pin" and ext == "txt":
        return [PersistedCapture(type=CaptureType.WPS_PIN, timestamp=epoch, path=str(path),
                                 bssid=bssid, value=_read_wps_psk(path), ssid=ssid,
                                 pin=_read_wps_pin(path))]
    if kind == "wps_pbc" and ext == "txt":
        return [PersistedCapture(type=CaptureType.WPS_PBC, timestamp=epoch, path=str(path),
                                 bssid=bssid, value=_read_wps_psk(path), ssid=ssid)]
    if kind == "cracked" and ext == "txt":
        return [PersistedCapture(type=CaptureType.CRACKED, timestamp=epoch, path=str(path),
                                 bssid=bssid, value=_read_wps_psk(path), ssid=ssid)]
    if kind == "eviltwin_psk" and ext == "txt":
        return [PersistedCapture(type=CaptureType.EVILTWIN_PSK, timestamp=epoch, path=str(path),
                                 bssid=bssid, value=_read_wps_psk(path), ssid=ssid)]
    if kind == "handshake" and ext in ("hc22000", "pcap"):
        count = _count_hashlines(path, "WPA*02*") if ext == "hc22000" else 0
        return [PersistedCapture(type=CaptureType.HS, timestamp=epoch, path=str(path),
                                 bssid=bssid, ssid=ssid, record_count=count)]
    if kind == "pmkid" and ext in ("hc22000", "pcap"):
        count = _count_hashlines(path, "WPA*01*") if ext == "hc22000" else 0
        return [PersistedCapture(type=CaptureType.PMKID, timestamp=epoch, path=str(path),
                                 bssid=bssid, ssid=ssid, record_count=count)]
    if kind == "sae" and ext == "pcap":
        return [PersistedCapture(type=CaptureType.SAE, timestamp=epoch, path=str(path),
                                 bssid=bssid, ssid=ssid,
                                 record_count=_count_sae_pairs(path, bssid))]
    return []


def _resolve_captures_dir() -> Path:
    """Resolve the captures directory robustly.

    Config.captures_dir may be a relative path (e.g. ``captures``) that only
    resolves correctly when the working directory is the project root.  When it
    does not exist we try common fallback locations so that programmatic callers
    (``load_capture_index()`` invoked outside the TUI, tests, etc.) still see
    existing captures instead of silently returning an empty index.
    """
    configured = Path(Config.captures_dir)
    if configured.is_dir():
        return configured
    # Resolve relative to known project roots.
    candidates: list[Path] = []
    if not configured.is_absolute():
        for base in (Path.home(), Path.cwd()):
            candidates.append(base / configured)
            candidates.append(base / "Projects" / "wifi-collector" / str(configured))
    # Absolute but missing — try sibling dirs.
    candidates.append(Path.home() / "Projects" / "wifi-collector" / "captures")
    for c in candidates:
        if c.is_dir():
            logger.debug("capture_history: captures_dir resolved to %s (fallback)", c)
            return c
    # Nothing found — return the configured path so callers see it didn't exist.
    return configured


def _bssid_from_parent(path: Path) -> str | None:
    """Extract a BSSID from a file's parent directory name.

    v14.py stores captures under ``captures/<essid>_<hex_bssid>/``.  Older runs
    created filenames like ``<essid>_YYYYMMDD_HHMMSS-NN.cap`` (no BSSID in the
    filename), so regex matching on ``path.name`` fails.  This scans the parent
    directory name for a 12-char hex segment and returns it as a colon-separated
    BSSID, or None.
    """
    parts = path.parent.name.split("_")
    # Scan right-to-left: the BSSID is typically the last underscore-delimited token,
    # but scanning all segments handles SSIDs that themselves contain underscores.
    for part in reversed(parts):
        if len(part) == 12:
            try:
                int(part, 16)
                return _v14_bssid_to_colon(part)
            except ValueError:
                continue
    return None


def load_capture_index() -> Dict[str, List[PersistedCapture]]:
    """Scan ``captures_dir``, return bssid->captures sorted by newest-first."""
    index: Dict[str, List[PersistedCapture]] = defaultdict(list)
    root = _resolve_captures_dir()
    if not root.is_dir():
        logger.warning(
            "capture_history: captures directory %r does not exist — "
            "no saved captures will be shown. Check airscope config.", str(root))
        return {}
    # Use rglob so captures stored by v14.py in per-AP subdirectories
    # (e.g. SSID_BSSID/SSID_BSSID_timestamp_handshake.pcap) are also found,
    # not just airscope's own flat-layout files at the top level.
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        bssid: str | None = None
        # --- Filename-based regex matching (primary) ---
        m = LEGACY_CAPTURE_RE.match(path.name)
        if m:
            bssid = bssid_to_colon(m.group("bssid"))
        else:
            m_agg = AGGREGATED_HC22000_RE.match(path.name)
            if m_agg:
                bssid = bssid_to_colon(m_agg.group("bssid"))

        if not bssid:
            m_v14 = V14_CAPTURE_RE.match(path.name)
            if m_v14:
                bssid = _v14_bssid_to_colon(m_v14.group("bssid"))

        if not bssid:
            m_v14_agg = V14_AGGREGATED_HC22000_RE.match(path.name)
            if m_v14_agg:
                bssid = _v14_bssid_to_colon(m_v14_agg.group("bssid"))

        # --- Fallback: BSSID from parent directory name (v14.py folder format) ---
        # Older v14.py runs created filenames without the BSSID segment;
        # the 12-char hex is only in the folder name. Without this fallback,
        # those captures are silently invisible to airscope.
        if not bssid:
            bssid = _bssid_from_parent(path)

        if bssid:
            index[bssid].extend(_parse_file(path, bssid))
    for caps in index.values():
        caps.sort(key=lambda c: c.timestamp, reverse=True)
    return {b: c for b, c in index.items() if c}


def summarize(index: Dict[str, List[PersistedCapture]]) -> tuple[int, int, int, int, int]:
    """(handshakes, pmkids, wep_keys, wps_psks, cracked_psks) as a count of *APs*
    that have each type, de-duped per AP: an AP with 11 saved handshakes counts
    as one, not eleven."""
    hs = pmkid = wep = wps = cracked = 0
    for caps in index.values():
        types = {c.type for c in caps}
        hs += CaptureType.HS in types
        pmkid += CaptureType.PMKID in types
        wep += CaptureType.WEP in types
        wps += bool(types & {CaptureType.WPS_PIN, CaptureType.WPS_PBC})
        cracked += bool(types & {CaptureType.CRACKED, CaptureType.EVILTWIN_PSK})
    return hs, pmkid, wep, wps, cracked
