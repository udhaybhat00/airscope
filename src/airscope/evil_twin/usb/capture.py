"""Cross-platform 802.11 frame capture.

On Linux: PyUSB bulk reads (kernel passes frames through).
On macOS: libpcap via ctypes (kernel blocks USB RX, use system capture).
On Windows: PyUSB bulk reads (with WinUSB driver).

No new pip dependencies -- libpcap ships with macOS and Linux.
"""

import ctypes
import ctypes.util
import os
import platform
import struct
import time
import logging
from typing import Optional

log = logging.getLogger(__name__)

try:
    import usb.core
except ImportError:
    usb_core = None
else:
    usb_core = usb.core


class CaptureSession:
    """Platform-abstracted 802.11 frame capture."""

    def __init__(self):
        self._backend = None
        self._pcap = None
        self._pcap_handle = None
        self._usb_dev = None
        self._ep_rx = 0x81

    def open(self, interface: str = None, channel: int = 6,
             usb_dev=None, ep_rx: int = 0x81):
        system = platform.system()

        if system == "Darwin":
            self._backend = "pcap"
            self._open_pcap(interface or self._find_mon_iface(), channel)
        else:
            self._backend = "usb"
            self._usb_dev = usb_dev
            self._ep_rx = ep_rx

        log.info("Capture backend: %s (iface=%s)", self._backend, interface)

    def read_frame(self, timeout: float = 1.0) -> Optional[bytes]:
        if self._backend == "pcap":
            return self._read_pcap(timeout)
        return self._read_usb(timeout)

    def close(self):
        if self._backend == "pcap" and self._pcap_handle and self._pcap:
            try:
                self._pcap.pcap_close(self._pcap_handle)
            except Exception:
                pass
            self._pcap_handle = None

    def _find_airport(self) -> str:
        candidates = [
            "/System/Library/PrivateFrameworks/Apple80211.framework"
            "/Versions/Current/Resources/airport",
            "/usr/libexec/airport",
            "/System/Library/PrivateFrameworks/Apple80211.framework"
            "/Versions/A/Resources/airport",
        ]
        for path in candidates:
            if os.path.exists(path):
                return path
        import shutil
        return shutil.which("airport") or ""

    def _find_mon_iface(self) -> str:
        import subprocess
        import re

        try:
            out = subprocess.check_output(
                ["networksetup", "-listallhardwareports"],
                text=True, timeout=5
            )
            usb_iface = None
            for block in out.split("Hardware Port:"):
                if "USB" in block.upper() or "REALTEK" in block.upper():
                    m = re.search(r"Device:\s*(en\d+)", block)
                    if m:
                        usb_iface = m.group(1)
                        break
            if usb_iface:
                return usb_iface
        except Exception:
            pass

        try:
            out = subprocess.check_output(
                ["ifconfig"], text=True, timeout=5
            )
            for line in out.split("\n"):
                if line.startswith("en") and "inet " not in line:
                    m = re.match(r"(en\d+):", line)
                    if m:
                        iface = m.group(1)
                        if iface != "en0":
                            return iface
        except Exception:
            pass

        return "en0"

    def _open_pcap(self, iface: str, channel: int):
        import subprocess
        airport = self._find_airport()
        if airport:
            try:
                subprocess.run(
                    ["sudo", airport, "-c", str(channel)],
                    capture_output=True, timeout=5
                )
                time.sleep(0.5)
            except Exception as e:
                log.warning("airport channel set failed: %s", e)

        lib_path = ctypes.util.find_library("pcap")
        if not lib_path:
            for p in ["/usr/lib/libpcap.dylib",
                       "/usr/local/lib/libpcap.dylib",
                       "/opt/homebrew/lib/libpcap.dylib"]:
                if os.path.exists(p):
                    lib_path = p
                    break

        if not lib_path:
            log.error("libpcap not found, falling back to USB")
            self._backend = "usb"
            return

        pcap = ctypes.CDLL(lib_path)
        errbuf = ctypes.create_string_buffer(256)
        handle = pcap.pcap_open_live(
            iface.encode(), 65535, 1, 100, errbuf
        )
        if not handle:
            err = errbuf.value.decode()
            if "Permission denied" in err or "cannot open BPF" in err:
                log.error(
                    "BPF permission denied. Run with sudo, or fix with:\n"
                    "  sudo chgrp wheel /dev/bpf*\n"
                    "  sudo chmod g+r /dev/bpf*"
                )
            else:
                log.error("pcap_open_live: %s", err)
            self._backend = "usb"
            return

        pcap.pcap_setdirection(handle, 1)
        self._pcap = pcap
        self._pcap_handle = handle
        log.info("pcap opened on %s", iface)

    def _read_pcap(self, timeout: float) -> Optional[bytes]:
        try:
            pcap = self._pcap
            handle = self._pcap_handle

            header_ptr = ctypes.c_void_p()
            data_ptr = ctypes.c_void_p()

            ret = pcap.pcap_next_ex(
                handle,
                ctypes.byref(header_ptr),
                ctypes.byref(data_ptr),
            )

            if ret == 1 and header_ptr and data_ptr:
                hdr_bytes = ctypes.string_at(header_ptr, 16)
                caplen = int.from_bytes(hdr_bytes[8:12], "little")
                if caplen > 0 and caplen < 65535:
                    pkt = ctypes.string_at(data_ptr, caplen)
                    if len(pkt) >= 2:
                        fc = struct.unpack("<H", pkt[0:2])[0]
                        ftype = (fc >> 2) & 0x03
                        if ftype in (0, 1, 2):
                            return pkt
        except Exception as e:
            log.debug("pcap read error: %s", e)
        return None

    def _read_usb(self, timeout: float) -> Optional[bytes]:
        if not self._usb_dev:
            return None
        try:
            ms = int(timeout * 1000)
            data = self._usb_dev.read(self._ep_rx, 4096, timeout=ms)
            if data:
                return bytes(data)
        except Exception:
            pass
        return None
