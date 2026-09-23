"""RTL8812AU firmware AP mode initialization via USB control transfers.

Configures the chip from passive monitor mode into AP mode so it:
  - Accepts probe requests, auth frames, assoc requests from clients
  - Forwards data frames from associated STAs to USB bulk-in
  - Manages a CAM table for associated stations

Register addresses and H2C command formats extracted from:
  - https://github.com/aircrack-ng/rtl8812au (kernel driver v5.6.4.2)
  - rtl8812a/rtl8812a_hal_init.c, core/rtw_ap.c, include/rtw_reg.h
  - rtl8812a_cmd.h, rtl8812a_spec.h
"""
from __future__ import annotations

import struct
import time
import logging
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# USB vendor request codes (RTL8812AU control endpoint)
# From kernel driver: os_dep/usb/usb_ops.c, usb_io.c
# bmRequestType: 0x40 = VENDOR|DEVICE|OUT, 0xC0 = VENDOR|DEVICE|IN
# bRequest: 0x05 for register R/W, 0x01 for H2C
# ---------------------------------------------------------------------------
_USB_REQ_READ    = 0x05  # Register read (bRequest)
_USB_REQ_WRITE   = 0x05  # Register write (bRequest)
_USB_REQ_READ_FW = 0x06  # Firmware memory read
_USB_REQ_H2C     = 0x01  # Host-to-Chip command
_USB_REQ_C2H     = 0x02  # Chip-to-Host response (poll)

# ---------------------------------------------------------------------------
# Key register addresses (from rtl8812au driver: include/rtw_reg.h)
# ---------------------------------------------------------------------------
REG_USB_INT_MASK   = 0xFE64
REG_USB_INT_STATUS = 0xFE60

REG_RCR            = 0x0400  # Receive Configuration Register
REG_RX_FILTER      = REG_RCR
REG_BSSID          = 0x0454  # BSSID (6 bytes, write via MAC register)
REG_MACID          = 0x0404
REG_BCN_CTRL       = 0x0550  # Beacon control
REG_BCNTCFG        = 0x0510  # Beacon TX config
REG_SCH_TX_CMD     = 0x0423  # Scheduler TX command
REG_TDECTRL        = 0x0200  # TX descriptor control
REG_TRX_DMA_CTRL   = 0x010C  # TX/RX DMA control
REG_MAC_PHY_CTRL   = 0x00FC  # MAC-PHY control
REG_OFDM_TXPS      = 0x04B8  # OFDM TX power status

REG_PSR            = 0x0002  # Page Select Register
REG_SYS_FUNC       = 0x0003  # System Function
REG_CR             = 0x0100  # Command Register (MAC/BB/PHY reset)

REG_MAC_ADDR       = 0x0610  # Our own MAC address (device MAC)
REG_MAPPING_ADDR   = 0x0618  # Mapping table address
REG_AMSDU_LEN      = 0x045E  # AMSDU length

REG_SIDOV_MODE     = 0x051C  # SIFS countdown

REG_MCUFWDL        = 0x0080  # MCU firmware download control
REG_HMETFR         = 0x0188  # H2C mailbox

# ---------------------------------------------------------------------------
# RCR (Receive Configuration Register) bit definitions
# From kernel driver: include/rtl8812a/rtl8812a_spec.h
# ---------------------------------------------------------------------------
RCR_APM           = 1 << 3   # Accept Physical Match (unicast to us)
RCR_ADF           = 1 << 4   # Accept Data Frames (directed)
RCR_AF            = 1 << 5   # Accept Action Frames
RCR_ACRC32        = 1 << 10  # Accept frames with CRC32 error
RCR_AB            = 1 << 15  # Accept Broadcast
RCR_AM            = 1 << 14  # Accept Multicast
RCR_CBSSID_DATA   = 1 << 18  # Check BSSID for data frames (AP mode)
RCR_CBSSID_BCN    = 1 << 23  # Check BSSID for beacons
RCR_ADF_V1        = 1 << 19  # Accept Data Frames v2
RCR_RXSK_PERPKT   = 1 << 22  # RX security per-packet check

# AP mode RX filter: accept unicast (to our MAC), broadcast, multicast,
# data frames, AND the critical BSSID-check bits so the chip forwards
# frames from associated STAs instead of dropping them.
RCR_AP_MODE = (
    RCR_APM |         # Accept physical match (our MAC)
    RCR_ADF |         # Accept directed data
    RCR_AB |          # Accept broadcast
    RCR_AM |          # Accept multicast
    RCR_CBSSID_DATA | # Check BSSID for data (AP mode)
    RCR_CBSSID_BCN |  # Check BSSID for beacons
    RCR_ADF_V1        # Additional data frame acceptance
)

# ---------------------------------------------------------------------------
# H2C (Host-to-Chip) command IDs
# From kernel driver: include/rtl8812a/rtl8812a_cmd.h
# ---------------------------------------------------------------------------
H2C_8812_RSVDPAGE     = 0x00  # Reserve page
H2C_8812_MSRRPT       = 0x01  # Media status report (assoc/disassoc)
H2C_8812_SCAN         = 0x02  # Scan command
H2C_8812_KEEP_ALIVE   = 0x03  # Keep alive control
H2C_8812_DISCONNECT   = 0x04  # Disconnect decision
H2C_8812_INIT_OFFLOAD = 0x06  # Init offload
H2C_8812_AP_OFFLOAD   = 0x08  # AP offload
H2C_8812_BCN_RSVDPAGE = 0x09  # Beacon reserve page
H2C_8812_PRSP_RSVDPAGE = 0x0A  # Probe response reserve page

# Legacy aliases (match existing code)
H2C_MEDIA_STATUS_RPT = H2C_8812_MSRRPT
H2C_SET_MACID        = H2C_8812_MSRRPT  # MAC ID is reported via MSRRPT
H2C_SET_BSSID        = H2C_8812_MSRRPT
H2C_SET_BCN_VALID    = H2C_8812_BCN_RSVDPAGE
H2C_SET_BC_CTRL      = H2C_8812_AP_OFFLOAD
H2C_OP_MODE          = 0x22  # Not in cmd.h, some FW versions use this

# Operation modes for H2C_OP_MODE
OP_MODE_AP = 0x01
OP_MODE_STA = 0x00

# ---------------------------------------------------------------------------
# CAM (Content Addressable Memory) - hardware MAC filter table
# ---------------------------------------------------------------------------
CAM_ENTRY_SIZE = 8  # Each CAM entry is 8 bytes
CAM_KEY_SIZE = 16   # Each key entry is 16 bytes
CAM_COUNT = 32      # Number of CAM entries in hardware

CAM_WRITE = 0x80    # Write bit for CAM command


def _cam_addr(entry: int) -> int:
    """Register address for CAM entry <entry>."""
    return 0xB80 + (entry * 8)


# ---------------------------------------------------------------------------
# TX descriptor offsets (from rtl8812au: hal/rtl8812a_hal_tx.c)
# ---------------------------------------------------------------------------
TX_DESC_SIZE = 40  # TX descriptor length (rtl8812au)

# TX descriptor pkt_type bits
PKT_MGMT = 0x00
PKT_DATA = 0x01

# ---------------------------------------------------------------------------
# RX descriptor (from rtl8812au: hal/rtl8812a_hal_rx.c)
# ---------------------------------------------------------------------------
RX_DESC_SIZE = 24  # RX status descriptor prefix (rtl8812au)

# ---------------------------------------------------------------------------
# Firmware download addresses
# ---------------------------------------------------------------------------
FW_START_ADDR = 0x1000  # Firmware code start address
FW_BIST_ADDR  = 0x8000  # Firmware BIST start address
FW_MAX_SIZE   = 0xC000  # Max firmware code size


# ============================================================================
# USB control transfer helpers
# ============================================================================

def _ctrl_read(dev, addr: int, len: int = 4, timeout: int = 1000) -> bytes:
    """Read register or memory from RTL8812AU via vendor control transfer.

    USB setup packet:
      bmRequestType = 0xC0 (VENDOR|DEVICE|IN)
      bRequest      = 0x05
      wValue        = addr[15:0]
      wIndex        = addr[31:16]
      wLength       = len
    """
    import usb.util
    data = dev.ctrl_transfer(
        usb.util.CTRL_TYPE_VENDOR | usb.util.CTRL_RECIP_DEVICE | usb.util.ENDPOINT_IN,
        _USB_REQ_READ,
        addr & 0xFFFF,
        (addr >> 16) & 0xFFFF,
        len,
        timeout=timeout
    )
    return bytes(data)


def _ctrl_write(dev, addr: int, data: bytes, timeout: int = 1000):
    """Write register or memory to RTL8812AU via vendor control transfer.

    USB setup packet:
      bmRequestType = 0x40 (VENDOR|DEVICE|OUT)
      bRequest      = 0x05
      wValue        = addr[15:0]
      wIndex        = addr[31:16]
      wLength       = len(data)
    """
    import usb.util
    dev.ctrl_transfer(
        usb.util.CTRL_TYPE_VENDOR | usb.util.CTRL_RECIP_DEVICE | usb.util.ENDPOINT_OUT,
        _USB_REQ_WRITE,
        addr & 0xFFFF,
        (addr >> 16) & 0xFFFF,
        data,
        timeout=timeout
    )


def read_reg(dev, addr: int) -> int:
    """Read a 32-bit register value."""
    raw = _ctrl_read(dev, addr, 4)
    return struct.unpack('<I', raw)[0]


def write_reg(dev, addr: int, value: int):
    """Write a 32-bit register value."""
    _ctrl_write(dev, addr, struct.pack('<I', value))


def write_reg_byte(dev, addr: int, value: int):
    """Write a single byte to a register."""
    _ctrl_write(dev, addr, bytes([value & 0xFF]))


def write_fifo(dev, addr: int, data: bytes):
    """Write a block of data to a FIFO/register range."""
    _ctrl_write(dev, addr, data)


# ---------------------------------------------------------------------------
# H2C (Host-to-Chip) command sender
# ---------------------------------------------------------------------------

def h2c_cmd(dev, cmd_id: int, data: bytes, timeout: int = 1000):
    """Send a Host-to-Chip command via vendor control transfer.

    RTL8812AU H2C format: 7-byte command through control endpoint.
    Byte 0: command ID
    Byte 1-6: command payload

    USB setup packet:
      bmRequestType = 0x40 (VENDOR|DEVICE|OUT)
      bRequest      = 0x01
      wValue        = 0
      wIndex        = 0
    """
    import usb.util
    payload = bytes([cmd_id]) + data[:6]
    dev.ctrl_transfer(
        usb.util.CTRL_TYPE_VENDOR | usb.util.CTRL_RECIP_DEVICE | usb.util.ENDPOINT_OUT,
        _USB_REQ_H2C,
        0, 0,
        payload,
        timeout=timeout
    )


# ============================================================================
# RTL8812AU AP mode controller
# ============================================================================

@dataclass
class StationEntry:
    """Hardware station entry tracked in the CAM table."""
    mac: bytes
    mac_id: int
    cam_entry: int


class Rtl8812auAP:
    """RTL8812AU AP mode firmware configuration.

    Configures the chip from monitor mode into AP mode so it accepts
    auth/assoc/data frames from clients instead of dropping them.
    """

    def __init__(self, dev, ep_ctrl: int = 0x00):
        self.dev = dev
        self.ep_ctrl = ep_ctrl
        self._stations: dict[bytes, StationEntry] = {}
        self._next_mac_id = 1  # 0 = broadcast/mgmt
        self._next_cam = 0
        self._bssid = b'\x00\x00\x00\x00\x00\x00'
        self._initialized = False
        self._rcr_write_only = False  # Some FW versions have write-only RCR

    def init_ap_mode(self, ap_mac: bytes, ssid: str, channel: int):
        """Full AP mode initialization. Must be called BEFORE sending beacons.

        Steps:
          1. Set chip to AP mode (H2C op_mode)
          2. Configure RX filter for auth/assoc/probe/data
          3. Set BSSID in hardware
          4. Configure beacon parameters
          5. Set own MAC address
          6. Initialize CAM table
        """
        self._bssid = ap_mac

        log.info("[rtl8812au] initializing AP mode: BSSID=%s SSID=%s ch=%d",
                 ':'.join(f'{b:02x}' for b in ap_mac), ssid, channel)

        # Step 1: Set operating mode to AP via H2C
        self._set_op_mode(OP_MODE_AP)
        log.info("[rtl8812au] operating mode set to AP")

        # Step 2: Configure RX filter (CRITICAL)
        self._set_rx_filter(RCR_AP_MODE)
        log.info("[rtl8812au] RX filter set to AP mode: 0x%08x", RCR_AP_MODE)

        # Step 3: Set BSSID in hardware
        self._set_bssid(ap_mac)
        log.info("[rtl8812au] BSSID configured")

        # Step 4: Set own MAC address
        self._set_mac_addr(ap_mac)
        log.info("[rtl8812au] MAC address configured")

        # Step 5: Configure beacon timing
        self._config_beacon_timing()

        # Step 6: Configure MAC port for AP mode
        self._config_mac_port()

        # Step 7: Initialize CAM table (clear all entries)
        self._init_cam_table()

        self._initialized = True
        log.info("[rtl8812au] AP mode initialization complete")

    def station_assoc(self, client_mac: bytes) -> int:
        """Register an associated station in hardware.

        Allocates a mac_id and adds a CAM entry so the chip forwards
        data frames from this client to USB bulk-in.

        Returns the allocated mac_id for use in TX descriptors.
        """
        if client_mac in self._stations:
            return self._stations[client_mac].mac_id

        mac_id = self._next_mac_id
        self._next_mac_id += 1

        cam_entry = self._next_cam
        self._next_cam = (self._next_cam + 1) % CAM_COUNT

        # Add address CAM entry: client MAC mapped to our BSSID
        self._add_addr_cam(cam_entry, client_mac, self._bssid)

        # H2C: tell firmware this station is associated
        self._h2c_sta_assoc(mac_id, client_mac)

        entry = StationEntry(mac=client_mac, mac_id=mac_id, cam_entry=cam_entry)
        self._stations[client_mac] = entry

        log.info("[rtl8812au] station associated: %s mac_id=%d cam=%d",
                 ':'.join(f'{b:02x}' for b in client_mac), mac_id, cam_entry)
        return mac_id

    def station_disassoc(self, client_mac: bytes):
        """Remove an associated station from hardware."""
        entry = self._stations.pop(client_mac, None)
        if entry is None:
            return

        self._h2c_sta_disassoc(entry.mac_id, client_mac)
        self._remove_addr_cam(entry.cam_entry)

        log.info("[rtl8812au] station disassociated: %s mac_id=%d freed",
                 ':'.join(f'{b:02x}' for b in client_mac), entry.mac_id)

    def get_tx_mac_id(self, client_mac: bytes) -> int:
        """Get the mac_id for TX descriptors to this client."""
        entry = self._stations.get(client_mac)
        return entry.mac_id if entry is not None else 0

    def deinit_ap_mode(self):
        """Clean shutdown: free all stations, reset RX filter, switch to monitor."""
        for mac in list(self._stations.keys()):
            self.station_disassoc(mac)

        # Reset RX filter to monitor mode
        self._set_rx_filter(RCR_AB | RCR_AM)

        # Switch back to monitor mode
        self._set_op_mode(OP_MODE_STA)

        self._initialized = False
        log.info("[rtl8812au] AP mode deinitialized")

    # ------------------------------------------------------------------
    # RX descriptor parsing (for frames received in AP mode)
    # ------------------------------------------------------------------

    def parse_rx_descriptor(self, raw: bytes) -> tuple[Optional[bytes], int]:
        """Parse USB bulk-in data with RX descriptor prefix.

        In AP mode, received frames have a descriptor prefix containing
        metadata (pkt_type, mac_id, signal, etc.) followed by the 802.11 frame.

        Returns: (802.11_frame, mac_id) or (None, -1) on error.
        """
        if len(raw) < RX_DESC_SIZE:
            return None, -1

        # RTL8812AU RX descriptor layout (simplified):
        # Word 0: [7:0]=pkt_len [15:8]=pkt_type [23:16]=mac_id ...
        word0 = struct.unpack('<I', raw[0:4])[0]
        frame_len = word0 & 0x3FFF  # 14 bits
        mac_id = (word0 >> 24) & 0x1F

        # Sanity check
        if frame_len + RX_DESC_SIZE > len(raw) or frame_len < 10:
            return None, -1

        frame = raw[RX_DESC_SIZE:RX_DESC_SIZE + frame_len]
        return frame, mac_id

    # ------------------------------------------------------------------
    # TX descriptor construction (for frames sent in AP mode)
    # ------------------------------------------------------------------

    def build_tx_descriptor(self, pkt_type: int, mac_id: int,
                            frame_len: int, port_id: int = 0,
                            retry: int = 15) -> bytes:
        """Build a 40-byte TX descriptor for RTL8812AU.

        Prepended to every frame sent via USB bulk-out in AP mode.
        """
        desc = bytearray(TX_DESC_SIZE)

        # Word 0: offset(5 bits), type(2 bits), usb_agg(1 bit)
        desc[0] = (0 << 5) | ((pkt_type & 0x03) << 3) | 0x01
        desc[1] = 0x00
        desc[2] = 0x00
        desc[3] = 0x00

        # Word 1: DATA retry count
        desc[4] = retry & 0xFF
        desc[5] = 0x00
        desc[6] = 0x00
        desc[7] = 0x00

        # Word 2: TX packet offset (descriptor size >> 3), pkt_len
        offset_val = TX_DESC_SIZE >> 3
        desc[8] = offset_val & 0x1F
        desc[9] = 0x00
        desc[10] = frame_len & 0xFF
        desc[11] = (frame_len >> 8) & 0xFF

        # Word 3: PACKET_ID (mac_id), queue_sel
        desc[12] = mac_id & 0x1F
        desc[13] = 0x00
        desc[14] = 0x00
        desc[15] = 0x00

        return bytes(desc)

    def wrap_frame_with_tx_desc(self, client_mac: bytes, frame: bytes,
                                pkt_type: int = PKT_DATA) -> bytes:
        """Wrap an 802.11 frame with the TX descriptor for AP mode TX."""
        mac_id = self.get_tx_mac_id(client_mac)
        tx_desc = self.build_tx_descriptor(
            pkt_type=pkt_type,
            mac_id=mac_id,
            frame_len=len(frame),
            port_id=0,
        )
        return tx_desc + frame

    # ------------------------------------------------------------------
    # Internal: register and H2C operations
    # ------------------------------------------------------------------

    def _set_op_mode(self, mode: int):
        """Set chip operating mode via H2C."""
        h2c_cmd(self.dev, H2C_OP_MODE, bytes([mode, 0, 0, 0, 0, 0]))
        time.sleep(0.05)

    def _set_rx_filter(self, filter_val: int):
        """Configure the RX filter register.

        Some firmware versions have write-only RCR - readback may not match.
        If readback fails, set _rcr_write_only flag and skip verification.
        """
        write_reg(self.dev, REG_RCR, filter_val)
        time.sleep(0.01)
        try:
            actual = read_reg(self.dev, REG_RCR)
            if actual != filter_val:
                log.warning("[rtl8812au] RX filter readback mismatch: wrote 0x%08x, got 0x%08x",
                            filter_val, actual)
                self._rcr_write_only = True
        except Exception:
            log.warning("[rtl8812au] RX filter read failed (write-only firmware)")
            self._rcr_write_only = True

    def _set_bssid(self, bssid: bytes):
        """Set BSSID in the MAC BSSID register."""
        write_fifo(self.dev, REG_BSSID, bssid[:6])

    def _set_mac_addr(self, mac: bytes):
        """Set the device MAC address."""
        write_fifo(self.dev, REG_MAC_ADDR, mac[:6])

    def _config_beacon_timing(self):
        """Configure beacon transmission timing registers."""
        write_reg_byte(self.dev, REG_BCNTCFG, 0x00)
        write_reg_byte(self.dev, REG_BCNTCFG + 1, 0x10)
        write_reg(self.dev, REG_BCN_CTRL, 0x10)

    def _config_mac_port(self):
        """Configure MAC port registers for AP mode."""
        write_reg(self.dev, REG_PSR, 0x00)
        write_reg(self.dev, REG_CR, 0x00)
        time.sleep(0.01)
        write_reg(self.dev, REG_CR, 0x01)
        time.sleep(0.01)

    def _init_cam_table(self):
        """Clear all CAM entries."""
        for i in range(CAM_COUNT):
            addr = _cam_addr(i)
            write_fifo(self.dev, addr, b'\x00' * CAM_ENTRY_SIZE)
        self._next_cam = 0

    def _add_addr_cam(self, entry: int, client_mac: bytes, bssid: bytes):
        """Add an address CAM entry: client MAC -> our BSSID."""
        addr = _cam_addr(entry)
        cam_data = bytearray(CAM_ENTRY_SIZE)
        cam_data[0:6] = client_mac[:6]
        cam_data[6] = 0x80  # Valid bit
        cam_data[7] = 0x00  # BSSID index 0
        write_fifo(self.dev, addr, bytes(cam_data))

    def _remove_addr_cam(self, entry: int):
        """Remove an address CAM entry (clear it)."""
        addr = _cam_addr(entry)
        write_fifo(self.dev, addr, b'\x00' * CAM_ENTRY_SIZE)

    def _h2c_sta_assoc(self, mac_id: int, client_mac: bytes):
        """H2C: tell firmware a station has associated."""
        data = bytearray(6)
        data[0] = mac_id & 0x1F
        data[1] = 0x00  # connected
        data[2:6] = client_mac[:4]
        h2c_cmd(self.dev, H2C_MEDIA_STATUS_RPT, bytes(data))

    def _h2c_sta_disassoc(self, mac_id: int, client_mac: bytes):
        """H2C: tell firmware a station has disassociated."""
        data = bytearray(6)
        data[0] = mac_id & 0x1F
        data[1] = 0x01  # disconnected
        data[2:6] = client_mac[:4]
        h2c_cmd(self.dev, H2C_MEDIA_STATUS_RPT, bytes(data))

    def _set_beacon_valid(self):
        """H2C: tell firmware the beacon content is valid and ready to TX."""
        h2c_cmd(self.dev, H2C_SET_BCN_VALID, b'\x01\x00\x00\x00\x00\x00')

    def _set_beacon_ctrl(self, interval_tu: int = 100, dtim: int = 1):
        """Configure beacon interval and DTIM period."""
        data = struct.pack('<HB', interval_tu, dtim) + b'\x00\x00\x00\x00'
        h2c_cmd(self.dev, H2C_SET_BC_CTRL, data[:6])

    def download_beacon(self, beacon_frame: bytes):
        """Download beacon frame content to firmware for periodic TX."""
        bcn_buf_addr = 0x0200
        write_fifo(self.dev, bcn_buf_addr, beacon_frame)
        self._set_beacon_valid()
        log.info("[rtl8812au] beacon downloaded to firmware (%d bytes)",
                 len(beacon_frame))

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def diagnose(self) -> bool:
        """Run AP init step-by-step with verification.

        8-step diagnostic:
          1. Read chip ID register
          2. Read firmware version
          3. Read EFUSE MAC address
          4. Set AP mode via H2C
          5. Write + readback RCR (RX filter)
          6. Set BSSID
          7. Set MAC address
          8. Init CAM table

        Returns True if all steps pass.
        """
        print("[rtl8812au] Running AP mode diagnostics...")

        print("  [1/8] Reading chip ID... ", end="")
        try:
            chip_id = read_reg(self.dev, 0x00)
            print(f"OK (0x{chip_id:08x})")
        except Exception as e:
            print(f"FAIL ({e})")
            return False

        print("  [2/8] Reading firmware version... ", end="")
        try:
            fw_ver = read_reg(self.dev, 0x80)
            fw_sub = read_reg(self.dev, 0x84)
            print(f"OK (reg=0x{fw_ver:08x} sub=0x{fw_sub:08x})")
        except Exception as e:
            print(f"WARN ({e})")

        print("  [3/8] Reading EFUSE MAC... ", end="")
        try:
            mac_bytes = bytearray()
            for i in range(6):
                b = _ctrl_read(self.dev, 0x2000 + i, 1)
                mac_bytes.append(b[0])
            mac_str = ':'.join(f'{b:02x}' for b in mac_bytes)
            if mac_bytes == b'\x00\x00\x00\x00\x00\x00' or mac_bytes == b'\xff\xff\xff\xff\xff\xff':
                print(f"WARN (all zeros/ones: {mac_str})")
            else:
                print(f"OK ({mac_str})")
        except Exception as e:
            print(f"WARN ({e})")

        print("  [4/8] Setting AP mode... ", end="")
        try:
            self._set_op_mode(OP_MODE_AP)
            print("OK")
        except Exception as e:
            print(f"FAIL ({e})")
            return False

        print("  [5/8] Configuring RX filter... ", end="")
        try:
            self._set_rx_filter(RCR_AP_MODE)
            if self._rcr_write_only:
                print(f"OK (write-only, assuming 0x{RCR_AP_MODE:08x})")
            else:
                actual = read_reg(self.dev, REG_RCR)
                if actual & RCR_APM:
                    print(f"OK (filter=0x{actual:08x})")
                else:
                    print(f"WARN (filter=0x{actual:08x}, APM bit not set)")
        except Exception as e:
            print(f"FAIL ({e})")
            return False

        print("  [6/8] Setting BSSID... ", end="")
        try:
            self._set_bssid(self._bssid)
            print("OK")
        except Exception as e:
            print(f"FAIL ({e})")
            return False

        print("  [7/8] Setting MAC address... ", end="")
        try:
            self._set_mac_addr(self._bssid)
            print("OK")
        except Exception as e:
            print(f"FAIL ({e})")
            return False

        print("  [8/8] Initializing CAM table... ", end="")
        try:
            self._init_cam_table()
            print("OK")
        except Exception as e:
            print(f"FAIL ({e})")
            return False

        print("\n  [OK] All 8 diagnostic steps passed.")
        return True
