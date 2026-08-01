"""Read and rewrite one `macro Label, …` line, argument by argument.

The dialect-free half of a header edit. Every tree keeps its map header as a
`macro` line anchored on the map's label — prism's `map_header`/`map_header_2`,
the family's `map`/`map_attributes` — and the discipline for editing one is the
same in all of them: **an argument you did not change comes back exactly as it
was written**, comments and spacing intact (see :func:`..editvocab.same`). What
forks between trees is *which* file, *which* macro, and *which* argument index a
field lands on — all of that is the caller's, handed in as data.

**Reading lives here too, and that is the point.** The reader used to be
hand-rolled once per site, and the copies disagreed about a trailing
`; comment` — prism folded it into the last argument, the family dropped it, the
writer preserved it — so prism's read path and prism's *own* write path did not
agree about what the arguments of one line were. They now share
:func:`_anchored`, which is what makes an argument index mean the same thing to
:func:`find_macro_args` and :func:`splice_macro_args`.

This is not a general asm parser and does not want to become one: sites that ask
a differently-shaped question (every `connection` line in a file, a
`sprite_header`'s four typed fields) keep their own regex, because a flag-driven
parser serving all of them would be harder to read than any of them.

Kept in `wiring/` and free of any `hacks.*` import on purpose, the same reason
`editvocab` is: this is rgbds macro syntax, not any one hack's layout, so both
prism's `mapedit` and the family's own header editor reach it without either
dragging the other across the seam.
"""

from __future__ import annotations

import re

from pathlib import Path
from typing import NamedTuple

from .editvocab import EditError, same
from ..shared.edits import Edit


class MacroLine(NamedTuple):
    """One macro invocation, as its three parts."""
    macro: str
    args: list[str]
    comment: str


#: A macro invocation: the name, its arguments, an optional trailing comment.
#: Lowercase-initial by rgbds-family convention, which is what keeps a `Label:`
#: line — and `SECTION`, `ENDM`, `EQU` — from reading as a macro.
_INVOCATION_RE = re.compile(
    r"^\s*(?P<macro>[a-z_]\w*)\s+(?P<args>.*?)\s*(?P<comment>;.*)?$")


def read_macro_line(line: str) -> MacroLine | None:
    """One `macro arg, arg, …` line split into its parts, or None if it is not one.

    The general reader: it does not know which macro it is looking at, so the
    label (where there is one) comes back as the first argument. Use
    :func:`find_macro_args` when you know the macro and the label and want the
    arguments *after* it, indexed the way :func:`splice_macro_args` writes them.
    """
    m = _INVOCATION_RE.match(line)
    if not m:
        return None
    return MacroLine(m.group("macro"),
                     [a.strip() for a in m.group("args").split(",")],
                     m.group("comment") or "")


def _anchored(macro: str, label: str) -> re.Pattern[str]:
    """The one anchor the reader and the writer share.

    Anchored on the label *and the comma after it*, so a map whose name is a
    prefix of another's (`Route30`, `Route30Gate`) is not matched by its
    neighbour's line — which is why this is not a substring search. A trailing
    comment is split off rather than left in the last argument.
    """
    return re.compile(rf"^(?P<head>\s*{macro}\s+{re.escape(label)}\s*,)"
                      rf"(?P<args>.*?)(?P<comment>\s*;.*)?$")


def find_macro_args(text: str, macro: str, label: str) -> list[str] | None:
    """The arguments of `macro`'s line for `label`, after the label, or None.

    Indexed exactly as :func:`splice_macro_args` indexes them, so a field read
    at 3 is written at 3 — the property the hand-rolled readers lacked.
    """
    rx = _anchored(macro, label)
    for line in text.split("\n"):
        if m := rx.match(line):
            return [a.strip() for a in m.group("args").split(",")]
    return None


def splice_macro_args(root: Path, rel: str, macro: str, label: str,
                      changed: dict[int, str], detail: str) -> Edit:
    """One `macro Label, …` line, with only these arguments replaced.

    Anchored by :func:`_anchored`, the same reader :func:`find_macro_args` uses,
    so the index a caller read a field at is the index it writes it back at. An
    argument named in `changed` whose value did not actually move comes back
    untouched too (`same`), so a form submitted unchanged writes nothing.
    """
    path = root / rel
    if not path.exists():
        raise EditError(f"{rel} is missing")
    original = path.read_text()
    lines = original.split("\n")

    rx = _anchored(macro, label)
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
