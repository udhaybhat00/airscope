import functools
import logging
import sys
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import (
    Static, ListView, ListItem, Label, Footer, Button, SelectionList)
from textual.widgets.selection_list import Selection
from textual.containers import Vertical, Center, Horizontal
from textual import events, work
from rich.text import Text

from typing import TYPE_CHECKING, Optional

from airscope.ui.screens.setup_error import SetupErrorDialog
from airscope.device.manager import Status
from airscope.tokens import NOIR

if TYPE_CHECKING:
    from airscope.ui.app import AirscopeApp

logger = logging.getLogger(__name__)

_DUP_SUFFIX = " #{n}"
_LEFT_MARGIN = " "


def _build_logo() -> Text:
    """Build a clean, modern logo as a Rich Text object."""
    primary = NOIR["primary"]
    foreground = NOIR["foreground"]
    muted = NOIR["muted"]

    text = Text(justify="center", no_wrap=True)

    # Signal/radar wave icon
    waves = [
        "                 * * * * * *",
        "             *               *",
        "         *     * * * * *     *",
        "     *                           *",
        "         *     *         *",
        "             *               *",
        "                 * * * * *",
    ]
    for line in waves:
        text.append(line + "\n", style=f"bold {primary}")

    # Blank line
    text.append("\n")

    # Main title - wide spaced for legibility
    title = "A   I   R   S   C   O   P   E"
    text.append("  " + title + "\n", style=f"bold {foreground}")

    # Thin separator
    sep = "\u2500" * len(title)
    text.append("  " + sep + "\n", style=f"dim {muted}")

    # Tagline
    text.append("  wireless auditor", style=f"italic {muted}")

    return text


class _PulsingDot(Static):
    _phase: float = 0.0
    _chars = ["\u25cf", "\u25cb", "\u25cb"]

    def on_mount(self) -> None:
        self.set_interval(0.5, self._tick)
        self._repaint()

    def _tick(self) -> None:
        self._phase = (self._phase + 0.33) % 1.0
        self._repaint()

    def _repaint(self) -> None:
        idx = int(self._phase * 3) % 3
        char = self._chars[idx]
        self.update(Text(char, style="bold cyan"))


def _alpha_head(chipset: str) -> str:
    i = 0
    while i < len(chipset) and not chipset[i].isdigit():
        i += 1
    return chipset[:i]


def device_list_labels(devices, bands=None) -> list:
    if not devices:
        return []
    chip_counts: dict = {}
    for d in devices:
        chip_counts[d.chipset] = chip_counts.get(d.chipset, 0) + 1

    prefix_w = max(len(_alpha_head(d.chipset)) for d in devices)
    seen: dict = {}
    heads = []
    for dev in devices:
        seen[dev.chipset] = seen.get(dev.chipset, 0) + 1
        head = " " * (prefix_w - len(_alpha_head(dev.chipset))) + dev.chipset
        if chip_counts[dev.chipset] > 1:
            head += _DUP_SUFFIX.format(n=seen[dev.chipset])
        heads.append(head)
    head_w = max(len(h) for h in heads)

    labels = []
    for dev, head in zip(devices, heads):
        brand = " ".join(x for x in (dev.vendor, dev.product_name) if x)
        body = f"{head.ljust(head_w)} · {brand}" if brand else head
        if bands:
            badge = _band_badge(bands.get(dev.chipset))
            if badge:
                body += f"  {badge}"
        labels.append(_LEFT_MARGIN + body)
    return labels


def device_capability_line(dev) -> str:
    try:
        from airscope.chips.driver import FakeMacSupport
        from airscope.device.manager import supported_ids
        for claim in supported_ids().values():
            if claim.entry.chipset != dev.chipset:
                continue
            driver_cls = claim.import_driver()
            fake_mac = getattr(driver_cls, "FAKE_MAC", FakeMacSupport.NONE)
            if fake_mac not in (FakeMacSupport.NONE, FakeMacSupport.UNIMPLEMENTED):
                return "[dim]Can create fake networks \u2713[/dim]"
            return "[dim]Listen and inject only[/dim]"
    except Exception:
        pass
    return ""


def _band_badge(bands: Optional[tuple]) -> str:
    if not bands:
        return ""
    lo, hi = bands
    if lo and hi:
        return "[bold cyan]2G[/]+[bold green]5G[/]"
    if lo:
        return "[bold cyan]2G[/]"
    if hi:
        return "[bold green]5G[/]"
    return ""


@functools.lru_cache(maxsize=64)
def _chipset_bands(chipset: str) -> Optional[tuple]:
    try:
        from airscope.device.manager import supported_ids
        for claim in supported_ids().values():
            if claim.entry.chipset != chipset:
                continue
            channels = claim.import_driver().SUPPORTED_CHANNELS
            return (any(c <= 14 for c in channels), any(c > 14 for c in channels))
    except Exception:
        logger.debug("Band lookup failed for %s", chipset, exc_info=True)
    return None


class SplashView(Screen):
    app: "AirscopeApp"

    BINDINGS = [
        ("q", "app.quit", "Quit"),
        ("v", "vault", "Captured Results"),
        Binding("enter", "enter", "Start", priority=True),
    ]

    CSS = """
    SplashView { background: $surface; }
    SplashView #splash-container { height: 1fr; align: center middle; }
    SplashView #ascii-art { content-align: center middle; width: 100%; margin-bottom: 0; }
    SplashView #heading-label { width: 100%; content-align: center middle; text-style: bold; margin-top: 1; }
    SplashView #status-row { width: 100%; align: center middle; height: auto; margin-top: 0; }
    SplashView #status-dot { width: 3; content-align: center middle; }
    SplashView #status-label { width: 100%; content-align: center middle; }
    SplashView #error-label { width: 100%; content-align: center middle; margin-top: 0; }
    SplashView #device-list { border: round $primary; }
    SplashView #device-list ListItem.-highlight {
        border-left: solid $primary;
        background: $surface;
        color: $primary;
        text-style: bold;
    }
    SplashView #device-list:focus ListItem.-highlight {
        border-left: solid $primary;
        background: $primary 18%;
        color: $foreground;
        text-style: bold;
    }
    SplashView #button-row { height: auto; margin-top: 1; }
    SplashView #button-row Button { width: auto; min-width: 11; }
    SplashView #vault-btn {
        background: transparent;
        border: tall $success;
        color: $success;
    }
    SplashView #prefs-btn {
        background: transparent;
        border: tall #64748b;
        color: #64748b;
    }
    SplashView #help-strip { width: 100%; content-align: center middle; height: 1; margin-top: 1; }
    """

    def __init__(self):
        super().__init__()
        self._is_initializing = False
        self._devices = []

    def compose(self) -> ComposeResult:
        with Vertical(id="splash-container"):
            with Center():
                yield Static(self._logo(), id="ascii-art")
            with Center():
                yield Label("[bold]Choose your Wi-Fi adapter to get started[/bold]",
                            id="heading-label")
            with Center():
                with Horizontal(id="status-row"):
                    yield _PulsingDot(id="status-dot")
                    yield Label("[dim]Scanning for compatible hardware...[/dim]",
                                id="status-label")
            with Center():
                yield Label("", id="error-label")
            with Center():
                with Horizontal(id="device-row"):
                    yield ListView(id="device-list")
                    yield SelectionList(id="device-select")
            with Center():
                with Horizontal(id="button-row"):
                    yield Button("Start Scanning", id="start-btn", variant="success")
                    yield Button("Uninstall", id="uninstall-btn", variant="error")
                    yield Button("Captured Results", id="vault-btn")
                    yield Button("Settings", id="prefs-btn")
            with Center():
                yield Label(self._platform_hint(), id="help-strip")
        yield Footer()

    @staticmethod
    def _platform_hint() -> str:
        import sys
        import os
        if sys.platform == "darwin" and not os.environ.get("AIRSCOPE_IN_VM"):
            return ("[yellow]macOS: scanning/capture only. "
                    "TX injection (deauth, evil twin) requires Linux.\n"
                    "  Plug adapter into a Linux box and run: "
                    "airscope --connect user@host[/yellow]")
        return ("[dim]Plug in your supported USB Wi-Fi adapter and select it here "
                "to begin scanning nearby networks[/dim]")

    def _both_lists(self):
        return (self.query_one("#device-list", ListView),
                self.query_one("#device-select", SelectionList))

    def _logo(self) -> Text:
        theme = self.app.current_theme
        variables = theme.variables
        primary = variables.get("primary", NOIR["primary"])
        foreground = variables.get("foreground", NOIR["foreground"])
        muted = variables.get("muted", NOIR["muted"])
        text = Text(justify="center", no_wrap=True)
        waves = [
            "                 * * * * * *",
            "             *               *",
            "         *     * * * * *     *",
            "     *                           *",
            "         *     *         *",
            "             *               *",
            "                 * * * * *",
        ]
        for line in waves:
            text.append(line + "\n", style=f"bold {primary}")
        text.append("\n")
        title = "A   I   R   S   C   O   P   E"
        text.append("  " + title + "\n", style=f"bold {foreground}")
        sep = "\u2500" * len(title)
        text.append("  " + sep + "\n", style=f"dim {muted}")
        text.append("  wireless auditor", style=f"italic {muted}")
        return text

    def refresh_theme_art(self) -> None:
        logo = self.query_one("#ascii-art", Static)
        logo.update(self._logo())

    def _enter_scanning_mode(self) -> None:
        self._is_initializing = False
        self._devices = []
        self.query_one("#error-label").display = False
        single_list, multi_list = self._both_lists()
        single_list.clear()
        single_list.disabled = False
        single_list.display = True
        multi_list.clear_options()
        multi_list.disabled = False
        multi_list.display = False
        self.query_one("#start-btn", Button).disabled = True
        self.query_one("#uninstall-btn", Button).disabled = True
        self.query_one("#status-label", Label).update(
            "[dim]Scanning for compatible hardware...[/dim]")
        self.query_one("#status-dot", _PulsingDot).display = True

    def _repopulate_adapters(self) -> None:
        present = self.app.device_watch.present()
        if present:
            self.render_devices(present)

    async def on_mount(self) -> None:
        uninstall = self.query_one("#uninstall-btn", Button)
        if sys.platform == "darwin":
            uninstall.display = False
        self._enter_scanning_mode()
        self.set_timer(0.5, self._repopulate_adapters)
        self.app.theme_changed_signal.subscribe(
            self, lambda _theme: self.refresh_theme_art())

    def reset_for_reentry(self) -> None:
        self._enter_scanning_mode()
        self.app.device_watch.resume()
        self.render_devices(self.app.device_watch.present())

    def render_devices(self, devices) -> None:
        if self._is_initializing:
            return
        self._devices = devices
        single_list, multi_list = self._both_lists()
        bands = {d.chipset: _chipset_bands(d.chipset) for d in devices}
        labels = device_list_labels(devices, bands=bands)
        multi = len(devices) >= 2
        if multi:
            multi_list.clear_options()
            multi_list.add_options([Selection(labels[i], i, initial_state=True)
                                    for i in range(len(devices))])
            single_list.display = False
            multi_list.display = True
        else:
            single_list.clear()
            for i, dev in enumerate(labels):
                cap = device_capability_line(devices[i]) if devices else ""
                item_label = Label(f"{dev}\n{cap}") if cap else Label(dev)
                single_list.append(ListItem(item_label, name=str(i)))
            multi_list.display = False
            single_list.display = True

        status = self.query_one("#status-label", Label)
        start_btn = self.query_one("#start-btn", Button)
        uninstall_btn = self.query_one("#uninstall-btn", Button)
        if devices:
            status.update(self._ready_prompt())
            start_btn.disabled = False
            uninstall_btn.disabled = False
            try:
                self.query_one("#status-dot", _PulsingDot).display = False
            except Exception:
                pass
            if multi:
                if multi_list.highlighted is None:
                    multi_list.highlighted = 0
                multi_list.focus()
            else:
                if single_list.index is None:
                    single_list.index = 0
                single_list.focus()
        else:
            status.update("[dim]No adapter detected - plug in a supported USB Wi-Fi adapter. "
                          "See docs/SUPPORTED-HARDWARE.md for compatible devices.[/dim]")
            start_btn.disabled = True
            uninstall_btn.disabled = True

    def _show_error(self, message: str) -> None:
        label = self.query_one("#error-label", Label)
        label.update(f"[bold red]\u26a0  {message}[/bold red]")
        label.display = True
        self.query_one("#status-label", Label).update("[bold red]\u25cf Bring-up failed[/]")
        self.notify(message, title="Card bring-up failed", severity="error")

    def _clear_error(self) -> None:
        label = self.query_one("#error-label", Label)
        label.update("")
        label.display = False

    def _using_multi(self) -> bool:
        return len(self._devices) >= 2

    def _ready_prompt(self) -> str:
        prefix = "Select card(s) and " if self._using_multi() else ""
        return f"[bold green]\u25cf[/] {prefix}Press START to begin scanning"

    def _start_targets(self) -> list:
        if self._using_multi():
            sl = self.query_one("#device-select", SelectionList)
            return [self._devices[i] for i in sorted(sl.selected) if i < len(self._devices)]
        return list(self._devices)

    def _highlighted_device(self):
        if self._using_multi():
            index = self.query_one("#device-select", SelectionList).highlighted
        else:
            index = self.query_one("#device-list", ListView).index
        if index is None or index >= len(self._devices):
            return None
        return self._devices[index]

    def action_enter(self) -> None:
        if self._is_initializing:
            return
        focused = self.app.focused
        if focused is not None and focused.id == "uninstall-btn":
            dev = self._highlighted_device()
            if dev is not None:
                self.perform_uninstall(dev)
            return
        if focused is not None and focused.id == "vault-btn":
            self.action_vault()
            return
        if focused is not None and focused.id == "prefs-btn":
            self.action_prefs()
            return
        self.action_start()

    def action_start(self) -> None:
        if self._is_initializing:
            return
        targets = self._start_targets()
        if not targets:
            if self._devices:
                self.notify("Select at least one card.", severity="warning")
            return
        self.perform_start(targets)

    def on_click(self, event: events.Click) -> None:
        if event.chain < 2 or self._is_initializing or self._using_multi():
            return
        clicked = event.widget
        single_list = self.query_one("#device-list", ListView)
        if clicked is not None and single_list in clicked.ancestors_with_self:
            self.action_start()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if self._is_initializing:
            return
        if event.button.id == "start-btn":
            self.action_start()
        elif event.button.id == "uninstall-btn":
            dev = self._highlighted_device()
            if dev is not None:
                self.perform_uninstall(dev)
        elif event.button.id == "vault-btn":
            self.action_vault()
        elif event.button.id == "prefs-btn":
            self.action_prefs()

    def action_vault(self) -> None:
        self.app.push_screen("vault")

    def action_prefs(self) -> None:
        self.app.action_preferences()

    def _enter_busy(self) -> None:
        self._is_initializing = True
        self.app.device_watch.pause()
        single_list, multi_list = self._both_lists()
        single_list.disabled = True
        multi_list.disabled = True
        self.query_one("#start-btn", Button).disabled = True
        self.query_one("#uninstall-btn", Button).disabled = True

    def _exit_busy(self) -> None:
        self._is_initializing = False
        self.app.device_watch.resume()
        single_list, multi_list = self._both_lists()
        single_list.disabled = False
        multi_list.disabled = False
        self.query_one("#start-btn", Button).disabled = False
        self.query_one("#uninstall-btn", Button).disabled = False
        (multi_list if self._using_multi() else single_list).focus()

    @work(exclusive=True)
    async def perform_start(self, devices) -> None:
        self._clear_error()
        self._enter_busy()
        pooled = 0
        failures = []
        try:
            for dev in devices:
                res = await self.app.device_manager.bringup(dev)
                if res.status is Status.READY:
                    pooled += 1
                elif res.status is Status.FAILED:
                    failures.append(res.message)
        finally:
            self._exit_busy()

        if pooled > 0:
            if failures:
                self.notify(f"{len(failures)} card(s) failed to start.", severity="warning")
            self.app.switch_screen("scanner")
        elif failures:
            self._show_error(failures[-1])
        else:
            self.query_one("#status-label", Label).update(self._ready_prompt())

    @work(exclusive=True)
    async def perform_uninstall(self, device_id) -> None:
        self._clear_error()
        self._enter_busy()
        try:
            res = await self.app.device_manager.uninstall(device_id)
        finally:
            self._exit_busy()

        status = self.query_one("#status-label", Label)
        if res.ok:
            status.update(f"[bold green]\u25cf {res.message}[/]")
            self.notify(f"[green]\u2713[/green] {res.message}", title="Uninstalled",
                        severity="information")
        elif res.cancelled:
            status.update(self._ready_prompt())
        else:
            status.update("[bold red]\u25cf Uninstall failed.[/]")
            self.app.push_screen(SetupErrorDialog("Uninstall failed", res.message, res.detail))
