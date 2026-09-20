"""Signal Noir tokens: single source for TUI themes and web CSS."""
from airscope.tokens import NOIR, to_css
from airscope.ui.themes import custom_themes


def test_noir_theme_matches_tokens():
    noir = next(t for t in custom_themes() if t.name == "airscope-noir")
    assert noir.primary == NOIR["primary"]
    assert noir.background == NOIR["background"]
    assert noir.variables["airscope-attack"] == NOIR["attack"]
    assert noir.variables["airscope-track"] == NOIR["track"]


def test_css_emits_every_token():
    css = to_css()
    assert css.startswith(":root {") and css.endswith("}\n")
    for name, value in NOIR.items():
        assert f"--{name}: {value};" in css
