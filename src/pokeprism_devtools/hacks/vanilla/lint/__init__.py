"""The family dialogue-overflow linter: does the text fit the box it draws in.

A `FamilyLintContext` that satisfies the seam's `Lints` — the first non-`None`
`ctx` a family tree carries. Everything here is shared across family trees except
the width `Metrics`, which is engine-specific; `build` wires vanilla's. Polished
imports this package the way it imports vanilla's read mechanics and supplies its
own `Metrics`, forking that one reader and reusing the box, the parse and the
rules unchanged.

The box (`..box`), the parse (`..dialogue`), the charmap (`..charmap`) and the
widths (`..metrics`) all sit *outside* this package on purpose, and each moved out
the moment a second reader wanted it. The reword form needs the box and the parse
— a linter and a writer that disagree about where a line begins are a writer that
edits the wrong one — and the reword *gutter* needs the charmap and the widths,
because saying a line is nineteen tiles wide while you can still shorten it and
saying it after the fact are the same count asked at two moments. What is left in
here is what only a linter wants: the rules and the context that holds them.
"""

from __future__ import annotations

from pathlib import Path

from .. import metrics
from .context import FamilyLintContext


def build(root: Path) -> FamilyLintContext:
    """Vanilla's family linter: its own width reader over the shared rules."""
    from ..read import label_of
    return FamilyLintContext(root, metrics.load, dict(label_of(root)),
                             metrics.ENGINE_FILES)
