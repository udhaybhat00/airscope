"""Standalone RTL8812AU monitor mode diagnostic.

Usage:
    uv run python -m airscope.diagnose                # 4-step practical test
    uv run python -m airscope.diagnose --verbose      # debug logging
    uv run python -m airscope.diagnose --sniff        # sniff for auth/assoc frames
    uv run python -m airscope.diagnose --raw-rx       # raw hex dump from RX
    uv run python -m airscope.diagnose --test-reg     # test register R/W
    uv run python -m airscope.diagnose --brute-reg    # brute-force vendor request codes
    uv run python -m airscope.diagnose --start-ap     # start live AP
"""

import sys
import time
import struct
import logging
import argparse


def main():
    parser = argparse.ArgumentParser(description="RTL8812AU monitor mode diagnostic")
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    parser.add_argument("--sniff", action="store_true",
                        help="Sniff for incoming 802.11 frames")
    parser.add_argument("--raw-rx", action="store_true",
                        help="Raw hex dump from RX endpoint (bypass parser)")
    parser.add_argument("--test-reg", action="store_true",
                        help="Test if register R/W works")
    parser.add_argument("--brute-reg", action="store_true",
                        help="Brute-force vendor request codes")
    parser.add_argument("--start-ap", action="store_true",
                        help="Start a live AP (requires --ssid and --channel)")
    parser.add_argument("--ssid", default="TestNet", help="SSID for --start-ap")
    parser.add_argument("--channel", type=int, default=6, help="Channel for --start-ap")
    parser.add_argument("--iface", default=None,
                        help="WiFi interface for capture (macOS: en0, Linux: wlan0)")
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    log = logging.getLogger("diagnose")

    from .evil_twin.usb.device import find_adapter, setup_device
    from .evil_twin.usb.rtl8812au_ap import Rtl8812auAP

    log.info("Searching for RTL8812AU/8814AU adapter...")
    dev = find_adapter()
    if dev is None:
        log.error("No supported adapter found.")
        sys.exit(1)

    log.info("Found: %04x:%04x", dev.idVendor, dev.idProduct)
    ep_rx, ep_tx, ep_ctrl = setup_device(dev)
    log.info("Endpoints: RX=0x%02x  TX=0x%02x  CTRL=0x%02x", ep_rx, ep_tx, ep_ctrl)

    ap = Rtl8812auAP(dev, ep_rx=ep_rx, ep_tx=ep_tx, ep_ctrl=ep_ctrl)

    if args.raw_rx:
        _run_raw_rx(ap, args)
    elif args.test_reg:
        _run_test_reg(ap)
    elif args.brute_reg:
        _run_brute_reg(ap)
    elif args.start_ap:
        _run_start_ap(ap, args, log)
    elif args.sniff:
        _run_sniff(ap, args, log)
    else:
        _run_diagnostic(ap, log)

    try:
        import usb.util
        usb.util.dispose_resources(dev)
    except Exception:
        pass
    log.info("Adapter released.")


def _run_diagnostic(ap, log):
    print("\n" + "=" * 50)
    print("  RTL8812AU Practical Diagnostic")
    print("=" * 50 + "\n")

    try:
        ok = ap.diagnose()
        if ok:
            print("\n" + "=" * 50)
            print("  ALL STEPS PASSED -- chip is ready")
            print("=" * 50)
        else:
            sys.exit(1)
    except Exception as e:
        print(f"\n  FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        ap.deinit_monitor_rx()


def _run_raw_rx(ap, args):
    """Read raw bytes from RX endpoint. No parsing. Just hex dump."""
    duration = 15
    print(f"\n{'=' * 50}")
    print(f"  Raw RX dump for {duration}s (Ctrl+C to stop)")
    print(f"  Reading from EP 0x{ap.ep_rx:02x}...")
    print(f"{'=' * 50}\n")

    ap.init_monitor_rx()
    count = 0
    start = time.monotonic()
    try:
        while time.monotonic() - start < duration:
            try:
                data = ap.dev.read(ap.ep_rx, 512, timeout=1000)
                if data:
                    count += 1
                    hex_str = ' '.join(f'{b:02x}' for b in data[:64])
                    print(f"[{count:4d}] {len(data):3d} bytes: {hex_str}")
                    if len(data) > 64:
                        print(f"       ... ({len(data)-64} more bytes)")
            except Exception as e:
                if 'timeout' not in str(e).lower():
                    print(f"USB Error: {e}")
    except KeyboardInterrupt:
        pass

    print(f"\nTotal reads: {count}")
    if count == 0:
        print("NOTHING coming in on RX endpoint.")
        print("  -> Problem is RCR (chip not forwarding frames)")
        print("  -> Try: uv run python -m airscope.diagnose --test-reg")
    else:
        print("Frames ARE arriving! Parser is the problem.")
        print("  -> Check _try_parse_rx() descriptor offset")

    ap.deinit_monitor_rx()


def _run_test_reg(ap):
    """Test if register R/W works at all."""
    print(f"\n{'=' * 50}")
    print("  Register R/W Test")
    print(f"{'=' * 50}\n")

    results = ap.test_registers()

    print(f"{'Address':<10} {'Value':<12} {'Status'}")
    print("-" * 40)

    all_zero = True
    all_ff = True
    for addr, val in results.items():
        status = ""
        if isinstance(val, str):
            print(f"0x{addr:04X}     {val}")
            continue
        if val != 0:
            all_zero = False
        if val != 0xFFFFFFFF:
            all_ff = False
        if addr == 0x14C:
            status = "<- RCR candidate"
        elif addr == 0x148:
            status = "<- RCR candidate"
        print(f"0x{addr:04X}     0x{val:08X}   {status}")

    print("-" * 40)

    if all_zero:
        print("ALL registers read 0x00000000")
        print("  -> Register READS are not working")
        print("  -> Vendor request code for READ is wrong")
        print("  -> Try: uv run python -m airscope.diagnose --brute-reg")
    elif all_ff:
        print("ALL registers read 0xFFFFFFFF")
        print("  -> Register READS are returning garbage")
        print("  -> Vendor request code for READ is wrong")
    else:
        print("Some registers have non-trivial values")
        print("  -> Register R/W is working")
        print("  -> RCR write should be landing")
        print("  -> Problem is likely the RX parser, not RCR")

    from .evil_twin.usb.rtl8812au_ap import read_reg, write_reg
    print("\nWrite/Readback Test:")
    test_addr = 0x14C
    test_val = 0xFFFFFFFF
    try:
        write_reg(ap.dev, test_addr, test_val)
        time.sleep(0.1)
        readback = read_reg(ap.dev, test_addr)
        if readback == test_val:
            print(f"  OK 0x{test_addr:04X} = 0x{test_val:08X} (write+readback OK)")
        else:
            print(f"  WARN 0x{test_addr:04X}: wrote 0x{test_val:08X}, read 0x{readback:08X}")
            print("     -> Write may be working but readback is wrong (write-only reg?)")
            print("     -> OR write is being silently ignored")
    except Exception as e:
        print(f"  FAIL Write failed: {e}")


def _run_brute_reg(ap):
    """Brute-force vendor request codes."""
    print(f"\n{'=' * 50}")
    print("  Brute-forcing vendor request codes")
    print(f"{'=' * 50}\n")

    working_read, working_write = ap.brute_force_register_access()

    if working_read and working_write:
        print(f"\nWorking codes: READ={working_read}, WRITE={working_write}")
        print("  Update rtl8812au_ap.py to use these.")
    else:
        print("\nNo working vendor request code found.")
        print("  The adapter may use a completely different protocol.")


def _run_sniff(ap, args, log):
    """Listen for 802.11 frames and print auth/assoc/data."""
    verbose = args.verbose

    print(f"\n{'=' * 50}")
    print("  Sniffing for 802.11 frames...")
    print("  Move near a Wi-Fi router to see beacons")
    print("  Press Ctrl+C to stop")
    print(f"{'=' * 50}\n")

    from .evil_twin.usb.capture import CaptureSession
    cap = CaptureSession()
    system = __import__("platform").system()

    if system == "Darwin":
        iface = args.iface or "en0"
        cap.open(interface=iface, channel=6)
        print(f"  Using libpcap on {iface} (macOS capture backend)")
    else:
        cap.open(usb_dev=ap.dev, ep_rx=ap.ep_rx)
        ap.init_monitor_rx()
        print(f"  Using USB bulk reads (EP 0x{ap.ep_rx:02x})")

    frame_count = 0
    reject_count = 0
    try:
        while True:
            raw = cap.read_frame(timeout=1.0)
            if raw is None:
                continue

            frame = ap._try_parse_rx(raw) if system != "Darwin" else raw
            if frame is None or len(frame) < 2:
                reject_count += 1
                if verbose:
                    hex_head = ' '.join(f'{b:02x}' for b in raw[:32])
                    print(f"  [REJECTED] {len(raw)} bytes: {hex_head}")
                continue

            fc = struct.unpack('<H', frame[0:2])[0]
            ftype = (fc >> 2) & 0x03
            subtype = (fc >> 4) & 0x0F
            frame_count += 1
            ts = time.strftime("%H:%M:%S")

            if ftype == 0:  # Management
                _da, sa, bssid = frame[4:10], frame[10:16], frame[16:22]
                names = {
                    0x00: "ASSOC_REQ", 0x01: "ASSOC_RESP",
                    0x04: "PROBE_REQ", 0x05: "PROBE_RESP",
                    0x08: "BEACON", 0x0B: "AUTH",
                    0x0A: "DISASSOC", 0x0C: "DEAUTH",
                }
                name = names.get(subtype, f"MGMT_{subtype:02x}")
                if subtype in (0x08, 0x05):
                    ssid = ap._extract_ssid(frame)
                    print(f"  [{ts}] #{frame_count} {name} "
                          f"{bssid.hex(':')} SSID='{ssid}'")
                elif subtype == 0x04:
                    ssid = ap._extract_ssid(frame)
                    print(f"  [{ts}] #{frame_count} {name} "
                          f"from {sa.hex(':')} SSID='{ssid}'")
                else:
                    print(f"  [{ts}] #{frame_count} {name} from {sa.hex(':')}")

            elif ftype == 2:  # Data
                ra, ta = frame[4:10], frame[10:16]
                print(f"  [{ts}] #{frame_count} DATA "
                      f"{ta.hex(':')} -> {ra.hex(':')} ({len(frame)} bytes)")

    except KeyboardInterrupt:
        pass

    cap.close()
    print(f"\n  Stopped. Parsed: {frame_count}, Rejected: {reject_count}")


def _run_start_ap(ap, args, log):
    """Start a fake AP: RCR + beacon TX + auth/assoc response."""
    from .evil_twin.ap.frames import craft_beacon, craft_auth_response, craft_assoc_response
    from .evil_twin.usb.capture import CaptureSession

    ap_mac = ap.read_efuse_mac() or b'\x02\x00\x00\x00\x00\x01'
    ssid = args.ssid
    channel = args.channel

    cap = CaptureSession()
    system = __import__("platform").system()

    if system == "Darwin":
        iface = args.iface or "en0"
        cap.open(interface=iface, channel=channel)
        ap.init_monitor_rx()
        print(f"\n{'=' * 50}")
        print(f"  Starting AP: SSID='{ssid}'")
        print(f"  BSSID={ap_mac.hex(':')}  Channel={channel}")
        print(f"  Capture: libpcap on {iface}")
        print("  Listening for auth/assoc requests...")
        print("  Press Ctrl+C to stop")
        print(f"{'=' * 50}\n")
    else:
        cap.open(usb_dev=ap.dev, ep_rx=ap.ep_rx)
        ap.init_monitor_rx()
        print(f"\n{'=' * 50}")
        print(f"  Starting AP: SSID='{ssid}'")
        print(f"  BSSID={ap_mac.hex(':')}  Channel={channel}")
        print("  Listening for auth/assoc requests...")
        print("  Press Ctrl+C to stop")
        print(f"{'=' * 50}\n")

    beacon = craft_beacon(ap_mac, ssid, channel, seq=0)

    mgmt_seq = 1
    next_beacon = time.monotonic()
    beacon_count = 0

    try:
        while True:
            now = time.monotonic()

            if now >= next_beacon:
                try:
                    ap.dev.write(ap.ep_tx, beacon, timeout=50)
                    beacon_count += 1
                except Exception:
                    pass
                next_beacon = now + 0.1

            raw = cap.read_frame(timeout=0.01)
            if raw is None:
                continue

            frame = ap._try_parse_rx(raw) if system != "Darwin" else raw
            if frame is None or len(frame) < 24:
                continue

            fc = struct.unpack('<H', frame[0:2])[0]
            ftype = (fc >> 2) & 0x03
            subtype = (fc >> 4) & 0x0F

            if ftype != 0:
                continue

            _da, sa, _bssid = frame[4:10], frame[10:16], frame[16:22]

            if subtype == 0x0B:  # Auth Request
                print(f"  [AUTH REQ] from {sa.hex(':')}")
                resp = craft_auth_response(sa, ap_mac, mgmt_seq)
                mgmt_seq = (mgmt_seq + 1) & 0xFFF
                ap.dev.write(ap.ep_tx, resp, timeout=50)
                print(f"  [AUTH RESP] sent to {sa.hex(':')}")

            elif subtype == 0x00:  # Assoc Request
                print(f"  [ASSOC REQ] from {sa.hex(':')}")
                resp = craft_assoc_response(sa, ap_mac, aid=1, seq=mgmt_seq)
                mgmt_seq = (mgmt_seq + 1) & 0xFFF
                ap.dev.write(ap.ep_tx, resp, timeout=50)
                print(f"  [ASSOC RESP] sent to {sa.hex(':')} (AID=1)")
                ap.station_assoc(sa)

            elif subtype == 0x04:  # Probe Request
                probe_ssid = ap._extract_ssid(frame)
                if probe_ssid == ssid or probe_ssid == '':
                    print(f"  [PROBE REQ] from {sa.hex(':')} "
                          f"SSID='{probe_ssid}'")

    except KeyboardInterrupt:
        print(f"\n\n  Stopped. Beacons sent: {beacon_count}")

    cap.close()


if __name__ == "__main__":
    main()
