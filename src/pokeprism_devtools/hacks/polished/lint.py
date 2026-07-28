"""Polished's dialogue-overflow linter: its own widths over the shared rules.

There is nothing here but the wiring, and that is the point — polished shares the
overflow question with vanilla and everything that answers it except the width
reader, so the fork is one argument (`.metrics.load`) and one file list, not a
second linter. The rules, the box, the parse and the suppression channel are
`..vanilla.lint`'s, unchanged.
"""

from __future__ import annotations

from pathlib import Path

from ..vanilla.lint.context import FamilyLintContext
from . import metrics


def build(root: Path) -> FamilyLintContext:
    """Polished's family linter: its n-gram width reader over the shared rules."""
    from ..vanilla.read import label_of
    return FamilyLintContext(root, metrics.load, dict(label_of(root)),
                             metrics.ENGINE_FILES)
