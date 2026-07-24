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

Nothing here knows the studio exists. What the seam is allowed to ask of a
block — which entries may be added, edited, deleted, and what each refusal
says — is :mod:`.write`, and the split is prism's own between `eventheader`
and `write`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ...shared.edits import Edit
from ...studio import panels

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
        editing safe where deleting is not.

        The comment is taken by splitting on the semicolon rather than by
        asking :data:`_MACRO_RE` where the arguments stopped, and the
        difference is not stylistic: that pattern's trailing `(?:;.*)?`
        *consumes* the comment, so `m.end()` is the end of the line and the
        slice it used to take was always empty. Every comment on every edited
        entry was being dropped — including the `; hole` that is the only thing
        distinguishing a Blackthorn Gym floor hole from a door, and the
        `; inaccessible, left over from G/S` on three Burned Tower warps.
        Twenty lines in vanilla and eighty-three in polished, found by
        round-tripping every real entry rather than by reading this method.
        """
        entry = self.lists[kind].entries[index]
        _, semi, comment = entry.raw.partition(";")
        # `entry.macro`, not the list's canonical macro: a polished object list
        # holds convenience macros (`itemball_event`, `smashrock_event`) that
        # are object entries but are not spelled `object_event`. Rewriting one —
        # a resize shifting its coordinates, say — must re-emit *that* macro, not
        # slide its few args into a malformed twelve-column `object_event`. For a
        # plain entry `entry.macro` is the canonical macro, so nothing else moves.
        line = format_entry(entry.macro, args)
        self.lines[entry.lineno] = f"{line} ;{comment}" if semi else line
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
    """The entry lines under one ``def_*`` line, until the block ends. No count
    decides where the list ends — the lines do, which in this dialect is also
    exactly what the assembler counts: every entry macro in a ``def_*`` block
    bumps that block's self-count, so every entry macro is one entry.

    For the object list that means the *convenience macros* count too. Polished's
    object block interleaves ``object_event`` with shorthands that each assemble
    to exactly one — ``itemball_event``, ``smashrock_event``, ``pokemon_event``
    and kin — and every one is an object the ROM has and the object consts number
    past. An earlier writer stopped at the first shorthand (four objects where
    the reader saw seven, on 89 of 607 maps); its successor *skipped* them, which
    matched a reader that dropped them too. Now the reader expands them
    (:func:`..events.parse`, `..polished.shorthand`), so this enumeration keeps
    step by counting each shorthand as the object it is — held under its own
    macro, because :meth:`EventBlock.replace_entry` must re-emit it as written,
    and refused by the object editor's slot-count guard rather than rewritten
    into a twelve-column line. Vanilla writes no shorthand, so its object block
    is unchanged; the other three lists have no shorthand form, so a non-matching
    macro there still ends them.

    The block ends at the blank line every ``def_*`` list closes with, or at a
    label or ``object_const_def`` (neither of which matches a macro with
    arguments).
    """
    legal = LIST_MACROS[kind]
    entries: list[Entry] = []
    for j in range(def_lineno + 1, len(lines)):
        line = lines[j]
        s = line.strip()
        if not s:
            break                        # the blank line that closes the list
        if s.startswith(";"):
            continue                     # a comment, still inside the block
        m = _MACRO_RE.match(line)
        if not m:
            break                        # a label or bare directive ends it
        macro = m.group("macro")
        if macro != legal and kind != "object":
            continue                     # only the object list has shorthands
        entries.append(Entry(macro=macro,
                             args=[a.strip() for a in m.group("args").split(",")],
                             lineno=j, raw=line))
    return entries
