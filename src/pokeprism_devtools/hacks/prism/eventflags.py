"""Model of ``constants/event_flags.asm`` — and a safe allocator for new flags.

Event flags are a flat auto-incrementing enum (~2000 of them) whose *values are
positions*: they index bits in the player's save file. So inserting a flag in
the middle renumbers every flag after it and silently invalidates every existing
save. The file avoids that by carrying **823 pre-reserved filler slots**::

    const skip          ; macros/enum.asm:34 — bumps the counter, defines nothing

Allocating a flag therefore means *replacing the earliest ``const skip``* with
the new name, which keeps every other flag's value fixed and is save-compatible.
Appending at the end also works but wastes the reserve, so :func:`allocate` uses
a skip slot when one exists and only falls back to appending when they run out.

The counter this file starts from is not hardcoded: ``constants.asm`` does
``const_def`` + ``const EVENT_0`` before INCLUDEing it, so it starts at 1
(EVENT_1 == 1). :func:`load` reads that offset back out of the parent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ...shared.edits import Edit

_REL = "constants/event_flags.asm"
_PARENT_REL = "constants.asm"

_CONST_RE = re.compile(r"^\s*const\s+([A-Za-z_]\w*)\s*(?:;.*)?$")
_CONST_DEF_RE = re.compile(r"^\s*const_def(?:\s+(-?\d+|\$[0-9a-fA-F]+))?\s*(?:;.*)?$")
_CONST_VALUE_RE = re.compile(r"^\s*const_value\s*=\s*(-?\d+|\$[0-9a-fA-F]+)\s*(?:;.*)?$")
_INCLUDE_RE = re.compile(r'^\s*INCLUDE\s+"([^"]+)"')
_NUM_EVENTS_RE = re.compile(r"^\s*NUM_EVENTS\s+EQU\s+const_value")

_SKIP = "skip"
_INDENT = "\t"


class FlagError(RuntimeError):
    pass


@dataclass(frozen=True)
class Flag:
    name: str
    value: int
    lineno: int          # 0-based index into EventFlags.lines


@dataclass
class EventFlags:
    path: Path
    lines: list[str]                                  # the file, verbatim
    start_value: int                                  # counter on entering the file
    flags: list[Flag] = field(default_factory=list)
    skips: list[Flag] = field(default_factory=list)   # free slots (name == "skip")
    #: Flags defined in constants.asm *before* the INCLUDE — EVENT_0 lives there.
    #: They are real flags and maps reference them, but they are not ours to edit.
    preamble: dict[str, int] = field(default_factory=dict)
    _eol: str = "\n"

    # -- read --------------------------------------------------------------- #
    @property
    def by_name(self) -> dict[str, int]:
        """Every event flag that exists, including the preamble's."""
        return {**self.preamble, **{f.name: f.value for f in self.flags}}

    @property
    def num_events(self) -> int:
        """What ``NUM_EVENTS EQU const_value`` resolves to: one past the last."""
        return self.start_value + len(self.flags) + len(self.skips)

    @property
    def free_slots(self) -> int:
        return len(self.skips)

    def has(self, name: str) -> bool:
        return any(f.name == name for f in self.flags)

    def to_text(self) -> str:
        return self._eol.join(self.lines)

    # -- write -------------------------------------------------------------- #
    def allocate(self, name: str) -> Flag:
        """Reserve `name`, reusing the earliest free ``const skip`` slot.

        Returns the Flag (with the value it will have). Idempotent: allocating a
        name that already exists returns the existing flag and changes nothing.
        Raises if the reserve is exhausted — appending instead would be correct
        for the ROM but would grow the flag array, so it's the caller's call.
        """
        existing = next((f for f in self.flags if f.name == name), None)
        if existing:
            return existing
        if not _NAME_RE.match(name):
            raise FlagError(f"{name!r} is not a valid flag name")
        if not self.skips:
            raise FlagError(
                f"no `const skip` slots left in {_REL} — every one of the "
                f"{len(self.flags)} flags is allocated. Appending at the end "
                "would work but grows the event-flag array; do that explicitly."
            )
        slot = self.skips[0]
        self.lines[slot.lineno] = f"{_INDENT}const {name}"
        self._reparse()
        return next(f for f in self.flags if f.name == name)

    def free(self, name: str) -> Flag:
        """Give `name`'s slot back, by turning it into a ``const skip`` again.

        The inverse of :meth:`allocate`, and it has to be done this way round:
        *deleting* the line would renumber every flag below it, and flag values
        are save-file bit positions, so that would invalidate every save in
        existence. Rewriting it to ``skip`` holds every other flag's value
        exactly where it was and returns the slot to the reserve.

        Returns the freed slot. Idempotent in the sense that freeing a name that
        isn't allocated raises rather than silently doing nothing — a caller
        that thinks it owns a flag it doesn't is a caller with a bug.
        """
        flag = next((f for f in self.flags if f.name == name), None)
        if flag is None:
            raise FlagError(f"{name} is not an allocated flag in {_REL}")

        self.lines[flag.lineno] = f"{_INDENT}const {_SKIP}"
        self._reparse()
        return Flag(_SKIP, flag.value, flag.lineno)

    def to_edit(self, root: Path, detail: str) -> Edit:
        text = self.to_text()
        base = self.path.read_text()
        changed = text != base
        return Edit(_REL, changed, detail, text if changed else "", base=base)

    def _reparse(self) -> None:
        fresh = _parse(self.path, self.lines, self.start_value, self._eol)
        self.flags, self.skips = fresh.flags, fresh.skips


_NAME_RE = re.compile(r"^[A-Za-z_]\w*$")


# --------------------------------------------------------------------------- #
# parsing                                                                     #
# --------------------------------------------------------------------------- #

def load(root: Path) -> EventFlags:
    path = root / _REL
    if not path.exists():
        raise FlagError(f"{path} not found")
    start, preamble = _preamble(root)
    flags = _parse(path, path.read_text().split("\n"), start, "\n")
    flags.preamble = preamble
    return flags


def start_value(root: Path) -> int:
    """The const counter as it stands when ``constants.asm`` INCLUDEs the event
    flags — read from source, so a change upstream is picked up rather than
    silently shifting every flag value this tool reports."""
    return _preamble(root)[0]


def _preamble(root: Path) -> tuple[int, dict[str, int]]:
    """Walk constants.asm up to the event-flag INCLUDE, returning the counter it
    hands over and any EVENT_* it defined on the way (EVENT_0 is defined there,
    and maps do reference it)."""
    parent = root / _PARENT_REL
    if not parent.exists():
        raise FlagError(f"{parent} not found")

    counter = 0
    defined: dict[str, int] = {}
    for line in parent.read_text().split("\n"):
        m = _INCLUDE_RE.match(line)
        if m and m.group(1) == _REL:
            return counter, defined
        if m := _CONST_DEF_RE.match(line):
            counter = _to_int(m.group(1)) if m.group(1) else 0
        elif m := _CONST_VALUE_RE.match(line):
            counter = _to_int(m.group(1))
        elif m := _CONST_RE.match(line):
            if m.group(1).startswith("EVENT_"):
                defined[m.group(1)] = counter
            counter += 1
    raise FlagError(f"{_PARENT_REL} does not INCLUDE {_REL}")


def _parse(path: Path, lines: list[str], start: int, eol: str) -> EventFlags:
    flags: list[Flag] = []
    skips: list[Flag] = []
    counter = start

    for i, line in enumerate(lines):
        if _CONST_DEF_RE.match(line) or _CONST_VALUE_RE.match(line):
            raise FlagError(
                f"{path}:{i + 1}: the event flag enum resets its counter here; "
                "flag values are save-file bit positions and this parser assumes "
                "one unbroken run"
            )
        m = _CONST_RE.match(line)
        if not m:
            continue
        name = m.group(1)
        (skips if name == _SKIP else flags).append(Flag(name, counter, i))
        counter += 1

    return EventFlags(path=path, lines=lines, start_value=start,
                      flags=flags, skips=skips, _eol=eol)


def declares_num_events(lines: list[str]) -> bool:
    return any(_NUM_EVENTS_RE.match(ln) for ln in lines)


def _to_int(s: str) -> int:
    s = s.strip()
    if s.startswith("$"):
        return int(s[1:], 16)
    if s.startswith("%"):
        return int(s[1:], 2)
    return int(s, 10)
