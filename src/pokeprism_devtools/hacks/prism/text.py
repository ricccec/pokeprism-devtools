"""Rewording dialogue that is already in the game.

The other wiring modules add things. This one changes what a thing *says*, which
is a narrower and more dangerous job: the words are the only part of a text block
a person means to touch, and everything around them — the `cont` that scrolls the
box, the `para` that opens a fresh one, the label that scripts jump to — has to
come back exactly as it was.

So the splice is the block's own macros and nothing else. The label above it is
not ours to move: a script jumps to it, and every jump would break. And the
macros are reused *positionally* by :func:`.dialogue.render`, so changing
a word in the third line of a box leaves the first two byte-identical, along with
the alignment whitespace somebody chose and the blank line they left above it.
"""

from __future__ import annotations

from pathlib import Path

from . import dialogue, mapsource
from ...shared.edits import Edit


class TextError(RuntimeError):
    pass


def blocks(root: Path, map_const: str) -> list[dialogue.Block]:
    """Every text block in one map, in source order."""
    return dialogue.parse(root, _path(root, map_const))


def reword(root: Path, map_const: str, label: str, prose: str) -> Edit:
    """One block's words replaced by `prose`, the rest of the file untouched.

    `prose` is what :func:`.dialogue.plain` produces: one screen line per
    line, a blank line wherever a fresh box starts. No macros, because the macros
    are not the author's business — they are copied back from what was there.
    """
    path = _path(root, map_const)
    original = path.read_text()
    source = original.split("\n")

    block = next((b for b in dialogue.parse(root, path) if b.label == label), None)
    if block is None:
        raise TextError(f"{path.name} has no text block called {label}")

    text = "\n".join(dialogue.rewrite(source, block, prose))
    rel = f"maps/{path.stem}.asm"
    return Edit(rel, text != original, f"{label}: reworded", text, base=original)


def _path(root: Path, map_const: str) -> Path:
    label = {c: l for l, c in mapsource.header_pairs(root)}.get(map_const)
    if label is None:
        raise TextError(f"{map_const} has no map_header_2 — wire the map first")
    path = root / "maps" / f"{label}.asm"
    if not path.exists():
        raise TextError(f"{map_const} has no script file at maps/{label}.asm")
    return path
