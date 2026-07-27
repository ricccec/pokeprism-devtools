"""How wide each rendered line is, and which row it lands on.

The walk that decides *which lines exist* is not here — it is `..dialogue`,
shared with the Texts browser and the reword form, because a reader and a writer
that disagree about where a line begins are a writer that edits the wrong one.
What is left here is the half only the linter needs: the tiles a line prints,
read through the tree's own :class:`Metrics`, and the row it lands on, read
through the tree's own :class:`Box`.

The split is not tidiness. Both of those need the engine off disk —
`constants/charmap.asm`, `home/text.asm`, the box constants — and the Texts
browser has to keep listing a map's words on a tree whose engine files are
mid-edit or absent. So the structure is parsed with none of them and measured
with all of them, and the linter is the only caller that pays.

The width reader is the only part of the family lint that differs between family
trees; this measuring, the parse under it and the rules over it do not.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .. import box, dialogue
from ..box import Box
from .metrics import Metrics

#: rgbds string interpolation — `{d:PRICE}` assembles to the *value* of PRICE, a
#: handful of digits, not the forty characters of its name. It is the family's
#: `deciram`: a variable the source cannot bound, so it is dropped from the
#: determinate count rather than measured as literal text (which flagged every
#: price line in the game as a fifty-tile overflow).
_INTERP_RE = re.compile(r"\{[^}]*\}")


@dataclass(frozen=True)
class Line:
    """One rendered line of a box, measured."""
    lineno: int          # 1-based, in the map's asm
    macro: str           # the macro that opened it: text, line, para, …
    row: int             # the screen row it lands on
    determinate: int     # tiles certain to draw — literals and fixed expansions
    bounded: int         # extra tiles when every name buffer on it is at its bound
    text: str            # the source string(s), joined — for naming the culprit
    unbounded: list[str] = field(default_factory=list)  # buffers with no bound

    @property
    def worst(self) -> int:
        """Tiles when every name buffer here is at its longest — the width a
        seven-letter name makes real. `text-width-name`'s question. This does not
        include `unbounded` buffers, which have no worst case to add."""
        return self.determinate + self.bounded


@dataclass(frozen=True)
class Block:
    """One text box's worth of rendered lines, `text` through `done`."""
    lines: list[Line]


def parse(root: Path, path: Path, metrics: Metrics) -> list[Block]:
    """Every dialogue box in one map file, each line measured and placed."""
    speech = box.speech_box(root)
    out: list[Block] = []
    for block in dialogue.parse(path):
        if lines := measure(root, metrics, speech, block):
            # A box whose every line draws nothing — a lone `text_start` — has no
            # width to report and nothing for a rule to be about. The parse keeps
            # it because the writer has to see it to refuse it; this drops it.
            out.append(Block(lines))
    return out


def measure(root: Path, metrics: Metrics, speech: Box,
            block: dialogue.Block) -> list[Line]:
    """One parsed block's lines, with their widths and rows filled in."""
    out: list[Line] = []
    for line, row in zip(block.lines, dialogue.rows(block, speech)):
        det = bnd = 0
        unbounded: list[str] = []
        parts: list[str] = []
        for draw in line.draws:
            for s in (_INTERP_RE.sub("", x) for x in draw.strings):
                # Stopping at the `@` that ends the draw, exactly as the engine
                # does, is `determinate` and `bounded`'s own business: both walk
                # the string's tokens and stop at the first control code.
                det += metrics.determinate(root, s)
                bnd += metrics.bounded(root, s)
                parts.append(s)
            if not draw.buffer:
                continue
            # A name buffer adds its worst case to the bounded width, like an
            # inline `<PLAYER>`; any other buffer holds something the text cannot
            # bound, so it is recorded unbounded and adds no width — the worst
            # case is unknown, not zero, which `text-buffer` reads.
            if draw.buffer in metrics.ram_bound:
                bnd += metrics.ram_bound[draw.buffer]
            else:
                unbounded.append(draw.buffer)
        if not parts and not unbounded:
            continue
        out.append(Line(line.lineno, line.macro, row, det, bnd,
                        "".join(parts), unbounded))
    return out
