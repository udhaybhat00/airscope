"""USB worker thread for the captive-portal AP.

Runs the beacon TX loop and dispatches incoming frames to the AP core,
DHCP, DNS, and TCP stacks.  Integrates with the existing airscope driver
(async ``inject_frame`` / ``register_rx_callback``) via ``asyncio``.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass, field
from typing import Callable, Optional

from airscope.evil_twin.ap.ap_core import APStateMachine
from airscope.evil_twin.ap.frames import craft_beacon

log = logging.getLogger(__name__)

_BEACON_INTERVAL_MS = 100
_STALE_CLIENT_SEC = 30.0


@dataclass
class ApWorker:
    """Runs the captive-portal AP over an existing airscope driver."""
    driver: object
    iface: object
    ssid: str
    bssid: str
    channel: int
    hs: object
    pair: object
    on_password: Optional[Callable[[str], None]] = None
    log_fn: Optional[Callable[[str], None]] = None

    _ap: Optional[APStateMachine] = field(default=None, repr=False)
    _beacon_task: Optional[asyncio.Task] = field(default=None, repr=False)
    _cleanup_task: Optional[asyncio.Task] = field(default=None, repr=False)
    _running: bool = field(default=False, repr=False)
    _tx_queue: list = field(default_factory=list, repr=False)
    _tx_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _tx_event: threading.Event = field(default_factory=threading.Event, repr=False)

    def __post_init__(self) -> None:
        self._log = self.log_fn or (lambda m: log.info(m))
        bssid_bytes = bytes(int(o, 16) for o in self.bssid.split(":"))

        self._ap = APStateMachine(
            ap_mac=bssid_bytes,
            ssid=self.ssid,
            channel=self.channel,
            usb_tx=self._usb_tx,
        )

    def _usb_tx(self, frame: bytes, priority: int = 2) -> None:
        """Thread-safe TX enqueue. Called from AP core / DHCP / DNS."""
        with self._tx_lock:
            self._tx_queue.append((priority, frame))
            self._tx_event.set()

    async def _tx_worker(self) -> None:
        """Drain the TX queue, sending frames sorted by priority."""
        while self._running:
            self._tx_event.wait(timeout=0.01)
            self._tx_event.clear()
            frames = []
            with self._tx_lock:
                if self._tx_queue:
                    self._tx_queue.sort(key=lambda t: t[0])
                    frames = self._tx_queue[:]
                    self._tx_queue.clear()
            for _priority, frame in frames:
                try:
                    await self.driver.inject_frame(frame)
                except Exception:
                    log.debug("inject_frame failed", exc_info=True)

    async def start(self) -> None:
        self._running = True
        self.iface.register_rx_callback(self._on_rx)
        self._beacon_task = asyncio.create_task(self._beacon_loop())
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        asyncio.create_task(self._tx_worker())
        self._log(f"[ap-worker] {self.ssid} started on ch {self.channel}")

    async def stop(self) -> None:
        self._running = False
        if self._beacon_task:
            self._beacon_task.cancel()
        if self._cleanup_task:
            self._cleanup_task.cancel()
        self.iface.unregister_rx_callback(self._on_rx)
        self._log("[ap-worker] stopped")

    def _on_rx(self, pkt) -> None:
        raw = pkt.raw
        if len(raw) < 12:
            return
        self._ap.handle_rx(raw)

    async def _beacon_loop(self) -> None:
        bssid_bytes = bytes(int(o, 16) for o in self.bssid.split(":"))
        seq = 0
        while self._running:
            seq = (seq + 1) & 0xFFF
            beacon = craft_beacon(bssid_bytes, self.ssid, self.channel, seq)
            await self.driver.inject_frame(beacon)
            await asyncio.sleep(_BEACON_INTERVAL_MS / 1000.0)

    async def _cleanup_loop(self) -> None:
        while self._running:
            await asyncio.sleep(10.0)
