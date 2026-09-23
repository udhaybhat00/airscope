"""Standalone RTL8812AU monitor mode diagnostic.

Usage:
    uv run python -m airscope.diagnose                # 4-step practical test
    uv run python -m airscope.diagnose --verbose      # debug logging
    uv run python -m airscope.diagnose --sniff        # sniff for auth/assoc frames
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
    parser.add_argument("--start-ap", action="store_true",
                        help="Start a live AP (requires --ssid and --channel)")
    parser.add_argument("--ssid", default="TestNet", help="SSID for --start-ap")
    parser.add_argument("--channel", type=int, default=6, help="Channel for --start-ap")
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

    if args.start_ap:
        _run_start_ap(ap, args, log)
    elif args.sniff:
        _run_sniff(ap, log)
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


def _run_sniff(ap, log):
    """Listen for 802.11 frames and print auth/assoc/data."""
    import usb.core

    ap.init_monitor_rx()

    print(f"\n{'=' * 50}")
    print("  Sniffing for 802.11 frames...")
    print("  Move near a Wi-Fi router to see beacons")
    print("  Press Ctrl+C to stop")
    print(f"{'=' * 50}\n")

    frame_count = 0
    try:
        while True:
            try:
                data = ap.dev.read(ap.ep_rx, 4096, timeout=1000)
                if not data:
                    continue

                frame = ap._try_parse_rx(bytes(data))
                if frame is None or len(frame) < 2:
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
                    if subtype in (0x08, 0x05):  # Beacon/Probe Resp
                        ssid = ap._extract_ssid(frame)
                        print(f"  [{ts}] #{frame_count} {name} {bssid.hex(':')} SSID='{ssid}'")
                    elif subtype == 0x04:  # Probe Req
                        ssid = ap._extract_ssid(frame)
                        print(f"  [{ts}] #{frame_count} {name} from {sa.hex(':')} SSID='{ssid}'")
                    else:
                        print(f"  [{ts}] #{frame_count} {name} from {sa.hex(':')}")

                elif ftype == 2:  # Data
                    ra, ta = frame[4:10], frame[10:16]
                    print(f"  [{ts}] #{frame_count} DATA {ta.hex(':')} -> {ra.hex(':')} ({len(frame)} bytes)")

            except usb.core.USBError as e:
                if e.errno == 19:
                    print("\n  USB disconnected.")
                    break
                continue
    except KeyboardInterrupt:
        print(f"\n\n  Stopped. Total frames: {frame_count}")

    ap.deinit_monitor_rx()


def _run_start_ap(ap, args, log):
    """Start a fake AP: RCR + beacon TX + auth/assoc response."""
    import usb.core
    from .evil_twin.ap.frames import craft_beacon, craft_auth_response, craft_assoc_response

    ap_mac = ap.read_efuse_mac() or b'\x02\x00\x00\x00\x00\x01'
    ssid = args.ssid
    channel = args.channel

    ap.init_monitor_rx()
    beacon = craft_beacon(ap_mac, ssid, channel, seq=0)

    print(f"\n{'=' * 50}")
    print(f"  Starting AP: SSID='{ssid}'")
    print(f"  BSSID={ap_mac.hex(':')}  Channel={channel}")
    print("  Listening for auth/assoc requests...")
    print("  Press Ctrl+C to stop")
    print(f"{'=' * 50}\n")

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

            try:
                data = ap.dev.read(ap.ep_rx, 4096, timeout=10)
                if not data:
                    continue

                frame = ap._try_parse_rx(bytes(data))
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
                        print(f"  [PROBE REQ] from {sa.hex(':')} SSID='{probe_ssid}'")

            except usb.core.USBError as e:
                if e.errno == 19:
                    print("\n  USB disconnected.")
                    break
                continue

    except KeyboardInterrupt:
        print(f"\n\n  Stopped. Beacons sent: {beacon_count}")

    ap.deinit_monitor_rx()


if __name__ == "__main__":
    main()
