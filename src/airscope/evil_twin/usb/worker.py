"""USB worker thread: all blocking PyUSB I/O happens here.
Cross-platform: works on macOS (IOKit), Windows (WinUSB), Linux (libusb).
"""

import threading
import time
import queue
import logging
from dataclasses import dataclass
from typing import Optional, Callable


log = logging.getLogger(__name__)


@dataclass
class TxFrame:
    data: bytes
    priority: int  # 0=highest (mgmt), 1=dhcp/dns, 2=http, 3=beacon, 4=deauth
    timestamp: float = 0.0


class UsbWorker:
    """
    Dedicated daemon thread for all USB I/O.

    - RX: continuously reads from the USB RX endpoint, dispatches frames
    - TX: priority queue for outgoing frames (mgmt > dhcp > http > beacon > deauth)
    - Beacon: timer-based, sends pre-built beacon every 100ms
    - Deauth: timer-based, sends pre-built deauth frames at configured rate
    """

    def __init__(self, usb_dev, ep_rx: int, ep_tx: int,
                 ap_state_machine, beacon_frame: bytes,
                 deauth_frames: list[bytes], deauth_interval: float = 0.1,
                 beacon_interval: float = 0.1):
        self._dev = usb_dev
        self._ep_rx = ep_rx
        self._ep_tx = ep_tx
        self._ap = ap_state_machine
        self._beacon = beacon_frame
        self._deauth_frames = deauth_frames
        self._deauth_interval = deauth_interval
        self._beacon_interval = beacon_interval

        self._tx_queue: queue.PriorityQueue = queue.PriorityQueue()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._tx_count = 0
        self._rx_count = 0
        self._last_tui_update = 0.0
        self._stats_callback: Optional[Callable] = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="USB-Worker")
        self._thread.start()
        log.info("USB Worker started")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=3.0)
        log.info("USB Worker stopped")

    def set_stats_callback(self, callback: Callable):
        self._stats_callback = callback

    def enqueue_tx(self, frame: bytes, priority: int = 2):
        self._tx_queue.put(TxFrame(data=frame, priority=priority,
                                   timestamp=time.monotonic()))

    def _run(self):
        next_beacon = time.monotonic()
        next_deauth = time.monotonic()
        deauth_idx = 0

        while self._running:
            now = time.monotonic()

            try:
                data = self._dev.read(self._ep_rx, 4096, timeout=5)
                if data:
                    self._rx_count += 1
                    self._ap.handle_rx(bytes(data))
            except Exception:
                pass

            while not self._tx_queue.empty():
                try:
                    tx_frame = self._tx_queue.get_nowait()
                    self._dev.write(self._ep_tx, tx_frame.data, timeout=50)
                    self._tx_count += 1
                except Exception as e:
                    log.debug(f"TX error: {e}")
                    break

            if now >= next_beacon:
                try:
                    self._dev.write(self._ep_tx, self._beacon, timeout=50)
                    self._tx_count += 1
                except Exception:
                    pass
                next_beacon = now + self._beacon_interval

            if self._deauth_frames and now >= next_deauth:
                try:
                    frame = self._deauth_frames[deauth_idx % len(self._deauth_frames)]
                    self._dev.write(self._ep_tx, frame, timeout=50)
                    self._tx_count += 1
                    deauth_idx += 1
                except Exception:
                    pass
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

    @property
    def stats(self) -> dict:
        return {'tx': self._tx_count, 'rx': self._rx_count}
