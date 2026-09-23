"""Orchestration for the captive-portal EvilTwin attack.

Ties the USB worker, AP stack, and handshake validation together into
a single start/stop lifecycle that the EvilTwin campaign drives.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Optional

from airscope.evil_twin.usb.worker import ApWorker

log = logging.getLogger(__name__)


@dataclass
class CaptivePortalOrchestrator:
    """High-level controller for the captive-portal EvilTwin.

    Called from ``EvilTwinCampaign._step3_captive_portal`` after Step 1
    captures a real handshake and Step 2 brings up the OPEN twin beacon.
    """
    driver: object
    iface: object
    ssid: str
    bssid: str
    channel: int
    hs: object
    pair: object
    log_fn: Optional[Callable[[str], None]] = None
    on_password: Optional[Callable[[str], None]] = None

    _worker: Optional[ApWorker] = field(default=None, repr=False)
    _log: Optional[Callable] = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self._log = self.log_fn or (lambda m: log.info(m))

    async def start(self) -> None:
        self._worker = ApWorker(
            driver=self.driver,
            iface=self.iface,
            ssid=self.ssid,
            bssid=self.bssid,
            channel=self.channel,
            hs=self.hs,
            pair=self.pair,
            on_password=self.on_password,
            log_fn=self._log,
        )
        await self._worker.start()
        self._log("[captive-portal] AP stack running")

    async def stop(self) -> None:
        if self._worker:
            await self._worker.stop()
            self._worker = None
            self._log("[captive-portal] AP stack stopped")
