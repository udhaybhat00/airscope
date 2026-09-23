"""Textual screen for entering a custom handshake file path."""

from textual.screen import ModalScreen
from textual.widgets import Static, Input, Button
from textual.containers import Vertical


class PathInputScreen(ModalScreen[str | None]):
    """Returns the path string or None if cancelled."""

    CSS = """
    PathInputScreen { align: center middle; }
    #dialog {
        width: 60;
        background: $surface;
        border: round $accent;
        padding: 1 2;
    }
    #title { text-style: bold; margin-bottom: 1; }
    #hint { color: $muted; margin-bottom: 1; }
    Input { margin-bottom: 1; }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, default_path: str):
        super().__init__()
        self._default = default_path

    def compose(self):
        with Vertical(id="dialog"):
            yield Static("📂 Custom Handshake Path", id="title")
            yield Static("Enter path to a .pcap / .hc22000 / .hccapx file:", id="hint")
            yield Input(value=self._default, placeholder="/path/to/handshake.pcap")
            yield Button("Load Handshake", variant="primary", id="confirm")

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "confirm":
            input_widget = self.query_one(Input)
            path = input_widget.value.strip()
            if path:
                self.dismiss(path)
            else:
                self.dismiss(None)

    def action_cancel(self):
        self.dismiss(None)
