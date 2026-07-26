"""The box family dialogue is drawn in, and where each break lands the cursor.

The family draws NPC speech and signs in the same window — the bottom textbox,
two rows of `TEXTBOX_INNERW` tiles — so, unlike prism, there is one box here and
no signpost split. Its shape is read from the engine's own constants, not
reproduced: `TEXTBOX_INNERW` (the width) and `TEXTBOX_INNERY` (where `text`
starts) resolve out of `constants/text_constants.asm` on top of the screen
dimensions in `constants/hardware.inc`. A fork that widens the box gets the new
width for free.

The cursor moves are the other half. `<LINE>` is *absolute* — it always goes to
the box's second row — while `<NEXT>`/`<LNBRK>` are *relative*, two rows and one
below wherever the last line began. That difference is the whole of `text-rows`:
an absolute move cannot leave the box, but two relative ones in a two-row box
walk straight off the bottom.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_TEXT_CONSTANTS = "constants/text_constants.asm"
_HARDWARE = "constants/hardware.inc"

# What a break macro does to the cursor. `text`/`para` open at the top row,
# `line` jumps absolutely to the second, `cont` scrolls and reuses it, and the
# relative moves walk down from where they are.
OPEN = "open"            # text / para -> the first row, box cleared
LINE_ABS = "line"        # <LINE>      -> the second row, absolutely
SCROLL = "scroll"        # <CONT>      -> scroll up; the second row is free again
DOWN_2 = "down2"         # <NEXT>      -> two rows below the last line
DOWN_1 = "down1"         # <LNBRK>     -> one row below it
END = "end"              # <DONE> / <PROMPT> / @

_DEF_RE = re.compile(r"^\s*(?:DEF\s+)?(\w+)\s+EQU\s+(.+?)\s*(?:;.*)?$", re.IGNORECASE)


@dataclass(frozen=True)
class Box:
    """The dialogue window, and the rows its breaks land on."""
    name: str
    cols: int            # tiles per line — TEXTBOX_INNERW
    first_row: int       # where `text`/`para` start — TEXTBOX_INNERY
    second_row: int      # where `line` lands, absolutely
    last_row: int        # the last row inside the border

    def rows_for(self, action: str, row: int) -> int:
        if action in (LINE_ABS, SCROLL):
            return self.second_row
        if action == DOWN_2:
            return row + 2
        if action == DOWN_1:
            return row + 1
        if action == OPEN:
            return self.first_row
        return row


def equs(root: Path, rel: str, known: dict[str, int]) -> dict[str, int]:
    """`[DEF] NAME EQU <arithmetic>` lines, resolved against what is known so far.

    The family writes `DEF NAME EQU expr` in its own constants and the plain
    `def NAME equ N` of hardware.inc; both are one case-insensitive shape, and a
    line that is symbolic or non-arithmetic is skipped — nothing the box needs is.

    Shared with `metrics`, which reads the same constants file for the name-buffer
    length bounds `text-width-name` measures against.
    """
    out = dict(known)
    for line in (root / rel).read_text().split("\n"):
        m = _DEF_RE.match(line)
        if not m:
            continue
        try:
            out[m.group(1)] = int(eval(m.group(2), {"__builtins__": {}}, out))  # noqa: S307
        except Exception:
            continue
    return out


@lru_cache(maxsize=4)
def speech_box(root: Path) -> Box:
    """The one box family dialogue lands in, measured from the engine."""
    syms = equs(root, _HARDWARE, {})
    syms = equs(root, _TEXT_CONSTANTS, syms)
    inner_w = syms["TEXTBOX_INNERW"]
    inner_y = syms["TEXTBOX_INNERY"]
    return Box("textbox", cols=inner_w, first_row=inner_y,
               second_row=inner_y + 2, last_row=inner_y + 2)
