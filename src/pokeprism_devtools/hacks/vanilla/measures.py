"""What a line you are still typing will cost, in tiles, against its box.

The seam's `Measures`, for the family. The reword form counts every line on every
keystroke and puts the answer in a gutter beside it, so `#mon Center` reads
nineteen tiles against an eighteen-column box *while you can still shorten it* —
which is the whole point, because the linter's version of that sentence arrives
after the line is written and the form has closed.

**This is the linter's arithmetic, not a second copy of it.** The tiles come from
`..metrics.Metrics.tiles`, the box from `..box.speech_box`, and both are what the
overflow rules read — a gutter that said sixteen where the linter said nineteen
would be worse than no gutter at all. What differs is only *what is being
measured*: the rules measure lines the parse found in a file, this measures lines
you typed, one per screen row, a blank one starting a fresh box.

Like `..box` and `..dialogue` this lives in `vanilla/` and is polished's too. The
one thing that forks is the `Metrics` each tree hands in — vanilla's `dict`
table, polished's n-grams — which is the same fork the linter carries and no
other.
"""

from __future__ import annotations

from pathlib import Path

from ...studio import panels
from . import box
from .metrics import Metrics


def measure_lines(root: Path, metrics: Metrics, text: str) -> panels.TextPreview:
    """Prose as the form holds it, measured line by line against the one box.

    The `box` key the seam passes is not read, and that is a fact about the family
    rather than a shortcut: it draws NPC speech and signs in the same bottom
    window, so unlike prism there is no signpost to tell apart and every key names
    the same eighteen columns.
    """
    bx = box.speech_box(root)
    return panels.TextPreview(bx.name, bx.cols, [
        _measured(root, metrics, line, bx.cols)
        for line in text.replace("\r\n", "\n").split("\n")
    ])


def _measured(root: Path, metrics: Metrics, line: str, cols: int) -> panels.Measured:
    cost = metrics.tiles(root, line)
    return panels.Measured(
        text=line, tiles=cost.determinate, bounded=cost.bounded,
        unbounded=cost.unbounded, unknown=cost.unknown,
        over=max(0, cost.determinate - cols),
        over_at_worst=max(0, cost.determinate + cost.bounded - cols))
