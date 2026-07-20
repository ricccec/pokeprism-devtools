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

from ...shared.constants import ConstSet, read_set
from ...shared.edits import Edit
from ...studio import actions, panels
from ...studio.actions import Action, ActionError, Result
from ...wiring import warpdel
from ...wiring.warpdel import BlindTable, DeadDoor, WarpGrammar, WarpMacro
from ..mount import Refused

#: The four lists, in the order every map file writes them. The key is the
#: word the read adapter's handles carry — ``("bg", 3)`` names the fourth
#: ``bg_event`` — so a handle resolves here without translation.
LIST_MACROS = {"warp": "warp_event", "coord": "coord_event",
               "bg": "bg_event", "object": "object_event"}
LIST_ORDER = tuple(LIST_MACROS)

#: How the family spells a warp reference, for :mod:`...wiring.warpdel`. The
#: survey that produced this record is the reason Phase 5 was a port and not a
#: copy: prism's two macros are three here, and neither tree has prism's
#: `dummy_warp`.
#:
#: * ``warp_event x, y, MAP, n`` — the coordinates turn and the seats move, which
#:   is the whole reason the grammar is data.
#: * ``warpmod n, MAP`` — the one macro the family spells exactly as prism does.
#: * ``elevfloor FLOOR, n, MAP`` — an elevator's floor list. Prism has no such
#:   macro; both family trees use it (14 rows in vanilla, 17 in polished), and
#:   missing it would have left every elevator quietly off by one.
#:
#: The dead door took the longest to find, because the family has no
#: `dummy_warp` and the obvious conclusion — that it therefore cannot spell one
#: — is wrong. Both trees ``DEF GROUP_NONE`` and ``DEF MAP_NONE`` to 0, and
#: ``map_id NONE`` emits ``db 0, 0``, so ``warp_event x, y, NONE, -1`` assembles
#: to the very five bytes prism's ``dummy_warp y, x`` does. It is the same door
#: to nowhere, spelled in the family's own declared constants rather than in a
#: macro prism invented — and, as :class:`~...wiring.warpdel.DeadDoor` records,
#: "nowhere" is a weaker promise than either dialect's comments claim.
WARPS = WarpGrammar(
    macros=(WarpMacro("warp_event", at=3, at_map=2, door=True),
            WarpMacro("warpmod", at=0, at_map=1),
            WarpMacro("elevfloor", at=1, at_map=2)),
    dead_door=DeadDoor("warp_event", keeps=(0, 1), extra=("NONE", "-1")),
)

#: Polished's, which forks the macro set as it forks everything else: it adds
#: `digmod` (Dig's exit, two uses), and it keeps hidden-grotto return warps in
#: `data/` as bare numbers whose map is named nowhere on the line — a table this
#: scan cannot see and will not guess at, so it is declared and warned about.
POLISHED_WARPS = WarpGrammar(
    macros=WARPS.macros + (WarpMacro("digmod", at=0, at_map=1),),
    dead_door=WARPS.dead_door,
    blind=(BlindTable(
        "data/events/hidden_grottoes/grottoes.asm",
        "each row's warp belongs to the map its HIDDENGROTTO_* constant is "
        "named after, and a naming convention is not a reference"),),
)

#: What a family form may offer, by the field vocabulary `studio/actions.py`
#: names. The keys are field *kinds*, not answers: naming one here says this
#: dialect can enumerate that sort of thing, and a kind absent from this map
#: answers `[]`, which the form renders as a plain text box.
#:
#: Both trees keep all six in the same six files — the survey checked rather
#: than assumed, since Phase 5's `elevfloor` was exactly this question answered
#: wrong. The event flags are the one set that is a *suggestion* rather than a
#: bound: see `studio/offers.py` on why holding you to the list would mean the
#: only NPCs you could gate are the gated ones.
CHOICES = {
    actions.SPRITES: ConstSet("constants/sprite_constants.asm", "SPRITE_"),
    actions.MOVEMENTS: ConstSet("constants/map_object_constants.asm",
                                "SPRITEMOVEDATA_"),
    #: `PAL_NPC_*`, and the prefix is the whole finding. Prism's objects wear
    #: `PAL_OW_RED`; both family trees define a `PAL_OW_*` set *and never put
    #: one on an object_event* — all 1,466 vanilla and 2,161 polished object
    #: lines name a `PAL_NPC_*`. Offering the `PAL_OW_` set would have been a
    #: palette field that suggested only constants the maps never use.
    actions.PALETTES: ConstSet("constants/sprite_data_constants.asm", "PAL_NPC_"),
    actions.ITEMS: ConstSet("constants/item_constants.asm"),
    actions.FLAGS: ConstSet("constants/event_flags.asm", "EVENT_"),
    #: The family's signpost kinds. Prism calls these `SIGNPOST_*` and the
    #: studio's field is still named `facings` after them; the family says
    #: `BGEVENT_*` and neither tree has ever heard of the other's spelling.
    actions.FACINGS: ConstSet("constants/script_constants.asm", "BGEVENT_"),
}

#: Polished's, forking in exactly one entry — and that entry is why `ConstSet`
#: carries a `macro` field at all. Vanilla writes `const PAL_NPC_RED`; polished
#: writes `ow_npc_pal_const RED`, one macro that defines both the `PAL_OW_` and
#: the `PAL_NPC_` name and lets rgbasm paste the prefix on, so neither appears
#: in the source. Reading polished with vanilla's record does not fail loudly —
#: it returns **one** palette, `PAL_NPC_DEFAULT`, the only member written out
#: longhand. A near-empty list is indistinguishable from "this field is free
#: text", so the palette box would have quietly stopped suggesting anything on
#: exactly one tree out of three. Measured, not assumed.
POLISHED_CHOICES = {
    **CHOICES,
    actions.PALETTES: ConstSet("constants/sprite_data_constants.asm", "PAL_NPC_",
                               macro="ow_npc_pal_const"),
}

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
        line = format_entry(LIST_MACROS[kind], args)
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

    **Deletion is the write that crosses today**, now including warps. Removing
    an entry is the operation the seam's whole identity story was built for — a
    handle resolved by handing it back, the const list kept in step — and for
    everything but a warp its blast radius is a single file. A warp's is the
    repo, and it crosses through :data:`WARPS`: the rule and the scan live in
    `wiring/warpdel`, this dialect's spelling of them is a record, and the one
    thing the dialect cannot do (spell a door to nowhere) is a refusal that
    names the doors rather than a silence.

    **Editing crosses for all four lists, adding for three of them.** An
    editor rewrites one line in place, which moves nothing and renumbers
    nothing, so it is safe wherever the line already parses; an adder appends
    one, which is safe exactly when the line it appends needs no script block
    written beside it. Trainers and props need one, so they have no adder and
    the tab's Add row says nothing rather than producing a map that will not
    assemble. See `.actions` for the slot orders, which fork between the two
    trees in four columns and swap the movement radius between two of them.

    What is left is a declared hole rather than a capability the session could
    misread: `form()` is None for all three app-level forms — new map is Phase
    7, resize stands on it, rewording is the text project — and `follows` and
    `sprite_hint` are argued absences, not stubs. The protocol is
    `hacks/mount.py`'s docstring.
    """

    def __init__(self, root: Path, anchor: str = "_MapEvents",
                 grammar: WarpGrammar = WARPS,
                 set_of: dict[str, ConstSet] | None = None,
                 forms: tuple[dict, dict] | None = None) -> None:
        self.root = root
        self.anchor = anchor
        #: The fourth fork the mount declares: which dialect's actions these
        #: are, already stamped with its anchor and its `object_event` slot
        #: order. Resolved lazily rather than defaulted in the signature
        #: because `.actions` imports this module — the actions are the write
        #: half of this adapter, so the arrow points that way and not back.
        self._forms = forms
        #: Which warp macros this tree writes — the family's, or polished's
        #: larger set. Declared by the mount beside the anchor, for the same
        #: reason: both are forks the code states rather than sniffs.
        self.grammar = grammar
        #: Where this tree keeps each constant set a form may offer. The third
        #: fork the mount declares, and the third one a survey found rather
        #: than a rule predicted — see :data:`POLISHED_CHOICES`.
        self.set_of = CHOICES if set_of is None else set_of

    # -- what a form may offer ----------------------------------------------- #
    @property
    def _actions(self) -> tuple[dict, dict]:
        from . import actions as fa
        if self._forms is None:
            self._forms = (fa.VANILLA_ADDERS, fa.VANILLA_EDITORS)
        return self._forms

    def adders(self, kind: str) -> tuple:
        """What the tab-foot "Add new…" row opens.

        Three of the four lists are here; trainers and props are not, and the
        absence is measured rather than pending. Their entry line points at a
        `trainer` / `itemball` / `fruittree` / `hiddenitem` block, and writing
        blocks is family scaffolding — the project rewording is, and the one
        Phase 6 said it would not claim. An adder that spliced the line alone
        would produce a map that does not assemble, which is worse than a tab
        whose Add row says nothing.
        """
        return self._actions[0].get(kind, ())

    def form(self, name: str) -> None:
        """None for every app-level form: `newmap` is Phase 7, `resize` stands
        on it, and `reword` is the text project. The view renders each as the
        key not existing, which is the truth."""
        return None

    def choices(self, kind: str, map_consts: tuple[str, ...],
                values: dict[str, str] | None = None) -> list[str]:
        """The constants a family field of this kind will accept.

        An unknown kind is `[]` — free text, not an error — and that is the
        honest answer for most of the vocabulary here rather than a stub. This
        tree has no trainer classes the studio can roster (`PARTIES`,
        `CLASSES`), and its TMs are pasted together by `add_tm` at assembly
        time and appear nowhere in the source (`TMHMS`), which is the same trap
        prism's `studio/offers.py` documents. The map-header enums
        (`TILESETS`, `LANDMARKS`, `MUSIC`) exist in these trees and stay unread
        because nothing family-side asks yet: they belong to the new-map form,
        which is Phase 7.
        """
        if kind == actions.MAPS:
            return list(map_consts)
        if (cs := self.set_of.get(kind)) is None:
            return []
        return list(read_set(self.root, cs))

    def follows(self, action, changed: str,
                values: dict[str, str]) -> dict[str, str]:
        """Nothing follows from anything here, and that is a measurement.

        Prism's one rule fills the sprite and palette a trainer class usually
        wears, and it does that by *counting* every trainer in the repo — see
        `hacks/prism/trainerstats.py`, which exists because no rule was ever
        going to produce `SPRITE_BUENA` for a `SKIER`. The family's forms have
        no class field to hang that off, so there is nothing to suggest, and an
        invented suggestion would be worse than an empty one.
        """
        return {}

    def sprite_hint(self, map_const: str, sprite: str) -> str:
        """No hint, honestly.

        Prism answers this with two facts, and the family can supply neither.
        *Who wears this sprite* is counted off prism's trainer tables. *Whether
        they can walk here* is `maplint`'s VRAM-table measurement, and the
        linter is written against prism — `Hack.ctx` is None for these trees,
        which is the same absence the Diagnostics pane already renders. A hint
        assembled from half the facts would read as authoritative, so the field
        gets no hint line at all rather than a misleading one.
        """
        return ""

    def warm(self) -> None:
        """Read the constant sets off the UI thread, so the first form to open
        does not pay for 2,254 event flags while you look at an empty box."""
        for cs in self.set_of.values():
            read_set(self.root, cs)

    def forget(self) -> None:
        """Something was written: a new flag is a new name the next form must
        offer. `read_set` is an `lru_cache` on a module function, so
        `shared/caches.py` finds it too — this is belt and braces, and the belt
        is the one that gets tested."""
        read_set.cache_clear()

    def editor(self, label: str, const: str, ref, said: list):
        """The form `e` would open on this row, filled in with what is there.

        Keyed by the **list** the entry lives in rather than by `ref.what`.
        The six tables above the seam are a reading of the block each entry
        points at — an `object_event` is an NPC or a fruit tree depending on a
        macro in another block entirely — but what an editor rewrites is a
        line, and a line belongs to exactly one of four lists. So resolving the
        handle *is* choosing the form, and the row's kind never comes into it.

        `said` goes unused: rewording is the text project, and a family text
        block is not a field on any of these forms.
        """
        if ref.what == "map":
            raise Refused(
                "the map's own attributes live in three files this adapter "
                "only reads — editing them is not wired for this dialect yet.")
        if ref.what == "connection":
            raise Refused(
                "editing a connection means rewriting the neighbour's side "
                "too — not wired for this dialect yet.")

        from . import actions as fa
        block = parse_map(self.root / f"maps/{label}.asm", self.anchor)
        kind, index = _resolve(block, label, ref)
        action = self._actions[1][kind]
        return action, fa.prefill(block, kind, index, action.shape), {}

    # -- what a selected row can do ------------------------------------------- #
    def deletion(self, label: str, const: str, ref):
        """The action `d` would run on this row — or the reason there isn't one."""
        from ..mount import Refused
        if ref.what == "map":
            raise Refused("deleting a whole map is not something this does.")
        if ref.what == "connection":
            raise Refused(
                "removing a connection means rewriting the neighbour's side "
                "too — not wired for this dialect yet.")

        block = parse_map(self.root / f"maps/{label}.asm", self.anchor)
        kind, index = _resolve(block, label, ref)
        if ref.what == "warp":
            return RemoveWarp(label, const, self.anchor, self.grammar,
                              index=str(index))

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


def delete_warp(root: Path, label: str, map_const: str, index: int,
                anchor: str = "_MapEvents",
                grammar: WarpGrammar = WARPS) -> warpdel.Deletion:
    """Take warp #(index+1) out of `label`, and fix the whole repo behind it.

    The mirror of prism's :func:`..prism.write.delete_warp` over the family's
    own parser: this half is the dialect's — find the map file, splice the entry
    out of its ``def_warp_events`` list — and :mod:`...wiring.warpdel` does the
    half that is every tree's, from the grammar handed to it. Neither function
    is a copy of the other; the rule they share lives in one place and each
    tree's spelling of it is a record.
    """
    path = root / f"maps/{label}.asm"
    try:
        block = parse_map(path, anchor)
    except (UnparseableEvents, panels.Unreadable) as exc:
        raise warpdel.WarpDelError(
            f"{map_const}'s event block can't be read, so its warps can't be "
            f"counted: {exc}") from exc

    warps = block.lists["warp"].entries
    if not 0 <= index < len(warps):
        raise warpdel.WarpDelError(
            f"{map_const} has {len(warps)} warp{'s' if len(warps) != 1 else ''}, "
            f"so there is no warp #{index + 1} to delete")

    y, x = _shown_coords(warps[index].args)
    block.remove_entry("warp", index)
    return warpdel.delete_warp(root, map_const, index, grammar,
                               own_rel=f"maps/{label}.asm",
                               spliced=block.to_text(),
                               where=f"({y}, {x})" if y else "")


class RemoveWarp(Action):
    """A warp is the one deletion whose blast radius is not one map file.

    Its destination is a *position* in the destination map's warp list, so
    every door in the repo that counted its way past this one has to be pulled
    back a step — and in this dialect three different macros do that counting.
    The preview shows every file that touches, which for a busy map is a dozen;
    that is not the preview being noisy, it is the true cost of the operation.

    Unlike prism's, this one can refuse *after* you have pointed at it: a door
    that led here has nowhere to go in a dialect with no `dummy_warp`, and the
    refusal names the doors so they can be repointed first.
    """
    name = "remove warp"
    title = "Remove a warp"

    def __init__(self, label: str, map_const: str, anchor: str,
                 grammar: WarpGrammar, **values: str) -> None:
        super().__init__(**values)
        self.label = label
        self.map = map_const
        self.anchor = anchor
        self.grammar = grammar

    def describe(self) -> str:
        return f"remove warp #{self.integer('index') + 1} from {self.map}"

    def run(self, root: Path) -> Result:
        try:
            d = delete_warp(root, self.label, self.map, self.integer("index"),
                            self.anchor, self.grammar)
        except warpdel.WarpDelError as e:
            raise ActionError(str(e)) from e
        return Result(d.summary, d.changes, d.warnings)


class Remove(Action):
    """Take one entry out of a map — the family's other write today.

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
