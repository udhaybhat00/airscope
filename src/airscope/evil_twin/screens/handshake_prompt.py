"""Textual modal screen for handshake detection prompt."""

from textual.screen import ModalScreen
from textual.widgets import Static, OptionList
from textual.containers import Vertical
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
    OptionList {
        height: 5;
    }
    #help {
        color: $muted;
        text-style: italic;
        margin-top: 1;
    }
    """

    BINDINGS = [
        ("1", "select(0)", "Use existing"),
        ("2", "select(1)", "Custom path"),
        ("3", "select(2)", "Capture new"),
        ("escape", "select(-1)", "Cancel"),
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
            yield Static("⚡ Handshake Already Exists", id="title")
            yield Static(f"File: {self._path.name}", id="path")
            yield Static(
                f"Captured: {mtime_str}  |  Size: {self._size/1024:.1f} KB",
                id="info"
            )
            yield OptionList(
                OptionList.Option("  ✓ Use this handshake (skip Step 1)", id="0"),
                OptionList.Option("  📂 Provide custom handshake path", id="1"),
                OptionList.Option("  🔄 Capture new handshake", id="2"),
                highlight=True,
            )
            yield Static("↑↓ select  |  1/2/3 shortcut  |  Esc cancel", id="help")

    def on_option_list_highlighted(self, event: OptionList.Highlighted):
        pass

    def action_select(self, value: int):
        self.dismiss(value)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected):
        self.dismiss(int(event.option.id))
