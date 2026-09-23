"""Handshake-exists prompt shown before EvilTwin Step 1 when a capture file
already exists for the target BSSID."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label


class HandshakePromptResult:
    """Structured result from the handshake prompt."""

    def __init__(self, choice: int, path: Optional[Path] = None) -> None:
        self.choice = choice  # 0=use existing, 1=custom path, 2=capture new
        self.path = path


class HandshakePromptScreen(ModalScreen[Optional[HandshakePromptResult]]):
    """Prompt when a handshake file already exists for the target BSSID.

    Returns a ``HandshakePromptResult`` or ``None`` on cancel."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
    ]

    DEFAULT_CSS = """
    HandshakePromptScreen { align: center middle; }
    HandshakePromptScreen #dialog {
        width: 72; height: auto; max-height: 90%;
        border: thick $primary; background: $surface; padding: 1 2;
    }
    HandshakePromptScreen #title {
        width: 1fr; content-align: center middle;
        margin-bottom: 1; text-style: bold; color: $accent;
    }
    HandshakePromptScreen .info { color: $text-muted; margin-bottom: 0; }
    HandshakePromptScreen .path-label { color: $primary; text-style: bold; }
    HandshakePromptScreen #custom-row { height: auto; margin-top: 1; display: none; }
    HandshakePromptScreen #custom-row Label { width: 16; color: $text-muted; }
    HandshakePromptScreen #custom-row Input { width: 1fr; }
    HandshakePromptScreen #btn-row { height: auto; align: center middle; margin-top: 1; }
    HandshakePromptScreen #btn-row Button { margin: 0 1; min-width: 12; }
    HandshakePromptScreen #warn { color: $error; height: auto; display: none; }
    """

    def __init__(self, existing_path: Path, bssid: str) -> None:
        super().__init__()
        self._path = existing_path
        self._bssid = bssid

    def compose(self) -> ComposeResult:
        stat = self._path.stat()
        size_kb = stat.st_size / 1024
        from datetime import datetime
        mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")

        with Vertical(id="dialog"):
            yield Label("Handshake Already Exists", id="title")
            yield Label(f"Found existing capture for [bold]{self._bssid}[/bold]:", classes="info")
            yield Label(str(self._path), classes="path-label")
            yield Label(f"Modified: {mtime}  |  Size: {size_kb:.1f} KB", classes="info")

            with Vertical(id="custom-row"):
                yield Label("Custom path:")
                yield Input(value=str(self._path), id="custom-path")

            yield Label("", id="warn")

            with Vertical(id="btn-row"):
                with Horizontal(id="btn-row-inner"):
                    yield Button("Use existing", variant="primary", id="btn-use")
                    yield Button("Custom path", variant="default", id="btn-custom")
                    yield Button("Capture new", variant="default", id="btn-new")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn-use":
            self.dismiss(HandshakePromptResult(choice=0, path=self._path))
        elif bid == "btn-custom":
            custom_row = self.query_one("#custom-row")
            if custom_row.display:
                custom_path = Path(self.query_one("#custom-path", Input).value.strip())
                if not custom_path.is_file():
                    self._show_warn(f"File not found: {custom_path}")
                    return
                self.dismiss(HandshakePromptResult(choice=1, path=custom_path))
            else:
                custom_row.display = True
                self.query_one("#custom-path", Input).focus()
        elif bid == "btn-new":
            self.dismiss(HandshakePromptResult(choice=2))

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _show_warn(self, text: str) -> None:
        warn = self.query_one("#warn", Label)
        warn.update(text)
        warn.display = bool(text)
