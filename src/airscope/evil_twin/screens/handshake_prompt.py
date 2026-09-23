"""Textual modal screen for handshake detection prompt."""

from textual.screen import ModalScreen
from textual.widgets import Static, Button
from textual.containers import Vertical, Horizontal
from pathlib import Path


class HandshakePromptScreen(ModalScreen[int]):
    """
    Shown when an existing handshake file is found.
    Dismisses with: 0=use existing, 1=custom path, 2=capture new, -1=cancel
    """

    CSS = """
    HandshakePromptScreen {
        align: center middle;
    }
    #dialog {
        width: 60;
        height: auto;
        background: $surface;
        border: round $accent;
        padding: 1 2;
    }
    #title {
        text-style: bold;
        color: $warning;
        margin-bottom: 1;
    }
    #path {
        color: $text;
        margin-bottom: 1;
    }
    #info {
        color: $muted;
        margin-bottom: 1;
    }
    #btn-row {
        height: auto;
        align: center middle;
        margin-top: 1;
    }
    #btn-row Button {
        margin: 0 1;
        min-width: 14;
    }
    #help {
        color: $muted;
        text-style: italic;
        margin-top: 1;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, existing_path: Path):
        super().__init__()
        self._path = existing_path
        self._size = existing_path.stat().st_size
        self._mtime = existing_path.stat().st_mtime

    def compose(self):
        from datetime import datetime
        mtime_str = datetime.fromtimestamp(self._mtime).strftime('%Y-%m-%d %H:%M')

        with Vertical(id="dialog"):
            yield Static("Handshake Already Exists", id="title")
            yield Static(f"File: {self._path.name}", id="path")
            yield Static(
                f"Captured: {mtime_str}  |  Size: {self._size/1024:.1f} KB",
                id="info"
            )
            with Horizontal(id="btn-row"):
                yield Button("Use existing", variant="primary", id="btn-use")
                yield Button("Custom path", variant="default", id="btn-custom")
                yield Button("Capture new", variant="default", id="btn-new")
            yield Static("1/2/3 shortcut  |  Esc cancel", id="help")

    def on_button_pressed(self, event: Button.Pressed):
        bid = event.button.id
        if bid == "btn-use":
            self.dismiss(0)
        elif bid == "btn-custom":
            self.dismiss(1)
        elif bid == "btn-new":
            self.dismiss(2)

    def action_cancel(self):
        self.dismiss(-1)
