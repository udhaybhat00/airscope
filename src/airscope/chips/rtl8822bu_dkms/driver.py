"""RTL8822BU / 2T2R driver — vendor (HALMAC/PHYDM) cleanroom port.

`connect()` runs the deterministic cold bring-up the byte-for-byte gate verifies
(`scripts/chips/rtl8822bu_dkms/verify_pcap.py` → `bringup.cold_bringup`): the entire vendor `rtl8822b_init`
— chip-ID/USB-PHY → EFUSE → two-cycle power/FW/MAC → BB/AGC/crystal/RF tables → full `odm_dm_init`
(RX seed + RF-cal tail) → `phy_bf_init`/wifi-only-coex/`init_misc`. It then tunes to the default
channel (`chan.set_channel_bw`, byte-verified against the capture's airodump hops), starts the bulk-IN
RX reader, and runs the airmon monitor RX-enable (`mac.enable_monitor`, gate-verified against
the capture's monitor switch: MSR no-link, RCR=AAP|APP_PHYSTS|APP_FCS, DRVINFO sniffer-mode,
RXFLTMAP0/1/2=0xFFFF). RX frames decode via `rx.iter_frames` (24-byte rx_pkt_desc + jaguar2 phy-status
RSSI, FCS-stripped).

Not registered in the manager (the mainline `chips/rtl8822bu/` owns 2357:0138); this `_dkms` port
is exercised standalone via `scripts/chips/rtl8822bu_dkms/test_hw.py`. `inject_frame` builds a
48-byte fill_fake_txdesc + bulk-OUT payload (TX descriptor is unit-tested against the HALMAC
field offsets + the XOR-16 checksum; live TX smoke-tested via deauth + beacon injection).
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Callable, ClassVar, List, Optional

import usb.core
import usb.util

from airscope.chips.driver import DeviceID, Driver, FakeMacSupport, ProgressCallback
from airscope.errors import BringUpError
from airscope.dot11.parser import WlanFrameParser

from ..rx_reader import RxReaderThread
from . import bringup, chan, dm_watchdog, led, mac, sipi, tx, txpower
from .rx import FCS_LEN, RXDESC_SIZE, _rnd8, iter_frames
from .transport import Rtl8822buTransport

logger = logging.getLogger(__name__)

USB_VID_REALTEK = 0x2357
USB_PID_T3U_PLUS = 0x0138
_DEFAULT_CHANNEL = 1
_HEAL_5G_CHANNEL = 36                           # 5 GHz channel used to re-cycle a stuck cold synth
_BULK_OUT_EP_TX = 0x05                          # 8822b bulk-OUT (FW/TX)
CHANNELS_2G = list(range(1, 15))
CHANNELS_5G = [36, 40, 44, 48, 52, 56, 60, 64, 100, 104, 108, 112, 116, 120, 124,
               128, 132, 136, 140, 144, 149, 153, 157, 161, 165]
# Scan set excludes the DFS band (52-144): passive-scan-only, radar-shared, home APs avoid it.
# set_channel + verify_channels still drive the full CHANNELS_5G above, byte-for-byte vs the capture.
CHANNELS_5G_NON_DFS = [36, 40, 44, 48, 149, 153, 157, 161, 165]

# The pcap-gated reference card is rfe_type 3 / cut 3; rfe_type 2 / cut 3 is live-hardware
# verified on a TP-Link Archer T4U v3. Other burns run vendor-ported but hardware-untested RFE arms.
_REF_RFE_TYPE = 3
_REF_CUT = 3
_HARDWARE_VERIFIED_RFE_CUTS = frozenset({(2, 3), (_REF_RFE_TYPE, _REF_CUT)})
# rfe types whose per-channel RFE PINMUX is NOT ported (OEM-only phydm_8822b_type15/18_rfe); the
# dispatch runs the iFEM pinmux as a give-it-a-shot fallback, and connect() escalates the warning.
_RFE_PINMUX_UNPORTED = frozenset({15, 18})


@dataclass
class _RxDebugStats:
    bufs: int = 0
    bytes: int = 0
    desc: int = 0
    good: int = 0
    crc_err: int = 0
    icv_err: int = 0
    c2h: int = 0
    runt: int = 0
    zero_len: int = 0
    truncated: int = 0


def _rx_desc_stats(buf: bytes) -> _RxDebugStats:
    st = _RxDebugStats(bufs=1, bytes=len(buf))
    off, n = 0, len(buf)
    while off + RXDESC_SIZE <= n:
        w0 = int.from_bytes(buf[off:off + 4], "little")
        pkt_len = w0 & 0x3FFF
        crc_err = (w0 >> 14) & 1
        icv_err = (w0 >> 15) & 1
        drvinfo_sz = ((w0 >> 16) & 0xF) << 3
        shift_sz = (w0 >> 24) & 0x3
        c2h = (int.from_bytes(buf[off + 8:off + 12], "little") >> 28) & 1
        if pkt_len <= 0:
            st.zero_len += 1
            break
        pkt_offset = RXDESC_SIZE + drvinfo_sz + shift_sz + pkt_len
        if pkt_offset > n - off:
            st.truncated += 1
            break
        st.desc += 1
        if c2h:
            st.c2h += 1
        elif crc_err:
            st.crc_err += 1
        elif icv_err:
            st.icv_err += 1
        elif pkt_len <= FCS_LEN:
            st.runt += 1
        else:
            st.good += 1
        off += _rnd8(pkt_offset)
    return st


def _rx_state_line(t) -> str:
    """Read back the band-dependent RX-path registers for the cold-wedge diagnostic.

    Each is decoded with its expected 2.4 GHz value, so a single silent-boot capture is
    interpretable on its own — but the money comparison is the ch1 snapshot from the cold
    (deaf) initial tune vs the ch1 snapshot after a 5->2.4 round-trip (working): whichever
    field differs is the register `switch_band` failed to wire from the cold-init state.
    Reads only; DEBUG-gated by the callers so it adds no USB traffic in a normal run.
    """
    rf18a = sipi.read_rf_reg(t, sipi.RF_PATH_A, 0x18)
    rf18b = sipi.read_rf_reg(t, sipi.RF_PATH_B, 0x18)
    cbc = t.read32(0x0CBC)
    ca0 = t.read32(0x0CA0)
    r808 = t.read32(0x0808)
    r8cc = t.read32(0x08CC)
    a9c = t.read32(0x0A9C)
    r454 = t.read8(0x0454)
    ra80 = t.read32(0x0A80)
    igi_a = sipi.get_bb_reg(t, 0x0C50, 0x7F)
    igi_b = sipi.get_bb_reg(t, 0x0E50, 0x7F)
    return (
        f"RF18 A=0x{rf18a:05x} B=0x{rf18b:05x} (ch=low byte; 2.4G: bit8/bit16 clear) | "
        f"ant 0xCBC[9:8]={(cbc >> 8) & 3} (2.4G->2 5G->1) 0xCA0=0x{ca0 & 0xFFFF:04x} (2.4G->0xa501) | "
        f"0x808 cck_en[28]={(r808 >> 28) & 1} (2.4G->1) rx_ant[7:0]=0x{r808 & 0xFF:02x} | "
        f"0x8CC=0x{r8cc:08x} (2.4G->0x08108492) | "
        f"IGI A=0x{igi_a:02x} B=0x{igi_b:02x} | cck_new_agc 0xA9C[17]={(a9c >> 17) & 1} | "
        f"0x454[7]={(r454 >> 7) & 1}(2.4G->0) 0xA80[18]={(ra80 >> 18) & 1}(2.4G->0)"
    )


class Rtl8822buDkmsDriver(Driver):
    SUPPORTED_CHANNELS: ClassVar[List[int]] = CHANNELS_2G + CHANNELS_5G_NON_DFS
    FAKE_MAC = FakeMacSupport.SPOOFABLE
    AP_MODE = True

    def __init__(self, transport: Rtl8822buTransport):
        super().__init__()          # base owns the ACK tally (_ack_detect_on / _our_tx_macs / _ack_counts)
        self.transport = transport
        self.mac_address: Optional[str] = None
        self._chip = None                       # (info, efuse) from cold_bringup
        # Runtime EFUSE/chip-cut discriminators (set after cold_bringup). Default = the pcap-gated
        # reference card (rfe_type 3 iFEM, D-cut); a non-reference burn re-selects the FEM CCA
        # table + RFE pinmux + SoML RxHP arm in chan.set_channel_bw.
        self._rfe_type: int = _REF_RFE_TYPE
        self._cut: int = _REF_CUT
        self._txpwr_pg = None                   # decoded PG TX-power block (per-channel TXAGC)
        self._channel: Optional[int] = None
        self._rx_cb: Optional[Callable[[dict], None]] = None
        self._on_lost: Optional[Callable[[Exception], None]] = None
        self._reader: Optional[RxReaderThread] = None
        self._io_lock = asyncio.Lock()
        self._dig_st: Optional[dm_watchdog.DigState] = None
        self._watchdog_task: Optional[asyncio.Task] = None
        # Per-dwell RX tally (DEBUG only) — proves which channels are deaf when the
        # intermittent cold-boot "2.4 GHz silent until the first 5 GHz hop" wedge hits.
        self._dbg_frames = 0
        self._dbg_beacons = 0
        self._dbg_rx = _RxDebugStats()
        self._inject_count = 0

    @classmethod
    def from_usb_device(cls, dev: usb.core.Device, id_entry: DeviceID) -> "Rtl8822buDkmsDriver":
        return cls(Rtl8822buTransport(dev, bulk_out_ep=_BULK_OUT_EP_TX))

    def register_rx_callback(self, cb: Callable[[dict], None]) -> None:
        self._rx_cb = cb

    def register_disconnect_callback(self, cb: Callable[[Exception], None]) -> None:
        """Sink for a terminal RX-reader failure (unplug). Forwarded to the RxReaderThread's
        on_fatal; resolved at call time so registration order vs connect() can't strand it."""
        self._on_lost = cb

    def _claim(self) -> None:
        """Detach kernel driver / configure / claim interface 0 (OS-level USB plumbing —
        outside the vendor op stream the gate reproduces)."""
        dev = self.transport.dev
        try:
            if dev.is_kernel_driver_active(0):
                dev.detach_kernel_driver(0)
        except (NotImplementedError, usb.core.USBError) as e:
            logger.debug("kernel-driver detach skipped: %s", e)
        try:
            dev.set_configuration()
        except usb.core.USBError as e:
            raise IOError(f"set_configuration failed: {e}") from e
        usb.util.claim_interface(dev, 0)

    async def connect(self, progress_cb: Optional[ProgressCallback] = None) -> bool:
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, self._claim)

            if progress_cb:
                progress_cb(0.1, "Cold bring-up: chip-ID / EFUSE / FW / MAC / BB / RF")
            info, e = await loop.run_in_executor(None, bringup.cold_bringup, self.transport)
            self._chip = (info, e)
            self._rfe_type, self._cut = e.rfe_type, info.chip_ver
            self._txpwr_pg = txpower.parse_pg(e.log_map)
            if e.mac_address:                          # program the card's own MAC (TX source/ACK)
                await loop.run_in_executor(None, mac.set_mac_addr, self.transport, e.mac_address)
                self.mac_address = e.mac_address
            self._log_detected_config(info, e)

            if progress_cb:
                progress_cb(0.8, f"Tuning to channel {_DEFAULT_CHANNEL} @ 20 MHz")

            def _initial_tune(t):
                chan.set_channel_bw(t, _DEFAULT_CHANNEL, txpwr_pg=self._txpwr_pg,
                                    rfe_type=self._rfe_type, cut=self._cut, is_scan=True)

            await loop.run_in_executor(None, _initial_tune, self.transport)
            self._channel = _DEFAULT_CHANNEL
            await self._dbg_rx_state(f"post-initial-tune ch{_DEFAULT_CHANNEL}")

            # Start the bulk-IN reader before opening the RX gate (an undrained pipe wedges RX FIFO).
            self._reader = RxReaderThread(
                loop, self._read_once, self._dispatch, name="8822bu-dkms-rx",
                on_fatal=lambda e: self._on_lost and self._on_lost(e))
            self._reader.start()
            # The airmon monitor RX-enable (gate-verified vs the capture's monitor switch):
            # MSR no-link, RCR=AAP|APP_PHYSTS|APP_FCS, DRVINFO sniffer-mode, RXFLTMAP0/1/2=0xFFFF.
            await loop.run_in_executor(None, mac.enable_monitor, self.transport)
            await loop.run_in_executor(None, led.enable_tx_blink, self.transport)
            await loop.run_in_executor(None, self._heal_cold_synth, self.transport)
            await self._dbg_rx_state(f"post-enable-monitor ch{_DEFAULT_CHANNEL}")

            # Seed the DIG state from the chip and start the runtime PHYDM watchdog (~2 s cadence): the
            # dig_init IGI is only a seed, so without this loop the RX gain never tracks the channel's
            # false-alarm rate. Reads FA counters, adapts IGI (0xC50/0xE50), resets the counters.
            def _seed_dig(tr):
                return dm_watchdog.DigState(
                    cur_ig_value=sipi.get_bb_reg(tr, 0x0C50, 0x7F),
                    big_jump_step1=sipi.get_bb_reg(tr, 0x08C8, 0xE),
                    cck_new_agc=bool(sipi.get_bb_reg(tr, 0x0A9C, 1 << 17)))

            self._dig_st = await loop.run_in_executor(None, _seed_dig, self.transport)
            self._watchdog_task = loop.create_task(self._watchdog_loop())

            if progress_cb:
                progress_cb(1.0, f"Tuned to channel {_DEFAULT_CHANNEL} @ 20 MHz (monitor)")
            return True
        except (IOError, usb.core.USBError, NotImplementedError) as e:
            raise BringUpError("bring-up", str(e)) from e

    def _log_detected_config(self, info, e) -> None:
        """One-line log of the EFUSE/chip-cut burn at connect. rfe/cut burns not in the
        hardware-verified set are tagged; rfe 15/18 also warns because their OEM pinmux is not ported."""
        untested = (e.rfe_type, info.chip_ver) not in _HARDWARE_VERIFIED_RFE_CUTS
        logger.info(
            "RTL8822BU board: rfe_type=%d cut=%d rf=2T2R crystal_cap=0x%02x thermal=0x%02x "
            "id_valid=%d usb_switch=%d eeprom_vidpid=%04x:%04x regulatory=%d interface=%d "
            "bt_raw=%d bt_coexist=%d bt_ant=%d bt_path=%s board_type=0x%02x "
            "pa_lna=2g:%d/%d 5g:%d/%d type=gpa%d/apa%d/glna%d/alna%d mac=%s%s",
            e.rfe_type, info.chip_ver, e.crystal_cap, e.thermal_meter, int(e.eeprom_id_valid),
            int(e.usb_mode_switch), e.eeprom_vid, e.eeprom_pid, e.regulatory,
            e.interface_sel, int(e.bt_coexist_raw), int(e.bt_coexist), 2 if e.bt_ant_num else 1,
            "B" if e.bt_ant_path else "A", e.board_type, int(e.external_pa_2g),
            int(e.external_lna_2g), int(e.external_pa_5g), int(e.external_lna_5g), e.type_gpa,
            e.type_apa, e.type_glna, e.type_alna, e.mac_address or "<none>",
            "  [untested variant]" if untested else "")
        if e.rfe_type in _RFE_PINMUX_UNPORTED:
            logger.warning("RTL8822BU: untested variant: rfe_type=%d RFE pinmux "
                           "(phydm_8822b_type%d_rfe) is not ported — running the iFEM fallback; "
                           "antenna routing may be wrong.", e.rfe_type, e.rfe_type)

    async def _watchdog_loop(self) -> None:
        """Run `phydm_watchdog` every ~2 s (the vendor cadence) — read the FA counters, adapt the RX
        IGI, reset the counters. Also verify TX is not paused (REG_TXPAUSE read as 16-bit). Serialized
        with `set_channel` via `_io_lock`; control I/O only, never 802.11 TX."""
        loop = asyncio.get_running_loop()
        while True:
            await asyncio.sleep(2.0)
            if self._io_lock.locked():
                continue
            try:
                async with self._io_lock:
                    fa = await loop.run_in_executor(
                        None, dm_watchdog.phydm_watchdog, self.transport, self._dig_st)
                    txpause = await loop.run_in_executor(
                        None, self.transport.read16, 0x0522)
                if txpause:
                    logger.warning("[WATCHDOG] TXPAUSE=0x%04x — clearing", txpause)
                    async with self._io_lock:
                        await loop.run_in_executor(
                            None, self.transport.write16, 0x0522, 0x0000)
                if logger.isEnabledFor(logging.DEBUG) and self._dig_st is not None:
                    logger.debug(
                        "[WATCHDOG] fa=%d cca=%d cck=%d ofdm=%d igi=0x%02x cckpd=%d cck_ma=%s",
                        fa.cnt_all, fa.cnt_cca_all, fa.cck_fail, fa.ofdm_fail,
                        self._dig_st.cur_ig_value, self._dig_st.cck_pd_lv,
                        "reset" if self._dig_st.cck_fa_ma == dm_watchdog.CCK_FA_MA_RESET
                        else self._dig_st.cck_fa_ma)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.debug("8822bu watchdog tick skipped: %s", e)

    # --- RX path -----------------------------------------------------------
    def _read_once(self) -> Optional[bytes]:
        return self.transport.bulk_in()

    def _dispatch(self, buf: bytes) -> None:
        if logger.isEnabledFor(logging.DEBUG):
            self._add_rx_debug_stats(_rx_desc_stats(buf))
        cb = self._rx_cb
        if cb is None and not self._ack_detect_on:
            return
        for frame, rssi in iter_frames(buf):
            # A 10-byte 0xD4 frame is an ACK (the parser drops control frames); the base tallies it
            # iff the ACK tap is armed and RA=frame[4:10] is a MAC we inject as.
            if len(frame) == 10 and frame[0] == 0xD4:
                self.record_ack(frame)
                continue
            if cb is None:
                continue
            parsed = WlanFrameParser.parse_80211_frame(frame, rssi)
            if parsed is not None:
                self._dbg_frames += 1                       # per-dwell tally (see set_channel)
                if parsed.type == "beacon":
                    self._dbg_beacons += 1
                cb(parsed)

    def _add_rx_debug_stats(self, st: _RxDebugStats) -> None:
        self._dbg_rx.bufs += st.bufs
        self._dbg_rx.bytes += st.bytes
        self._dbg_rx.desc += st.desc
        self._dbg_rx.good += st.good
        self._dbg_rx.crc_err += st.crc_err
        self._dbg_rx.icv_err += st.icv_err
        self._dbg_rx.c2h += st.c2h
        self._dbg_rx.runt += st.runt
        self._dbg_rx.zero_len += st.zero_len
        self._dbg_rx.truncated += st.truncated

    def _rx_debug_line(self) -> str:
        st = self._dbg_rx
        return (
            f"rxbuf={st.bufs}/{st.bytes}B desc={st.desc} good={st.good} "
            f"crc={st.crc_err} icv={st.icv_err} c2h={st.c2h} runt={st.runt} "
            f"zero={st.zero_len} trunc={st.truncated}"
        )

    def _reset_rx_debug_stats(self) -> None:
        self._dbg_frames = 0
        self._dbg_beacons = 0
        self._dbg_rx = _RxDebugStats()

    async def _enable_rx_acks(self) -> None:
        """No-op: enable_monitor already accept-alls RXFLTMAP1 (all ctrl subtypes incl. ACK are
        admitted), so the recipient's ACK control frames already reach RX. Nothing to enable on
        the chip (the base arms the tally). Not enter_active_monitor, which makes the chip emit ACKs."""
        return

    async def _disable_rx_acks(self) -> None:
        """No-op, matching ``_enable_rx_acks``: the monitor RX filter is left untouched."""
        return

    def _heal_cold_synth(self, t) -> None:
        """Recover the intermittent cold-boot 2.4 GHz synth wedge (~20% of cold boots).

        Symptom: the cold->2.4 GHz tune leaves the synth unlocked (RF18 bit15 set) and 2.4 GHz RX
        is deaf until a band re-cycle. The bring-up wire is byte-for-byte (verify_pcap /
        verify_channels green), so this is a HW synth-lock fault the kernel's tight transfer pacing
        avoids and userland USB intermittently hits — not a missing op. The chip's own recovery is a
        5->2.4 GHz re-cycle, but HW-measured it only re-locks once the synth has SETTLED: an immediate
        bounce right after the stuck tune does nothing, a short settle first makes it take. So settle,
        bounce through 5 GHz and back, re-check; repeat a few times. No-op on the 80% of boots that
        lock cleanly (bit15 clear -> returns immediately)."""
        for attempt in range(4):
            if not (sipi.read_rf_reg(t, sipi.RF_PATH_A, 0x18) & (1 << 15)):
                return
            logger.warning("8822bu cold 2.4 GHz synth unlocked (RF18 bit15) — settle + re-cycle "
                           "5->2.4 GHz (try %d)", attempt + 1)
            time.sleep(0.3)
            chan.set_channel_bw(t, _HEAL_5G_CHANNEL, prev_ch=_DEFAULT_CHANNEL,
                                txpwr_pg=self._txpwr_pg, rfe_type=self._rfe_type, cut=self._cut)
            chan.set_channel_bw(t, _DEFAULT_CHANNEL, prev_ch=_HEAL_5G_CHANNEL,
                                txpwr_pg=self._txpwr_pg, rfe_type=self._rfe_type, cut=self._cut)
        if sipi.read_rf_reg(t, sipi.RF_PATH_A, 0x18) & (1 << 15):
            logger.error("8822bu 2.4 GHz synth still unlocked after re-cycles — RX may be deaf on 2.4 GHz")

    async def _dbg_rx_state(self, ctx: str) -> None:
        """Log the decoded RX-path register read-back (DEBUG only) — the cold-wedge probe."""
        if not logger.isEnabledFor(logging.DEBUG):
            return
        loop = asyncio.get_running_loop()
        async with self._io_lock:
            line = await loop.run_in_executor(None, _rx_state_line, self.transport)
        logger.debug("[RXSTATE %s] %s", ctx, line)

    async def set_channel(self, channel: int, scan: bool = False) -> bool:
        loop = asyncio.get_running_loop()
        prev = self._channel
        # Report the dwell we're leaving — exposes the "ch1..13 caught 0, ch36 caught N"
        # signature of the intermittent cold-boot 2.4 GHz silence — then reset for the next.
        prev_5g = prev is not None and prev > 14
        band_change = prev is None or prev_5g != (channel > 14)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "[HOP] ch%s->%d band_change=%s | ch%s dwell: frames=%d beacons=%d | %s",
                prev, channel, band_change, prev, self._dbg_frames, self._dbg_beacons,
                self._rx_debug_line())
        self._reset_rx_debug_stats()

        def _tune(t):
            chan.set_channel_bw(t, channel, prev_ch=prev, txpwr_pg=self._txpwr_pg,
                                rfe_type=self._rfe_type, cut=self._cut, is_scan=True)

        async with self._io_lock:
            await loop.run_in_executor(None, _tune, self.transport)
        # Verify the RF actually landed on the requested channel (read RF18 back).
        actual_ch = await self._verify_channel(channel, loop)
        if actual_ch is not None and actual_ch != channel:
            logger.warning("[CHAN] tune reported ch%d but RF18 readback says ch%d — "
                           "retrying once", channel, actual_ch)
            async with self._io_lock:
                await loop.run_in_executor(None, _tune, self.transport)
            actual_ch = await self._verify_channel(channel, loop)
            if actual_ch is not None and actual_ch != channel:
                logger.error("[CHAN] second tune still on ch%d instead of ch%d", actual_ch, channel)
        self._channel = channel
        if band_change:
            await self._dbg_rx_state(f"post-tune ch{channel} (band change)")
        return True

    async def _verify_channel(self, expected_ch: int, loop) -> Optional[int]:
        """Read RF18 back and extract the channel number the RF is actually on."""
        try:
            async with self._io_lock:
                rf18 = await loop.run_in_executor(
                    None, lambda: sipi.read_rf_reg(self.transport, sipi.RF_PATH_A, 0x18))
            actual_ch = rf18 & 0xFF
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("[CHAN] RF18 readback=0x%05x actual_ch=%d expected=%d",
                             rf18, actual_ch, expected_ch)
            return actual_ch
        except Exception as exc:
            logger.debug("[CHAN] RF18 readback failed: %s", exc)
            return None

    async def _inject_frame(self, frame_bytes: bytes) -> bool:
        """Build the fill_fake_txdesc descriptor (`tx.build_inject_txdesc`, HW ACK-retry limit
        12) and bulk-OUT the frame once.  On macOS the IOKit USB backend can accept a
        control-transfer register write (TXPAUSE clear) into its buffer but not propagate it
        to the device before the subsequent bulk-OUT is scheduled.  A short sleep gives the
        control pipe time to flush."""
        payload = tx.build_inject_txdesc(bytes(frame_bytes))
        loop = asyncio.get_running_loop()
        try:
            async with self._io_lock:
                await loop.run_in_executor(None, self.transport.write16, 0x0522, 0x0000)
                await loop.run_in_executor(None, time.sleep, 0.001)
                await loop.run_in_executor(None, self.transport.bulk_out, payload)
        except Exception as exc:
            logger.warning("[inject] bulk-OUT failed: %s", exc)
            return False
        self._inject_count += 1
        if logger.isEnabledFor(logging.DEBUG) and self._inject_count <= 3:
            try:
                async with self._io_lock:
                    cr = await loop.run_in_executor(None, self.transport.read8, 0x0100)
                    txpause = await loop.run_in_executor(None, self.transport.read8, 0x0522)
                    pqmap = await loop.run_in_executor(None, self.transport.read16, 0x010C)
                    bcn_ctrl = await loop.run_in_executor(None, self.transport.read8, 0x0550)
                logger.debug("[TXDIAG #%d] CR=0x%02x TXPAUSE=0x%02x PQMAP=0x%04x BCN_CTRL=0x%02x"
                             " | CR.TXDMA=%d CR.HCI_TXDMA=%d payload=%dB",
                             self._inject_count, cr, txpause, pqmap, bcn_ctrl,
                             bool(cr & 0x04), bool(cr & 0x01), len(payload))
            except Exception as exc:
                logger.debug("[TXDIAG] register read failed: %s", exc)
        return True

    async def check_tx_capability(self) -> tuple[bool, str]:
        """Verify TX works: check DMA registers, send a test frame, and (on Linux
        only) listen for it on RX.  On macOS the RX loopback is skipped because
        macOS does not reflect injected frames back to the RX path (unlike
        Linux mac80211), so TX verification is register-level only."""
        import sys
        from airscope.dot11.deauth import build_deauth
        loop = asyncio.get_running_loop()
        bcast = b"\xff\xff\xff\xff\xff\xff"
        test_frame = build_deauth(bcast, bcast, bcast, 7)

        ok = await self.inject_frame(test_frame)
        if not ok:
            return False, "bulk-OUT failed; adapter may be disconnected or busy"

        try:
            async with self._io_lock:
                cr = await loop.run_in_executor(None, self.transport.read8, 0x0100)
                txpause = await loop.run_in_executor(None, self.transport.read16, 0x0522)
        except Exception as exc:
            return False, f"register read-back failed: {exc}"

        issues: list[str] = []
        if not (cr & 0x01):
            issues.append("HCI_TXDMA_EN not set")
        if not (cr & 0x04):
            issues.append("TXDMA_EN not set")
        if txpause:
            issues.append(f"TXPAUSE=0x{txpause:04x} (TX paused)")
        if issues:
            return False, "TX DMA issue: " + "; ".join(issues)

        if sys.platform == "darwin":
            return True, (f"TX registers OK (CR=0x{cr:02x} TXPAUSE=0x{txpause:04x}); "
                          "macOS TX loopback not available — TX verified at USB level")

        from airscope.dot11.mac import mac_to_str
        marker = b"\x02\x00\x00\x00\x00\x01"
        marker_str = mac_to_str(marker)
        test_frame2 = build_deauth(bcast, marker, bcast, 7)
        seen = asyncio.Event()
        original_cb = self._rx_cb

        def _watcher(pkt):
            if pkt is not None and pkt.subtype_id == 12:
                if pkt.source == marker_str or pkt.transmitter == marker_str:
                    seen.set()
            if original_cb is not None:
                original_cb(pkt)

        self._rx_cb = _watcher
        try:
            await self.inject_frame(test_frame2)
            try:
                await asyncio.wait_for(seen.wait(), timeout=0.3)
            except asyncio.TimeoutError:
                return False, (
                    "TX test frame not seen on RX stream; the adapter may not "
                    "be transmitting. Try: replug the adapter, or use a "
                    "different adapter (e.g. Alfa AWUS036ACH with RTL8812AU)."
                )
        finally:
            self._rx_cb = original_cb

        return True, f"TX OK (loopback + registers: CR=0x{cr:02x} TXPAUSE=0x{txpause:04x})"

    def _stamp_tx_seq(self, frame_bytes: bytes) -> bytes:
        """Realtek HW assigns the 802.11 sequence number (the txdesc sets EN_HWSEQ), so the
        frame goes out unchanged."""
        return frame_bytes

    async def enter_active_monitor(self, mac: bytes, bssid: Optional[bytes] = None) -> bytes:
        """Re-point REG_MACID to ``mac`` so the hardware HW-ACKs frames to it.
        Reversed by exit_active_monitor."""
        await self._set_self_mac(":".join(f"{b:02x}" for b in mac))
        return bytes(mac)

    async def exit_active_monitor(self) -> None:
        """Restore the card's real MAC in REG_MACID."""
        if self.mac_address:
            await self._set_self_mac(self.mac_address)

    async def _set_self_mac(self, mac_str: str) -> None:
        loop = asyncio.get_running_loop()
        async with self._io_lock:
            await loop.run_in_executor(None, mac.set_mac_addr, self.transport, mac_str)

    async def close(self) -> None:
        if self._watchdog_task is not None:
            self._watchdog_task.cancel()
            self._watchdog_task = None
        if self._reader is not None:
            await self._reader.stop()
            self._reader = None
        try:
            usb.util.release_interface(self.transport.dev, 0)
        except usb.core.USBError as e:
            logger.debug("release_interface(0): %s", e)
        self.transport.close()
