"""The two comparisons that decide whether a rendered line fits its box.

This is the whole of what prism's `rules_text` and the family's overflow rules
have in common, and it is deliberately *only* this. Both engines place one 8x8
tile per byte on the dialogue path — fixed width, no kerning — so "does the line
fit" is a tile count against the box, and "does the line land inside the box" is
a row against its last row. Those two sums are engine-agnostic; everything that
feeds them — which tokens a byte is, how wide a control code expands, where a
macro moves the cursor — is not, and stays in each tree's own reader.

Kept stdlib-only, next to `diagnostics`, so a family linter can reach it without
loading the prism rules that would otherwise come with this package.
"""

from __future__ import annotations


def overshoot(tiles: int, cols: int) -> int:
    """How many tiles a line runs past the box's right border — 0 or less when
    it fits. Positive means the last glyphs are drawn over the frame (or the map
    behind it): the engine writes one tile per byte and never wraps, so a line
    wider than the box overflows every single time it is shown."""
    return tiles - cols


def below_box(row: int, last_row: int) -> bool:
    """Whether a line lands past the last row inside the box.

    The cursor moves that get here are the *relative* ones (`<NEXT>` two rows
    down, `<LNBRK>` one) — an absolute `<LINE>` cannot leave the box, but two
    relative moves in a short box walk off the bottom and draw into whatever is
    behind the window."""
    return row > last_row
