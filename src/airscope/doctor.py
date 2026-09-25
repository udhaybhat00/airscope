"""Pre-flight check. Run before the main app to catch setup issues early."""

import sys
import platform
import shutil
from dataclasses import dataclass
from enum import Enum


class Status(Enum):
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"


@dataclass
class CheckResult:
    name: str
    status: Status
    message: str
    fix: str = ""


def run_doctor() -> list[CheckResult]:
    results: list[CheckResult] = []
    system = platform.system()

    py_ver = sys.version_info
    if py_ver >= (3, 11):
        results.append(CheckResult(
            "Python version", Status.OK,
            f"{py_ver.major}.{py_ver.minor}.{py_ver.micro}",
        ))
    else:
        results.append(CheckResult(
            "Python version", Status.FAIL,
            f"{py_ver.major}.{py_ver.minor}.{py_ver.micro} (need 3.11+)",
            "Install Python 3.11+ or use: uv python install 3.12",
        ))

    try:
        from .evil_twin.usb.device import _init_usb_backend
        import usb.core
        _init_usb_backend()
        devs = list(usb.core.find(find_all=True))
        results.append(CheckResult(
            "libusb / PyUSB backend", Status.OK,
            f"Backend active, {len(devs)} USB devices visible",
        ))
    except Exception as e:
        if system == "Darwin":
            fix = "brew install libusb"
        elif system == "Windows":
            fix = "pip install pyusb  (bundles libusb0.dll)"
        else:
            fix = "sudo apt install libusb-1.0-0  (or: sudo dnf install libusb1)"
        results.append(CheckResult(
            "libusb / PyUSB backend", Status.FAIL, str(e), fix,
        ))

    try:
        from .evil_twin.usb.device import find_adapter
        dev = find_adapter()
        if dev:
            results.append(CheckResult(
                "Wi-Fi adapter", Status.OK,
                f"Found {dev.idVendor:04x}:{dev.idProduct:04x}",
            ))
        else:
            results.append(CheckResult(
                "Wi-Fi adapter", Status.FAIL,
                "No supported RTL8812AU/8814AU adapter detected",
                "Plug in adapter. If it's a different PID, run:\n"
                "  uv run python -m airscope.doctor --list-usb\n"
                "Then add the VID:PID to ~/.airscope/adapters.json",
            ))
    except Exception as e:
        results.append(CheckResult(
            "Wi-Fi adapter", Status.FAIL, str(e),
            "Check USB connection and driver",
        ))

    if system == "Windows":
        results.append(CheckResult(
            "WinUSB driver", Status.WARN,
            "Verify adapter uses WinUSB driver (not MUSB/Android)",
            "If adapter not found: download Zadig (zadig.akeo.ie) -> "
            "Replace driver -> WinUSB",
        ))
    elif system == "Linux":
        import os
        if os.access('/dev/bus/usb', os.R_OK):
            results.append(CheckResult(
                "USB permissions", Status.OK, "Can access /dev/bus/usb",
            ))
        else:
            results.append(CheckResult(
                "USB permissions", Status.WARN,
                "May need udev rule or sudo",
                'echo \'SUBSYSTEM=="usb", ATTR{idVendor}=="0bda", MODE="0666"\' | '
                'sudo tee /etc/udev/rules.d/99-airscope.rules && sudo udevadm control --reload',
            ))
    elif system == "Darwin":
        results.append(CheckResult(
            "IOKit authorization", Status.OK,
            "macOS: first run will prompt for USB access (click Allow)",
        ))

    if shutil.which("uv"):
        results.append(CheckResult("uv", Status.OK, "Found in PATH"))
    else:
        results.append(CheckResult(
            "uv", Status.WARN,
            "uv not found (using system Python)",
            "Install: curl -LsSf https://astral.sh/uv/install.sh | sh",
        ))

    if system == "Darwin" and not __import__("os").environ.get("AIRSCOPE_IN_VM"):
        results.append(CheckResult(
            "Platform capabilities", Status.WARN,
            "macOS: scanning/capture works. TX injection (deauth, evil twin) "
            "requires Linux.",
            "Plug adapter into a Linux box (Raspberry Pi, old laptop, cloud VM), "
            "run airscope there, then:\n"
            "  airscope --connect user@linux-host",
        ))
    elif system == "Windows" and not __import__("os").environ.get("AIRSCOPE_IN_VM"):
        import shutil as _shutil
        if _shutil.which("wsl"):
            results.append(CheckResult(
                "Platform capabilities", Status.OK,
                "Windows + WSL2: full features. Attach adapter with:\n"
                "  usbipd wsl attach --busid <BUSID>",
            ))
        else:
            results.append(CheckResult(
                "Platform capabilities", Status.WARN,
                "WSL2 not found. Install it for full features:\n"
                "  wsl --install",
            ))

    return results


def print_report(results: list[CheckResult]) -> bool:
    icons = {Status.OK: "+", Status.WARN: "!", Status.FAIL: "x"}

    print()
    print("=" * 55)
    print("  airscope -- Pre-flight Check")
    print("=" * 55)
    print()

    has_fail = False
    for r in results:
        icon = icons[r.status]
        print(f"  [{icon}] {r.name}")
        print(f"      {r.message}")
        if r.fix and r.status in (Status.FAIL, Status.WARN):
            print(f"      Fix: {r.fix}")
        print()
        if r.status == Status.FAIL:
            has_fail = True

    print("=" * 55)
    if has_fail:
        print("  Setup incomplete. Fix the issues above, then re-run.")
    else:
        print("  All checks passed. Ready to go!")
    print("=" * 55)
    print()

    return not has_fail


def list_usb_devices():
    import usb.core
    from .evil_twin.usb.device import _init_usb_backend
    _init_usb_backend()
    print()
    print("All USB devices:")
    print()
    for dev in usb.core.find(find_all=True):
        vid = dev.idVendor
        pid = dev.idProduct
        mfg = ""
        prod = ""
        try:
            mfg = dev.manufacturer or ""
            prod = dev.product or ""
        except Exception:
            pass
        marker = ""
        if vid in (0x0BDA, 0x13B1, 0x2357, 0x2001):
            marker = "  <-- likely Wi-Fi adapter"
        print(f"  {vid:04x}:{pid:04x}  {mfg} {prod}{marker}")
    print()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="airscope pre-flight check")
    parser.add_argument("--list-usb", action="store_true",
                        help="List all USB devices (find your adapter's VID:PID)")
    parser.add_argument("--add-adapter", nargs=2, metavar=("VID", "PID"),
                        help="Add a custom adapter (e.g., --add-adapter 13b1 011b)")
    args = parser.parse_args()

    if args.list_usb:
        list_usb_devices()
        return

    if args.add_adapter:
        vid = int(args.add_adapter[0], 16)
        pid = int(args.add_adapter[1], 16)
        from .evil_twin.usb.device import add_adapter
        add_adapter(vid, pid)
        print(f"Added adapter {vid:04x}:{pid:04x} to ~/.airscope/adapters.json")
        print("Re-run the app to use it.")
        return

    results = run_doctor()
    ok = print_report(results)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
