"""Cross-platform USB device abstraction."""

import os
import platform
import logging

log = logging.getLogger(__name__)

USB_VID = 0x0BDA
USB_PIDS = [0xC812, 0xA801, 0xC820, 0x3593]


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


def find_adapter():
    """Find the RTL8812AU/8814AU USB adapter. Cross-platform."""
    _init_usb_backend()
    import usb.core

    for pid in USB_PIDS:
        dev = usb.core.find(idVendor=USB_VID, idProduct=pid)
        if dev is not None:
            log.info("Found adapter: %04x:%04x", USB_VID, pid)
            return dev

    dev = usb.core.find(idVendor=USB_VID)
    if dev is not None:
        log.info("Found Realtek adapter (uncommon PID): %04x", dev.idProduct)
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
