"""Rewrite one `macro Label, …` line in place, argument by argument.

The dialect-free half of a header edit. Every tree keeps its map header as a
`macro` line anchored on the map's label — prism's `map_header`/`map_header_2`,
the family's `map`/`map_attributes` — and the discipline for editing one is the
same in all of them: **an argument you did not change comes back exactly as it
was written**, comments and spacing intact (see :func:`..editvocab.same`). What
forks between trees is *which* file, *which* macro, and *which* argument index a
field lands on — all of that is the caller's, handed in as data.

Kept in `wiring/` and free of any `hacks.*` import on purpose, the same reason
`editvocab` is: this is rgbds macro syntax, not any one hack's layout, so both
prism's `mapedit` and the family's own header editor reach it without either
dragging the other across the seam.
"""

from __future__ import annotations

import re

from pathlib import Path

from .editvocab import EditError, same
from ..shared.edits import Edit


def splice_macro_args(root: Path, rel: str, macro: str, label: str,
                      changed: dict[int, str], detail: str) -> Edit:
    """One `macro Label, …` line, with only these arguments replaced.

    Anchored on the label, so a map whose name is a prefix of another's
    (`Route30`, `Route30Gate`) is not matched by its neighbour's line — which is
    what `\\s*,` after the label is doing, and why this is not a bare substring
    search. An argument named in `changed` whose value did not actually move
    comes back untouched too (`same`), so a form submitted unchanged writes
    nothing.
    """
    path = root / rel
    if not path.exists():
        raise EditError(f"{rel} is missing")
    original = path.read_text()
    lines = original.split("\n")

    rx = re.compile(
        rf"^(?P<head>\s*{macro}\s+{re.escape(label)}\s*,)"
        rf"(?P<args>.*?)(?P<comment>\s*;.*)?$")
    for i, line in enumerate(lines):
        m = rx.match(line)
        if not m:
            continue
        args = [a.strip() for a in m.group("args").split(",")]
        for at, value in changed.items():
            if at >= len(args):
                raise EditError(
                    f"{rel}:{i + 1}: this {macro} has {len(args)} arguments, so "
                    f"there is nothing at {at} to change.")
            if not same(args[at], value):
                args[at] = str(value).strip()
        rebuilt = f"{m.group('head')} {', '.join(args)}{m.group('comment') or ''}"
        if rebuilt == line:
            break                       # nothing moved: leave the line alone
        lines[i] = rebuilt
        text = "\n".join(lines)
        return Edit(rel, True, detail, text, base=original)
    else:
        raise EditError(f"{rel} has no {macro} line for {label}")

    return Edit(rel, False, detail, "", base=original)
