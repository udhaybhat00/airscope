"""Regenerate the splash logo text (logo_sm.ans) with new wording.

Keeps the Wi-Fi arcs artwork byte-identical; redraws only the block-letter
text rows in the same visual style (white face + gray right shadow) and the
same theme-mapped triplets so recolor_logo() keeps working:
  face  = fg(255,255,255) + bg(255,255,255)  -> theme text-primary
  shade = fg(255,255,255) + bg(128,128,128)  -> theme text-secondary
  empty = fg(255,255,255) + bg(0,0,0)        -> transparent via make_black_transparent
"""
import re
import sys
from pathlib import Path

FONT = {
    # 4-wide x 7-tall block faces ('#' = pixel).
    "A": [" ## ", "#  #", "#  #", "####", "#  #", "#  #", "#  #"],
    "I": ["####", " ## ", " ## ", " ## ", " ## ", " ## ", "####"],
    "R": ["### ", "#  #", "#  #", "### ", "# # ", "#  #", "#  #"],
    "S": ["####", "#   ", "#   ", "####", "   #", "   #", "####"],
    "C": [" ###", "#   ", "#   ", "#   ", "#   ", "#   ", " ###"],
    "O": [" ###", "#  #", "#  #", "#  #", "#  #", "#  #", " ###"],
    "P": ["### ", "#  #", "#  #", "### ", "#   ", "#   ", "#   "],
    "E": ["####", "#   ", "#   ", "### ", "#   ", "#   ", "####"],
}

WHITE = (255, 255, 255)
GRAY = (128, 128, 128)
BLACK = (0, 0, 0)
FG = (255, 255, 255)

TEXT_ROWS = (10, 17)   # [start, end) rows holding the wordmark in logo_sm.ans
WIDTH = 54


def sgr(bg):
    return f"\x1b[38;2;{FG[0]};{FG[1]};{FG[2]};48;2;{bg[0]};{bg[1]};{bg[2]}m"


def render_word(word: str) -> list[list[tuple]]:
    """7 rows of per-cell bg colors for the wordmark with right shadows."""
    rows: list[list[tuple]] = [[BLACK] * WIDTH for _ in range(7)]
    stride = 6  # 4 face + 1 shadow + 1 gap
    total = len(word) * stride - 1
    x0 = (WIDTH - total) // 2
    for li, letter in enumerate(word):
        face = FONT[letter]
        x = x0 + li * stride
        for r in range(7):
            has_ink = False
            for c in range(4):
                if face[r][c] == "#":
                    rows[r][x + c] = WHITE
                    has_ink = True
            if has_ink:
                rows[r][x + 4] = GRAY
    return rows


def encode_row(cells: list[tuple]) -> str:
    """Run-length SGR encoding matching the original file's style."""
    out = []
    cur = None
    buf = []
    for bg in cells:
        if bg != cur:
            if buf:
                out.append(sgr(cur) + " " * len(buf))
                buf = []
            cur = bg
        buf.append(bg)
    if buf:
        out.append(sgr(cur) + " " * len(buf))
    return "".join(out) + "\x1b[0m"


def main() -> None:
    word = sys.argv[1] if len(sys.argv) > 1 else "AIRSCOPE"
    path = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    if any(ch not in FONT for ch in word):
        raise SystemExit(f"no glyphs for {word!r} (have {sorted(FONT)})")
    if path is None:
        raise SystemExit("usage: make_logo.py WORD path/to/logo_sm.ans")
    lines = path.read_text(encoding="utf-8").split("\n")
    start, end = TEXT_ROWS
    assert end - start == 7, "font height changed; adjust TEXT_ROWS"
    art = render_word(word)
    for i in range(7):
        lines[start + i] = encode_row(art[i])
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {word} into {path} rows {start}-{end - 1}")


if __name__ == "__main__":
    main()
