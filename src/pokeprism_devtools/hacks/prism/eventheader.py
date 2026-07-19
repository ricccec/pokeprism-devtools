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

What an entry *is* — the four lists, the argument order of a `person_event`, the
number a `$hex` denotes — lives in :mod:`.eventmodel`, and is re-exported here so
that callers never have to care that the split exists.

Round-trip contract
-------------------
The whole file is retained verbatim as :attr:`EventHeader.lines`; mutations
splice regenerated lines into the recorded spans and nothing else. Serializing
an unmodified header is therefore byte-identical by construction, and code
above the header label — hand-written scripts and text — is never touched.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ...shared.edits import Edit
# What an entry *means* is :mod:`.eventmodel`; this module is about the file it
# lives in. Re-exported, because every caller wants both and the split is ours,
# not theirs.
from .eventmodel import (LIST_MACROS, LIST_ORDER, PROPS, Entry, EventList,
                         Handle, ListKind, Prop, UnparseableHeader, as_int,
                         format_entry, markers, _INDENT, _MACRO_RE, _split_args)

__all__ = ["LIST_MACROS", "LIST_ORDER", "PROPS", "Entry", "EventHeader",
           "EventList", "Handle", "ListKind", "Prop", "UnparseableHeader",
           "as_int", "format_entry", "markers", "parse_map", "parse_text"]

#: Finding the block in a file, which is this module's whole job. The regex that
#: reads *one line of it* is `eventmodel._MACRO_RE` — a different question.
_HEADER_RE = re.compile(r"^(\w+)_MapEventHeader::?(.*)$")
_DB_RE = re.compile(r"^(?P<prefix>.*?\bdb\s+)(?P<args>.+?)\s*(?P<comment>;.*)?$")


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

    def entry_at(self, handle: Handle) -> Entry | None:
        """The entry a :class:`~.eventmodel.Handle` names, or None if the map no
        longer has one there. Resolution lives here rather than with the caller
        because only the side that minted the handle knows what kind of name it
        holds — the port passes it back and asks."""
        entries = self.lists[handle.kind].entries
        return entries[handle.index] if 0 <= handle.index < len(entries) else None

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
        self._set_count(lst.count_lineno, len(lst.entries) + 1)
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
        self._set_count(lst.count_lineno, len(lst.entries) - 1)
        self._reparse()

    def replace_entry(self, kind: ListKind, index: int, args: list[str], *,
                      macro: str | None = None) -> None:
        """Rewrite an entry in place, keeping its macro, and its comment.

        Renumbers nothing and moves nothing — one line becomes another line — so a
        ``warp_to`` elsewhere in the repo that counts its way to this entry still
        counts right. That is what makes editing safe where deleting is not.

        `macro` is for the one case where an entry's *shape* changes with its
        contents: a ``dummy_warp`` is a door to nowhere, and giving it a
        destination makes it a ``warp_def``. The comment is kept because it is
        about the thing, not about the arguments it had when somebody wrote it.
        """
        lst = self.lists[kind]
        entry = lst.entries[index]
        chosen = macro or entry.macro
        if chosen not in LIST_MACROS[kind]:
            raise UnparseableHeader(f"{chosen} is not a {kind.value} macro — those "
                                    f"are {', '.join(LIST_MACROS[kind])}")
        m = _MACRO_RE.match(entry.raw)
        comment = m.group("comment") if m else None
        line = format_entry(chosen, args)
        self.lines[entry.lineno] = f"{line} {comment}" if comment else line
        self._reparse()

    def fix_count(self, kind: ListKind) -> None:
        """Make the count byte agree with the entry lines actually present."""
        lst = self.lists[kind]
        self._set_count(lst.count_lineno, len(lst.entries))
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
        base = self.path.read_text()
        changed = text != base
        return Edit(rel, changed, detail, text if changed else "", base=base)

    # -- internals ---------------------------------------------------------- #
    def _set_count(self, lineno: int, n: int) -> None:
        """Rewrite a ``db N`` count, preserving whatever sits around it — the
        leading tab, an inline label (``.Warps: db 6``), a trailing comment.

        Every caller passes the number of entries that will actually be in the
        list, never ``declared_count ± 1``. On a healthy list those are the same
        number. On a list whose count was already wrong they are not, and writing
        ``declared_count + 1`` would leave the object we were just asked to add
        sitting past the count byte, unspawnable, for a reason that has nothing to
        do with what was asked. So a list we rewrite comes back counted correctly:
        the diff shows it, and it is the only count that is true.
        """
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


# --------------------------------------------------------------------------- #
# parsing                                                                     #
# --------------------------------------------------------------------------- #

def parse_map(path: Path) -> EventHeader:
    """Parse the event header of a single ``maps/*.asm`` file.

    Raises :class:`UnparseableHeader` if the file has no event header (some map
    asms are pure script includes) or its header doesn't match the four-list
    shape.
    """
    return parse_text(path.read_text(), path)


def parse_text(text: str, path: Path) -> EventHeader:
    """The same, over text already in hand rather than text on disk — for a caller
    partway through changing the file. Rewording what an object says grows the
    block above the event header, and every line number below it slides, so the
    header must be read from what the file is *becoming*. See `wiring/objedit.py`.
    """
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

    **The count byte does not decide where the list ends — the lines do.** Entry
    macros are consumed until something that is not one (EOF, the next list's
    ``db``, a label, ordinary code), and the count is recorded beside them as the
    claim it is. Reading only the first N would be believing the byte over the
    file, and the byte is exactly the thing that is wrong when these two disagree
    — see :class:`~.eventmodel.EventList`.

    Nothing is guessed about which list an over-hanging line belongs to: it is
    only taken if its macro is legal *here*, and a `signpost` under the BG count
    can be nothing else.
    """
    count_lineno, count = _next_count(path, lines, i, kind)
    legal = LIST_MACROS[kind]

    entries: list[Entry] = []
    j = count_lineno + 1
    while j < len(lines):
        entry = _entry_at(lines, j, legal)
        if entry is _SKIP:
            j += 1                     # a blank or a comment inside the list
            continue
        if entry is None:
            break                      # this line is not ours; the list is over
        entries.append(entry)
        j += 1

    return EventList(kind=kind, count_lineno=count_lineno, declared_count=count,
                     entries=entries), j


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
        n = as_int(args[0])
        if n is None:
            raise UnparseableHeader(
                f"{path}:{j + 1}: {kind.value} count is not a literal: {args[0]!r}"
            )
        return j, n
    raise UnparseableHeader(f"{path}: no {kind.value} count found")
