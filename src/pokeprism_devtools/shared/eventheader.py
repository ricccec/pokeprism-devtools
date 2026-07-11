"""Parse + round-trip-safe writer for the ``<Label>_MapEventHeader`` block.

Every map asm ends with an event header: a filler word, then **four counted
lists in a fixed order** — warps, coord events (xy triggers), BG events
(signposts), object events (people). The engine reads them positionally, so the
order and the count bytes are what matter; the ``.Warps`` / ``.CoordEvents`` /
… labels above each list are decoration and are *not* reliable in practice::

    304 maps    .Warps / .CoordEvents / .BGEvents / .ObjectEvents
    146 maps    no labels at all, just ``;warps`` style comments
      2 maps    .Warps / .XYTriggers / .Signposts / .PersonEvents
      1 map     .Object instead of .ObjectEvents
      n maps    the count inlined on the label: ``.CoordEvents: db 0``

So this parser is **structural, not name-based**: after the header label it
reads four lists in order, each being "the next ``db N`` line, then exactly N
entry lines", and it checks each entry's macro against the ones legal for that
list. A map whose header doesn't fit that shape raises :class:`UnparseableHeader`
and callers must treat it as unmanaged rather than guess (10 maps under
``maps/`` have no event header at all — script includes).

Round-trip contract
-------------------
The whole file is retained verbatim as :attr:`EventHeader.lines`; mutations
splice regenerated lines into the recorded spans and nothing else. Serializing
an unmodified header is therefore byte-identical by construction, and code
above the header label — hand-written scripts and text — is never touched.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .edits import Edit


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

_HEADER_RE = re.compile(r"^(\w+)_MapEventHeader::?(.*)$")
_DB_RE = re.compile(r"^(?P<prefix>.*?\bdb\s+)(?P<args>.+?)\s*(?P<comment>;.*)?$")
_MACRO_RE = re.compile(r"^\s*(?P<macro>[a-z_]\w*)\s+(?P<args>.*?)\s*(?P<comment>;.*)?$")

_INDENT = "\t"


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
        return _try_int(self.args[i])

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


@dataclass
class EventHeader:
    label: str
    path: Path
    lines: list[str]                       # the whole file, verbatim
    header_lineno: int                     # index of the `X_MapEventHeader::` line
    lists: dict[ListKind, EventList]
    _eol: str = "\n"

    # -- read --------------------------------------------------------------- #
    def list_of(self, kind: ListKind) -> EventList:
        return self.lists[kind]

    @property
    def warps(self) -> list[Entry]:
        return self.lists[ListKind.WARPS].entries

    @property
    def coord_events(self) -> list[Entry]:
        return self.lists[ListKind.COORD_EVENTS].entries

    @property
    def bg_events(self) -> list[Entry]:
        return self.lists[ListKind.BG_EVENTS].entries

    @property
    def object_events(self) -> list[Entry]:
        return self.lists[ListKind.OBJECT_EVENTS].entries

    def to_text(self) -> str:
        """The file's full text. Byte-identical to the source if nothing was
        mutated — the lines are held verbatim and only spliced on write."""
        return self._eol.join(self.lines)

    # -- write -------------------------------------------------------------- #
    def add_entry(self, kind: ListKind, args: list[str], *, index: int | None = None) -> Entry:
        """Insert an entry (default: append) and bump the list's count byte.

        Returns the new Entry. Warps are 1-based-indexed by other maps, so
        appending — not inserting — is what keeps existing ``warp_to`` targets
        valid; ``index`` exists for callers that know what they're doing.
        """
        lst = self.lists[kind]
        macro = LIST_MACROS[kind][0]
        line = format_entry(macro, args)
        at = len(lst.entries) if index is None else index

        if lst.entries:
            insert_at = (lst.entries[at].lineno if at < len(lst.entries)
                         else lst.entries[-1].lineno + 1)
        else:
            insert_at = lst.count_lineno + 1

        self.lines.insert(insert_at, line)
        self._set_count(lst.count_lineno, lst.declared_count + 1)
        self._reparse()
        return self.lists[kind].entries[at]

    def remove_entry(self, kind: ListKind, index: int) -> None:
        """Delete an entry and decrement the count byte.

        Renumbers nothing: callers that remove a warp must fix up every
        ``warp_to`` in other maps that pointed past it (see wiring/warps.py).
        """
        lst = self.lists[kind]
        entry = lst.entries[index]
        del self.lines[entry.lineno]
        self._set_count(lst.count_lineno, lst.declared_count - 1)
        self._reparse()

    def replace_entry(self, kind: ListKind, index: int, args: list[str]) -> None:
        """Rewrite an entry in place, keeping its macro."""
        lst = self.lists[kind]
        entry = lst.entries[index]
        self.lines[entry.lineno] = format_entry(entry.macro, args)
        self._reparse()

    def fix_count(self, kind: ListKind) -> None:
        """Make the count byte agree with the entry lines actually present.

        Strays count: they are entry lines the count byte was too small to
        reach, so absorbing them is exactly the repair an under-declared list
        needs. An over-declared list shrinks to what's really there.
        """
        lst = self.lists[kind]
        self._set_count(lst.count_lineno, len(lst.entries) + len(lst.strays))
        self._reparse()

    def reparse(self) -> None:
        """Re-read the recorded line numbers from `lines`.

        Every method here does this for itself. It is public for callers that
        splice into ``lines`` *directly* — adding a text block above the header
        shifts every line number below it, and nothing else would notice.
        """
        self._reparse()

    def to_edit(self, root: Path, detail: str) -> Edit:
        """This header's pending changes as an :class:`~.edits.Edit`, so callers
        get dry-run previews and idempotence the same way map wiring does."""
        rel = str(self.path.relative_to(root))
        text = self.to_text()
        changed = text != self.path.read_text()
        return Edit(rel, changed, detail, text if changed else "")

    # -- internals ---------------------------------------------------------- #
    def _set_count(self, lineno: int, n: int) -> None:
        """Rewrite a ``db N`` count, preserving whatever sits around it — the
        leading tab, an inline label (``.Warps: db 6``), a trailing comment."""
        m = _DB_RE.match(self.lines[lineno])
        if not m:                                     # pragma: no cover - parser guarantees
            raise UnparseableHeader(f"{self.path}:{lineno + 1}: not a db line")
        comment = m.group("comment")
        self.lines[lineno] = f"{m.group('prefix')}{n}" + (f" {comment}" if comment else "")

    def _reparse(self) -> None:
        fresh = _parse_lines(self.label, self.path, self.lines, self._eol)
        self.header_lineno = fresh.header_lineno
        self.lists = fresh.lists


# --------------------------------------------------------------------------- #
# formatting                                                                  #
# --------------------------------------------------------------------------- #

def format_entry(macro: str, args: list[str]) -> str:
    """Render an entry line in the repo's dominant style: tab, macro, ``, ``."""
    return f"{_INDENT}{macro} {', '.join(str(a).strip() for a in args)}"


# --------------------------------------------------------------------------- #
# parsing                                                                     #
# --------------------------------------------------------------------------- #

def parse_map(path: Path) -> EventHeader:
    """Parse the event header of a single ``maps/*.asm`` file.

    Raises :class:`UnparseableHeader` if the file has no event header (some map
    asms are pure script includes) or its header doesn't match the four-list
    shape.
    """
    text = path.read_text()
    # split("\n") is exactly invertible by "\n".join — splitlines() is not,
    # and the round-trip contract depends on that.
    return _parse_lines(None, path, text.split("\n"), "\n")


def _parse_lines(label: str | None, path: Path, lines: list[str], eol: str) -> EventHeader:
    header_lineno, found_label = _find_header(lines)
    if header_lineno is None:
        raise UnparseableHeader(f"{path}: no <Label>_MapEventHeader in file")
    label = label or found_label

    i = header_lineno + 1
    lists: dict[ListKind, EventList] = {}
    for kind in LIST_ORDER:
        lst, i = _parse_list(path, lines, i, kind)
        lists[kind] = lst

    return EventHeader(
        label=label, path=path, lines=lines,
        header_lineno=header_lineno, lists=lists, _eol=eol,
    )


def _find_header(lines: list[str]) -> tuple[int | None, str]:
    """The event header's anchor line. Two maps (MoundB2F/B3F) stack a second
    alias label on top of the real one; the *last* of a consecutive run is the
    one carrying the filler and preceding the lists."""
    anchor, label = None, ""
    for i, ln in enumerate(lines):
        m = _HEADER_RE.match(ln)
        if not m:
            continue
        anchor, label = i, m.group(1)
        # keep walking only while the next line is another header label
        if i + 1 < len(lines) and _HEADER_RE.match(lines[i + 1]):
            continue
        break
    return anchor, label


def _parse_list(path: Path, lines: list[str], i: int, kind: ListKind) -> tuple[EventList, int]:
    """Read one counted list starting at line ``i``: skip decoration, take the
    next ``db N``, then take the entry lines under it. Returns the list and the
    index just past it.

    The count byte is a *claim*, not a guarantee — it is read tolerantly. Lines
    are consumed while they are legal entry macros for this list, up to the
    declared count; the list ends early at anything else (EOF, the next list's
    ``db``, a stray label, a commented-out entry that leaves the list short).
    Entry macros found *past* the count are recorded as ``strays`` rather than
    absorbed, so an under-declared count can be reported without guessing which
    list an orphaned line belongs to.
    """
    count_lineno, count = _next_count(path, lines, i, kind)
    legal = LIST_MACROS[kind]

    entries: list[Entry] = []
    j = count_lineno + 1
    while len(entries) < count and j < len(lines):
        entry = _entry_at(lines, j, legal)
        if entry is _SKIP:
            j += 1
            continue
        if entry is None:
            break                      # list ends short of its declared count
        entries.append(entry)
        j += 1

    strays: list[int] = []
    k = j
    while k < len(lines):
        entry = _entry_at(lines, k, legal)
        if entry is _SKIP:
            k += 1
            continue
        if entry is None:
            break                      # next list (or non-entry code) begins
        strays.append(k)
        k += 1

    return EventList(kind=kind, count_lineno=count_lineno, declared_count=count,
                     entries=entries, strays=strays), max(j, k)


_SKIP = object()          # a blank/comment line inside a list — skip, don't end it


def _entry_at(lines: list[str], j: int, legal: tuple[str, ...]) -> Entry | None | object:
    """The entry at line ``j``, ``_SKIP`` for a blank/comment, or None if this
    line ends the list. A ``.Label`` ends it: the next list has begun."""
    line = lines[j]
    s = line.strip()
    if not s or s.startswith(";"):
        return _SKIP
    if s.startswith("."):
        return None
    m = _MACRO_RE.match(line)
    if not m or m.group("macro") not in legal:
        return None
    return Entry(macro=m.group("macro"), args=_split_args(m.group("args")),
                 lineno=j, raw=line)


def _next_count(path: Path, lines: list[str], i: int, kind: ListKind) -> tuple[int, int]:
    """Find the next count byte, skipping blanks, comments and list labels.

    The filler word on the header line (``:: db 0, 0``) is inline and so never
    seen here, but a handful of maps put a two-value ``db`` on its own line —
    a count is always a single value, which is how the two are told apart.
    """
    for j in range(i, len(lines)):
        line = lines[j]
        s = line.strip()
        if not s or s.startswith(";"):
            continue                      # blank or comment — never carries a count
        m = _DB_RE.match(line)
        if not m:
            if s.startswith("."):
                continue                  # a bare list label, count is below it
            raise UnparseableHeader(
                f"{path}:{j + 1}: expected the {kind.value} count (db N), "
                f"got: {line.strip()!r}"
            )
        args = _split_args(m.group("args"))
        if len(args) != 1:
            continue                      # the `db 0, 0` filler word, not a count
        n = _try_int(args[0])
        if n is None:
            raise UnparseableHeader(
                f"{path}:{j + 1}: {kind.value} count is not a literal: {args[0]!r}"
            )
        return j, n
    raise UnparseableHeader(f"{path}: no {kind.value} count found")


def _split_args(rest: str) -> list[str]:
    return [a.strip() for a in rest.split(",")]


def _try_int(s: str) -> int | None:
    s = s.strip()
    try:
        if s.startswith("$"):
            return int(s[1:], 16)
        if s.startswith("%"):
            return int(s[1:], 2)
        return int(s, 10)
    except ValueError:
        return None
