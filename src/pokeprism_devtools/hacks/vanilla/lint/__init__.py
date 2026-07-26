"""The family dialogue-overflow linter: does the text fit the box it draws in.

A `FamilyLintContext` that satisfies the seam's `Lints` — the first non-`None`
`ctx` a family tree carries. Everything here is shared across family trees except
the width `Metrics`, which is engine-specific; `build` wires vanilla's. Polished
imports this package the way it imports vanilla's read mechanics and supplies its
own `Metrics`, forking that one reader and reusing the box, the parse and the
rules unchanged.
"""

from __future__ import annotations

from pathlib import Path

from .context import FamilyLintContext
from . import metrics


def build(root: Path) -> FamilyLintContext:
    """Vanilla's family linter: its own width reader over the shared rules."""
    from ..read import label_of
    return FamilyLintContext(root, metrics.load, dict(label_of(root)))
