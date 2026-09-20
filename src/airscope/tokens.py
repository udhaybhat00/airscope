"""Signal Noir design tokens: the single source for the palette.

``ui.themes`` builds the Textual themes from ``NOIR`` (values must stay
identical), and ``web`` renders ``to_css()`` for the dashboard. Add a color
here once, use it everywhere; never hardcode hex outside this module.
"""
from __future__ import annotations

NOIR: dict[str, str] = {
    # Textual theme slots
    "primary": "#7df0c4",
    "secondary": "#5ac8fa",
    "accent": "#ffb454",
    "foreground": "#d6dce5",
    "background": "#0a0e14",
    "success": "#7df0c4",
    "warning": "#ffb454",
    "error": "#ff6b6b",
    "surface": "#11161f",
    "panel": "#161d29",
    # Noir extensions (``airscope-*`` Textual variables)
    "muted": "#5b6472",
    "attack": "#c792ea",
    "track": "#232b3a",
    "logo-bars-primary": "#7df0c4",
    "logo-bars-secondary": "#2a7a5c",
    "logo-text-primary": "#e8edf3",
    "logo-text-secondary": "#5b6472",
    "cursor": "#7df0c4",
    "cursor-blurred": "#2a3a4a",
    "hover": "#1b2534",
    "input-selection": "#23404a",
    "screen-selection": "#1f4a3f",
}


def to_css(palette: dict[str, str] = NOIR) -> str:
    """Render ``:root`` CSS variables (``--primary`` …). Generated file header
    marks web output as do-not-edit; regenerate after palette changes."""
    lines = [":root {"]
    lines.extend(f"  --{name}: {value};" for name, value in palette.items())
    lines.append("}")
    return "\n".join(lines) + "\n"
