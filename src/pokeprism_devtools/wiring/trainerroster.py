"""The trainer classes a map may place, and the parties each class already has.

Read-only, and the family's — both vanilla and polished cite a trainer by a
`CLASS, PARTY` pair of named constants (`trainer BUG_CATCHER, AL, …` and
`generictrainer BUG_CATCHER, BENNY, …`), and both declare those names the same
way in `constants/trainer_constants.asm`: a `trainerclass CLASS` line opens a
run and the `const PARTY` lines under it name that class's parties. So one
reader answers `CLASSES` and `PARTIES` for both dialects. Prism cites a party by
its 1-based position instead, so its roster is a different reader and this is not
it — the two trees of the family agree here where prism does not.

`AddTrainer` places against a party that already exists; making a party is a
change to a shared roster file and a different job — the same line prism's own
form draws — so this module only reads.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

#: The one file both dialects declare classes and parties in.
CONSTANTS = "constants/trainer_constants.asm"
#: The non-class the file opens with: its `const`s are phone contacts, not
#: parties, and it is not a trainer anyone battles. Skipped so the phone book
#: does not read back as a class with a roster.
_NOT_A_CLASS = "TRAINER_NONE"

_TRAINERCLASS = re.compile(r"^\s*trainerclass\s+(\w+)")
_CONST = re.compile(r"^\s*const\s+(\w+)")


class RosterError(RuntimeError):
    """The roster file is not where a tree of this family keeps it."""


@lru_cache(maxsize=None)
def _roster(root: Path) -> dict[str, list[str]]:
    """`class -> its party constants, in the order the file declares them`.

    A class with no parties maps to `[]` — polished declares several (the
    player-character classes, whose `trainerclass` opens no run of `const`s) —
    and that is a real answer, not a gap: the class exists and has nothing a
    reuse-only form can place.
    """
    path = root / CONSTANTS
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise RosterError(
            f"{path} does not exist — this tree declares no trainer classes "
            "where the family keeps them.") from exc
    out: dict[str, list[str]] = {}
    current: str | None = None
    for raw in lines:
        line = raw.split(";")[0]
        if m := _TRAINERCLASS.match(line):
            name = m.group(1)
            current = None if name == _NOT_A_CLASS else name
            if current is not None:
                out.setdefault(current, [])
            continue
        if current is not None and (m := _CONST.match(line)):
            out[current].append(m.group(1))
    return out


def classes(root: Path) -> list[str]:
    """The trainer classes a party can be placed for — those with at least one
    party, in declaration order. A class with none is left off: the form places
    an *existing* party, so a class you could pick and then find nothing under
    is an offer with no answer."""
    return [cls for cls, parties in _roster(root).items() if parties]


def parties(root: Path, cls: str) -> list[str]:
    """One class's party constants, or `[]`. An unknown class is `[]` too — the
    form asks as the class name is typed, and a half-typed one is not an error."""
    return list(_roster(root).get(cls, []))


def has(root: Path, cls: str, party: str) -> bool:
    """Whether `party` is one of `cls`'s — the check `AddTrainer` makes before it
    writes a `trainer CLASS, PARTY` line the assembler would otherwise reject."""
    return party in _roster(root).get(cls, [])
