"""Cross-platform USB device abstraction."""

import json
import os
import platform
import logging
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_ADAPTERS = [
    (0x0BDA, 0xC812),
    (0x0BDA, 0xA801),
    (0x0BDA, 0xC820),
    (0x0BDA, 0x3593),
    (0x13B1, 0x011B),
    (0x13B1, 0x008E),
    (0x2357, 0x0601),
    (0x2357, 0x0602),
    (0x2001, 0x1234),
]

USER_ADAPTERS_FILE = Path.home() / ".airscope" / "adapters.json"


def _load_user_adapters() -> list[tuple[int, int]]:
    if USER_ADAPTERS_FILE.exists():
        try:
            data = json.loads(USER_ADAPTERS_FILE.read_text())
            return [(int(x[0], 16), int(x[1], 16)) for x in data]
        except Exception:
            pass
    return []


def _save_user_adapters(adapters: list[tuple[int, int]]):
    USER_ADAPTERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = [[f"{v:04x}", f"{p:04x}"] for v, p in adapters]
    USER_ADAPTERS_FILE.write_text(json.dumps(data, indent=2))


def add_adapter(vid: int, pid: int):
    adapters = _load_user_adapters()
    if (vid, pid) not in adapters:
        adapters.append((vid, pid))
        _save_user_adapters(adapters)


def _init_usb_backend():
    """Initialize PyUSB backend. On macOS, explicitly point to Homebrew libusb."""
    import usb.core
    import usb.backend.libusb1

    if platform.system() != "Darwin":
        return

    try:
        list(usb.core.find(find_all=True))
        return
    except usb.core.NoBackendError:
        pass

    candidates = [
        "/opt/homebrew/lib/libusb-1.0.dylib",
        "/opt/homebrew/lib/libusb-1.0.0.dylib",
        "/usr/local/lib/libusb-1.0.dylib",
        "/usr/local/lib/libusb-1.0.0.dylib",
        "/opt/local/lib/libusb-1.0.dylib",
    ]

    for path in candidates:
        if os.path.exists(path):
            backend = usb.backend.libusb1.get_backend(
                find_library=lambda name, p=path: p
            )
            usb.core.default_backend = backend
            log.info("PyUSB backend: %s", path)
            return

    raise RuntimeError(
        "libusb not found. Install with: brew install libusb\n"
        "Or set: export DYLD_LIBRARY_PATH=\"/opt/homebrew/lib:$DYLD_LIBRARY_PATH\""
    )


def find_adapter(vid: int = None, pid: int = None):
    """Find the Wi-Fi adapter.

    If vid/pid are provided, look for that specific device.
    Otherwise, search all known + user-added adapters.
    """
    _init_usb_backend()
    import usb.core

    if vid and pid:
        return usb.core.find(idVendor=vid, idProduct=pid)

    all_adapters = DEFAULT_ADAPTERS + _load_user_adapters()

    for v, p in all_adapters:
        dev = usb.core.find(idVendor=v, idProduct=p)
        if dev is not None:
            log.info("Found adapter: %04x:%04x", v, p)
            return dev

    return None


def setup_device(dev) -> tuple[int, int, int]:
    """Configure the USB device for monitor/AP mode.
    Returns (ep_rx, ep_tx, ep_ctrl)."""
    import usb.util

    try:
        dev.reset()
    except Exception:
        pass

    try:
        if dev.is_kernel_driver_active(0):
            dev.detach_kernel_driver(0)
    except (NotImplementedError, usb.core.USBError):
        pass

    cfg = dev.get_active_configuration()
    dev.set_configuration(cfg)

    intf = cfg[(0, 0)]
    ep_rx = None
    ep_tx = None
    ep_ctrl = 0x00

    for ep in intf:
        if usb.util.endpoint_type(ep.bmAttributes) == usb.util.ENDPOINT_TYPE_BULK:
            if usb.util.endpoint_direction(ep.bEndpointAddress) == usb.util.ENDPOINT_IN:
                ep_rx = ep.bEndpointAddress
            else:
                ep_tx = ep.bEndpointAddress
        elif usb.util.endpoint_type(ep.bmAttributes) == usb.util.ENDPOINT_TYPE_CONTROL:
            ep_ctrl = ep.bEndpointAddress

    if ep_rx is None or ep_tx is None:
        raise RuntimeError(f"Could not find bulk endpoints (rx={ep_rx}, tx={ep_tx})")

    log.info("USB endpoints: RX=0x%02x, TX=0x%02x, CTRL=0x%02x", ep_rx, ep_tx, ep_ctrl)
    return ep_rx, ep_tx, ep_ctrl


def get_ctrl_endpoint(dev) -> int:
    """Get control endpoint address (EP0) for vendor requests."""
    return 0x00


def platform_setup():
    """Platform-specific initialization at startup."""
    system = platform.system()

    if system == "Windows":
        import ctypes
        ctypes.windll.winmm.timeBeginPeriod(1)
        log.info("Windows: timer resolution set to 1ms")

    elif system == "Darwin":
        log.info("macOS: using kqueue event loop (default)")

    elif system == "Linux":
        log.info("Linux: using epoll event loop")
        if not os.access('/dev/bus/usb', os.R_OK):
            log.warning(
                "Linux: May need udev rule or sudo for USB access.\n"
                'Add: SUBSYSTEM=="usb", ATTR{idVendor}=="0bda", MODE=="0666"'
            )
