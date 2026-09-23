"""Entry point for ``python -m airscope`` and the ``airscope`` console script."""


async def _smoke() -> None:
    """Headless self-test: prove the PyInstaller bundle is intact, then exit. Used by CI to
    catch bundling breaks the unit-test import-smoke can't.

    Three checks:
      1. The bundled libusb shared lib is where ``libusb_package.get_library_path()`` looks
         (``libusb_package/libusb-1.0.*``) and actually loads. A onefile build can misplace it,
         which breaks USB enumeration with "No backend available". We deliberately do NOT
         ``libusb_init``/enumerate here: CI runners have no USB subsystem (no ``/dev/bus/usb``),
         so init legitimately fails there. That's a runtime-env concern, not a packaging break.
      2. ``App.run_test()`` mounts every screen headless (no TTY), pulling the widget .tcss and
         logo assets that a broken ``collect_all`` would silently drop.
      3. ``supported_ids()`` is non-empty: the pkgutil chip-discovery walk only enumerates
         drivers PyInstaller actually collected, so an empty map means the bundle shipped with
         no drivers and the app would launch but show zero interfaces.
    """
    import ctypes
    import os

    from libusb_package import get_library_path

    lib = get_library_path()
    if not (lib and os.path.isfile(str(lib))):
        raise RuntimeError(f"bundled libusb not found via libusb_package: {lib!r}")
    ctypes.CDLL(str(lib))  # must load from the bundle (deps resolved), not just exist on disk

    from airscope.ui.app import AirscopeApp

    app = AirscopeApp(cli_log_level="unset")
    async with app.run_test() as pilot:
        await pilot.pause()

    # Chip discovery actually finds drivers. supported_ids() walks airscope.chips via pkgutil; if
    # PyInstaller didn't collect the dynamically-imported chip packages the map is empty and the
    # app launches fine but shows zero interfaces. That is the break this check exists to catch.
    from airscope.device.manager import supported_ids

    if not supported_ids():
        raise RuntimeError("chip discovery found no driver packages (PyInstaller bundling break)")


async def _auto(args) -> int:
    """Headless batch mode: bring up every present card, scan, then run the
    WPS -> PMKID -> handshake plan over all (or --targets) APs. Progress goes
    to stdout, structured events to the JSONL session file. No TUI, no setup:
    cards needing one-time driver setup must go through the TUI once first."""
    import time

    from airscope.campaigns.batch import BatchRunner, build_plan
    from airscope.device.manager import devices, wlan_iface
    from airscope.persist.config import Config, ConfigError
    from airscope.persist.vault import Vault
    from airscope.wlan.array import WlanArray

    try:
        Config.load()
    except ConfigError as e:
        print(f"airscope: {e}")

    try:
        devs = devices()
    except Exception as e:
        print(f"airscope: USB scan failed: {e}")
        return 2
    if not devs:
        print("airscope: no supported USB adapters found (see docs/SUPPORTED-HARDWARE.md)")
        return 2

    array = WlanArray()
    for i, dev in enumerate(devs):
        iface = wlan_iface(dev, name=f"wlan{i}")
        if iface is None:
            print(f"airscope: skip {dev.description}: not present")
            continue
        try:
            ok = await iface.connect()
        except Exception as e:
            print(f"airscope: skip {dev.description}: {e}")
            print("airscope: cards needing one-time setup must use the TUI once first")
            continue
        if not ok:
            print(f"airscope: skip {dev.description}: bring-up failed")
            continue
        array.attach(iface)
        print(f"airscope: up {dev.description} as wlan{i}")
    if not array.members:
        print("airscope: no card could be brought up")
        return 2

    try:
        await array.start_hopping()
        print(f"airscope: scanning {args.scan_secs}s...")
        import asyncio as _asyncio
        await _asyncio.sleep(args.scan_secs)
        aps = array.get_access_points()
        print(f"airscope: {len(aps)} APs in range")

        if args.list:
            for ap in sorted(aps, key=lambda a: a.bssid):
                print(f"  {ap.bssid}  CH{ap.channel}  {ap.signal} dBm  {ap.ssid or '<hidden>'}")
            return 0

        if args.targets:
            wanted = [t.strip().lower() for t in args.targets.split(",") if t.strip()]
            aps = [ap for ap in aps
                   if ap.bssid.lower() in wanted
                   or any(t in (ap.ssid or "").lower() for t in wanted)]
            print(f"airscope: {len(aps)} APs match --targets")
        if not aps:
            print("airscope: nothing to attack")
            return 0

        vault = Vault()
        steps, skipped = build_plan(aps, vault)
        for s in skipped:
            print(f"airscope: skip {s.ssid or s.bssid}: {s.detail}")
        if not steps:
            print("airscope: no applicable attacks")
            return 0

        session_path = args.session or f"airscope_auto_{int(time.time())}.jsonl"
        timeouts = {"wps": args.wps_timeout, "pmkid": args.pmkid_timeout,
                    "handshake": args.hs_timeout, "sae": args.sae_timeout}
        runner = BatchRunner(array, vault, log=lambda m: print(f"airscope: {m}"),
                             timeouts=timeouts)
        try:
            import signal as _signal
            try:
                _asyncio.get_running_loop().add_signal_handler(
                    _signal.SIGINT, runner.request_stop)
            except NotImplementedError:
                pass  # Windows: Ctrl-C raises instead (handled below)
        except Exception:
            pass
        try:
            with open(session_path, "w", encoding="utf-8") as fh:
                runner.session = fh
                summary = await runner.run(steps, aps)
        except KeyboardInterrupt:
            print("airscope: interrupted")
            return 130
        print(f"airscope: session log: {session_path}")
        solved = [r for r in summary.results if r.outcome in ("solved", "captured")]
        ap_set = {r.bssid for r in summary.results}
        print(f"airscope: done: {len(solved)} captures over "
              f"{len(summary.results)} steps on {len(ap_set)} APs")
        for r in summary.results:
            if r.outcome in ("solved", "captured"):
                print(f"airscope: WIN {r.ssid or r.bssid} [{r.kind}]: {r.detail}")
        return 0
    finally:
        await array.close()


def _export(args) -> int:
    """Write field-tool exports from captures/ (+ batch JSONL when present)."""
    from pathlib import Path

    from airscope import exports
    from airscope.persist.config import Config, ConfigError
    from airscope.persist.vault import Vault

    try:
        Config.load()
    except ConfigError as e:
        print(f"airscope: {e}")
    vault = Vault()
    session = Path(args.session) if args.session else exports.latest_session_jsonl(Path.cwd())
    if args.session and not Path(args.session).is_file():
        print(f"airscope: session not found: {args.session}")
        return 2
    aps = exports.inventory_from_jsonl(session) if session else []
    if session is None:
        print("airscope: no batch session log; report covers VAULT captures only")
    steps = exports.steps_from_jsonl(session) if session else []
    cracks = exports.cracks_from_vault(vault)
    keys = {c.bssid: c.psk for c in cracks}
    outdir = Path(args.out or "airscope_exports")
    outdir.mkdir(parents=True, exist_ok=True)
    wanted = {"csv", "netxml", "cracked", "html"} if args.export == "all" else {args.export}
    made = exports.export_all(outdir, aps, cracks, steps, keys)
    for name in sorted(wanted):
        print(f"airscope: wrote {made[name]}")
    return 0


def _web_banner(url: str, demo: bool) -> str:
    """Terminal banner: URL plus an unmissable mode line."""
    mode = "DEMO  (simulated scan - no hardware, nothing is real)" if demo else \
        "LIVE  (real radio - authorized targets only)"
    bar = "+" + "-" * 62 + "+"
    return (f"{bar}\n"
            f"|  airscope web{' ' * 47}|\n"
            f"|  {url:<60}|\n"
            f"|  mode: {mode:<53}|\n"
            f"{bar}")


def _web(args) -> int:
    """Serve the local dashboard and open the browser to it."""
    try:
        import uvicorn
    except ImportError:
        print("airscope: web extras missing. Install them with:\n"
              "  pip install 'fastapi>=0.115' 'uvicorn[standard]>=0.30'")
        return 2

    from airscope.web import create_app
    from airscope.web.context import HeadlessContext

    ctx = HeadlessContext(demo=args.demo)
    app = create_app(ctx)
    url = f"http://{args.host}:{args.port}/"
    print(_web_banner(url, args.demo), flush=True)
    if not args.no_browser:
        import webbrowser
        webbrowser.open(url)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


def main() -> None:
    """Parse CLI args, then run the headless smoke test or launch the TUI."""
    import argparse
    from pathlib import Path

    from airscope import __version__

    parser = argparse.ArgumentParser(prog="airscope", description="USB Wireless Auditor")
    parser.add_argument("--version", action="version", version=f"airscope {__version__}")
    parser.add_argument("--smoke", action="store_true", help="TEST ONLY: Run headless, render, exit 0")
    parser.add_argument("--quiet", action="store_true", help="Do not emit any logs")
    parser.add_argument("--debug", action="store_true", help="Emit verbose debug logs")
    parser.add_argument("--trace", action="store_true", help="Emit very verbose trace logs")
    parser.add_argument("--auto", action="store_true",
                        help="Headless batch mode: scan, then attack all targets automatically")
    parser.add_argument("--list", action="store_true",
                        help="With --auto: print APs in range and exit")
    parser.add_argument("--targets", default="",
                        help="With --auto: comma-separated BSSIDs or SSID substrings to attack")
    parser.add_argument("--scan-secs", type=float, default=30.0,
                        help="With --auto: seconds to scan before attacking (default 30)")
    parser.add_argument("--wps-timeout", type=float, default=300.0)
    parser.add_argument("--pmkid-timeout", type=float, default=120.0)
    parser.add_argument("--hs-timeout", type=float, default=300.0)
    parser.add_argument("--sae-timeout", type=float, default=600.0)
    parser.add_argument("--session", default="",
                        help="With --auto: JSONL session log path (default airscope_auto_<epoch>.jsonl)")
    parser.add_argument("--export", choices=["csv", "netxml", "cracked", "html", "all"],
                        help="Write field-tool exports from captures/ and exit")
    parser.add_argument("--out", default="",
                        help="With --export: output directory (default airscope_exports)")
    parser.add_argument("--web", action="store_true",
                        help="Serve the local web dashboard and open the browser")
    parser.add_argument("--port", type=int, default=8765, help="With --web: port (default 8765)")
    parser.add_argument("--host", default="127.0.0.1", help="With --web: bind host (loopback only)")
    parser.add_argument("--no-browser", action="store_true", help="With --web: do not open the browser")
    parser.add_argument("--demo", action="store_true",
                        help="With --web: fake a wandering scan (no hardware needed)")
    parser.add_argument("--doctor", action="store_true",
                        help="Run pre-flight check and exit")
    args = parser.parse_args()

    if args.doctor:
        import sys as _sys
        from airscope.doctor import run_doctor, print_report
        results = run_doctor()
        ok = print_report(results)
        _sys.exit(0 if ok else 1)

    if args.web:
        import sys

        sys.exit(_web(args))

    if args.export:
        import sys

        sys.exit(_export(args))

    if args.smoke:
        import asyncio

        # 60s ceiling so a hung mount fails CI instead of stalling the runner.
        asyncio.run(asyncio.wait_for(_smoke(), timeout=60))
        return

    if args.auto:
        import asyncio
        import sys

        sys.exit(asyncio.run(_auto(args)))

    # Lazy import for WEP cracker ProcessPoolExecutor case
    from airscope.ui.app import AirscopeApp

    config_dir = Path.home() / ".airscope"
    first_run = not (config_dir / "has_run_before").exists()

    if first_run:
        from airscope.doctor import run_doctor, print_report
        print("\nFirst run -- checking setup...\n")
        results = run_doctor()
        ok = print_report(results)

        if not ok:
            print("Fix the issues above, then run again.")
            print("Or run: uv run python -m airscope.doctor --list-usb")
            print("        uv run python -m airscope.doctor --add-adapter VID PID\n")
            sys.exit(1)

        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "has_run_before").touch()

    cli_log_level = None
    if args.debug:
        cli_log_level = "debug"
    if args.trace:
        cli_log_level = "trace"
    if args.quiet:
        cli_log_level = "quiet"

    _print_startup_banner()
    AirscopeApp(cli_log_level=cli_log_level).run()


def _print_startup_banner() -> None:
    """ANSI-colored startup banner printed before the TUI opens."""
    import time
    from airscope import __version__
    mint = "\033[38;2;125;240;196m"
    cyan = "\033[38;2;90;200;250m"
    dim = "\033[2m"
    reset = "\033[0m"
    lines = [
        f"{mint}airscope{reset}",
        f"{dim}{__version__}{reset}",
        f"{cyan}wireless auditor{reset}",
    ]
    for line in lines:
        print(line)
        time.sleep(0.3)


if __name__ == "__main__":
    # Frozen (PyInstaller) builds use the `spawn` start method, so each
    # ProcessPoolExecutor worker (the WEP cracker) re-execs this exe. freeze_support()
    # makes that re-exec run the worker bootstrap and exit, instead of launching a
    # second TUI. It is a no-op for normal `python -m airscope` / console-script runs.
    import multiprocessing

    multiprocessing.freeze_support()
    main()
