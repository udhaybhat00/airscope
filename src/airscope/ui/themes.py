"""Airscope's custom Textual themes (colors live in ``airscope.tokens``)."""
from textual.theme import Theme

from airscope.tokens import NOIR
from airscope.ui.ansi_art import (
    THEME_BARS_PRIMARY_KEY, THEME_BARS_SECONDARY_KEY,
    THEME_TEXT_PRIMARY_KEY, THEME_TEXT_SECONDARY_KEY
)

def register_app_themes(app) -> None:
    for theme in custom_themes():
        app.register_theme(theme)


def custom_themes() -> list[Theme]:
    return [
        _airscope_noir(),
        _airscope_noir_contrast(),
        _airscope_green_dark(),
    ]


def _airscope_noir() -> Theme:
    """Midnight: deep navy base, electric blue primary, warm amber accent."""
    return Theme(
        name="airscope-noir",
        dark=True,
        primary=NOIR["primary"],
        secondary=NOIR["secondary"],
        accent=NOIR["accent"],
        foreground=NOIR["foreground"],
        background=NOIR["background"],
        success=NOIR["success"],
        warning=NOIR["warning"],
        error=NOIR["error"],
        surface=NOIR["surface"],
        panel=NOIR["panel"],
        variables={
            "block-cursor-background": NOIR["cursor"],
            "block-cursor-blurred-background": NOIR["cursor-blurred"],
            "block-hover-background": NOIR["hover"],
            "input-selection-background": NOIR["input-selection"],
            "screen-selection-background": NOIR["screen-selection"],
            "airscope-muted": NOIR["muted"],
            "airscope-attack": NOIR["attack"],
            "airscope-track": NOIR["track"],
            THEME_BARS_PRIMARY_KEY: NOIR["logo-bars-primary"],
            THEME_BARS_SECONDARY_KEY: NOIR["logo-bars-secondary"],
            THEME_TEXT_PRIMARY_KEY: NOIR["logo-text-primary"],
            THEME_TEXT_SECONDARY_KEY: NOIR["logo-text-secondary"],
        },
    )


def _airscope_noir_contrast() -> Theme:
    """High-contrast Noir for projectors / sunlight."""
    return Theme(
        name="airscope-noir-contrast",
        dark=True,
        primary="#93c5fd",
        secondary="#c4b5fd",
        accent="#fcd34d",
        foreground="#f1f5f9",
        background="#000000",
        success="#6ee7b7",
        warning="#fcd34d",
        error="#fca5a5",
        surface="#0f172a",
        panel="#1e293b",
        variables={
            "block-cursor-background": "#93c5fd",
            "block-cursor-blurred-background": "#1e3a5f",
            "block-hover-background": "#1e293b",
            "input-selection-background": "#1e3a5f",
            "screen-selection-background": "#1e3a5f",
            "airscope-muted": "#94a3b8",
            "airscope-attack": "#d8b4fe",
            "airscope-track": "#1e293b",
            THEME_BARS_PRIMARY_KEY: "#93c5fd",
            THEME_BARS_SECONDARY_KEY: "#60a5fa",
            THEME_TEXT_PRIMARY_KEY: "#ffffff",
            THEME_TEXT_SECONDARY_KEY: "#94a3b8",
        },
    )


def _airscope_green_dark() -> Theme:
    return Theme(
        name="airscope-green-dark",
        dark=True,
        primary="#00ff88",
        secondary="#00c8ff",
        accent="#00ff88",
        foreground="#d8ffe8",
        background="#050805",
        success="#00ff88",
        warning="#ffd75f",
        error="#cc6666",
        surface="#0b120b",
        panel="#101810",
        variables={
            "block-cursor-background": "#00ff88",
            "block-cursor-blurred-background": "#1f5f3f",
            "block-hover-background": "#163322",
            "input-selection-background": "#005f3a",
            "screen-selection-background": "#007a48",
            "airscope-muted": "#7aa88a",
            "airscope-attack": "#00ff88",
            "airscope-track": "#101810",
            THEME_BARS_PRIMARY_KEY: "#00ff22",
            THEME_BARS_SECONDARY_KEY: "#008f22",
            THEME_TEXT_PRIMARY_KEY: "#f4fff8",
            THEME_TEXT_SECONDARY_KEY: "#7aa88a",
        },
    )
