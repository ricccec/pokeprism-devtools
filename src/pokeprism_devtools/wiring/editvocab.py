"""The dialect-free vocabulary of editing an entry that is already in the map.

These are the primitives every editor in the write layer shares, and not one of
them knows a hack's dialect. The rule they encode — *rewrite only the arguments
that actually moved, and hand back the source text of everything else* — is the
same discipline whether the entry is prism's thirteen-argument `person_event` or
a family `generictrainer`. What differs between hacks is the layout those
arguments sit in, and none of that lives here.

The prism-bound editor that *uses* this vocabulary — `MapEdit`, the field-index
constants (`PALETTE`, `S_X`, `W_Y`), the `edit_*` functions — is in
`hacks/prism/objedit`, because those encode prism's layout and no other tree's.
This module is kept in `wiring/` and free of any `hacks.prism` import on purpose:
a family editor may one day reuse the discipline, and it must be able to without
dragging the prism parser stack across the seam.
"""

from __future__ import annotations

import re

from dataclasses import dataclass, field
from typing import Protocol

from ..shared.constants import as_int
from ..shared.edits import Edit


class Spliceable(Protocol):
    """What :func:`spliced` needs of an entry: a macro name and its argument
    vector. Structural on purpose — naming a concrete `Entry` type would tie this
    module to whichever hack defined it, which is the coupling it exists to avoid.
    """

    macro: str
    args: list[str]


#: The palette argument is not just a palette. `8 + PAL_OW_BLUE` draws the body
#: *behind* the background layer — and so does `PAL_OW_PLAYER + 8`, which is the
#: same thing written the other way round, and a few objects carry a bare number
#: with no palette name in it at all. The form asks about the colour and has never
#: asked about any of the rest, so the rest is carried across untouched: find the
#: name, swap the name, leave the arithmetic where it was. See :func:`palette_of`.
_PAL_RE = re.compile(r"\bPAL_OW_\w+")


class EditError(RuntimeError):
    """This thing cannot be changed the way you asked. Carries a message meant
    for a human, as the rest of the wiring layer's errors do."""


@dataclass
class Change:
    """Everything one edit touches. Apply the edits together or not at all."""
    summary: str
    edits: list[Edit] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def changes(self) -> list[Edit]:
        return [e for e in self.edits if e.changed]


def same(old: str, new: object) -> bool:
    """Is this argument being *changed*, or merely restated?

    Not string equality, and that distinction is the difference between an editor
    and a reformatter. Two thirds of the warps in this repo write their
    coordinates in hex — `warp_def $18, $19, …` — and a form shows you `24` and
    hands back `24`, which is the same number and a different eleven characters.
    Believe the characters and moving one NPC rewrites a thousand warp lines.
    """
    old, new = old.strip(), str(new).strip()
    if old == new:
        return True
    a, b = as_int(old), as_int(new)
    return a is not None and a == b


def spliced(entry: Spliceable, changed: dict[int, object]) -> list[str]:
    """The entry's arguments with only these replaced, the rest verbatim.

    The rule the whole write layer rests on, and it is stronger than it looks: an
    argument not named here comes back as the *source text* that was there — the
    expression, the constant, the hex, the spacing somebody chose. And an argument
    that *is* named here, but whose value did not actually move, comes back the
    same way (see :func:`same`). So an edit is a promise about everything it did
    not change, and the round-trip test is a test of that promise.
    """
    args = list(entry.args)
    for i, value in changed.items():
        if not -len(args) <= i < len(args):
            raise EditError(
                f"a {entry.macro} has {len(args)} arguments, so there is nothing "
                f"at {i} — this map's entry is not the shape the editor expects.")
        if not same(args[i], value):
            args[i] = str(value).strip()
    return args


def palette_of(arg: str) -> str:
    """The palette name out of an argument that may be arithmetic. What the form
    is shown, and what it hands back. An argument with no name in it — a bare `0` —
    is its own answer, and the form will show it and write it straight back."""
    m = _PAL_RE.search(arg)
    return m.group(0) if m else arg.strip()


def repainted(arg: str, palette: str) -> str:
    """A palette argument with a new colour in it, and everything else where it
    was — the `8 +`, the `+ 8`, the spacing."""
    if palette == palette_of(arg):
        return arg
    m = _PAL_RE.search(arg)
    return f"{arg[:m.start()]}{palette}{arg[m.end():]}" if m else palette
