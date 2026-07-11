"""The unit of change every asm editor in this repo speaks: :class:`Edit`.

An editor never writes as a side effect. It returns a full-file-text Edit that
the caller can diff (dry run), stack with other edits, and apply in one go —
which is what makes the writers idempotent and previewable. ``mapfit.mapwire``
re-exports both names, so ``mapwire.Edit`` stays the canonical spelling for
map-wiring callers.

Because an Edit carries the *whole* file, two of them built against the same
starting text and then applied one after the other do not merge — the second
simply overwrites the first, and the first silently never happened. That is a
very easy mistake to make (build up several changes, apply them at the end) and
a very quiet one: the flag allocator would hand the same ``const skip`` slot to
both. So an Edit records the text it was derived from, and :func:`apply_edits`
refuses to write when the file on disk has moved on since.

The rule that falls out: **build an edit, apply it, then build the next.**
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class StaleEdit(RuntimeError):
    """An edit was computed against a version of the file that is no longer on
    disk, so applying it would throw away whatever changed in between."""


@dataclass
class Edit:
    path: str            # repo-relative
    changed: bool
    detail: str
    new_text: str = ""   # full file text after the edit (for dry-run diffing)
    #: The file's text when this edit was computed. None means "don't check" —
    #: for editors that create a file, or that were written before the check
    #: existed and only ever produce one edit per file per run.
    base: str | None = None
    #: A file that is not text. A `.blk` is one byte per block and decodes as
    #: nothing, so it cannot travel in `new_text` — the encoder would mangle it.
    #: When this is set it is what gets written, and `new_text` is only a
    #: sentence about it, because a diff has nothing useful to say about bytes.
    data: bytes | None = None

    @property
    def binary(self) -> bool:
        return self.data is not None


def apply_edits(root: Path, edits: list[Edit], *, dry_run: bool) -> None:
    """Write each edit to disk (unless dry_run), creating files as needed.

    Raises :class:`StaleEdit` rather than clobbering a file that has changed
    since the edit was computed.
    """
    if dry_run:
        return
    for e in edits:
        if not (e.changed and (e.new_text or e.binary)):
            continue
        path = root / e.path
        if e.base is not None and path.exists() and path.read_text() != e.base:
            raise StaleEdit(
                f"{e.path} has changed since this edit was computed "
                f"({e.detail!r}); applying it would discard those changes. "
                f"Build an edit, apply it, then build the next."
            )
        # An editor that creates a file may be creating the first one in its
        # directory — `.devtools/specs/` doesn't exist until a spec is saved.
        path.parent.mkdir(parents=True, exist_ok=True)
        if e.binary:
            path.write_bytes(e.data)      # type: ignore[arg-type]
        else:
            path.write_text(e.new_text)
