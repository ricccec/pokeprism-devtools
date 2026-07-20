"""Parse + round-trip-safe writer for the family's ``def_*`` event lists.

The write half of the dialect :mod:`.events` reads: four lists in a fixed
order — ``def_warp_events``, ``def_coord_events``, ``def_bg_events``,
``def_object_events`` — plus the ``object_const_def`` block that names the
objects. The prism analogue is `hacks/prism/eventheader`, and the differences
between the two writers are exactly the feasibility ledger's rows #1–#3:

* **The lists self-count.** A ``def_*`` macro initialises a counter and every
  entry macro bumps it at assembly, so there is no ``db N`` byte to keep in
  step and no way for the file to disagree with itself about how many entries
  it has. Where prism's writer spends its care on the count byte
  (`_set_count`, `fix_count`, the ``declared_count`` claim), this one simply
  has no counts — an entry line added is an entry counted.

* **Identity is named.** ``object_const_def`` numbers the objects in order,
  and scripts address them by those names (``disappear AZALEAGYM_BUGSY``).
  The consts are positional underneath — the Nth ``const`` names the Nth
  ``object_event`` — so any edit that changes object *positions* must move
  the const list in step, and this writer does: removing object N removes
  its ``const``, which is precisely what keeps every name after it pointing
  at the object it always pointed at. (A list may name only its leading
  objects — polished does this — and then the unnamed tail can grow and
  shrink without the consts noticing.)

* **The block's end of the file is a parameter.** Vanilla ends a map file
  with the event block; polished opens with it, scripts below. The splice
  never cares — a mutation touches recorded line numbers and nothing else —
  but the *anchor* the parser demands is the family fork's one structural
  difference, so it is the same ``anchor`` argument :func:`.events.parse`
  takes.

Round-trip contract
-------------------
Same as prism's, stated the same way: the whole file is retained verbatim as
:attr:`EventBlock.lines`; mutations splice single lines in and out and touch
nothing else. Serializing an unmodified block is byte-identical by
construction, and the hand-written code outside the spliced lines — above the
tail block in vanilla, *below* the head block in polished — is never touched.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ...shared.edits import Edit
from ...studio import panels
from ...studio.actions import Action, ActionError, Result
from ..mount import Refused

#: The four lists, in the order every map file writes them. The key is the
#: word the read adapter's handles carry — ``("bg", 3)`` names the fourth
#: ``bg_event`` — so a handle resolves here without translation.
LIST_MACROS = {"warp": "warp_event", "coord": "coord_event",
               "bg": "bg_event", "object": "object_event"}
LIST_ORDER = tuple(LIST_MACROS)

_DEF_RE = re.compile(r"^\s*def_(warp|coord|bg|object)_events\b")
_MACRO_RE = re.compile(r"^\s*(?P<macro>\w+)\s+(?P<args>.*?)\s*(?:;.*)?$")
_CONST_DEF_RE = re.compile(r"^\s*object_const_def\b")
_CONST_RE = re.compile(r"^\s*const\s+(\w+)")


class UnparseableEvents(RuntimeError):
    """The file doesn't carry the shape this dialect promises — no anchor, a
    missing ``def_*`` line, an entry where none is legal. Callers treat the
    map as unmanaged rather than guess."""


@dataclass
class Entry:
    macro: str
    args: list[str]
    lineno: int
    raw: str


@dataclass
class EventList:
    kind: str
    def_lineno: int              # the `def_*_events` line
    entries: list[Entry]


@dataclass
class EventBlock:
    """One map file, held whole, with the event lists and the const block
    located for splicing. The mirror of prism's ``EventHeader``, minus the
    counts it doesn't need."""

    label: str
    path: Path
    lines: list[str]                       # the whole file, verbatim
    anchor: str                            # `_MapEvents` | `_MapScriptHeader`
    anchor_lineno: int                     # the `<Label><anchor>:` line
    lists: dict[str, EventList]
    #: `object_const_def` names in order, with the line each sits on. May name
    #: only the leading objects; may be absent entirely (const_lineno None).
    names: list[tuple[str, int]]
    const_lineno: int | None
    _eol: str = "\n"

    # -- read --------------------------------------------------------------- #
    def entry_at(self, kind: str, index: int) -> Entry | None:
        entries = self.lists[kind].entries
        return entries[index] if 0 <= index < len(entries) else None

    def name_of(self, index: int) -> str:
        """The const that names object ``index``, or "" for the unnamed tail."""
        return self.names[index][0] if index < len(self.names) else ""

    def index_of(self, name: str) -> int | None:
        """Which object a const names — its position, which is the whole point
        of the const list. None for a name the block doesn't declare."""
        for i, (n, _) in enumerate(self.names):
            if n == name:
                return i
        return None

    def to_text(self) -> str:
        """The file's full text. Byte-identical to the source if nothing was
        mutated — the lines are held verbatim and only spliced on write."""
        return self._eol.join(self.lines)

    # -- write -------------------------------------------------------------- #
    def add_entry(self, kind: str, args: list[str], *,
                  name: str | None = None) -> Entry:
        """Append an entry. No count to bump: the ``def_*`` macros self-count.

        ``name`` adds a matching ``const`` for an object — and is refused
        unless the const list names *every* object, because the consts are
        positional: appending a name to a partially-named list would hand it
        the wrong ordinal, silently, for every script that uses it.
        """
        lst = self.lists[kind]
        if name is not None:
            if kind != "object":
                raise UnparseableEvents(
                    f"only object_events are named; a {kind} entry takes no const")
            if len(self.names) != len(lst.entries):
                raise UnparseableEvents(
                    f"{self.path.name} names {len(self.names)} of "
                    f"{len(lst.entries)} objects — the consts are positional, so "
                    "appending a named object to a partially-named list would "
                    "give it the wrong ordinal. Add it unnamed, or name the rest.")

        insert_at = (lst.entries[-1].lineno if lst.entries else lst.def_lineno) + 1
        self.lines.insert(insert_at, format_entry(LIST_MACROS[kind], args))
        if name is not None:
            const_at = (self.names[-1][1] if self.names else self.const_lineno)
            if const_at is None:
                raise UnparseableEvents(
                    f"{self.path.name} has no object_const_def block to name "
                    f"{name} in.")
            # The const block may sit above the events (vanilla: top of file)
            # or below them (polished: after the lists) — insert *after* the
            # entry so a lineno past the entry's is still right.
            if const_at >= insert_at:
                const_at += 1
            self.lines.insert(const_at + 1, f"\tconst {name}")
        self._reparse()
        return self.lists[kind].entries[-1]

    def remove_entry(self, kind: str, index: int) -> str:
        """Delete an entry — and, for a named object, its ``const``, in the
        same splice. That is the named-identity contract: the Nth const names
        the Nth object, so removing both keeps every later name pointing at
        the object it always pointed at. Returns the removed const name, or
        "" where there wasn't one.

        Renumbers nothing else, exactly like prism's writer: a caller that
        removes a *warp* still owns the repo-wide ``warp_event`` targets that
        counted their way past it.
        """
        entry = self.lists[kind].entries[index]
        doomed = [entry.lineno]
        name = ""
        if kind == "object" and index < len(self.names):
            name, const_lineno = self.names[index]
            doomed.append(const_lineno)
        # Highest first, so the second deletion's lineno hasn't shifted — the
        # const block sits above the events in vanilla and below in polished,
        # and this is the one line that has to be right about both.
        for lineno in sorted(doomed, reverse=True):
            del self.lines[lineno]
        self._reparse()
        return name

    def replace_entry(self, kind: str, index: int, args: list[str]) -> None:
        """Rewrite an entry in place, keeping its comment. One line becomes
        another line, so nothing moves and nothing renumbers — what makes
        editing safe where deleting is not."""
        entry = self.lists[kind].entries[index]
        m = _MACRO_RE.match(entry.raw)
        comment = entry.raw[m.end():] if m and entry.raw[m.end():].strip() else ""
        line = format_entry(LIST_MACROS[kind], args)
        self.lines[entry.lineno] = f"{line} {comment.strip()}" if comment else line
        self._reparse()

    def to_edit(self, root: Path, detail: str) -> Edit:
        """This block's pending changes as an :class:`~.edits.Edit`, so callers
        get dry-run previews and idempotence the same way prism's writes do."""
        rel = str(self.path.relative_to(root))
        text = self.to_text()
        base = self.path.read_text()
        changed = text != base
        return Edit(rel, changed, detail, text if changed else "", base=base)

    # -- internals ---------------------------------------------------------- #
    def _reparse(self) -> None:
        fresh = _parse_lines(self.label, self.path, self.lines,
                             self.anchor, self._eol)
        self.anchor_lineno = fresh.anchor_lineno
        self.lists = fresh.lists
        self.names = fresh.names
        self.const_lineno = fresh.const_lineno


# --------------------------------------------------------------------------- #
# formatting                                                                  #
# --------------------------------------------------------------------------- #

def format_entry(macro: str, args: list[str]) -> str:
    """One entry line, the way the family writes them: a tab, the macro, and
    the coordinate args right-aligned to two — `warp_event  4, 15, …` — so a
    written line sorts under its hand-written neighbours."""
    def pad(a: str, i: int) -> str:
        a = a.strip()
        return f"{a:>2}" if i < 2 and a.isdigit() else a
    return "\t" + macro + " " + ", ".join(pad(a, i) for i, a in enumerate(args))


# --------------------------------------------------------------------------- #
# parsing                                                                     #
# --------------------------------------------------------------------------- #

def parse_map(path: Path, anchor: str = "_MapEvents") -> EventBlock:
    """Parse the event block of a single ``maps/*.asm`` file. `anchor` is the
    family's one structural fork — vanilla's ``_MapEvents`` tail, polished's
    ``_MapScriptHeader`` head — same parameter, same reason as
    :func:`.events.parse`."""
    try:
        return parse_text(path.read_text(encoding="utf-8"), path, anchor)
    except FileNotFoundError as exc:
        raise panels.Unreadable(f"{path} does not exist.") from exc


def parse_text(text: str, path: Path, anchor: str = "_MapEvents") -> EventBlock:
    """The same, over text already in hand rather than text on disk.

    split("\\n") is exactly invertible by "\\n".join — splitlines() is not,
    and the round-trip contract depends on that.
    """
    return _parse_lines(None, path, text.split("\n"), anchor, "\n")


def _parse_lines(label: str | None, path: Path, lines: list[str],
                 anchor: str, eol: str) -> EventBlock:
    anchor_lineno = None
    found_label = ""
    for i, ln in enumerate(lines):
        if m := re.match(rf"^(\w+){anchor}::?", ln):
            anchor_lineno, found_label = i, m.group(1)
            break
    if anchor_lineno is None:
        raise UnparseableEvents(
            f"{path}: no <Label>{anchor} block — the anchor every map file in "
            "this dialect carries.")

    lists: dict[str, EventList] = {}
    for i, ln in enumerate(lines):
        m = _DEF_RE.match(ln)
        if not m:
            continue
        kind = m.group(1)
        if kind in lists:
            raise UnparseableEvents(
                f"{path}:{i + 1}: a second def_{kind}_events — one list each "
                "is the shape this dialect promises.")
        lists[kind] = EventList(kind, i, _entries_after(lines, i, kind))
    missing = [k for k in LIST_ORDER if k not in lists]
    if missing:
        raise UnparseableEvents(
            f"{path}: no def_{missing[0]}_events line — the four lists are "
            "not optional in this dialect, only their entries are.")

    names: list[tuple[str, int]] = []
    const_lineno = None
    in_consts = False
    for i, ln in enumerate(lines):
        if _CONST_DEF_RE.match(ln):
            const_lineno, in_consts = i, True
            continue
        if in_consts:
            if m := _CONST_RE.match(ln):
                names.append((m.group(1), i))
            elif ln.split(";")[0].strip():
                in_consts = False

    return EventBlock(label=label or found_label, path=path, lines=lines,
                      anchor=anchor, anchor_lineno=anchor_lineno, lists=lists,
                      names=names, const_lineno=const_lineno, _eol=eol)


def _entries_after(lines: list[str], def_lineno: int, kind: str) -> list[Entry]:
    """The entry lines under one ``def_*`` line: this list's macro until
    anything else. No count decides where the list ends — the lines do, which
    in this dialect is also exactly what the assembler counts."""
    legal = LIST_MACROS[kind]
    entries: list[Entry] = []
    for j in range(def_lineno + 1, len(lines)):
        line = lines[j]
        s = line.strip()
        if not s or s.startswith(";"):
            continue
        m = _MACRO_RE.match(line)
        if not m or m.group("macro") != legal:
            break
        entries.append(Entry(macro=legal,
                             args=[a.strip() for a in m.group("args").split(",")],
                             lineno=j, raw=line))
    return entries


# --------------------------------------------------------------------------- #
# the write adapter                                                           #
# --------------------------------------------------------------------------- #

class Writer:
    """The family's write adapter — what `hacks.mount` hands `Session` as
    ``Hack.writes`` for a vanilla or polished tree. Polished mounts this very
    class with its head anchor, the same way its read adapter imports
    vanilla's parsers: the fork relation is real, so the code states it.

    **Deletion is the write that crosses today.** It is the operation the
    seam's whole identity story was built for — a handle resolved by handing
    it back, the const list kept in step — and the one whose blast radius is
    a single file. Everything else answers with honest absence: no adders,
    no forms, no choices, and an `editor` that refuses with the reason. Each
    of those is a declared hole in this object, not a capability the session
    could ever misread — the protocol is `hacks/mount.py`'s docstring.
    """

    def __init__(self, root: Path, anchor: str = "_MapEvents") -> None:
        self.root = root
        self.anchor = anchor

    # -- what a form may offer: nothing, honestly ---------------------------- #
    def adders(self, kind: str) -> tuple:
        return ()

    def form(self, name: str) -> None:
        return None

    def choices(self, kind: str, map_consts: tuple[str, ...],
                values: dict[str, str] | None = None) -> list[str]:
        return []

    def follows(self, action, changed: str,
                values: dict[str, str]) -> dict[str, str]:
        return {}

    def sprite_hint(self, map_const: str, sprite: str) -> str:
        return ""

    def warm(self) -> None:
        pass

    def forget(self) -> None:
        pass

    def editor(self, label: str, const: str, ref, said: list):
        raise Refused(
            f"editing a {ref.what} is not wired for this dialect yet — "
            "deleting one is the write that crosses today.")

    # -- what a selected row can do ------------------------------------------- #
    def deletion(self, label: str, const: str, ref):
        """The action `d` would run on this row — or the reason there isn't one.

        A warp is refused for the same reason prism's needs `wiring/warpdel`:
        `warp_event x, y, MAP, N` names the destination's warp *by position*,
        so removing one pulls every door in the repo that counted past it off
        by a step. Saying so beats doing the easy half of it.
        """
        from ..mount import Refused
        if ref.what == "map":
            raise Refused("deleting a whole map is not something this does.")
        if ref.what == "connection":
            raise Refused(
                "removing a connection means rewriting the neighbour's side "
                "too — not wired for this dialect yet.")
        if ref.what == "warp":
            raise Refused(
                "removing a warp renumbers this map's warp list, and every "
                "warp_event in the repo that names a warp here by position "
                "would count past the hole — that bookkeeping is not wired "
                "for this dialect yet.")

        block = parse_map(self.root / f"maps/{label}.asm", self.anchor)
        kind, index = _resolve(block, label, ref)
        entry = block.lists[kind].entries[index]
        y, x = _shown_coords(entry.args)
        return Remove(label, self.anchor,
                      what=ref.what, kind=kind, index=str(index),
                      name=ref.handle if isinstance(ref.handle, str) else "",
                      y=y, x=x)


def _resolve(block: EventBlock, label: str, ref) -> tuple[str, int]:
    """The (list, position) a handle names, freshly resolved. A named object's
    handle is its const — resolution *is* the name lookup, which is what makes
    it survive the list reordering underneath it — and a stale handle of
    either shape refuses with the reason rather than pointing at whatever is
    standing in its place now."""
    handle = ref.handle
    if isinstance(handle, str):
        index = block.index_of(handle)
        if index is None:
            raise Refused(
                f"{label} no longer declares {handle} — the map changed under "
                "the table. Select it again.")
        return "object", index
    kind, index = handle
    if block.entry_at(kind, index) is None:
        raise Refused(
            f"{label} no longer has a {ref.what} at {handle} — the map "
            "changed under the table. Select it again.")
    return kind, index


def _shown_coords(args: list[str]) -> tuple[str, str]:
    """The (y, x) to *say* on the confirm screen — the macro writes (x, y),
    the turn the read adapter makes at the seam, made here for the same
    sentence. "" where the source wrote an expression."""
    x = args[0] if args and args[0].isdigit() else ""
    y = args[1] if len(args) > 1 and args[1].isdigit() else ""
    return y, x


class Remove(Action):
    """Take one entry out of a map — the family's whole write vocabulary today.

    `name`/`kind`+`index` say **which** entry, and the rest only says what to
    call it on the confirm screen. A named object is found by its const at
    run time, not by the position it had when you pointed at it: the name is
    the identity the dialect itself uses, so it is the identity this trusts.

    The script block the entry pointed at is left alone, and the notes say
    so: with no linter on this dialect, an orphaned block is yours to notice.
    """
    name = "remove"
    title = "Remove an entry"

    def __init__(self, label: str, anchor: str, **values: str) -> None:
        super().__init__(**values)
        self.label = label
        self.anchor = anchor

    def describe(self) -> str:
        what = self.text("name") or (
            f"{self.text('what')} at ({self.text('y')}, {self.text('x')})"
            if self.text("y") else f"{self.text('what')} #{self.integer('index') + 1}")
        return f"remove {what} from {self.label}"

    def run(self, root: Path) -> Result:
        block = parse_map(root / f"maps/{self.label}.asm", self.anchor)
        if name := self.text("name"):
            index = block.index_of(name)
            if index is None:
                raise ActionError(
                    f"{self.label} no longer declares {name} — nothing was removed.")
            kind = "object"
        else:
            kind, index = self.text("kind"), self.integer("index")
            if block.entry_at(kind, index) is None:
                raise ActionError(
                    f"{self.label} no longer has a {self.text('what')} there — "
                    "nothing was removed.")
        entry = block.lists[kind].entries[index]
        pointer = next((a for a in entry.args if a and a[0].isupper()
                        and not a.isupper()), "")
        removed = block.remove_entry(kind, index)
        notes = []
        if removed:
            notes.append(f"removed const {removed} with it — scripts that "
                         f"named it no longer assemble until they let go")
        if pointer:
            notes.append(f"{pointer} and its text stay in the file — "
                         "no linter reads this dialect, so an orphan is "
                         "yours to notice")
        return Result(self.describe(), [block.to_edit(root, self.describe())], notes)
