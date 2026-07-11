"""Model of ``trainers/groups/<class>.asm`` — and a safe way to add a party.

Every trainer class owns one file holding its parties back to back. A map picks
one with ``trainer FLAG, CLASS, <n>, …``, and **n is a 1-based ordinal**: the
engine walks the group from the top, skipping n-1 parties, and battles whatever
it lands on. Nothing but counting ties the map to the party — no label, no
symbol, no check. Insert a party in the middle of a group and every trainer
below it in the file silently gains a different team.

So this module only ever *appends*, and it re-derives the ``; n`` comments from
position rather than trusting the ones already written (they are decoration, and
a stale one is exactly the kind of thing that misleads a human into inserting in
the wrong place).

A party is::

    ; 3
    db "Ricky@"              <- name, @-terminated

    db TRAINERTYPE_NORMAL    <- how each mon below is encoded

    db 16, CHIKORITA         <- NORMAL: level, species
    db 16, BELLSPROUT
    db -1                    <- end of party

``TRAINERTYPE_ITEM`` mons carry a held item (``db 16, CHIKORITA, ORAN_BERRY``)
and ``TRAINERTYPE_MOVES`` mons are followed by exactly four indented ``db MOVE``
lines. The type is per-party, not per-mon.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .edits import Edit

_DIR = "trainers/groups"
_POINTERS = "trainers/trainer_pointers.asm"
_CLASSES = "constants/trainer_constants.asm"

NORMAL = "TRAINERTYPE_NORMAL"
MOVES = "TRAINERTYPE_MOVES"
ITEM = "TRAINERTYPE_ITEM"

#: A MOVES party spells out a full moveset for every mon, always four slots
#: (empty ones are NO_MOVE) — the engine reads a fixed four.
MOVES_PER_MON = 4

_GROUP_LABEL_RE = re.compile(r"^(\w+Group):")
_NAME_RE = re.compile(r'^\s*db\s+"(.*)@"')
_TYPE_RE = re.compile(r"^\s*db\s+(TRAINERTYPE_\w+)")
_END_RE = re.compile(r"^\s*db\s+-1\s*(?:;.*)?$")

_INDENT = "\t"
_MOVE_INDENT = "\t\t"


class TrainerPartyError(RuntimeError):
    pass


@dataclass(frozen=True)
class Mon:
    level: int
    species: str
    item: str | None = None          # TRAINERTYPE_ITEM only
    moves: tuple[str, ...] = ()      # TRAINERTYPE_MOVES only, four of them


@dataclass
class Party:
    index: int                       # 1-based — what the map's `trainer` macro cites
    name: str
    kind: str                        # TRAINERTYPE_*
    mons: list[Mon] = field(default_factory=list)
    start: int = 0                   # 0-based line of the `db "Name@"`
    end: int = 0                     # 0-based line of the closing `db -1`


@dataclass
class TrainerGroup:
    cls: str                         # "Youngster" — the group label minus "Group"
    label: str                       # "YoungsterGroup"
    path: Path
    lines: list[str]                 # the file, verbatim
    parties: list[Party] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.parties)

    def party(self, index: int) -> Party:
        if not 1 <= index <= self.count:
            raise TrainerPartyError(
                f"{self.label} has {self.count} parties; #{index} is out of range"
            )
        return self.parties[index - 1]

    def find(self, name: str) -> Party | None:
        return next((p for p in self.parties if p.name == name), None)

    def to_text(self) -> str:
        return "\n".join(self.lines)

    # -- write -------------------------------------------------------------- #
    def add_party(self, name: str, mons: list[Mon], kind: str = NORMAL) -> Party:
        """Append a party and return it, carrying the index the map must cite.

        Appending is the only safe edit: every existing party keeps its ordinal,
        so no map that already points into this group changes meaning.
        """
        _check(name, mons, kind)

        block = _render(self.count + 1, name, mons, kind)
        at = (self.parties[-1].end + 1) if self.parties else len(self.lines)

        # Land after the last party, keeping one blank line between parties and
        # not disturbing whatever trails the file.
        self.lines[at:at] = ["", *block]
        self._reparse()
        return self.parties[-1]

    def _reparse(self) -> None:
        fresh = _parse(self.path, self.lines)
        if fresh is None:                              # pragma: no cover - we just wrote it
            raise TrainerPartyError(f"{self.path}: lost the group label while editing")
        self.parties = fresh.parties

    def to_edit(self, root: Path, detail: str) -> Edit:
        rel = str(self.path.relative_to(root))
        text = self.to_text()
        base = self.path.read_text()
        changed = text != base
        return Edit(rel, changed, detail, text if changed else "", base=base)


def _check(name: str, mons: list[Mon], kind: str) -> None:
    if not name or "@" in name or '"' in name:
        raise TrainerPartyError(f"{name!r} is not a usable trainer name")
    if kind not in (NORMAL, MOVES, ITEM):
        raise TrainerPartyError(f"{kind!r} is not a trainer type")
    if not mons:
        raise TrainerPartyError(f"{name} has no Pokemon")
    for mon in mons:
        if kind == ITEM and not mon.item:
            raise TrainerPartyError(f"{name}: {kind} needs a held item on every mon")
        if kind == MOVES and len(mon.moves) != MOVES_PER_MON:
            raise TrainerPartyError(
                f"{name}: {kind} needs exactly {MOVES_PER_MON} moves on every mon "
                f"(pad with NO_MOVE), got {len(mon.moves)} for {mon.species}"
            )


def _render(index: int, name: str, mons: list[Mon], kind: str) -> list[str]:
    out = [f"{_INDENT}; {index}", f'{_INDENT}db "{name}@"', "", f"{_INDENT}db {kind}", ""]
    for mon in mons:
        if kind == ITEM:
            out.append(f"{_INDENT}db {mon.level}, {mon.species}, {mon.item}")
        else:
            out.append(f"{_INDENT}db {mon.level}, {mon.species}")
            if kind == MOVES:
                out += [f"{_MOVE_INDENT}db {move}" for move in mon.moves]
    out.append(f"{_INDENT}db -1")
    return out


# --------------------------------------------------------------------------- #
# parsing                                                                     #
# --------------------------------------------------------------------------- #

def load(root: Path) -> dict[str, TrainerGroup]:
    """Every trainer group, keyed by its asm label (``YoungsterGroup``)."""
    groups: dict[str, TrainerGroup] = {}
    for path in sorted((root / _DIR).glob("*.asm")):
        group = _parse(path, path.read_text().split("\n"))
        if group:
            groups[group.label] = group
    return groups


#: A class whose ``TrainerGroups`` slot is ``dw NULL`` — the class exists in the
#: enum but has no party data behind it.
NULL_GROUP = "NULL"


def class_groups(root: Path) -> dict[str, str | None]:
    """Trainer class const -> the group label holding its parties.

    The link is ``TrainerGroups`` in trainers/trainer_pointers.asm: a flat ``dw``
    table the engine indexes by class id, so slot *i* belongs to the *i*-th
    ``trainerclass`` in the enum. Reading it is the only way to get this right —
    names don't tell you (``CHAMPION`` battles out of ``LanceGroup``), and the
    table is where the truth is enforced.

    A class maps to None when its slot is ``dw NULL``, or when the class is past
    the end of the table (see :func:`unbacked_classes`) — both meaning "no
    parties", which callers must handle rather than index into.
    """
    classes = _class_order(root)
    pointers = _group_pointers(root)

    out: dict[str, str | None] = {}
    for i, cls in enumerate(classes):
        label = pointers[i] if i < len(pointers) else None
        out[cls] = None if label in (None, NULL_GROUP) else label
    return out


def unbacked_classes(root: Path) -> dict[str, str]:
    """Classes that cannot be battled, and why.

    Two ways a class ends up with no parties, both of which assemble cleanly:
    its ``TrainerGroups`` slot is ``dw NULL``, or the table simply ends before
    the class does — in which case indexing it reads *past the table*, and
    whatever ``dw`` happens to follow in the ROM gets used as a party pointer.
    """
    classes = _class_order(root)
    pointers = _group_pointers(root)
    if not pointers:
        return {}          # no table to judge against — say nothing rather than everything

    out: dict[str, str] = {}
    for i, cls in enumerate(classes):
        if i >= len(pointers):
            out[cls] = (
                f"has no entry in TrainerGroups ({_POINTERS} runs out after "
                f"{len(pointers)} of {len(classes)} classes) — battling it reads "
                f"past the end of the table"
            )
        elif pointers[i] == NULL_GROUP:
            out[cls] = f"points at `dw NULL` in TrainerGroups ({_POINTERS})"
    return out


def group_for(root: Path, cls: str) -> TrainerGroup:
    """The group backing trainer class `cls` (``SAGE``, ``BLACKBELT_T``, …)."""
    mapping = class_groups(root)
    if cls not in mapping:
        raise TrainerPartyError(f"{cls} is not a trainer class (no `trainerclass {cls}` in {_CLASSES})")

    label = mapping[cls]
    if label is None:
        raise TrainerPartyError(f"trainer class {cls} {unbacked_classes(root)[cls]}")

    group = load(root).get(label)
    if group is None:
        raise TrainerPartyError(
            f"{cls} points at {label} in {_POINTERS}, but no file in {_DIR} defines it"
        )
    return group


_TRAINERCLASS_RE = re.compile(r"^\s*trainerclass\s+(\w+)")
_DW_RE = re.compile(r"^\s*dw\s+(\w+)")

#: The enum opens with the sentinel class 0, which the pointer table skips.
_NO_CLASS = "TRAINER_NONE"


def _class_order(root: Path) -> list[str]:
    """The trainer classes, in enum order, excluding the id-0 sentinel."""
    classes = [m.group(1) for line in _lines(root / _CLASSES)
               if (m := _TRAINERCLASS_RE.match(line))]
    return classes[1:] if classes and classes[0] == _NO_CLASS else classes


def _group_pointers(root: Path) -> list[str]:
    return [m.group(1) for line in _lines(root / _POINTERS)
            if (m := _DW_RE.match(line))]


def _lines(path: Path) -> list[str]:
    """A repo without these files has no trainers to check; that's not an error."""
    return path.read_text().split("\n") if path.exists() else []


def _parse(path: Path, lines: list[str]) -> TrainerGroup | None:
    label: str | None = None
    for line in lines:
        m = _GROUP_LABEL_RE.match(line)
        if m:
            label = m.group(1)
            break
    if label is None:
        return None

    group = TrainerGroup(cls=_strip_group(label), label=label, path=path, lines=lines)
    group.parties = _parties(path, lines)
    return group


def _strip_group(label: str) -> str:
    return label[:-len("Group")] if label.endswith("Group") else label


def _parties(path: Path, lines: list[str]) -> list[Party]:
    """Every party, in file order — the order *is* the index.

    A party runs from its ``db "Name@"`` to its closing ``db -1``. That name line
    is the only unambiguous opener: the ``; n`` comments are decoration, and a
    party's mon lines are indistinguishable from any other ``db``.
    """
    parties: list[Party] = []
    current: Party | None = None

    for i, line in enumerate(lines):
        if m := _NAME_RE.match(line):
            if current is not None:
                raise TrainerPartyError(
                    f"{path}:{i + 1}: party '{m.group(1)}' opens before "
                    f"'{current.name}' was closed with `db -1`"
                )
            current = Party(index=len(parties) + 1, name=m.group(1), kind=NORMAL, start=i)
            continue
        if current is None:
            continue

        if m := _TYPE_RE.match(line):
            current.kind = m.group(1)
        elif _END_RE.match(line):
            current.end = i
            parties.append(current)
            current = None
        elif mon := _mon(line, current.kind):
            current.mons.append(mon)
        elif current.kind == MOVES and (move := _move(line)):
            if not current.mons:
                raise TrainerPartyError(f"{path}:{i + 1}: a move before any Pokemon")
            last = current.mons[-1]
            current.mons[-1] = Mon(last.level, last.species, last.item,
                                   (*last.moves, move))

    if current is not None:
        raise TrainerPartyError(f"{path}: party '{current.name}' is never closed with `db -1`")
    return parties


_MON_RE = re.compile(r"^\s*db\s+(\d+)\s*,\s*(\w+)\s*(?:,\s*(\w+)\s*)?(?:;.*)?$")
_MOVE_RE = re.compile(r"^\s+db\s+(\w+)\s*(?:;.*)?$")


def _mon(line: str, kind: str) -> Mon | None:
    m = _MON_RE.match(line)
    if not m:
        return None
    level, species, item = m.group(1), m.group(2), m.group(3)
    if kind != ITEM and item:
        return None
    return Mon(level=int(level), species=species, item=item if kind == ITEM else None)


def _move(line: str) -> str | None:
    m = _MOVE_RE.match(line)
    return m.group(1) if m else None
