"""The family dialogue-overflow linter: does the text fit the box it draws in.

A `FamilyLintContext` that satisfies the seam's `Lints` — the first non-`None`
`ctx` a family tree carries. Everything here is shared across family trees except
the width `Metrics`, which is engine-specific; `build` wires vanilla's. Polished
imports this package the way it imports vanilla's read mechanics and supplies its
own `Metrics`, forking that one reader and reusing the box, the parse and the
rules unchanged.

The box (`..box`) and the parse (`..dialogue`) sit *outside* this package on
purpose: the reword form needs both, and a linter and a writer that disagree
about where a line begins are a writer that edits the wrong one. What is left in
here is what only a linter wants — the widths, the rules, and the context that
holds them.
"""

from __future__ import annotations

from pathlib import Path

from .context import FamilyLintContext
from . import metrics

#: The files vanilla's box, charmap and widths are read from — the last, the
#: dict-and-print_name engine in `home/text.asm`, is the one polished spells
#: differently. The context degrades to silence if any is absent.
_ENGINE_FILES = ("constants/hardware.inc", "constants/text_constants.asm",
                 "constants/charmap.asm", "home/text.asm")


def build(root: Path) -> FamilyLintContext:
    """Vanilla's family linter: its own width reader over the shared rules."""
    from ..read import label_of
    return FamilyLintContext(root, metrics.load, dict(label_of(root)), _ENGINE_FILES)
