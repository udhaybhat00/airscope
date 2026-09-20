"""VaultItemView: the detail pane for one AP's saved captures. Given an AP's
PersistedCapture list it renders a per-kind panel (Handshake/PMKID, WEP, WPS PIN,
WPS PBC). Credential panels show one row per field (hex/ASCII, PSK/PIN) each with its
own Copy; capture panels show a summary + a Copy of the hashcat hashline. Delete and
(for legacy split .hc22000 files) Consolidate live in the panel too. All filesystem
work goes through app.vault.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from rich.markup import escape
from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalGroup
from textual.events import Event
from textual.message import Message
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select

from airscope.models import CaptureType, PersistedCapture
from airscope.crack import external as crack_ext
from airscope.persist.common import bssid_to_dashed

# (title, kinds) per panel, in display order. HS and PMKID share one panel.
_PANELS: list[tuple[str, tuple[CaptureType, ...]]] = [
    ("Captured Handshakes & PMKIDs", (CaptureType.HS, CaptureType.PMKID)),
    ("WEP Key", (CaptureType.WEP,)),
    ("WPS PIN", (CaptureType.WPS_PIN,)),
    ("WPS Push-Button", (CaptureType.WPS_PBC,)),
    ("Recovered Password", (CaptureType.CRACKED,)),
    ("SAE (WPA3)", (CaptureType.SAE,)),
]

# Per credential kind: the (row label, field key) rows to show, each with its own Copy.
_FIELDS: dict[CaptureType, list[tuple[str, str]]] = {
    CaptureType.WEP: [("WEP Key (hex)", "hex"), ("WEP Key (ASCII)", "ascii")],
    CaptureType.WPS_PIN: [("PSK", "psk"), ("PIN", "pin")],
    CaptureType.WPS_PBC: [("PSK", "psk")],
    CaptureType.CRACKED: [("PSK", "psk")],
}


def _hex_to_ascii(hex_key: Optional[str]) -> str:
    """Printable ASCII rendering of a hex WEP key, or "" if non-printable/invalid."""
    if not hex_key:
        return ""
    try:
        raw = bytes.fromhex(hex_key)
    except ValueError:
        return ""
    return raw.decode("ascii") if all(32 <= b < 127 for b in raw) else ""


def _field_value(cap: PersistedCapture, key: str) -> str:
    """The copyable text for one field of a capture (empty string if absent)."""
    if key == "hex":
        return cap.value or ""
    if key == "ascii":
        return _hex_to_ascii(cap.value)
    if key == "psk":
        return cap.value or ""
    if key == "pin":
        return cap.pin or ""
    return ""


class ConfirmModal(ModalScreen[bool]):
    """Yes/No confirmation; focus defaults to No."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    DEFAULT_CSS = """
    ConfirmModal { align: center middle; }
    ConfirmModal #dialog {
        width: 54; height: auto;
        border: thick $primary; background: $surface; padding: 1 2;
    }
    ConfirmModal #prompt { margin-bottom: 1; }
    ConfirmModal Horizontal { align: right middle; height: auto; }
    ConfirmModal Button { margin-left: 1; }
    """

    def __init__(self, prompt: str) -> None:
        super().__init__()
        self._prompt = prompt

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(Text.from_markup(self._prompt), id="prompt")
            with Horizontal():
                yield Button(Text("No"), "default", id="no")
                yield Button(Text("Yes"), "error", id="yes")

    @on(Button.Pressed, "#yes")
    def _yes(self, event: Event) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#no")
    def _no(self, event: Event) -> None:
        self.dismiss(False)

    def action_cancel(self) -> None:
        self.dismiss(False)


class ConsolidateModal(ModalScreen[bool]):
    """Confirm merging legacy per-capture .hc22000 files into one file per AP."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    DEFAULT_CSS = """
    ConsolidateModal { align: center middle; }
    ConsolidateModal #dialog {
        width: 54; height: auto;
        border: thick $primary; background: $surface; padding: 1 2;
    }
    ConsolidateModal #prompt { margin-bottom: 1; }
    ConsolidateModal Horizontal { align: right middle; height: auto; }
    ConsolidateModal Button { margin-left: 1; }
    """

    def __init__(self, legacy_count: int, target_count: int) -> None:
        super().__init__()
        self.legacy_count = legacy_count
        self.target_count = target_count

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("[bold]Consolidate .hc22000 Captures[/]", id="title")
            dupes = self.legacy_count - self.target_count
            msg = Text.from_markup(
                f"\nYou have [bold orange1]{self.legacy_count}[/] separate .hc22000 files from "
                f"[bold green]{self.target_count}[/] APs.\n\n"
                f"Do you want to condense these into single files per AP?\n\n"
                f"    [bold green]{self.target_count} files will be created/updated[/]\n"
                f"    [bold red]{dupes} duplicate files will be removed[/]"
            )
            yield Label(msg, id="prompt")
            with Horizontal():
                yield Button(Text("Yes"), "primary", id="confirm")
                yield Button(Text("No"), "default", id="cancel")

    @on(Button.Pressed, "#confirm")
    def _confirm(self, event: Event) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#cancel")
    def _cancel(self, event: Event) -> None:
        self.dismiss(False)


class CrackModal(ModalScreen[Optional[str]]):
    """Pick a wordlist for one capture; dismisses with the path, or None."""

    DEFAULT_CSS = """
    CrackModal { align: center middle; }
    CrackModal #crack-dialog {
        width: 64; height: auto;
        border: thick $primary; background: $surface; padding: 1 2;
    }
    CrackModal #crack-tool { margin-top: 1; }
    CrackModal #crack-wordlist { margin-top: 1; }
    CrackModal #crack-error { color: $error; height: auto; margin-top: 1; }
    CrackModal Horizontal { align: right middle; height: auto; margin-top: 1; }
    CrackModal Button { margin-left: 1; }
    """

    def __init__(self, filename: str, tool_line: str, default_wordlist: str,
                 can_start: bool = True) -> None:
        super().__init__()
        self._filename = filename
        self._tool_line = tool_line
        self._default_wordlist = default_wordlist
        self._can_start = can_start

    def compose(self) -> ComposeResult:
        with Vertical(id="crack-dialog"):
            yield Label("[bold]🔍 Crack Password[/]")
            yield Label(Text.from_markup(f"[dim]{escape(self._filename)}[/dim]"))
            yield Label(Text.from_markup(self._tool_line), id="crack-tool")
            yield Label("Wordlist:", id="crack-wordlist-label")
            yield Input(placeholder="/usr/share/wordlists/rockyou.txt",
                        value=self._default_wordlist, id="crack-wordlist")
            yield Label("", id="crack-error")
            with Horizontal():
                yield Button("Cancel", id="crack-cancel")
                yield Button("Start", "primary", id="crack-start", disabled=not self._can_start)

    @on(Button.Pressed, "#crack-cancel")
    def _cancel(self, event: Event) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#crack-start")
    def _start(self, event: Event) -> None:
        path = self.query_one("#crack-wordlist", Input).value.strip()
        if not path or not Path(path).is_file():
            self.query_one("#crack-error", Label).update("Wordlist file not found - check the path and try again.")
            return
        self.dismiss(path)

    def action_cancel(self) -> None:
        self.dismiss(False)


class _CapturePanel(VerticalGroup):
    """One kind-group of an AP's captures: file dropdown, per-field rows (or a
    capture summary), Copy/Delete, and Consolidate for legacy files."""

    DEFAULT_CSS = """
    _CapturePanel { height: auto; border: round $primary; padding: 0 1; margin-bottom: 1; }
    _CapturePanel .detail { height: auto; margin: 0 0 1 0; }
    _CapturePanel .modified { height: 1; margin-bottom: 1; }
    _CapturePanel .field { height: 1; align: left middle; }
    _CapturePanel .fval { width: 1fr; height: 1; }
    _CapturePanel .field .copy { height: 1; min-width: 8; border: none; }
    _CapturePanel .actions { height: auto; align: left middle; }
    _CapturePanel .actions Button { margin-right: 1; }
    _CapturePanel .crack-progress { height: auto; color: $text-muted; margin-top: 1; }
    """

    def __init__(self, title: str, captures: List[PersistedCapture],
                 show_consolidate: bool = False) -> None:
        super().__init__()
        self._title = title
        self._by_path: Dict[str, PersistedCapture] = {}
        for cap in sorted(captures, key=lambda c: c.timestamp, reverse=True):
            self._by_path.setdefault(cap.path, cap)   # unique files, newest first
        self._files = list(self._by_path.values())
        self._show_consolidate = show_consolidate
        self._crackable = bool({c.type for c in self._files} & {CaptureType.HS, CaptureType.PMKID})
        self._crack_worker = None
        self._crack_pending: Optional[tuple] = None
        self._crack_tool = ""

    def compose(self) -> ComposeResult:
        self.border_title = f"{self._title} ({len(self._files)})"
        newest = self._files[0]
        yield Select([(Path(c.path).name, c.path) for c in self._files],
                     value=newest.path, allow_blank=False, classes="file")
        fields = _FIELDS.get(newest.type, [])
        if fields:
            yield Label(self._modified_text(newest), classes="modified")
            for flabel, fkey in fields:
                with Horizontal(classes="field"):
                    yield Label(self._field_text(newest, flabel, fkey), classes=f"fval fval-{fkey}")
                    yield Button("Copy", classes=f"copy copy-{fkey}")
        else:
            yield Label(Text.from_markup(self._detail_markup(newest)), classes="detail")
        with Horizontal(classes="actions"):
            if not fields:
                yield Button("Copy", classes="copy copy-payload")
            if self._crackable:
                yield Button("Crack", classes="crack")
            yield Button("Delete", "error", classes="delete")
            if self._show_consolidate and self.app.vault.legacy_hc_file_count():
                yield Button("Consolidate", "warning", classes="consolidate")
        if self._crackable:
            yield Label("", classes="crack-progress")

    # ----- rendering -----

    def _selected(self) -> Optional[PersistedCapture]:
        return self._by_path.get(self.query_one(Select).value)

    @staticmethod
    def _modified_text(cap: PersistedCapture) -> Text:
        when = datetime.fromtimestamp(cap.timestamp).strftime("%Y-%m-%d %H:%M")
        return Text.from_markup(f"[dim]Modified:[/dim] {when}")

    @staticmethod
    def _field_text(cap: PersistedCapture, flabel: str, fkey: str) -> Text:
        val = _field_value(cap, fkey)
        shown = escape(val) if val else "[dim](none)[/dim]"
        return Text.from_markup(f"[dim]{escape(flabel)}:[/dim] {shown}")

    def _detail_markup(self, cap: PersistedCapture) -> str:
        when = datetime.fromtimestamp(cap.timestamp).strftime("%Y-%m-%d %H:%M")
        if cap.type == CaptureType.SAE:
            pairs = f"{cap.record_count} SAE pair" + ("s" if cap.record_count != 1 else "")
            detail = (f"[dim]{pairs} (Dragonfly commit+confirm)[/dim]\n"
                      f"[dim]Convert: hcxpcapngtool -o out.hc22000 {escape(Path(cap.path).name)}[/dim]\n"
                      f"[dim]Crack: hashcat -m 22000 out.hc22000 wordlist[/dim]")
        elif cap.path.endswith(".pcap"):
            detail = "[dim]raw .pcap capture[/dim]"
        else:
            detail = self._hc_summary(cap)
        return f"[dim]Modified:[/dim] {when}\n{detail}"

    def _hc_summary(self, cap: PersistedCapture) -> str:
        text = self.app.vault.capture_payload(cap)
        hs = sum(1 for ln in text.splitlines() if ln.startswith("WPA*02*"))
        pmkid = sum(1 for ln in text.splitlines() if ln.startswith("WPA*01*"))
        parts = []
        if hs:
            parts.append(f"{hs} handshake" + ("s" if hs != 1 else ""))
        if pmkid:
            parts.append(f"{pmkid} PMKID" + ("s" if pmkid != 1 else ""))
        return "[dim]" + (", ".join(parts) or "hashcat 22000 file") + "[/dim]"

    # ----- events -----

    @on(Select.Changed)
    def _file_changed(self, event: Select.Changed) -> None:
        cap = self._by_path.get(event.value)
        if cap is None:
            return
        fields = _FIELDS.get(cap.type, [])
        if fields:
            self.query_one(".modified", Label).update(self._modified_text(cap))
            for flabel, fkey in fields:
                self.query_one(f".fval-{fkey}", Label).update(self._field_text(cap, flabel, fkey))
        else:
            self.query_one(".detail", Label).update(Text.from_markup(self._detail_markup(cap)))

    @on(Button.Pressed, ".copy")
    def _copy(self, event: Button.Pressed) -> None:
        event.stop()
        cap = self._selected()
        if cap is None:
            return
        classes = event.button.classes
        if "copy-payload" in classes:
            text = self.app.vault.capture_payload(cap)
        else:
            key = next((c[len("copy-"):] for c in classes if c.startswith("copy-")), "")
            text = _field_value(cap, key)
        if not text:
            self.notify("Nothing to copy for this entry", severity="warning")
            return
        self.app.copy_to_clipboard(text)
        self.notify("Copied to clipboard")

    @on(Button.Pressed, ".delete")
    def _delete(self, event: Button.Pressed) -> None:
        event.stop()
        cap = self._selected()
        if cap is None:
            return

        def after(confirmed: bool | None) -> None:
            if not confirmed:
                return
            try:
                self.app.vault.delete_capture(cap)
            except OSError as exc:
                self.notify(f"Could not remove {Path(cap.path).name}: {exc}", severity="error")
                return
            self.notify(f"Removed {Path(cap.path).name}")
            self.post_message(VaultItemView.CapturesChanged())

        self.app.push_screen(ConfirmModal(f"Delete [bold]{escape(Path(cap.path).name)}[/]?"), after)

    @on(Button.Pressed, ".consolidate")
    def _consolidate(self, event: Button.Pressed) -> None:
        event.stop()
        vault = self.app.vault
        count = vault.legacy_hc_file_count()
        if not count:
            return
        unique = vault.legacy_hc_unique_count()

        def after(confirmed: bool | None) -> None:
            if not confirmed:
                return
            migrated, deleted = vault.consolidate_legacy_hc_files()
            self.notify(f"Consolidated {deleted} files into {migrated} AP files.",
                        title="Captures Consolidated")
            self.post_message(VaultItemView.CapturesChanged())

        self.app.push_screen(ConsolidateModal(count, unique), after)

    # ----- dictionary crack (hashcat preferred, aircrack-ng fallback) --------

    def _crack_note(self, text: str) -> None:
        """Progress/result line under the actions row (best-effort: pane may close)."""
        try:
            self.query_one(".crack-progress", Label).update(text)
        except Exception:
            pass

    @on(Button.Pressed, ".crack")
    def _crack_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if self._crack_worker is not None and self._crack_worker.is_running:
            self._crack_worker.cancel()
            return
        newest = self._files[0]
        records = crack_ext.hash_lines(Path(newest.path))
        tools = crack_ext.detect_tools()
        if tools.hashcat and records:
            pending = ("hashcat", tools.hashcat, newest.path, None)
            detail = f"Tool: hashcat · mode 22000 · {len(records)} hashline(s)"
        else:
            dashed = bssid_to_dashed(newest.bssid)
            pcap = crack_ext.sibling_pcap(Path(newest.path), dashed) if tools.aircrack else None
            if pcap is None:
                if not tools.hashcat and not tools.aircrack:
                    self._crack_note("No cracker installed. Install one, then retry: "
                                     + crack_ext.install_hint())
                elif not records:
                    self._crack_note("No WPA handshake/PMKID hash lines in this file.")
                else:
                    self._crack_note("hashcat not found and no .pcap sibling for aircrack-ng.")
                return
            pending = ("aircrack", tools.aircrack, newest.path, str(pcap))
            detail = f"Tool: aircrack-ng · {pcap.name}"
        default = next((h for h in crack_ext.WORDLIST_HINTS if Path(h).is_file()), "")
        self._crack_pending = pending
        self.app.push_screen(
            CrackModal(Path(newest.path).name, detail, default, can_start=True),
            self._crack_modal_closed)

    def _crack_modal_closed(self, wordlist: Optional[str]) -> None:
        """Wordlist picked (None = cancelled): launch the crack worker."""
        if not wordlist or self._crack_pending is None:
            return
        tool, _, _, _ = self._crack_pending
        self._crack_tool = tool
        try:
            self.query_one(".crack", Button).disabled = True
        except Exception:
            pass
        self._crack_note(f"Starting {tool}…")
        self._crack_worker = self.run_worker(self._run_crack(wordlist), exclusive=True)

    def _crack_tick(self, prog) -> None:
        """One parsed status line from the child: refresh the progress line."""
        if prog.total:
            pct = 100.0 * prog.fraction
            text = f"Cracking ({self._crack_tool}): {prog.tested:,}/{prog.total:,} ({pct:.0f}%)"
        else:
            text = f"Cracking ({self._crack_tool}): {prog.tested:,} tried"
        if prog.speed:
            text += f" · {prog.speed}"
        text += " - press Crack to stop"
        self._crack_note(text)

    async def _run_crack(self, wordlist: str) -> None:
        """Drive the child to completion, then attach any recovered PSK to VAULT."""
        pending = self._crack_pending
        assert pending is not None
        tool, binary, hash_path, pcap = pending
        hashfile = Path(hash_path)
        newest = self._files[0]
        kind = "HS" if newest.type == CaptureType.HS else "PMKID"
        psk: Optional[str] = None
        tmp_hashfile: Optional[Path] = None
        try:
            if tool == "hashcat":
                records = crack_ext.extract_records(hashfile, kind)
                if not records:
                    self._crack_note("No WPA handshake/PMKID hash lines in this file.")
                    return
                tmp_hashfile = crack_ext.write_temp_hashfile(
                    hashfile.parent, bssid_to_dashed(newest.bssid), records)
                pot = crack_ext.potfile_path(hashfile.parent)
                cmd = crack_ext.build_hashcat_cmd(binary, tmp_hashfile, Path(wordlist), pot)
                await crack_ext.run_crack(cmd, tool, on_progress=self._crack_tick)
                _, show = await crack_ext.run_capture_output(
                    crack_ext.build_hashcat_show(binary, tmp_hashfile, pot))
                psk = crack_ext.parse_hashcat_show(show, records, newest.ssid)
            else:
                keyfile = hashfile.parent / ".airscope-aircrack.key"
                cmd = crack_ext.build_aircrack_cmd(binary, Path(str(pcap)), Path(wordlist), keyfile)
                run = await crack_ext.run_crack(cmd, tool, on_progress=self._crack_tick)
                psk = crack_ext.parse_aircrack_key(run.output, keyfile)
                try:
                    keyfile.unlink(missing_ok=True)
                except OSError:
                    pass
            if psk:
                self.app.vault.save_cracked_psk(newest.bssid, newest.ssid, psk, tool)
                self._crack_note(f"✓ Password recovered: {psk}")
                self.notify(f"Cracked PSK for {newest.ssid or newest.bssid}: {psk}",
                            title="Password cracked")
                self.post_message(VaultItemView.CapturesChanged())
            else:
                self._crack_note("Finished - no match found in wordlist.")
        except asyncio.CancelledError:
            self._crack_note("Stopped.")
            raise
        finally:
            if tmp_hashfile is not None:
                try:
                    tmp_hashfile.unlink(missing_ok=True)
                except OSError:
                    pass
            try:
                self.query_one(".crack", Button).disabled = False
            except Exception:
                pass
            self._crack_worker = None


class VaultItemView(Vertical):
    """Detail pane for one AP: a title chip and a panel per capture kind present."""

    class CapturesChanged(Message):
        """A capture was deleted or consolidated; the parent should refresh."""

    DEFAULT_CSS = """
    VaultItemView { height: 1fr; padding: 0 1; }
    VaultItemView #vault-item-title { height: auto; margin-bottom: 1; }
    VaultItemView #vault-item-empty { color: $text-muted; }
    """

    # (bssid, ssid, captures); setting it rebuilds the panels for the new AP.
    _state: reactive[tuple] = reactive(("", None, ()), recompose=True)

    EMPTY_VAULT_MSG = "No captured handshakes yet - go to Scanner, pick a network, and capture."
    EMPTY_SELECT_MSG = "Select a network to view its captured handshakes and passwords"

    def load(self, bssid: str, ssid: Optional[str], captures: List[PersistedCapture],
             *, empty_vault: bool = False) -> None:
        """Show one AP's captures (empty bssid clears the pane)."""
        self._empty_vault = empty_vault
        state = (bssid, ssid, tuple(captures))
        if state == self._state:
            self.refresh(recompose=True)  # identical value: reactive won't refire
        else:
            self._state = state

    def compose(self) -> ComposeResult:
        bssid, ssid, captures = self._state
        if not bssid:
            msg = self.EMPTY_VAULT_MSG if getattr(self, "_empty_vault", False) else self.EMPTY_SELECT_MSG
            yield Label(msg, id="vault-item-empty")
            return
        yield Label(Text.from_markup(self._title_markup(bssid, ssid)), id="vault-item-title")
        for title, kinds in _PANELS:
            group = [c for c in captures if c.type in kinds]
            if group:
                yield _CapturePanel(title, list(group), show_consolidate=CaptureType.HS in kinds)

    def _title_markup(self, bssid: str, ssid: Optional[str]) -> str:
        name = ssid or "‹hidden›"
        return f"[black bold on cyan] {escape(name)} [/]\n[dim]{escape(bssid)}[/dim]"
