"""The unit of change every asm editor in this repo speaks: :class:`Edit`.

An editor never writes as a side effect. It returns a full-file-text Edit that
the caller can diff (dry run), stack with other edits, and apply in one go —
which is what makes the writers idempotent and previewable. ``mapfit.mapwire``
re-exports both names, so ``mapwire.Edit`` stays the canonical spelling for
map-wiring callers.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class Edit:
    path: str            # repo-relative
    changed: bool
    detail: str
    new_text: str = ""   # full file text after the edit (for dry-run diffing)


def apply_edits(root: Path, edits: list[Edit], *, dry_run: bool) -> None:
    """Write each edit's new_text to disk (unless dry_run)."""
    if dry_run:
        return
    for e in edits:
        if e.changed and e.new_text:
            (root / e.path).write_text(e.new_text)
