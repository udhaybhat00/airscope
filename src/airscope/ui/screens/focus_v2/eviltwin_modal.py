import os
import re
from typing import List, Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select

from airscope.chips.driver import FakeMacSupport
from airscope.wlan.array import fake_mac_rank
from airscope.wlan.channels import band_label
from airscope.ui.screens.focus_v2.art import display_name
from airscope.campaigns.eviltwin import EvilTwinInput

_MAC_RE = re.compile(r"^([0-9a-f]{2}:){5}[0-9a-f]{2}$")


def _plus_one(bssid: str) -> str:
    return bssid[:-1] + format((int(bssid[-1], 16) + 1) % 16, "x")


def _random_bssid() -> str:
    return "02:" + ":".join(f"{b:02x}" for b in os.urandom(5))


def _option(iface) -> str:
    """One picker row: display name plus the bands the card reaches."""
    bands = band_label(list(getattr(iface, "supported_channels", []) or []))
    return f"{display_name(iface)}  ({bands})" if bands else display_name(iface)


def _can_host(iface) -> bool:
    """A fake-AP host must run software-AP mode and HW-ACK a forged STA address."""
    return bool(getattr(iface, "supports_ap_mode", False)) and getattr(
        iface.driver, "FAKE_MAC", None) not in (FakeMacSupport.NONE, FakeMacSupport.UNIMPLEMENTED)


def _default_bssid_for(host, target) -> str:
    """The twin's default BSSID: spoof the target's own MAC on a spoofable card, else the card's
    hard MAC (the only address it will ACK/answer), else the target's."""
    if host is None or getattr(host.driver, "FAKE_MAC", None) is not FakeMacSupport.SPOOFABLE:
        return (getattr(host, "mac_address", None) or target.bssid)
    return target.bssid


class EvilTwinInputModal(ModalScreen[Optional[EvilTwinInput]]):
    """Pick the deauth and fake-AP adapters (and the twin's BSSID) before EvilTwin starts.
    The twin always mirrors the target's SSID and channel; no CSA funnels or punt controls."""

    BINDINGS = [Binding("escape", "cancel", "Cancel", show=True)]

    DEFAULT_CSS = """
    EvilTwinInputModal { align: center middle; }
    EvilTwinInputModal #dialog {
        width: 64; height: auto; max-height: 90%;
        border: thick $primary; background: $surface; padding: 1 2;
    }
    EvilTwinInputModal #title { width: 1fr; content-align: center middle; margin-bottom: 1; text-style: bold; }
    EvilTwinInputModal .row { height: auto; margin-bottom: 0; }
    EvilTwinInputModal .row-label { width: 22; height: 3; content-align: left middle; color: $text-muted; }
    EvilTwinInputModal .row Select { width: 1fr; }
    EvilTwinInputModal #bssid-col { width: 1fr; height: auto; }
    EvilTwinInputModal #bssid-btns { height: auto; }
    EvilTwinInputModal #bssid-btns Button {   /* min-width set in app.py: App CSS outranks DEFAULT_CSS */
        width: auto; height: 1; border: none; padding: 0 1; margin-right: 2;
        background: $primary; color: auto;
    }
    EvilTwinInputModal #channel-note { color: $text-muted; content-align: left middle; }
    EvilTwinInputModal #warn { color: $text-warning; content-align: center middle; height: auto; display: none; }
    EvilTwinInputModal #button-row { height: auto; align: center middle; margin-top: 0; }
    EvilTwinInputModal #button-row Button { margin: 0 1; }
    """

    def __init__(self, target, members: List) -> None:
        super().__init__()
        self.target = target
        self._hosts = sorted((m for m in members if _can_host(m)), key=fake_mac_rank)
        self._punters = list(members)
        self._single = len(self._hosts) == 1
        self._by_name = {m.name: m for m in members}

    def compose(self) -> ComposeResult:
        host = self._hosts[0] if self._hosts else None
        punter = next((m for m in self._punters if m is not host), host)
        with Vertical(id="dialog"):
            yield Label("EvilTwin - capture a real handshake, twin the AP, live-MIC the PSK",
                        id="title")

            with Horizontal(classes="row"):
                yield Label("Fake AP adapter", classes="row-label")
                yield Select([(_option(m), m.name) for m in self._hosts],
                             value=host.name if host else Select.BLANK,
                             allow_blank=False, id="twin-iface")

            with Horizontal(classes="row"):
                yield Label("Deauth adapter", classes="row-label")
                yield Select([(_option(m), m.name) for m in self._punters],
                             value=punter.name if punter else Select.BLANK,
                             allow_blank=False, id="punt-iface")

            with Horizontal(classes="row"):
                yield Label("Twin BSSID", classes="row-label")
                with Vertical(id="bssid-col"):
                    yield Input(value=self._default_bssid(), id="twin-bssid")
                    with Horizontal(id="bssid-btns"):
                        yield Button("Same", id="bssid-same")
                        yield Button("+1", id="bssid-plus1")
                        yield Button("Rand", id="bssid-random")

            with Horizontal(classes="row"):
                yield Label("Twin channel", classes="row-label")
                yield Label(f"mirrors the target on CH {self.target.channel} (Step 2 needs the "
                            "twin on the same channel)", id="channel-note")

            yield Label("", id="warn")
            with Horizontal(id="button-row"):
                yield Button("Start EvilTwin", variant="primary", id="btn-start")
                yield Button("Cancel", variant="default", id="btn-cancel")

    def on_mount(self) -> None:
        self._sync_bssid_field()
        self._sync_warning()

    def _default_bssid(self) -> str:
        return _default_bssid_for(self._hosts[0] if self._hosts else None, self.target)

    def _selected(self, widget_id: str):
        return self._by_name.get(self.query_one(f"#{widget_id}", Select).value)

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "twin-iface":
            self._sync_bssid_field()
        self._sync_warning()

    def _sync_bssid_field(self) -> None:
        host = self._selected("twin-iface")
        spoofable_host = host is not None and host.driver.FAKE_MAC is FakeMacSupport.SPOOFABLE
        bssid = self.query_one("#twin-bssid", Input)
        bssid.disabled = not spoofable_host
        for bid in ("bssid-same", "bssid-plus1", "bssid-random"):
            self.query_one(f"#{bid}", Button).disabled = not spoofable_host
        if not spoofable_host and host is not None:
            bssid.value = host.mac_address or self.target.bssid

    def _sync_warning(self) -> None:
        same_iface = self._selected("twin-iface") is self._selected("punt-iface")
        text = ("One adapter hosts the twin and deauths, so single-radio throughput suffers. "
                "Use 2 cards when you can." if same_iface else "")
        self._set_warn(text)

    def _set_warn(self, text: str) -> None:
        warn = self.query_one("#warn", Label)
        warn.update(text)
        warn.display = bool(text)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        bssid = self.query_one("#twin-bssid", Input)
        if bid == "bssid-same":
            bssid.value = self.target.bssid
        elif bid == "bssid-plus1":
            bssid.value = _plus_one(self.target.bssid)
        elif bid == "bssid-random":
            bssid.value = _random_bssid()
        elif bid == "btn-start":
            self._start()
        elif bid == "btn-cancel":
            self.action_cancel()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _start(self) -> None:
        host = self._selected("twin-iface")
        punter = self._selected("punt-iface")
        twin_bssid = self.query_one("#twin-bssid", Input).value.strip().lower()
        if not _MAC_RE.match(twin_bssid):
            self._error("Invalid BSSID")
            return
        self.dismiss(EvilTwinInput(
            twin_iface=host, punt_iface=punter, twin_channel=self.target.channel,
            twin_bssid=twin_bssid))

    def _error(self, text: str) -> None:
        self._set_warn(f"[red]{text}[/red]")