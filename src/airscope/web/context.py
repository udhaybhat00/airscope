"""Headless engine context for the web backend: array, vault, scan loop.

Phase 1 is read-only (list devices, snapshot APs, broadcast ticks). It owns
no radio on its own: ``bringup_all`` attaches present cards when asked, and
``AIRSCOPE_DEMO=1`` (or ``demo=True``) fakes a wandering scan for UI work
without hardware.
"""
from __future__ import annotations

import asyncio
import os
import time
from dataclasses import asdict
from pathlib import Path
from typing import List, Optional

from airscope import exports
from airscope.persist.vault import Vault
from airscope.web.bus import Bus

TICK_S = 0.5


class DemoArray:
    """Wandering synthetic scan. Demo only: never touches USB."""

    def __init__(self) -> None:
        import random

        from airscope.models import AccessPoint
        self._rng = random.Random(7)
        self.access_points = {}
        self.clients = {}
        self.forged_macs = set()
        self.members = []
        defs = [("aa:bb:cc:dd:ee:01", "HomeNet", 6, -42, "WPA2", ["PSK"], [2]),
                ("aa:bb:cc:dd:ee:02", "CoffeeShop", 11, -68, "OPEN", [], []),
                ("aa:bb:cc:dd:ee:03", None, 1, -75, "WEP", [], []),
                ("aa:bb:cc:dd:ee:04", "SecureNet", 36, -58, "WPA3", ["SAE"], [8]),
                ("aa:bb:cc:dd:ee:05", "MixedMode", 6, -63, "WPA2", ["PSK", "SAE"], [2, 8])]
        for bssid, ssid, ch, sig, enc, akms, suites in defs:
            ap = AccessPoint(bssid=bssid, ssid=ssid, channel=ch, encryption=enc,
                             akms=akms, akm_suites=suites, beacons=40)
            ap.signal_by_card = {"demo0": sig}
            ap.last_seen = time.time()
            self.access_points[bssid] = ap
        self._base = {b: a.signal_by_card["demo0"] for b, a in self.access_points.items()}
        self._rates: dict[str, dict[str, float]] = {}
        self._tick_rates()

    def get_access_points(self, include_eviltwin: bool = True):
        return list(self.access_points.values())

    async def start_hopping(self, channels=None, interval=0.25) -> None:
        return None

    async def close(self) -> None:
        return None

    def tick(self) -> None:
        """Wander signals and beacon counts so the table visibly lives."""
        for bssid, ap in self.access_points.items():
            base = self._base[bssid]
            ap.signal_by_card["demo0"] = base + self._rng.randint(-3, 3)
            ap.beacons += self._rng.randint(0, 3)
            ap.last_seen = time.time()
        self._tick_rates()

    def _tick_rates(self) -> None:
        """Simulated per-AP packet rates (packets/s by class)."""
        for bssid in self.access_points:
            prev = self._rates.get(bssid, {"beacon": 9.0, "data": 4.0,
                                           "inject": 0.0, "deauth": 0.0})
            burst = 30.0 if self._rng.random() < 0.06 else 0.0
            deauth = 12.0 if self._rng.random() < 0.03 else 0.0
            self._rates[bssid] = {
                "beacon": max(0.0, prev["beacon"] + self._rng.uniform(-1.5, 1.5)),
                "data": max(0.0, prev["data"] * 0.7 + self._rng.uniform(0, 6) + burst),
                "inject": max(0.0, prev["inject"] * 0.5 + self._rng.uniform(0, 2)),
                "deauth": deauth,
            }

    def demo_rates(self) -> dict:
        """Current simulated rates (same shape as the real diff path)."""
        return {b: dict(v) for b, v in self._rates.items()}


class HeadlessContext:
    """Engine state shared by every request/socket: array + vault + bus."""

    def __init__(self, array=None, demo: bool = False) -> None:
        self.demo = demo or os.environ.get("AIRSCOPE_DEMO") == "1"
        if self.demo:
            import tempfile

            from airscope.persist.config import Config
            self._prev_captures_dir = Config.captures_dir
            tmp = tempfile.mkdtemp(prefix="airscope-demo-")
            Config.captures_dir = tmp
        else:
            self._prev_captures_dir = None
        self.array = array
        self.vault = Vault()
        self.bus = Bus()
        self._scan_task: Optional[asyncio.Task] = None
        self.attack: Optional[dict] = None       # live attack record or None
        self._attack_stop = None                 # BatchRunner / campaign stop hook
        self.cracks: dict[str, dict] = {}        # job_id -> crack job record
        self._crack_seq = 0
        self.batches: dict[str, dict] = {}       # job_id -> batch job record
        self._batch_seq = 0
        self.scan_paused = False                 # hopping + ticks halted via /api/scan
        self._rate_prev: dict[str, dict] = {}
        self._rate_at: float = 0.0

    async def start(self) -> None:
        """Attach demo array when asked; hop when cards exist; tick forever."""
        if self.array is None and self.demo:
            self.array = DemoArray()
        if self.array is not None and getattr(self.array, "members", None):
            try:
                await self.array.start_hopping()
            except Exception:
                pass
        self._scan_task = asyncio.create_task(self._scan_loop())

    async def stop(self) -> None:
        if self._scan_task is not None:
            self._scan_task.cancel()
            try:
                await self._scan_task
            except asyncio.CancelledError:
                pass
            self._scan_task = None
        if self.array is not None:
            try:
                await self.array.close()
            except Exception:
                pass
        if self._prev_captures_dir is not None:
            from airscope.persist.config import Config
            Config.captures_dir = self._prev_captures_dir
            self._prev_captures_dir = None

    async def bringup_all(self) -> list[dict]:
        """Attach every present card (no setup: pre-installed cards only)."""
        from airscope.device.manager import devices, wlan_iface
        from airscope.wlan.array import WlanArray
        if self.array is None:
            self.array = WlanArray()
        done: list[dict] = []
        for i, dev in enumerate(devices()):
            iface = wlan_iface(dev, name=f"wlan{i}")
            if iface is None:
                continue
            try:
                ok = await iface.connect()
            except Exception as e:
                done.append({"device": dev.description, "ok": False, "error": str(e)})
                continue
            if not ok:
                done.append({"device": dev.description, "ok": False, "error": "bring-up failed"})
                continue
            self.array.attach(iface)
            done.append({"device": dev.description, "ok": True})
        return done

    async def _scan_loop(self) -> None:
        while True:
            if isinstance(getattr(self, "array", None), DemoArray):
                self.array.tick()
            if self.scan_paused:
                self._rate_at = 0.0   # resume from a fresh baseline, not a stale spike
                self.bus.publish("scan.tick", {"aps": self.snapshot_aps(), "rates": {},
                                               "scanning": False, "at": time.time()})
            else:
                self.bus.publish("scan.tick", {"aps": self.snapshot_aps(),
                                               "rates": self.snapshot_rates(),
                                               "scanning": True,
                                               "at": time.time()})
            await asyncio.sleep(TICK_S)

    # ----- attacks (Phase 2) -------------------------------------------------

    def device_list(self) -> List[dict]:
        """Present cards with attached state (empty list, never an error)."""
        try:
            from airscope.device.manager import devices
            devs = devices()
        except Exception:
            return []
        attached = set()
        for m in getattr(self.array, "members", None) or []:
            attached.add((getattr(m, "vid", None), getattr(m, "pid", None),
                          getattr(m, "bus", None), getattr(m, "address", None)))
        out = []
        for d in devs:
            out.append({"vid": d.vid, "pid": d.pid, "chipset": d.chipset,
                        "vendor": d.vendor, "product": d.product_name,
                        "bus": d.bus, "address": d.address,
                        "attached": (d.vid, d.pid, d.bus, d.address) in attached})
        return out

    def snapshot_aps(self) -> List[dict]:
        """Current APs as plain dicts (same shape as every scan.tick)."""
        if self.array is None:
            return []
        return [asdict(s) for s in exports.ap_snaps_from_array(self.array)]

    def snapshot_rates(self) -> dict[str, dict[str, float]]:
        """Per-AP packet rates (packets/s): real diffs, or the demo simulation."""
        if self.array is None:
            return {}
        if isinstance(self.array, DemoArray):
            return self.array.demo_rates()
        snapshot = getattr(getattr(self.array, "packet_stats", None), "snapshot", None)
        if snapshot is None:
            return {}
        now = time.time()
        dt = max(0.25, now - self._rate_at) if self._rate_at else 1.0
        out: dict[str, dict[str, float]] = {}
        for ap in self.array.get_access_points():
            cur = snapshot(ap.bssid)
            prev = self._rate_prev.get(ap.bssid, cur)
            out[ap.bssid] = {k: round(max(0.0, (cur.get(k, 0) - prev.get(k, 0)) / dt), 1)
                             for k in ("beacon", "data", "inject", "deauth")}
            self._rate_prev[ap.bssid] = cur
        self._rate_at = now
        return out

    async def set_scanning(self, on: bool) -> bool:
        """Halt or resume hopping (ticks keep flowing with a scanning flag)."""
        self.scan_paused = not on
        if self.array is not None and not isinstance(self.array, DemoArray):
            try:
                if on:
                    await self.array.start_hopping()
                else:
                    await self.array.stop_hopping()
            except Exception:
                pass
        return on

    def engine_state(self) -> str:
        """idle/demo/scanning; attacking is reported via attack.state events."""
        if self.array is None or not getattr(self.array, "members", None):
            return "demo" if self.demo and self.array is not None else "idle"
        return "scanning"

    def find_ap(self, bssid: str):
        """Live AP object by BSSID (case-insensitive), else None."""
        if self.array is None:
            return None
        want = bssid.lower()
        for ap in self.array.get_access_points():
            if ap.bssid.lower() == want:
                return ap
        return None

    def eligible_attacks(self, ap) -> List[dict]:
        """Attack buttons for one AP: kind/label plus the block reason (if any).

        Same gating as the Focus screen (``visible()`` + ``ineligible_reason()``),
        so the dashboard can never offer what the TUI would grey out.
        """
        from airscope.campaigns.deauth import DeauthCampaign
        from airscope.campaigns.eviltwin import EvilTwinCampaign
        from airscope.campaigns.pin import WpsCampaign
        from airscope.campaigns.pmkid import PmkidHarvestAttack
        from airscope.campaigns.sae import SaeCampaign
        from airscope.persist.config import Config
        out = []
        for cls, kind in ((WpsCampaign, "wps"), (PmkidHarvestAttack, "pmkid"),
                          (DeauthCampaign, "handshake"), (SaeCampaign, "sae"),
                          (EvilTwinCampaign, "eviltwin")):
            if not cls.visible(ap):
                continue
            if Config.is_silenced(ap.bssid):
                reason = "AP silenced"
            else:
                reason = cls.ineligible_reason(ap)
            out.append({"kind": kind, "label": cls.idle_label,
                        "blocked": reason})
        return out

    async def start_attack(self, kind: str, bssid: str, timeout: Optional[float] = None,
                           punt: bool = True) -> dict:
        """Start one attack; raises _Busy (radio taken), _NoTarget, _Blocked."""
        if kind not in ("wps", "pmkid", "handshake", "sae", "eviltwin"):
            raise _Blocked(f"unknown attack: {kind}")
        if self.attack is not None:
            raise _Busy(self.attack["kind"])
        ap = self.find_ap(bssid)
        if ap is None:
            raise _NoTarget(bssid)
        if self.demo:
            return await self._start_demo_attack(kind, ap, timeout)
        return await self._start_real_attack(kind, ap, timeout, punt)

    async def _start_demo_attack(self, kind: str, ap, timeout: Optional[float]) -> dict:
        from airscope.web.demo import DemoAttack
        from airscope.persist.config import Config
        attack = {"id": f"atk-{int(time.time() * 1000)}", "kind": kind,
                  "bssid": ap.bssid, "ssid": ap.ssid, "started": time.time(),
                  "state": "running", "demo": True}
        sim = DemoAttack(kind, ap, Path(Config.captures_dir),
                         log=lambda m: self.bus.publish(
                             "attack.log", {"attack_id": attack["id"], "line": m}))
        attack["task"] = asyncio.create_task(self._watch_demo(attack, sim))
        attack["handle"] = sim
        self.attack = attack
        self.bus.publish("attack.state", {**_public_attack(attack), "state": "started"})
        return _public_attack(attack)

    async def _watch_demo(self, attack: dict, sim) -> None:
        try:
            sim.run()
            await sim._task
        finally:
            self.vault.refresh()
            self.bus.publish("vault.changed", {})
            self.bus.publish("capture.saved", {"bssid": attack["bssid"]})
            self.attack = None
            self.bus.publish("attack.state", {**_public_attack(attack), "state": "finished"})

    async def _start_real_attack(self, kind: str, ap, timeout: Optional[float],
                                 punt: bool) -> dict:
        from airscope.campaigns.batch import BatchRunner, STEP_TIMEOUTS
        if kind == "eviltwin":
            return await self._start_eviltwin(ap, punt)
        if kind not in ("wps", "pmkid", "handshake", "sae"):
            raise _Blocked(f"unknown attack: {kind}")
        attack = {"id": f"atk-{int(time.time() * 1000)}", "kind": kind,
                  "bssid": ap.bssid, "ssid": ap.ssid, "started": time.time(),
                  "state": "running", "demo": False}
        runner = BatchRunner(
            self.array, self.vault,
            log=lambda m: self.bus.publish(
                "attack.log", {"attack_id": attack["id"], "line": m}),
            timeouts={kind: timeout or STEP_TIMEOUTS[kind]})
        attack["task"] = asyncio.create_task(self._watch_batch(attack, runner, ap, kind))
        attack["handle"] = runner
        self.attack = attack
        self.bus.publish("attack.state", {**_public_attack(attack), "state": "started"})
        return _public_attack(attack)

    async def _watch_batch(self, attack: dict, runner, ap, kind: str) -> None:
        from airscope.campaigns.batch import BatchStep
        step = BatchStep(attack["bssid"], attack["ssid"], kind, 0)
        try:
            summary = await runner.run([step], [ap])
            solved = [r for r in summary.results if r.outcome in ("solved", "captured")]
            detail = solved[0].detail if solved else (
                summary.results[0].detail if summary.results else "")
        finally:
            self.bus.publish("vault.changed", {})
            self.attack = None
            self.bus.publish("attack.state", {**_public_attack(attack),
                                              "state": "finished", "detail": detail})

    async def _start_eviltwin(self, ap, punt: bool) -> dict:
        from airscope.campaigns.eviltwin import (
            EvilTwinCampaign, EvilTwinInput, default_punt_modes)
        try:
            iface = self.array.select_iface(ap.channel) or self.array.select_iface(ap.channel)
            if iface is None:
                raise _Blocked("no card reaches the target band")
            evil = EvilTwinInput(
                twin_iface=iface, punt_iface=iface, twin_channel=ap.channel,
                twin_bssid=ap.bssid,
                punt_modes=default_punt_modes(ap) if punt else (),
                csa_channel=None, punt_period_sec=None, punt_once=False)
            camp = EvilTwinCampaign(self.array, ap, evil)
        except ValueError as e:
            raise _Blocked(str(e))
        if not camp.run():
            raise _Busy("eviltwin")
        attack = {"id": f"atk-{int(time.time() * 1000)}", "kind": "eviltwin",
                  "bssid": ap.bssid, "ssid": ap.ssid, "started": time.time(),
                  "state": "running", "demo": False}
        attack["task"] = asyncio.create_task(self._watch_campaign(attack, camp))
        attack["handle"] = camp
        self.attack = attack
        self.bus.publish("attack.state", {**_public_attack(attack), "state": "started"})
        return _public_attack(attack)

    async def _watch_campaign(self, attack: dict, camp) -> None:
        try:
            while not camp.done:
                await asyncio.sleep(0.5)
        finally:
            self.bus.publish("vault.changed", {})
            self.attack = None
            self.bus.publish("attack.state", {**_public_attack(attack), "state": "finished"})

    async def stop_attack(self) -> Optional[dict]:
        """Stop the live attack (fire-and-forget like the TUI stop buttons)."""
        attack = self.attack
        if attack is None:
            return None
        handle = attack.get("handle")
        if handle is not None:
            try:
                if hasattr(handle, "request_stop"):
                    handle.request_stop()
                else:
                    await handle.stop()
            except Exception:
                pass
        self.bus.publish("attack.state", {**_public_attack(attack), "state": "stopping"})
        return _public_attack(attack)

    # ----- batch jobs (Phase 3) ------------------------------------------------

    async def start_batch(self, bssids: Optional[list[str]] = None,
                          timeouts: Optional[dict] = None) -> dict:
        """Plan (build_plan verbatim) and run in the background. Demo mode
        simulates each step with DemoAttack; real mode runs BatchRunner."""
        from airscope.campaigns.batch import build_plan
        aps = self._batch_targets(bssids)
        if not aps:
            raise _Blocked("no targets: no APs match" if bssids else "no APs in range")
        steps, skipped = build_plan(aps, self.vault)
        self._batch_seq += 1
        job = {"id": f"batch-{self._batch_seq}", "started": time.time(),
               "state": "running",
               "steps": [s.__dict__ for s in steps],
               "skipped": [r.__dict__ for r in skipped],
               "results": [], "demo": self.demo}
        if self.demo:
            job["task"] = asyncio.create_task(self._watch_demo_batch(job, steps, aps))
        else:
            job["task"] = asyncio.create_task(
                self._watch_real_batch(job, steps, aps, timeouts or {}))
        self.batches[job["id"]] = job
        self.bus.publish("batch.started", _public_batch(job))
        return _public_batch(job)

    def _batch_targets(self, bssids: Optional[list[str]]):
        """Resolve BSSIDs (or every AP when omitted), dropping unknowns."""
        if self.array is None:
            return []
        if not bssids:
            return self.array.get_access_points()
        want = {b.lower() for b in bssids}
        return [ap for ap in self.array.get_access_points() if ap.bssid.lower() in want]

    async def _watch_demo_batch(self, job: dict, steps, aps) -> None:
        from airscope.web.demo import DemoAttack
        from airscope.persist.config import Config
        from pathlib import Path as _Path
        job["stop"] = False
        try:
            for i, step in enumerate(steps):
                if job["stop"]:
                    break
                ap = next((a for a in aps if a.bssid == step.bssid), None)
                if ap is None:
                    continue
                self.bus.publish("batch.step", {"job_id": job["id"], "index": i,
                                                "step": step.__dict__, "state": "started"})
                sim = DemoAttack(step.kind, ap, _Path(Config.captures_dir),
                                 log=lambda m, _i=i: self.bus.publish(
                                     "batch.log", {"job_id": job["id"], "index": _i,
                                                   "line": m}))
                job["sim"] = sim
                sim.run()
                await sim._task
                job["sim"] = None
                self.vault.refresh()
                outcome = ("solved", f"{step.kind.upper()} credential saved") \
                    if step.kind == "wps" else ("captured", f"{step.kind} material saved")
                if sim.stopped:
                    outcome = ("timeout", "Stopped by user")
                result = {"bssid": step.bssid, "ssid": step.ssid, "kind": step.kind,
                          "outcome": outcome[0], "detail": outcome[1], "seconds": 0.0}
                job["results"].append(result)
                self.bus.publish("batch.step", {"job_id": job["id"], "index": i,
                                                "step": step.__dict__, "state": "done",
                                                "result": result})
                self.bus.publish("vault.changed", {})
        finally:
            job["state"] = "done"
            self.bus.publish("batch.done", _public_batch(job))

    async def _watch_real_batch(self, job: dict, steps, aps, timeouts: dict) -> None:
        from airscope.campaigns.batch import BatchRunner
        runner = BatchRunner(
            self.array, self.vault,
            log=lambda m: self.bus.publish("batch.log", {"job_id": job["id"], "line": m}),
            timeouts=timeouts)
        job["handle"] = runner
        n = len(steps)
        try:
            for i, step in enumerate(steps):
                if job.get("stop"):
                    break
                self.bus.publish("batch.step", {"job_id": job["id"], "index": i,
                                                "step": step.__dict__, "state": "started",
                                                "total": n})
                summary = await runner.run([step], aps)
                result = summary.results[0].__dict__ if summary.results else {}
                job["results"].append(result)
                self.bus.publish("batch.step", {"job_id": job["id"], "index": i,
                                                "step": step.__dict__, "state": "done",
                                                "result": result, "total": n})
                self.bus.publish("vault.changed", {})
        finally:
            job["state"] = "done"
            self.bus.publish("batch.done", _public_batch(job))

    async def stop_batch(self, job_id: str) -> Optional[dict]:
        """Stop after the current step (no-op when already done)."""
        job = self.batches.get(job_id)
        if job is None or job["state"] != "running":
            return None
        job["stop"] = True
        sim = job.get("sim")
        if sim is not None:
            sim.request_stop()
        handle = job.get("handle")
        if handle is not None and hasattr(handle, "request_stop"):
            handle.request_stop()
        self.bus.publish("batch.stopped", {"job_id": job_id})
        return _public_batch(job)

    # ----- crack jobs (Phase 2) ----------------------------------------------

    async def start_crack(self, path: str, wordlist: str) -> dict:
        """Launch a dictionary crack on one vault capture; demo simulates it."""
        from pathlib import Path as _Path
        cap = next((c for c in self.vault.all_captures() if c.path == path), None)
        if cap is None:
            raise _NoTarget(path)
        if not _Path(wordlist).is_file():
            raise _Blocked(f"wordlist not found: {wordlist}")
        self._crack_seq += 1
        job = {"id": f"crack-{self._crack_seq}", "path": path, "wordlist": wordlist,
               "bssid": cap.bssid, "ssid": cap.ssid, "started": time.time(),
               "state": "running", "demo": self.demo}
        job["task"] = asyncio.create_task(self._watch_crack(job, cap, wordlist))
        self.cracks[job["id"]] = job
        return _public_crack(job)

    async def _watch_crack(self, job: dict, cap, wordlist: str) -> None:
        try:
            if self.demo:
                psk = await self._demo_crack(job)
            else:
                psk = await self._real_crack(job, cap, wordlist)
            if psk:
                self.vault.save_cracked_psk(cap.bssid, cap.ssid, psk, "web")
                job["state"], job["psk"] = "done", psk
                self.bus.publish("crack.done", {**_public_crack(job), "psk": psk})
                self.bus.publish("vault.changed", {})
            else:
                job["state"] = "exhausted"
                self.bus.publish("crack.done", {**_public_crack(job)})
        except asyncio.CancelledError:
            job["state"] = "stopped"
            self.bus.publish("crack.done", {**_public_crack(job)})
            raise
        except Exception as e:
            job["state"], job["error"] = "failed", str(e)
            self.bus.publish("crack.done", {**_public_crack(job)})

    async def _demo_crack(self, job: dict) -> Optional[str]:
        """Fake a 5-second dictionary run with live progress ticks."""
        total = 1000
        for i in range(1, 11):
            await asyncio.sleep(0.5)
            self.bus.publish("crack.progress", {**_public_crack(job),
                                                "tested": i * 100, "total": total,
                                                "speed": "200 H/s"})
        return "demodemo"

    async def _real_crack(self, job: dict, cap, wordlist: str) -> Optional[str]:
        from pathlib import Path as _Path
        from airscope.crack import external as crack_ext
        from airscope.persist.common import bssid_to_dashed
        tools = crack_ext.detect_tools()
        hashfile = _Path(cap.path)
        records = crack_ext.hash_lines(hashfile)
        if tools.hashcat and records:
            kind = "HS" if cap.type == "HS" else "PMKID"
            tmp = crack_ext.write_temp_hashfile(
                hashfile.parent, bssid_to_dashed(cap.bssid),
                crack_ext.extract_records(hashfile, kind))
            try:
                pot = crack_ext.potfile_path(hashfile.parent)
                cmd = crack_ext.build_hashcat_cmd(tools.hashcat, tmp, _Path(wordlist), pot)
                await crack_ext.run_crack(
                    cmd, "hashcat",
                    on_progress=lambda p: self.bus.publish(
                        "crack.progress", {**_public_crack(job), "tested": p.tested,
                                           "total": p.total, "speed": p.speed}))
                _, show = await crack_ext.run_capture_output(
                    crack_ext.build_hashcat_show(tools.hashcat, tmp, pot))
                return crack_ext.parse_hashcat_show(show, records, cap.ssid)
            finally:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass
        dashed = bssid_to_dashed(cap.bssid)
        pcap = crack_ext.sibling_pcap(hashfile, dashed) if tools.aircrack else None
        if pcap is None:
            if not tools.hashcat and not tools.aircrack:
                raise _Blocked("No cracker installed. " + crack_ext.install_hint())
            if not records:
                raise _Blocked("No WPA handshake/PMKID hash lines in this file.")
            raise _Blocked("hashcat not found and no .pcap sibling for aircrack-ng.")
        keyfile = hashfile.parent / ".airscope-web.key"
        try:
            cmd = crack_ext.build_aircrack_cmd(tools.aircrack, pcap, _Path(wordlist), keyfile)
            run = await crack_ext.run_crack(
                cmd, "aircrack",
                on_progress=lambda p: self.bus.publish(
                    "crack.progress", {**_public_crack(job), "tested": p.tested,
                                       "total": p.total, "speed": p.speed}))
            return crack_ext.parse_aircrack_key(run.output, keyfile)
        finally:
            try:
                keyfile.unlink(missing_ok=True)
            except OSError:
                pass


class _Busy(Exception):
    """Radio already owned: maps to HTTP 409."""

    def __init__(self, kind: str) -> None:
        super().__init__(f"radio busy ({kind} active)")
        self.kind = kind


class _NoTarget(Exception):
    """Unknown BSSID/path: maps to HTTP 404."""


class _Blocked(Exception):
    """Ineligible or unusable input: maps to HTTP 422."""


def _public_batch(job: dict) -> dict:
    out = {k: job[k] for k in ("id", "started", "state", "steps", "skipped", "results")
           if k in job}
    out["solved"] = sum(1 for r in job.get("results", [])
                        if r.get("outcome") in ("solved", "captured"))
    return out


def _public_attack(attack: dict) -> dict:
    return {k: attack[k] for k in ("id", "kind", "bssid", "ssid", "started", "state")
            if k in attack}


def _public_crack(job: dict) -> dict:
    return {k: job[k] for k in ("id", "path", "bssid", "ssid", "started", "state")
            if k in job}
