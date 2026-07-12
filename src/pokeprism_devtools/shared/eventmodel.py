"""What an event-header entry *is*: the four lists, and one line of one of them.

Split from :mod:`.eventheader`, which is about the *file* — how those lists are
found in a map's asm, and how they are written back without disturbing a byte
around them. This half is about their meaning, and it reads nothing.

The line between the two is the one every caller already draws. `wiring/objedit.py`
asks "which argument of a `person_event` is the palette"; `maplint` asks "what does
this entry point at". Neither is a question about parsing, and both were answered
here before this module had a name.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

_MACRO_RE = re.compile(r"^\s*(?P<macro>[a-z_]\w*)\s+(?P<args>.*?)\s*(?P<comment>;.*)?$")

#: The repo's dominant style for an entry line: a tab, the macro, `, ` between args.
_INDENT = "\t"

class UnparseableHeader(RuntimeError):
    """The map's event header doesn't fit the four-counted-lists shape."""


class ListKind(Enum):
    """The four lists, in the order the engine reads them."""
    WARPS = "warps"
    COORD_EVENTS = "coord_events"
    BG_EVENTS = "bg_events"
    OBJECT_EVENTS = "object_events"


#: Entry macros legal in each list. The first is what new entries are written as.
LIST_MACROS: dict[ListKind, tuple[str, ...]] = {
    ListKind.WARPS: ("warp_def", "dummy_warp"),
    ListKind.COORD_EVENTS: ("xy_trigger",),
    ListKind.BG_EVENTS: ("signpost",),
    ListKind.OBJECT_EVENTS: ("person_event",),
}

LIST_ORDER: tuple[ListKind, ...] = (
    ListKind.WARPS,
    ListKind.COORD_EVENTS,
    ListKind.BG_EVENTS,
    ListKind.OBJECT_EVENTS,
)

# --------------------------------------------------------------------------- #
# model                                                                       #
# --------------------------------------------------------------------------- #

@dataclass
class Entry:
    """One ``warp_def`` / ``xy_trigger`` / ``signpost`` / ``person_event`` line.

    ``args`` keeps the source text of each argument verbatim — expressions like
    ``8 + PAL_OW_BLUE`` and constants like ``SPRITE_SAGE`` survive a round trip
    untouched. Typed reads go through the accessors below.
    """
    macro: str
    args: list[str]
    lineno: int          # 0-based index into EventHeader.lines
    raw: str             # the source line, verbatim

    def arg(self, i: int) -> str:
        return self.args[i]

    def int_arg(self, i: int) -> int | None:
        """The argument as an int, or None if it's a symbol/expression."""
        return as_int(self.args[i])

    # -- person_event ------------------------------------------------------- #
    # macros/map.asm:20 — sprite, y, x, movement, radius_y, radius_x, hour,
    # daytime, color, persontype, <11>, then a persontype-dependent tail.
    @property
    def sprite(self) -> str:
        return self.args[0]

    @property
    def y(self) -> int | None:
        """The y written in the source. The macro adds +4 when assembling."""
        return self.int_arg(1)

    @property
    def x(self) -> int | None:
        return self.int_arg(2)

    @property
    def movement(self) -> str:
        return self.args[3]

    @property
    def persontype(self) -> str:
        return self.args[9]

    @property
    def script_pointer(self) -> str | None:
        """The script/text/item pointer — ``dw \\<12>``. Only meaningful for the
        common tail shape; MART and JUMPSTD spend that slot on a db instead."""
        if self.persontype in ("PERSONTYPE_MART", "PERSONTYPE_JUMPSTD"):
            return None
        return self.args[11]

    @property
    def event_flag(self) -> str:
        """The event flag. It is the last argument in *every* person_event tail
        shape (plain ``dw \\<13>``, MART's ``dw \\<14>``, and both JUMPSTD
        arities), which is what makes flag analysis shape-independent."""
        return self.args[-1]

    # -- any entry ---------------------------------------------------------- #
    # The accessors above read a person_event's layout. The four macros put the
    # same ideas in different places, so anything that walks entries generically
    # (removal, the studio's map grid) has to go through these instead.
    @property
    def coords(self) -> tuple[int | None, int | None]:
        """(y, x), wherever this macro happens to keep them."""
        at = _YX.get(self.macro)
        if at is None or len(self.args) <= max(at):
            return None, None
        return self.int_arg(at[0]), self.int_arg(at[1])

    @property
    def pointer(self) -> str | None:
        """The script/text/item this entry points at, if it points at anything.

        ``dummy_warp`` has none. A ``signpost`` only has one when its function
        isn't a JUMPSTD — those spend the slot on a ``db`` instead, exactly as
        the MART and JUMPSTD person_events do.
        """
        i = _POINTER.get(self.macro)
        if i is None or len(self.args) <= i:
            return None
        if self.macro == "person_event" and self.args[9] in _PERSON_NO_POINTER:
            return None
        if self.macro == "signpost" and self.args[2] in _SIGNPOST_NO_POINTER:
            return None
        return self.args[i]


#: Where (y, x) sit in each entry macro's arguments (macros/map.asm).
_YX = {
    "person_event": (1, 2),
    "signpost": (0, 1),
    "warp_def": (0, 1),
    "dummy_warp": (0, 1),
    "xy_trigger": (1, 2),
}

#: Where the pointer sits, for the macros that have one.
_POINTER = {"person_event": 11, "signpost": 3, "xy_trigger": 3}

_PERSON_NO_POINTER = ("PERSONTYPE_MART", "PERSONTYPE_JUMPSTD")
_SIGNPOST_NO_POINTER = ("SIGNPOST_JUMPSTD", "SIGNPOST_JUMPSTDNOSFX")


@dataclass
class EventList:
    """One counted list: its ``db N`` line plus the entry lines under it."""
    kind: ListKind
    count_lineno: int              # 0-based index of the `db N` line
    declared_count: int            # the N actually written in the source
    entries: list[Entry] = field(default_factory=list)
    strays: list[int] = field(default_factory=list)   # entry lines past the count

    @property
    def count_matches(self) -> bool:
        """False = a real bug, not a parse failure. The count byte is what the
        engine trusts: declaring more entries than exist makes it read the
        following bytes as a phantom object (three maps in pokeprism do this
        today); declaring fewer silently drops the tail. Either way the map
        still parses — the mismatch is a lint finding, so callers can edit and
        fix it rather than being locked out of the map."""
        return self.declared_count == len(self.entries) and not self.strays


def format_entry(macro: str, args: list[str]) -> str:
    """Render an entry line in the repo's dominant style: tab, macro, ``, ``."""
    return f"{_INDENT}{macro} {', '.join(str(a).strip() for a in args)}"


def as_int(s: str) -> int | None:
    """The number an argument denotes — decimal, `$hex`, `%binary` — or None if it
    is a symbol or an expression.

    Public because "is this the same number, written differently?" is a question
    anyone *rewriting* an entry must ask, and `int(s, 0)` cannot answer it: rgbasm
    spells hex `$b`, not `0xb`, and two thirds of the warps here are written that
    way. An editor that got this wrong would reformat the lot.
    """
    s = s.strip()
    try:
        if s.startswith("$"):
            return int(s[1:], 16)
        if s.startswith("%"):
            return int(s[1:], 2)
        return int(s, 10)
    except ValueError:
        return None


def _split_args(rest: str) -> list[str]:
    return [a.strip() for a in rest.split(",")]
