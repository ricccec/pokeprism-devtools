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

This sits beside `.dialogue` rather than inside `.lint` because both halves of
the family's text work read it: the linter, to say a line landed outside the
window, and `.text`, to pick the macro for a line you have just written. A
writer that did not know where `line` lands would emit one over the top of the
line above it — which is a finding the linter would then report against text
this studio wrote.
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


class Cursor:
    """Where the next line lands, and which rows already have ink on them.

    The bookkeeping you cannot do by looking at one macro. `<LINE>` is
    *absolute*, so whether a `line` is the box's second line or a line drawn
    straight over the last one is not a property of the `line` — it is a
    property of everything above it. In a two-row family box that question has
    teeth: a *third* line written as a third `line` draws over the second, and
    the way to a third line is `cont`, which scrolls the box and frees the row
    first.

    Prism's `textbox.Cursor` is the same class over prism's actions, and the
    duplication is the seam doing its job: the constants are each dialect's.
    """

    def __init__(self, box: Box) -> None:
        self.box = box
        self.row = box.first_row
        self.taken: set[int] = set()

    def lands(self, action: str) -> int:
        return self.box.rows_for(action, self.row)

    def clobbers(self, action: str) -> bool:
        """Whether a line with this action draws over one already there.

        `<CONT>` scrolls its row off the top before it writes and `<PARA>` wipes
        the box, so neither ever can — which is exactly why they are the way out
        when `<LINE>` has nowhere left to go.
        """
        if action in (SCROLL, OPEN):
            return False
        return self.lands(action) in self.taken

    def move(self, action: str) -> None:
        if action == OPEN:
            self.taken.clear()             # the box is wiped; every row is free
        elif action == SCROLL:
            self.taken.discard(self.row)   # this row scrolled off the top
        self.row = self.lands(action)
        self.taken.add(self.row)


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
