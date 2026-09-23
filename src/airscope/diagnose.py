"""Standalone RTL8812AU AP-mode diagnostic.

Usage:
    uv run python -m airscope.diagnose
    uv run python -m airscope.diagnose --verbose
"""

import sys
import logging
import argparse


def main():
    parser = argparse.ArgumentParser(description="RTL8812AU AP-mode diagnostic")
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
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
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)
    finally:
        try:
            ap.deinit_ap_mode()
        except Exception:
            pass
        try:
            import usb.util
            usb.util.dispose_resources(dev)
        except Exception:
            pass
        log.info("Adapter released.")


if __name__ == "__main__":
    main()
