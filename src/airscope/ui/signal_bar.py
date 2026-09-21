"""Reception-quality bar: a smooth beacons/s meter for the live UI.

An AP is fully heard at ~9.77 beacons/s (one per 102.4 ms TBTT), so beacons/s is
really a *reception-quality* signal. This renders it as a horizontal meter built
from left-fractional eighth-block glyphs (▏▎▍▌▋▊▉█), 8 sub-steps per character,
fine enough to track the windowed decimal rate without visibly stepping.

Colour is **single-hue** (Signal Noir mint): fill is always ``_FILL`` and the
track is always ``_TRACK``. Strength reads from fill *length* plus the tier
glyph in ``ui.icons`` - never from hue - so the bar never strobes as the rate
wobbles.
"""
from __future__ import annotations

from typing import Optional

from rich.text import Text

# 0/8 .. 8/8 of a cell, filled from the left.
_EIGHTHS = " ▏▎▍▌▋▊▉█"

# One beacon per 102.4 ms TBTT: the rate at which an AP is fully heard.
FULL_SCALE_RATE = 9.77

# Brightness of the unfilled track: a dim ghost of the fill hue, so the
# bar's full width (the headroom) stays visible.
_FILL = "#60a5fa"
_TRACK = "#1e293b"
_DEAD = "#ff6b6b"


def render_signal_bar(
    rate: Optional[float],
    *,
    width: int = 10,
    full_scale: float = FULL_SCALE_RATE,
    pulse: float = 1.0,
) -> Text:
    """Render the meter for ``rate`` beacons/s.

    ``rate=None`` → warming up (faint track). ``rate≈0`` → dead: solid track
    plus a red ╳. ``pulse`` is kept for API compat and ignored.
    """
    bar = Text(no_wrap=True)

    if rate is None:
        for _ in range(width):
            bar.append("█", style=_TRACK)
        return bar

    if rate <= 0.05:
        # Red X on the left. Account for the X + space consuming 2 chars.
        bar.append("X", style=f"bold {_DEAD}")
        bar.append(" ")
        for _ in range(max(0, width - 2)):
            bar.append("\u2588", style=_TRACK)
        return bar

    filled = min(1.0, rate / full_scale) * width
    full = int(filled)
    eighths = int(round((filled - full) * 8))
    if eighths == 8:
        full, eighths = full + 1, 0

    for i in range(width):
        if i < full:
            bar.append("█", style=_FILL)
        elif i == full and eighths:
            # Partial tip: bright fill on the left eighths, dim track behind.
            bar.append(_EIGHTHS[eighths], style=f"{_FILL} on {_TRACK}")
        else:
            bar.append("█", style=_TRACK)
    return bar
