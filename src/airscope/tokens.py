"""Signal Noir design tokens: the single source for the palette.

``ui.themes`` builds the Textual themes from ``NOIR`` (values must stay
identical), and ``web`` renders ``to_css()`` for the dashboard. Add a color
here once, use it everywhere; never hardcode hex outside this module.
"""
from __future__ import annotations

NOIR: dict[str, str] = {
    # Textual theme slots
    "primary": "#60a5fa",
    "secondary": "#a78bfa",
    "accent": "#f59e0b",
    "foreground": "#e2e8f0",
    "background": "#0b0f19",
    "success": "#34d399",
    "warning": "#fbbf24",
    "error": "#f87171",
    "surface": "#131825",
    "panel": "#1a2033",
    # Noir extensions (``airscope-*`` Textual variables)
    "muted": "#64748b",
    "attack": "#c084fc",
    "track": "#1e293b",
    "logo-bars-primary": "#60a5fa",
    "logo-bars-secondary": "#3b82f6",
    "logo-text-primary": "#e2e8f0",
    "logo-text-secondary": "#64748b",
    "cursor": "#60a5fa",
    "cursor-blurred": "#1e3a5f",
    "hover": "#1e293b",
    "input-selection": "#1e3a5f",
    "screen-selection": "#1e3a5f",
}


def to_css(palette: dict[str, str] = NOIR) -> str:
    """Render ``:root`` CSS variables (``--primary`` ...). Generated file header
    marks web output as do-not-edit; regenerate after palette changes."""
    lines = [":root {"]
    lines.extend(f"  --{name}: {value};" for name, value in palette.items())
    lines.append("}")
    return "\n".join(lines) + "\n"
