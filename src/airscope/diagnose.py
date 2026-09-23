"""Standalone RTL8812AU AP-mode diagnostic.

Usage:
    uv run python -m airscope.diagnose                # run 8-step diagnostic
    uv run python -m airscope.diagnose --verbose      # debug logging
    uv run python -m airscope.diagnose --start-ap     # start live AP
    uv run python -m airscope.diagnose --sniff        # sniff for auth frames
"""

import sys
import time
import logging
import argparse


def main():
    parser = argparse.ArgumentParser(description="RTL8812AU AP-mode diagnostic")
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    parser.add_argument("--start-ap", action="store_true",
                        help="Start a live AP (requires --ssid and --channel)")
    parser.add_argument("--sniff", action="store_true",
                        help="Sniff for incoming auth/assoc frames")
    parser.add_argument("--ssid", default="TestNet", help="SSID for --start-ap mode")
    parser.add_argument("--channel", type=int, default=6, help="Channel for --start-ap mode")
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

    # --- Find adapter ---
    log.info("Searching for RTL8812AU/8814AU adapter...")
    dev = find_adapter()
    if dev is None:
        log.error("No supported adapter found.")
        log.error("Check: USB connected, driver installed (WinUSB on Windows).")
        sys.exit(1)

    log.info("Found: %04x:%04x", dev.idVendor, dev.idProduct)

    # --- Setup ---
    ep_rx, ep_tx, ep_ctrl = setup_device(dev)
    log.info("Endpoints: RX=0x%02x  TX=0x%02x  CTRL=0x%02x", ep_rx, ep_tx, ep_ctrl)

    # --- Run diagnostic ---
    ap = Rtl8812auAP(dev, ep_ctrl=ep_ctrl)

    if args.start_ap:
        _run_start_ap(ap, dev, ep_rx, ep_tx, args, log)
    elif args.sniff:
        _run_sniff(ap, dev, ep_rx, ep_tx, log)
    else:
        _run_diagnostic(ap, log)

    try:
        import usb.util
        usb.util.dispose_resources(dev)
    except Exception:
        pass
    log.info("Adapter released.")


def _run_diagnostic(ap, log):
    """Run the 8-step diagnostic."""
    print("\n" + "=" * 60)
    print("  RTL8812AU AP-Mode Diagnostic")
    print("=" * 60 + "\n")

    try:
        ap.diagnose()
        print("\n" + "=" * 60)
        print("  ALL STEPS PASSED -- AP mode is ready")
        print("=" * 60)
    except Exception as e:
        print(f"\n{'=' * 60}")
        print(f"  FAILED: {e}")
        print(f"{'=' * 60}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        try:
            ap.deinit_ap_mode()
        except Exception:
            pass


def _run_start_ap(ap, dev, ep_rx, ep_tx, args, log):
    """Start a live AP and send beacons."""
    from .evil_twin.ap.ap_core import APStateMachine
    from .evil_twin.ap.frames import craft_beacon
    from .evil_twin.usb.worker import UsbWorker

    ssid = args.ssid
    channel = args.channel
    ap_mac = b'\x00\x11\x22\x33\x44\x55'

    print(f"\n{'=' * 60}")
    print(f"  Starting AP: SSID={ssid}  Channel={channel}")
    print(f"  BSSID={':'.join(f'{b:02x}' for b in ap_mac)}")
    print("  Press Ctrl+C to stop")
    print(f"{'=' * 60}\n")

    ap.init_ap_mode(ap_mac, ssid, channel)

    beacon = craft_beacon(ap_mac, ssid, channel, seq=0)

    ap_sm = APStateMachine(ap_mac, ssid, channel, usb_tx=lambda f, **kw: None)

    worker = UsbWorker(
        usb_dev=dev,
        ep_rx=ep_rx,
        ep_tx=ep_tx,
        ap_state_machine=ap_sm,
        beacon_frame=beacon,
        deauth_frames=[],
        deauth_interval=0.1,
        beacon_interval=0.1,
        rtl_ap=ap,
    )
    worker.start()

    try:
        while True:
            time.sleep(1)
            stats = worker.stats
            clients = len(ap._stations)
            print(f"\r  TX={stats['tx']}  RX={stats['rx']}  Clients={clients}  ", end="", flush=True)
    except KeyboardInterrupt:
        print("\n\n  Stopping AP...")
    finally:
        worker.stop()
        ap.deinit_ap_mode()
        print("  AP stopped.")


def _run_sniff(ap, dev, ep_rx, ep_tx, log):
    """Sniff for incoming auth/assoc frames."""
    from .evil_twin.ap.frames import parse_fc, FC_TYPE_MGMT

    print(f"\n{'=' * 60}")
    print("  Sniffing for auth/assoc frames...")
    print("  Connect a device to see traffic")
    print("  Press Ctrl+C to stop")
    print(f"{'=' * 60}\n")

    frame_count = 0
    try:
        while True:
            try:
                data = dev.read(ep_rx, 4096, timeout=500)
                if data:
                    raw = bytes(data)
                    frame, mac_id = ap.parse_rx_descriptor(raw)
                    if frame and len(frame) >= 2:
                        fc_type, subtype, to_ds, from_ds = parse_fc(frame)
                        frame_count += 1
                        ts = time.strftime("%H:%M:%S")
                        if fc_type == FC_TYPE_MGMT:
                            type_names = {
                                0x00: "ASSOC_REQ", 0x01: "ASSOC_RESP",
                                0x04: "PROBE_REQ", 0x05: "PROBE_RESP",
                                0x08: "BEACON", 0x0B: "AUTH",
                                0x0A: "DISASSOC", 0x0C: "DEAUTH",
                            }
                            name = type_names.get(subtype, f"SUBTYPE_{subtype:02x}")
                            if len(frame) >= 22:
                                sa = frame[10:16]
                                sa_str = ':'.join(f'{b:02x}' for b in sa)
                                print(f"  [{ts}] #{frame_count} {name} from {sa_str} mac_id={mac_id}")
                            else:
                                print(f"  [{ts}] #{frame_count} {name} (short) mac_id={mac_id}")
                        else:
                            if len(frame) >= 22:
                                sa = frame[10:16]
                                sa_str = ':'.join(f'{b:02x}' for b in sa)
                                print(f"  [{ts}] #{frame_count} DATA from {sa_str} mac_id={mac_id} len={len(frame)}")
            except Exception as e:
                import usb.core
                if isinstance(e, usb.core.USBError) and e.errno == 19:
                    print("\n  USB device disconnected.")
                    break
                continue
    except KeyboardInterrupt:
        print(f"\n\n  Stopped. Total frames: {frame_count}")


if __name__ == "__main__":
    main()
