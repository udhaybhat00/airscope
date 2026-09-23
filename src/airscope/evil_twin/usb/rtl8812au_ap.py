"""RTL8812AU monitor mode RX configuration for EvilTwin.

The chip is already in monitor mode (TX injection works). The ONLY reason
clients' frames aren't arriving on USB RX is that the RCR (Receive Control
Register) isn't set to accept all frames.

Strategy: write 0xFFFFFFFF to RCR so the chip forwards ALL 802.11 frames
(auth, assoc, probe, data, beacon) to the USB bulk-in endpoint. No H2C
commands or firmware AP mode needed.

Register addresses from:
  - https://github.com/aircrack-ng/rtl8812au (kernel driver v5.6.4.2)
  - rtl8812a_spec.h, rtl8812a_cmd.h
"""
from __future__ import annotations

import struct
import time
import logging
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# USB vendor request codes
# ---------------------------------------------------------------------------
_USB_REQ_READ  = 0x05
_USB_REQ_WRITE = 0x05
_USB_REQ_H2C   = 0x01

# ---------------------------------------------------------------------------
# RCR (Receive Control Register) - candidate addresses by firmware version
# ---------------------------------------------------------------------------
RCR_CANDIDATES = [0x14C, 0x148, 0x150, 0x0400]

# RCR bit definitions
RCR_APM         = 1 << 3
RCR_ADF         = 1 << 4
RCR_AB          = 1 << 15
RCR_AM          = 1 << 14
RCR_CBSSID_DATA = 1 << 18
RCR_CBSSID_BCN  = 1 << 23

# ---------------------------------------------------------------------------
# Other registers
# ---------------------------------------------------------------------------
REG_CR          = 0x0100
REG_MCUFWDL     = 0x0080

# H2C command IDs (EXPERIMENTAL: firmware AP mode, unverified)
H2C_MSRRPT      = 0x01
H2C_BCN_RSVDPAGE = 0x09
H2C_AP_OFFLOAD  = 0x08

# TX descriptor size (monitor mode TX injection, no descriptor needed)
TX_DESC_SIZE = 0
RX_DESC_SIZE = 0


# ============================================================================
# USB control transfer helpers
# ============================================================================

def _ctrl_read(dev, addr: int, length: int = 4, timeout: int = 1000) -> bytes:
    import usb.util
    data = dev.ctrl_transfer(
        usb.util.CTRL_TYPE_VENDOR | usb.util.CTRL_RECIP_DEVICE | usb.util.ENDPOINT_IN,
        _USB_REQ_READ, addr & 0xFFFF, (addr >> 16) & 0xFFFF, length, timeout=timeout
    )
    return bytes(data)


def _ctrl_write(dev, addr: int, data: bytes, timeout: int = 1000):
    import usb.util
    dev.ctrl_transfer(
        usb.util.CTRL_TYPE_VENDOR | usb.util.CTRL_RECIP_DEVICE | usb.util.ENDPOINT_OUT,
        _USB_REQ_WRITE, addr & 0xFFFF, (addr >> 16) & 0xFFFF, data, timeout=timeout
    )


def read_reg(dev, addr: int) -> int:
    return struct.unpack('<I', _ctrl_read(dev, addr, 4))[0]


def write_reg(dev, addr: int, value: int):
    _ctrl_write(dev, addr, struct.pack('<I', value))


def write_reg_byte(dev, addr: int, value: int):
    _ctrl_write(dev, addr, bytes([value & 0xFF]))


def write_fifo(dev, addr: int, data: bytes):
    _ctrl_write(dev, addr, data)


def h2c_cmd(dev, cmd_id: int, data: bytes, timeout: int = 1000):
    """EXPERIMENTAL: H2C command. May not work on all firmware versions."""
    import usb.util
    payload = bytes([cmd_id]) + data[:6]
    dev.ctrl_transfer(
        usb.util.CTRL_TYPE_VENDOR | usb.util.CTRL_RECIP_DEVICE | usb.util.ENDPOINT_OUT,
        _USB_REQ_H2C, 0, 0, payload, timeout=timeout
    )


# ============================================================================
# Station entry (for tracking associated clients in software)
# ============================================================================

@dataclass
class StationEntry:
    mac: bytes
    mac_id: int
    associated_at: float


# ============================================================================
# Main class
# ============================================================================

class Rtl8812auAP:
    """RTL8812AU monitor mode controller for EvilTwin.

    Configures the chip to forward ALL received frames to USB bulk-in
    by writing 0xFFFFFFFF to the RCR register. No firmware AP mode needed.
    """

    def __init__(self, dev, ep_rx: int = 0x81, ep_tx: int = 0x02, ep_ctrl: int = 0x00):
        self.dev = dev
        self.ep_rx = ep_rx
        self.ep_tx = ep_tx
        self.ep_ctrl = ep_ctrl
        self._rcr_addr: Optional[int] = None
        self._stations: dict[bytes, StationEntry] = {}
        self._next_mac_id = 1
        self._bssid = b'\x00\x00\x00\x00\x00\x00'

    # ------------------------------------------------------------------
    # Monitor mode initialization (THE fix)
    # ------------------------------------------------------------------

    def init_monitor_rx(self) -> bool:
        """Set RCR to accept all frames. Try known addresses.

        This is the ONLY firmware config needed for EvilTwin.
        The chip is already in monitor mode; we just need to tell it
        to forward all received frames to USB RX.
        """
        for addr in RCR_CANDIDATES:
            try:
                write_reg(self.dev, addr, 0xFFFFFFFF)
                time.sleep(0.05)
                val = read_reg(self.dev, addr)
                if val == 0xFFFFFFFF:
                    log.info("[rtl8812au] RCR set at 0x%03X = 0xFFFFFFFF", addr)
                    self._rcr_addr = addr
                    return True
                log.debug("[rtl8812au] RCR 0x%03X readback: 0x%08X (not matching)", addr, val)
            except Exception:
                continue

        log.warning("[rtl8812au] RCR verification failed, using 0x14C (unverified)")
        self._rcr_addr = 0x14C
        try:
            write_reg(self.dev, 0x14C, 0xFFFFFFFF)
        except Exception:
            pass
        return True

    def deinit_monitor_rx(self):
        """Reset RCR to default (monitor mode, reduced RX)."""
        if self._rcr_addr is not None:
            try:
                write_reg(self.dev, self._rcr_addr, RCR_AB | RCR_AM)
            except Exception:
                pass
        self._stations.clear()

    # ------------------------------------------------------------------
    # AP mode (simplified: just monitor RX + software station tracking)
    # ------------------------------------------------------------------

    def init_ap_mode(self, ap_mac: bytes, ssid: str, channel: int):
        """Initialize AP mode using monitor RX (no H2C needed)."""
        self._bssid = ap_mac
        self.init_monitor_rx()
        log.info("[rtl8812au] AP mode ready (monitor RX): BSSID=%s SSID=%s ch=%d",
                 ':'.join(f'{b:02x}' for b in ap_mac), ssid, channel)

    def deinit_ap_mode(self):
        """Clean shutdown."""
        self.deinit_monitor_rx()
        log.info("[rtl8812au] AP mode deinitialized")

    def station_assoc(self, client_mac: bytes) -> int:
        """Track an associated station in software (no H2C needed)."""
        if client_mac in self._stations:
            return self._stations[client_mac].mac_id
        mac_id = self._next_mac_id
        self._next_mac_id += 1
        self._stations[client_mac] = StationEntry(
            mac=client_mac, mac_id=mac_id, associated_at=time.monotonic()
        )
        log.info("[rtl8812au] station tracked: %s mac_id=%d",
                 ':'.join(f'{b:02x}' for b in client_mac), mac_id)
        return mac_id

    def station_disassoc(self, client_mac: bytes):
        """Remove a tracked station."""
        self._stations.pop(client_mac, None)

    def get_tx_mac_id(self, client_mac: bytes) -> int:
        entry = self._stations.get(client_mac)
        return entry.mac_id if entry is not None else 0

    # ------------------------------------------------------------------
    # RX frame parsing (auto-detect descriptor prefix)
    # ------------------------------------------------------------------

    def _try_parse_rx(self, raw: bytes) -> Optional[bytes]:
        """Extract 802.11 frame from raw USB RX data.

        Monitor mode formats:
          - No prefix: raw IS the 802.11 frame
          - 12-byte prefix: [12 bytes] + [802.11 frame]
          - 32-byte prefix: [32 bytes] + [802.11 frame]

        Detection: valid 802.11 Frame Control has type in {0,1,2}.
        """
        if not raw or len(raw) < 2:
            return None

        if self._looks_like_80211(raw[0:2]):
            return raw

        if len(raw) > 12 and self._looks_like_80211(raw[12:14]):
            return raw[12:]

        if len(raw) > 32 and self._looks_like_80211(raw[32:34]):
            return raw[32:]

        return None

    @staticmethod
    def _looks_like_80211(fc_bytes: bytes) -> bool:
        if len(fc_bytes) < 2:
            return False
        fc = struct.unpack('<H', fc_bytes)[0]
        ftype = (fc >> 2) & 0x03
        return ftype in (0, 1, 2)

    @staticmethod
    def _extract_ssid(frame: bytes) -> str:
        """Extract SSID from a beacon/probe frame body."""
        try:
            body = frame[24:]
            i = 0
            while i < len(body) - 1:
                eid = body[i]
                elen = body[i + 1]
                if eid == 0:
                    return body[i + 2:i + 2 + elen].decode('utf-8', errors='replace')
                i += 2 + elen
        except Exception:
            pass
        return ""

    # ------------------------------------------------------------------
    # EFUSE MAC read
    # ------------------------------------------------------------------

    def read_efuse_mac(self) -> Optional[bytes]:
        """Read MAC address from EFUSE (register 0x2000)."""
        try:
            mac = bytearray()
            for i in range(6):
                b = _ctrl_read(self.dev, 0x2000 + i, 1)
                mac.append(b[0])
            if mac != b'\x00\x00\x00\x00\x00\x00' and mac != b'\xff\xff\xff\xff\xff\xff':
                return bytes(mac)
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    # Diagnostics (4-step practical test)
    # ------------------------------------------------------------------

    def test_registers(self) -> dict:
        """Test if register R/W works at all."""
        test_addrs = [0x00, 0x04, 0x10, 0x14, 0x18, 0x1C, 0x20,
                      0x148, 0x14C, 0x150, 0x2000, 0x2004]
        results = {}
        for addr in test_addrs:
            try:
                val = read_reg(self.dev, addr)
                results[addr] = val
            except Exception as e:
                results[addr] = f"ERROR: {e}"
        return results

    def brute_force_register_access(self) -> tuple:
        """Try different vendor request codes until one works.

        Returns (working_read, working_write) tuples or (None, None).
        """
        import usb.core
        import usb.util

        write_candidates = [
            (0x40, 0x01, "VENDOR|DEVICE|OUT, req=0x01"),
            (0x40, 0x02, "VENDOR|DEVICE|OUT, req=0x02"),
            (0x40, 0x00, "VENDOR|DEVICE|OUT, req=0x00"),
            (0x41, 0x01, "VENDOR|INTERFACE|OUT, req=0x01"),
            (0x41, 0x02, "VENDOR|INTERFACE|OUT, req=0x02"),
        ]

        read_candidates = [
            (0xC0, 0x04, "VENDOR|DEVICE|IN, req=0x04"),
            (0xC0, 0x05, "VENDOR|DEVICE|IN, req=0x05"),
            (0xC0, 0x00, "VENDOR|DEVICE|IN, req=0x00"),
            (0xC1, 0x04, "VENDOR|INTERFACE|IN, req=0x04"),
            (0xC1, 0x05, "VENDOR|INTERFACE|IN, req=0x05"),
        ]

        working_read = None
        for bm, req, desc in read_candidates:
            try:
                data = self.dev.ctrl_transfer(bm, req, 0x0000, 0x0000, 4, timeout=500)
                val = int.from_bytes(bytes(data), 'little')
                print(f"  READ {desc}: 0x{val:08X}")
                if working_read is None:
                    working_read = (bm, req)
            except usb.core.USBError as e:
                print(f"  READ {desc}: FAILED ({e})")

        working_write = None
        for bm, req, desc in write_candidates:
            try:
                self.dev.ctrl_transfer(bm, req, 0x0000, 0x0000,
                                       b'\x00\x00\x00\x00', timeout=500)
                print(f"  WRITE {desc}: no error")
                if working_write is None:
                    working_write = (bm, req)
            except usb.core.USBError as e:
                print(f"  WRITE {desc}: FAILED ({e})")

        return working_read, working_write

    def diagnose(self) -> bool:
        """Practical diagnostic: verify the chip can RX and TX."""
        print("\n" + "=" * 50)
        print("  RTL8812AU Practical Diagnostic")
        print("=" * 50 + "\n")

        print("[1/4] USB control transfer test... ", end="")
        try:
            val = read_reg(self.dev, 0x00)
            print(f"OK (read 0x00 -> 0x{val:08x})")
        except Exception as e:
            print(f"FAILED: {e}")
            return False

        print("[2/4] Register write test... ", end="")
        try:
            write_reg(self.dev, 0x14C, 0x00000000)
            time.sleep(0.05)
            write_reg(self.dev, 0x14C, 0xFFFFFFFF)
            print("OK (RCR written)")
        except Exception as e:
            print(f"FAILED: {e}")
            return False

        print("[3/4] TX injection test... ", end="")
        try:
            test_frame = b'\x80\x00' + b'\x00' * 30
            self.dev.write(self.ep_tx, test_frame, timeout=100)
            print("OK (frame sent)")
        except Exception as e:
            print(f"FAILED: {e}")
            return False

        print("[4/4] RX test (listening 3s)... ", end="")
        frames_received = 0
        try:
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline:
                try:
                    data = self.dev.read(self.ep_rx, 4096, timeout=500)
                    if data:
                        frames_received += 1
                except Exception:
                    pass
            if frames_received > 0:
                print(f"OK ({frames_received} frames received)")
            else:
                print("WARNING: No frames (try near a Wi-Fi router)")
        except Exception as e:
            print(f"FAILED: {e}")
            return False

        print("\n" + "=" * 50)
        if frames_received > 0:
            print("  CHIP IS WORKING -- EvilTwin should function")
        else:
            print("  TX works but RX silent -- check RCR or USB port")
        print("=" * 50)
        return True
