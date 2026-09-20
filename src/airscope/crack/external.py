"""Dictionary cracking of .hc22000 captures via external tools.

hashcat (``-m 22000``, which covers both WPA*01* PMKID and WPA*02* handshake
records) is preferred; aircrack-ng is the fallback but needs a ``.pcap``
sibling since it cannot read hc22000. Pure functions (detect/build/parse)
stay UI-free and unit-testable; :func:`run_crack` drives the process.
"""
from __future__ import annotations

import asyncio
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from collections.abc import Callable
from typing import Optional

HASHCAT_MODE = 22000

WORDLIST_HINTS = [
    "/usr/share/wordlists/rockyou.txt",
    "/usr/share/wordlists/rockyou.txt.gz",
    str(Path.home() / "wordlists" / "rockyou.txt"),
    str(Path.home() / "rockyou.txt"),
    "/opt/homebrew/share/wordlists/rockyou.txt",
]

INSTALL_HINTS = {
    "darwin": "brew install hashcat aircrack-ng",
    "win32": "choco install hashcat; see aircrack-ng.org for the Windows build",
    "linux": "sudo apt install hashcat aircrack-ng",
}


def install_hint() -> str:
    """One-line install command for this platform."""
    if sys.platform == "darwin":
        return INSTALL_HINTS["darwin"]
    if sys.platform.startswith("win"):
        return INSTALL_HINTS["win32"]
    return INSTALL_HINTS["linux"]


@dataclass
class CrackTools:
    """Resolved cracker binaries (None when not installed)."""

    hashcat: Optional[str] = None
    aircrack: Optional[str] = None

    @property
    def preferred(self) -> Optional[str]:
        """'hashcat' or 'aircrack' (hashcat first), else None."""
        if self.hashcat:
            return "hashcat"
        if self.aircrack:
            return "aircrack"
        return None


def detect_tools() -> CrackTools:
    """Locate hashcat / aircrack-ng on PATH."""
    return CrackTools(hashcat=shutil.which("hashcat"), aircrack=shutil.which("aircrack-ng"))


def hash_lines(path: Path) -> list[str]:
    """WPA*01* / WPA*02* records in a .hc22000 file (empty if unreadable)."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [ln.strip() for ln in text.splitlines()
            if ln.strip().startswith(("WPA*01*", "WPA*02*"))]


def potfile_path(captures_dir: Path) -> Path:
    """Dedicated potfile beside captures/ (never the user's global one)."""
    return captures_dir / ".airscope.potfile"


def build_hashcat_cmd(hashcat: str, hashfile: Path, wordlist: Path, potfile: Path) -> list[str]:
    """hashcat WPA attack with once-a-second machine-readable status."""
    return [hashcat, "-m", str(HASHCAT_MODE), "--status", "--status-timer=1",
            "--machine-readable", "--quiet", "--potfile-path", str(potfile),
            str(hashfile), str(wordlist)]


def build_hashcat_show(hashcat: str, hashfile: Path, potfile: Path) -> list[str]:
    """Recover cracked passwords without touching the GPU."""
    return [hashcat, "-m", str(HASHCAT_MODE), "--show",
            "--potfile-path", str(potfile), str(hashfile)]


def sibling_pcap(hashfile: Path, dashed_bssid: str) -> Optional[Path]:
    """A ``_handshake.pcap`` companion for this BSSID (aircrack-ng's input)."""
    cands = sorted(hashfile.parent.glob(f"*_{dashed_bssid}_*_handshake.pcap"))
    return cands[0] if cands else None


def build_aircrack_cmd(aircrack: str, pcap: Path, wordlist: Path, keyfile: Path) -> list[str]:
    """aircrack-ng dictionary attack, key written to ``keyfile`` on success."""
    return [aircrack, "-w", str(wordlist), "-l", str(keyfile), str(pcap)]


@dataclass
class CrackProgress:
    """One parsed status tick: fraction done plus human counters."""

    tested: int = 0
    total: int = 0
    speed: str = ""
    status: str = "running"

    @property
    def fraction(self) -> float:
        """0..1 (0 when the total is still unknown)."""
        return min(1.0, self.tested / self.total) if self.total > 0 else 0.0


_HASHCAT_PROGRESS_RE = re.compile(r"PROGRESS\s+(\d+)\s+(\d+)")
_HASHCAT_SPEED_RE = re.compile(r"SPEED\s+(\d+)")
_GENERIC_COUNT_RE = re.compile(r"(\d+)\s*/\s*(\d+)")
_AIRCRACK_TESTED_RE = re.compile(r"(\d+)\s+keys tested")
_AIRCRACK_SPEED_RE = re.compile(r"\(([\d.]+\s*k/s)\)")


def parse_progress_line(line: str, tool: str) -> Optional[CrackProgress]:
    """Parse one stdout line from a cracker into progress, else None."""
    if tool == "hashcat":
        m = _HASHCAT_PROGRESS_RE.search(line)
        if not m:
            return None
        prog = CrackProgress(tested=int(m.group(1)), total=int(m.group(2)))
        s = _HASHCAT_SPEED_RE.search(line)
        if s:
            prog.speed = f"{int(s.group(1)):,} H/s"
        return prog
    m = _AIRCRACK_TESTED_RE.search(line)
    if not m:
        return None
    prog = CrackProgress(tested=int(m.group(1)))
    c = _GENERIC_COUNT_RE.search(line)
    if c:
        prog.tested, prog.total = int(c.group(1)), int(c.group(2))
    s = _AIRCRACK_SPEED_RE.search(line)
    if s:
        prog.speed = s.group(1)
    return prog


_NORMALIZED_RE = re.compile(r"^[0-9a-fA-F]{32}:[0-9a-fA-F]{12}:[0-9a-fA-F]{12}:")


def parse_hashcat_show(output: str, known_hashes: list[str],
                       ssid: Optional[str] = None) -> Optional[str]:
    """PSK from ``hashcat --show`` output.

    PMKID cracks echo ``{fullline}:{psk}`` (exact prefix match). Handshake
    cracks come back normalized to ``{pmkid}:{apmac}:{stamac}:{essid}:{psk}``,
    so with a known SSID the PSK is everything past the ``{essid}:`` marker
    (both ESSID and PSK may hold ``:``; the three leading hex fields cannot).
    """
    for out_line in output.splitlines():
        for known in known_hashes:
            if out_line.startswith(known + ":"):
                return out_line[len(known) + 1:]
    for out_line in output.splitlines():
        if not _NORMALIZED_RE.match(out_line):
            continue
        rest = out_line.split(":", 3)[3]
        # Handshake cracks require a known SSID (hashcat cannot form the
        # line without it); without one there is nothing exact to match.
        if ssid and rest.startswith(ssid + ":"):
            return rest[len(ssid) + 1:]
    return None


def extract_records(hashfile: Path, kind: str) -> list[str]:
    """This capture's own hash lines (``HS`` -> WPA*02*, ``PMKID`` -> WPA*01*)."""
    prefix = "WPA*02*" if kind == "HS" else "WPA*01*"
    return [ln for ln in hash_lines(hashfile) if ln.startswith(prefix)]


def write_temp_hashfile(captures_dir: Path, dashed_bssid: str, lines: list[str]) -> Path:
    """Single-AP hashfile for one crack run (any hit in it is ours)."""
    path = captures_dir / f".airscope-crack-{dashed_bssid}.hc22000"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


_AIRCRACK_FOUND_RE = re.compile(r"KEY FOUND!\s*\[\s*(.*?)\s*\]")


def parse_aircrack_key(output: str, keyfile: Optional[Path] = None) -> Optional[str]:
    """PSK from aircrack-ng stdout (``KEY FOUND! [ psk ]``) or its ``-l`` file."""
    m = _AIRCRACK_FOUND_RE.search(output)
    if m:
        return m.group(1)
    if keyfile is not None:
        try:
            text = keyfile.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            return None
        return text or None
    return None


@dataclass
class CrackRun:
    """Finished process: exit code plus progress ticks seen."""

    exit_code: int
    output: str = ""
    ticks: list[CrackProgress] = field(default_factory=list)


async def run_crack(cmd: list[str], tool: str,
                    on_progress: Optional[Callable[[CrackProgress], None]] = None) -> CrackRun:
    """Run a cracker, feeding parsed status ticks to ``on_progress``.

    Cancelling the awaiting task kills the child. stdout+stderr merge so
    callers see one stream.
    """
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    ticks: list[CrackProgress] = []
    chunks: list[str] = []
    try:
        assert proc.stdout is not None
        while True:
            raw = await proc.stdout.readline()
            if not raw:
                break
            line = raw.decode("utf-8", errors="replace")
            chunks.append(line)
            prog = parse_progress_line(line, tool)
            if prog is not None:
                ticks.append(prog)
                if on_progress is not None:
                    on_progress(prog)
    finally:
        if proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
        await proc.wait()
    return CrackRun(exit_code=proc.returncode or 0, output="".join(chunks), ticks=ticks)


async def run_capture_output(cmd: list[str]) -> tuple[int, str]:
    """Run a short helper (``--show``) and return (exit, output)."""
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    out, _ = await proc.communicate()
    return proc.returncode or 0, out.decode("utf-8", errors="replace")
