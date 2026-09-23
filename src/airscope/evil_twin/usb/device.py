"""Cross-platform USB device abstraction."""

import platform
import logging

log = logging.getLogger(__name__)

USB_VID = 0x0BDA
USB_PIDS = [0xC812, 0xA801, 0xC820, 0x3593]


def find_adapter():
    """Find the RTL8812AU/8814AU USB adapter. Cross-platform."""
    import usb.core
    import usb.util

    for pid in USB_PIDS:
        dev = usb.core.find(idVendor=USB_VID, idProduct=pid)
        if dev is not None:
            log.info(f"Found adapter: {USB_VID:04x}:{pid:04x}")
            return dev

    dev = usb.core.find(idVendor=USB_VID)
    if dev is not None:
        log.info(f"Found Realtek adapter (uncommon PID): {dev.idProduct:04x}")
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

    log.info(f"USB endpoints: RX=0x{ep_rx:02x}, TX=0x{ep_tx:02x}, CTRL=0x{ep_ctrl:02x}")
    return ep_rx, ep_tx, ep_ctrl


def get_ctrl_endpoint(dev) -> int:
    """Get control endpoint address (EP0) for vendor requests.

    For RTL8812AU the default control pipe is always 0x00.
    Prefer using setup_device() which returns (ep_rx, ep_tx, ep_ctrl).
    """
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
        import os
        if not os.access('/dev/bus/usb', os.R_OK):
            log.warning(
                "Linux: May need udev rule or sudo for USB access.\n"
                'Add: SUBSYSTEM=="usb", ATTR{idVendor}=="0bda", MODE=="0666"'
            )

    if system == "Windows":
        pass
