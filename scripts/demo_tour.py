"""Demo tour recorder: drives the TUI headless (Textual ``run_test``) and saves
frames for the README GIF. Scenes, in order:

  1. startup banner (rich capture of ``_print_startup_banner``)
  2. splash wordmark + adapter card + macOS platform hint
  3. scanner: live table, freeze mode (F), frozen banner, cursor navigation
  4. focus screen with the attack card row
  5. EvilTwin setup modal (the 3-step dialog; pushed directly, the platform
     gate keeps the button disabled on macOS native)
  6. vault: capture detail + hashcat crack progress
  7. web reports page (demo web, headless Chrome)

Requires the USB adapter plugged in, ffmpeg, gifski, Google Chrome (SVG
rasteriser) and hashcat for the crack scene. Scenes that cannot record print
a warning and are skipped. Assemble (run automatically at the end):

  gifski -o assets/demo-tour.gif -r 1 --width 800 -Q 75 <normalised frames>

  uv run python scripts/demo_tour.py
"""
import asyncio
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = Path("/tmp/tour")
GIF = ROOT / "assets" / "demo-tour.gif"
WORDLIST = Path("/tmp/tour_words.txt")
SIZE = (150, 42)
CANVAS = (800, 460)
BG = "0x0f1117"
WEB_PORT = 8799

CHROME = next((p for p in (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    shutil.which("chromium"), shutil.which("google-chrome"), shutil.which("chrome"),
) if p and Path(p).is_file()), None)

SHOT = {"n": 0}
# Unique dir per process: each SVG gets a unique file:// URL, so Chrome's
# file cache can never serve a stale render from a previous run.
_TMP_SVG = tempfile.mkdtemp(prefix="tour-svg-")


def rasterize(svg: Path) -> Path:
    """PNG the SVG via headless Chrome at the SVG's own viewBox size."""
    head = svg.read_text()[:500]
    m = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', head)
    if m:
        w, h = int(float(m.group(1))), int(float(m.group(2)))
    else:
        w = int(re.search(r'width="(\d+)', head).group(1))
        h = int(re.search(r'height="(\d+)', head).group(1))
    png = svg.with_suffix(".png")
    uniq = Path(_TMP_SVG) / svg.name
    shutil.copy(svg, uniq)
    subprocess.run([CHROME, "--headless", "--disable-gpu", "--hide-scrollbars",
                    f"--screenshot={png}", f"--window-size={w},{h}",
                    f"file://{uniq}"], capture_output=True, text=True)
    if not png.exists():
        raise RuntimeError(f"Chrome failed to rasterise {svg}")
    return png


def record_banner() -> None:
    """Frame 1: the startup banner exactly as a terminal prints it."""
    from rich.console import Console
    from rich.text import Text
    from airscope import __main__ as cli

    buf = io.StringIO()
    with redirect_stdout(buf):
        cli._print_startup_banner()
    console = Console(record=True, width=96, force_terminal=True)
    console.print(Text.from_ansi(buf.getvalue()))
    SHOT["n"] = 1
    (OUT / "f001.svg").write_text(console.export_svg(title="airscope startup"))
    rasterize(OUT / "f001.svg")
    print("frame: f001.png (banner)")


async def until(pilot, cond, timeout=30.0, what="condition") -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            if cond():
                return
        except Exception:
            pass
        await pilot.pause(0.4)
    raise RuntimeError(f"timeout waiting for {what}")


def snap(app, name: str | None = None) -> None:
    """One GIF frame; ``name`` also lands in docs/img/ for the landing page."""
    SHOT["n"] += 1
    svg = OUT / f"f{SHOT['n']:03d}.svg"
    app.save_screenshot(filename=svg.name, path=str(OUT))
    png = rasterize(svg)
    if name:
        img_dir = ROOT / "docs" / "img"
        img_dir.mkdir(exist_ok=True)
        shutil.copy(png, img_dir / f"{name}.png")
    print("frame:", png.name)


def pick_crack_target() -> tuple[Path, str]:
    """Newest-hashcat-ready capture: an .hc22000 whose BSSID is not already
    in the potfile; touched so it is the network's newest capture in the vault."""
    pot = ROOT / "captures" / ".potfile"
    pot_text = pot.read_text(errors="replace") if pot.exists() else ""
    candidates = sorted((ROOT / "captures").glob("*.hc22000"))
    for cap in candidates:
        m = re.search(r"((?:[0-9a-f]{2}-){5}[0-9a-f]{2})\.hc22000$", cap.name)
        if not m:
            continue
        dashed = m.group(1)
        colon = dashed.replace("-", ":")
        if colon in pot_text or dashed in pot_text:
            continue
        os.utime(cap, None)
        return cap, colon
    raise RuntimeError("no uncracked .hc22000 candidate in captures/")


def ensure_wordlist() -> None:
    """~12M words: long enough that hashcat (status every 1s) ticks before done."""
    if WORDLIST.exists() and WORDLIST.stat().st_size >= 80_000_000:
        return
    print("generating wordlist ...")
    with WORDLIST.open("w") as f:
        buf = []
        for i in range(12_000_000):
            buf.append(f"p{i:08d}")
            if len(buf) == 200_000:
                f.write("\n".join(buf))
                f.write("\n")
                buf = []
        if buf:
            f.write("\n".join(buf))
            f.write("\n")


async def tui_tour() -> None:
    from airscope.ui.app import AirscopeApp
    from airscope.ui.screens.scanner import ScannerView
    from airscope.ui.screens.focus_v2 import FocusViewV2
    from airscope.ui.screens.focus_v2.eviltwin_modal import EvilTwinInputModal
    from airscope.ui.screens.vault import VaultView
    from airscope.ui.screens.vault_item import VaultItemView, _CapturePanel

    # Modal close resumes VaultView, whose same-state load() recomposes the panel
    # and strands the crack worker's notes on the detached instance. Skip it.
    def _load_quiet(self, bssid, ssid, captures, *, empty_vault=False):
        self._empty_vault = empty_vault
        state = (bssid, ssid, tuple(captures))
        if state != self._state:
            self._state = state

    VaultItemView.load = _load_quiet

    os.environ.pop("AIRSCOPE_IN_VM", None)
    cap, bssid = pick_crack_target()  # before app start: vault index (load_capture_index)
    app = AirscopeApp(cli_log_level="unset")  # freezes capture mtimes when it boots
    async with app.run_test(size=SIZE) as pilot:
        # -- 2. splash: wordmark, adapter card, platform hint
        await until(pilot, lambda: app.screen.__class__.__name__ == "SplashView"
                    and not app.screen.query_one("#start-btn").disabled,
                    timeout=30, what="splash + adapter card")
        await pilot.pause(1.0)
        snap(app)

        # -- 3. scanner: bring up the card, wait for live APs
        await pilot.click("#start-btn")
        end = time.monotonic() + 120
        while not (app.screen.__class__.__name__ == "ScannerView"
                   and app.screen.query_one("#ap-table").row_count > 0):
            yes = app.screen.query("Button#btn-yes")
            if yes and yes[0].enabled:
                await pilot.click("#btn-yes")
            elif time.monotonic() > end:
                raise RuntimeError("scanner never appeared (bring-up failed?)")
            await pilot.pause(0.5)
        await pilot.pause(2.0)
        snap(app, "scanner")

        # -- freeze mode + cursor navigation while frozen
        await pilot.click("#ap-table")
        await pilot.press("f")
        await until(pilot, lambda: app.screen.query_one("#freeze-banner").display,
                    what="freeze banner")
        await pilot.pause(0.6)
        snap(app)
        await pilot.press("down")
        await pilot.pause(0.6)
        await pilot.press("down")
        await pilot.pause(0.6)
        snap(app)

        # -- 4. focus screen: attack cards
        await pilot.press("enter")
        await until(pilot, lambda: isinstance(app.screen, FocusViewV2)
                    and app.screen.query("Button#btn-deauth"),
                    timeout=15, what="focus screen")
        await pilot.pause(1.5)
        snap(app, "focus")

        # -- 5. EvilTwin setup modal (3-step dialog)
        app.push_screen(EvilTwinInputModal(app.target_ap, list(app.array.members)))
        await until(pilot, lambda: app.screen.__class__.__name__ == "EvilTwinInputModal",
                    timeout=10, what="EvilTwin modal")
        await pilot.pause(0.8)
        snap(app)
        await pilot.press("escape")
        await until(pilot, lambda: isinstance(app.screen, FocusViewV2), what="back to focus")

        # -- 6. vault: detail pane, then hashcat progress
        await pilot.press("escape")
        await until(pilot, lambda: isinstance(app.screen, ScannerView), what="back to scanner")
        await pilot.press("v")
        await until(pilot, lambda: isinstance(app.screen, VaultView)
                    and app.screen.query_one("#vault-aps").row_count > 0,
                    timeout=15, what="vault table")
        table = app.screen.query_one("#vault-aps")
        idx = next((i for i, k in enumerate(table.rows) if k.value == bssid), None)
        if idx is None:
            print("warn: crack target not in vault, skipping crack frames")
            snap(app)
        else:
            await pilot.click("#vault-aps")
            if idx == 0:
                await pilot.press("down")
                await pilot.pause(0.4)
                await pilot.press("up")
            else:
                for _ in range(idx):
                    await pilot.press("down")
                    await pilot.pause(0.2)
            await until(pilot, lambda: app.screen.query("Button.crack"),
                        timeout=10, what="crack button")
            print("panel newest:", app.screen.query_one("Select").value)
            snap(app)
            before = SHOT["n"]
            try:
                ensure_wordlist()
                await pilot.click(".crack")
                await until(pilot, lambda: app.screen.query("#crack-wordlist"),
                            timeout=10, what="crack modal")
                app.screen.query_one("#crack-wordlist").value = str(WORDLIST)
                await pilot.pause(0.4)
                await pilot.click("#crack-start")

                def progress() -> str:
                    val = app.screen.query_one(".crack-progress").content
                    return str(getattr(val, "plain", val))

                await until(pilot, lambda: progress().startswith("Cracking"),
                            timeout=30, what="hashcat progress")
                snap(app)
                await pilot.pause(2.0)
                snap(app)
            except RuntimeError as e:
                print(f"warn: crack progress skipped ({e})")
                if SHOT["n"] == before:
                    snap(app)
            finally:
                for p in app.query(_CapturePanel):
                    if p._crack_worker is not None:
                        p._crack_worker.cancel()


def record_reports() -> None:
    """Frame 7: the web reports page from a demo web instance."""
    env = {**os.environ, "AIRSCOPE_DEMO": "1"}
    proc = subprocess.Popen(
        [sys.executable, "-m", "airscope", "--web", "--demo",
         "--host", "127.0.0.1", "--port", str(WEB_PORT)],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True)
    try:
        end = time.monotonic() + 30
        while True:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{WEB_PORT}/", timeout=2).read()
                break
            except Exception:
                if time.monotonic() > end:
                    raise RuntimeError("web demo never came up")
                time.sleep(0.5)
        SHOT["n"] += 1
        png = OUT / f"f{SHOT['n']:03d}.png"
        subprocess.run([CHROME, "--headless", "--disable-gpu", "--hide-scrollbars",
                        f"--screenshot={png}", "--window-size=1500,950",
                        "--virtual-time-budget=15000",
                        f"http://127.0.0.1:{WEB_PORT}/#/reports"],
                       capture_output=True, text=True)
        if not png.exists():
            raise RuntimeError("Chrome failed on the reports page")
        print("frame:", png.name)
    finally:
        import signal
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass


def assemble() -> None:
    # Normalise every frame to the canvas, then encode with gifski: this
    # ffmpeg's paletteuse is broken here (one-pass split yields a single
    # frame; a two-pass looped palette repeats content after ~5 frames) and
    # a plain ffmpeg GIF is ~1.4 MB vs gifski's ~320 KB.
    w, h = CANVAS
    scaled = (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
              f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color={BG}")
    norm = OUT / "norm"
    if norm.exists():
        shutil.rmtree(norm)
    norm.mkdir()
    frames = sorted(OUT.glob("f[0-9][0-9][0-9].png"))
    if not frames:
        raise RuntimeError("no frames to assemble")
    for png in frames:
        subprocess.run(["ffmpeg", "-y", "-i", str(png), "-vf", scaled,
                        str(norm / png.name)],
                       check=True, capture_output=True)
    norm_frames = sorted(norm.glob("*.png"))
    subprocess.run(["gifski", "-o", str(GIF), "-r", "1", "--width", str(w),
                    "-Q", "75", *[str(p) for p in norm_frames]],
                   check=True, capture_output=True)
    img_dir = ROOT / "docs" / "img"
    img_dir.mkdir(exist_ok=True)
    shutil.copy(GIF, img_dir / "demo-tour.gif")
    print("wrote", GIF, GIF.stat().st_size, "bytes")


def main() -> None:
    if not CHROME:
        sys.exit("Google Chrome not found (needed to rasterise SVG frames)")
    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg not found")
    if not shutil.which("gifski"):
        sys.exit("gifski not found (needed to encode the demo GIF)")
    os.environ.pop("AIRSCOPE_IN_VM", None)  # record native mode (banner + platform gate)
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("f*"):
        old.unlink()
    SHOT["n"] = 0

    record_banner()
    asyncio.run(tui_tour())
    try:
        record_reports()
    except RuntimeError as e:
        print(f"warn: reports scene skipped ({e})")
    assemble()


if __name__ == "__main__":
    main()
