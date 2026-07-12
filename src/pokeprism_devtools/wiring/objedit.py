"""Changing something that is already in the map.

The other wiring modules add and remove. This one leaves a thing where it is and
changes what it says about itself — which sounds like the easiest of the three
and is the one with the sharpest edges, because *everything it does not touch has
to come back exactly as it was.*

Three rules hold the whole module up.

**Only the arguments the form owns are rewritten.** An entry is a fixed argument
vector — a `person_event` is thirteen arguments, of which an NPC's form knows
six — and the other seven are copied back verbatim out of :attr:`Entry.args`,
which keeps the *source text* of each one. So `8 + PAL_OW_BLUE` survives, the
radii and the hour and the persontype are never retyped, and an edit that changed
nothing writes nothing. See :func:`spliced`, which is where that rule lives.

**One file, one edit.** An object and the words it says are in the same
`maps/*.asm`, and an :class:`~..shared.edits.Edit` carries the *whole* file — so
rewriting the line and rewording the text as two edits means the second silently
overwrites the first (`shared/edits.py:13`). :class:`MapEdit` is one buffer that
both are spliced into, and one Edit comes out the end.

**The words come first.** A reword can change the line count, and every line
below it — including the object's own — then slides. So the text is spliced
first and the event header is re-read from the buffer as it now stands, rather
than from line numbers captured before the file moved under them.
"""

from __future__ import annotations

import re

from dataclasses import dataclass, field
from pathlib import Path

from ..shared import (consts, dialogue, eventheader as eh, mapsource, spritesets,
                      trainercite, trainerparty)
from ..shared.edits import Edit
from .scaffold import INDENT, Object, ScaffoldError, allocate_flag, require

#: Where a `person_event`'s arguments live. The flag is deliberately absent: it is
#: the *last* argument in every one of the macro's tail shapes, which is what makes
#: it findable without knowing which shape you are looking at — so it is `-1`, and
#: :func:`spliced` indexes from the end for it.
SPRITE, Y, X, MOVEMENT, PALETTE, PERSONTYPE, PARAM, POINTER = 0, 1, 2, 3, 8, 9, 10, 11
FLAG = -1

#: Where a `warp_def`'s live: y, x, the 1-based index into the destination's warp
#: list, and the destination.
W_Y, W_X, W_TO, W_MAP = 0, 1, 2, 3

#: A `signpost`: y, x, the function, the pointer.
S_Y, S_X, S_FACING, S_POINTER = 0, 1, 2, 3

#: An `xy_trigger`: the scene it belongs to, then y, x, then the script. Only the
#: coordinates are the form's business — see :func:`edit_trigger`.
T_Y, T_X = 1, 2

#: The engine reads "no flag here" as -1, and a fruit tree's is always that.
ALWAYS = "-1"

#: The palette argument is not just a palette. `8 + PAL_OW_BLUE` draws the body
#: *behind* the background layer — and so does `PAL_OW_PLAYER + 8`, which is the
#: same thing written the other way round, and a few objects carry a bare number
#: with no palette name in it at all. The form asks about the colour and has never
#: asked about any of the rest, so the rest is carried across untouched: find the
#: name, swap the name, leave the arithmetic where it was. See :func:`_palette`.
_PAL_RE = re.compile(r"\bPAL_OW_\w+")

_TRAINER_RE = re.compile(
    r"^(?P<head>\s*trainer\s+)(?P<args>.*?)(?P<comment>\s*;.*)?$")
_LABEL_RE = re.compile(r"^(\w+):")


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
    a, b = eh.as_int(old), eh.as_int(new)
    return a is not None and a == b


def spliced(entry: eh.Entry, changed: dict[int, object]) -> list[str]:
    """The entry's arguments with only these replaced, the rest verbatim.

    The rule the whole module rests on, and it is stronger than it looks: an
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


def _palette(arg: str, palette: str) -> str:
    """A palette argument with a new colour in it, and everything else where it
    was — the `8 +`, the `+ 8`, the spacing."""
    if palette == palette_of(arg):
        return arg
    m = _PAL_RE.search(arg)
    return f"{arg[:m.start()]}{palette}{arg[m.end():]}" if m else palette


def palette_of(arg: str) -> str:
    """The palette name out of an argument that may be arithmetic. What the form
    is shown, and what it hands back. An argument with no name in it — a bare `0` —
    is its own answer, and the form will show it and write it straight back."""
    m = _PAL_RE.search(arg)
    return m.group(0) if m else arg.strip()


class MapEdit:
    """One map's asm, held open while several changes are spliced into it.

    The sibling of `scaffold.MapCtx`, which does the same job for a map being
    added to. This one never grows the file by a block — it rewrites lines that
    are already there, and reflows the text under a label without moving the
    label, because a script jumps to it.
    """

    def __init__(self, root: Path, map_const: str) -> None:
        label = {c: l for l, c in mapsource.header_pairs(root)}.get(map_const)
        if label is None:
            raise EditError(f"{map_const} has no map_header_2 — wire the map first")
        path = root / "maps" / f"{label}.asm"
        if not path.exists():
            raise EditError(f"{map_const} has no script file at maps/{label}.asm")

        self.root = root
        self.map = map_const
        self.label = label
        self.path = path
        self._original = path.read_text()
        self.lines = self._original.split("\n")
        #: Edits to files other than this map — the flag table, so far.
        self.extra: list[Edit] = []
        self.notes: list[str] = []

    # -- reading -------------------------------------------------------------- #
    @property
    def header(self) -> eh.EventHeader:
        """The event header of the file *as it now stands*.

        Parsed afresh every time, deliberately. Reword an object's text and every
        line below it moves; a header held from before that would splice the new
        entry into whatever line happens to be sitting at the old number, which is
        a corruption that assembles.
        """
        try:
            return eh.parse_text("\n".join(self.lines), self.path)
        except eh.UnparseableHeader as exc:
            raise EditError(str(exc)) from exc

    def entry(self, kind: eh.ListKind, index: int) -> eh.Entry:
        entries = self.header.list_of(kind).entries
        if not 0 <= index < len(entries):
            raise EditError(
                f"{self.label} has no {kind.value} entry at position {index} — "
                f"the map changed under the table. Select it again.")
        return entries[index]

    # -- writing --------------------------------------------------------------- #
    def replace_entry(self, kind: eh.ListKind, index: int, args: list[str], *,
                      macro: str | None = None) -> None:
        header = self.header
        entry = header.list_of(kind).entries[index]
        if args == entry.args and macro in (None, entry.macro):
            return          # nothing moved: leave the line exactly as it is
        try:
            header.replace_entry(kind, index, args, macro=macro)
        except eh.UnparseableHeader as exc:
            raise EditError(str(exc)) from exc
        self.lines = header.lines

    def body(self, obj: Object, entry: eh.Entry) -> None:
        """Check the constants this body will emit — but only the ones it is
        actually *changing*.

        Not `Object.check`, which checks all three every time. Some objects in this
        repo carry a movement or a palette written as a raw number rather than a
        name — SilphCo's people all move by `$7` — and `Object.check` is quite
        right to refuse to *write* one of those. It must not, however, refuse to
        leave one alone, or nudging a Silph employee one tile east becomes
        impossible on the grounds that somebody else wrote his movement in hex.

        **You are not required to fix what you did not touch.** That is the same
        rule :func:`spliced` enforces on the bytes, enforced here on the checks.
        """
        if not same(entry.args[SPRITE], obj.sprite):
            require(self.root, "sprite", obj.sprite,
                    frozenset(spritesets.sprite_ids(self.root)))
        if not same(entry.args[MOVEMENT], obj.movement):
            require(self.root, "movement", obj.movement,
                    frozenset(spritesets.movedata_ids(self.root)))
        if obj.palette != palette_of(entry.args[PALETTE]):
            require(self.root, "palette", obj.palette,
                    consts.with_prefix(self.root, consts.SPRITES, "PAL_OW_"))

    def reword(self, owner: str, label: str, prose: str) -> None:
        """Replace one block's words, keeping its macros.

        **By owner and label, not by label alone.** A trainer's texts hang off
        local labels — `.before_battle_text` — and there are as many of those in a
        map as there are trainers in it. Finding the first one that matches the
        name reliably rewords somebody else's trainer.
        """
        blocks = dialogue.parse_source(self.root, self.lines)
        block = next((b for b in blocks
                      if b.label == label and b.owner == owner), None)
        if block is None:
            raise EditError(
                f"maps/{self.label}.asm has no text block {label} under {owner}")
        self.lines = dialogue.rewrite(self.lines, block, prose)

    def block(self, label: str) -> range:
        """The lines of a top-level label's block, from its definition to just
        before the next top-level label."""
        start = next((i for i, ln in enumerate(self.lines)
                      if ln.startswith(f"{label}:")), None)
        if start is None:
            raise EditError(f"maps/{self.label}.asm has no block called {label}")
        end = start + 1
        while end < len(self.lines):
            if _LABEL_RE.match(self.lines[end]):
                break
            end += 1
        return range(start, end)

    def flag(self, name: str, was: str) -> str:
        """Name this object's event flag, allocating it if it is new.

        The *old* flag is left allocated, and said so, rather than freed. A flag
        shared between two maps is a real thing in this repo, and the module that
        deletes objects is careful about exactly this (`removal.py`) — an editor
        that quietly freed a bit somebody else's map was standing on would be a
        worse citizen than one that leaks it.
        """
        if name in ("", ALWAYS, "0"):
            # Blank is not "no flag" — it is -1, which the engine reads as "always
            # there", and which is the right answer for most people in most towns.
            return ALWAYS
        if same(was, name):
            return was          # untouched: keep whatever the source called it
        try:
            allocated, edit = allocate_flag(self.root, name)
        except ScaffoldError as exc:
            raise EditError(str(exc)) from exc
        if edit.changed:
            self.extra.append(edit)
        if was not in (allocated, ALWAYS, "0", ""):
            self.notes.append(
                f"{was} is left allocated — another map may be standing on it")
        return allocated

    def done(self, summary: str, detail: str) -> Change:
        text = "\n".join(self.lines)
        edit = Edit(f"maps/{self.label}.asm", text != self._original, detail, text,
                    base=self._original)
        notes = list(self.notes)
        if not edit.changed and not any(e.changed for e in self.extra):
            notes.append("unchanged — nothing to write")
        return Change(summary, [*self.extra, edit], notes)


# --------------------------------------------------------------------------- #
# the objects                                                                 #
# --------------------------------------------------------------------------- #

def edit_npc(root: Path, map_const: str, index: int, obj: Object, *,
             flag: str | None = None, prose: str | None = None) -> Change:
    """An NPC's body, its flag, and what it says."""
    ctx = MapEdit(root, map_const)
    entry = ctx.entry(eh.ListKind.OBJECT_EVENTS, index)
    ctx.body(obj, entry)

    if prose is not None and (pointer := entry.pointer):
        ctx.reword(pointer, pointer, prose)

    entry = ctx.entry(eh.ListKind.OBJECT_EVENTS, index)
    ctx.replace_entry(eh.ListKind.OBJECT_EVENTS, index, spliced(entry, {
        SPRITE: obj.sprite, Y: obj.y, X: obj.x, MOVEMENT: obj.movement,
        PALETTE: _palette(entry.args[PALETTE], obj.palette),
        FLAG: ctx.flag(flag or "", entry.event_flag),
    }))
    return ctx.done(f"{obj.sprite} at ({obj.y}, {obj.x}) in {map_const}",
                    f"{obj.sprite} at ({obj.y}, {obj.x})")


def edit_trainer(root: Path, map_const: str, index: int, obj: Object, cls: str,
                 party: str, *, flag: str | None = None, sight: int = 1,
                 seen: str | None = None, defeated: str | None = None,
                 after: str | None = None) -> Change:
    """A trainer's body, class, party, sight, flag, and all three of its texts.

    The class and the party are not on the `person_event` at all — they are
    arguments to the `trainer` macro inside the script block, which is also where
    the two texts the macro points at are named. So this one reaches into the
    block as well as the header, and both land in the same buffer.
    """
    _check_party(root, cls, party)

    ctx = MapEdit(root, map_const)
    entry = ctx.entry(eh.ListKind.OBJECT_EVENTS, index)
    ctx.body(obj, entry)
    pointer = entry.pointer
    if not pointer:
        raise EditError(
            f"this trainer's person_event points at nothing, so its class and its "
            f"words cannot be found. Its persontype is {entry.persontype}.")
    _, macro = trainer_macro(ctx, pointer)
    was_flag, seen_at, beaten_at = macro[0], macro[3], macro[4]

    # The words first: a reword changes the line count, and the macro line and the
    # person_event line both sit below at least one of these blocks.
    for label, prose in ((pointer, after), (seen_at, seen), (beaten_at, defeated)):
        if prose is not None:
            ctx.reword(pointer, label, prose)

    # The class, the party and the beaten flag are all on the macro. The
    # person_event's own flag argument is a different question — whether the body
    # is *drawn* — and add_trainer leaves it at -1, so the form is not asking it.
    new_flag = ctx.flag(flag or was_flag, was_flag)
    macro_at, macro = trainer_macro(ctx, pointer)
    ctx.lines[macro_at] = _trainer_line(ctx.lines[macro_at], macro,
                                        {0: new_flag, 1: cls, 2: party})

    entry = ctx.entry(eh.ListKind.OBJECT_EVENTS, index)
    ctx.replace_entry(eh.ListKind.OBJECT_EVENTS, index, spliced(entry, {
        SPRITE: obj.sprite, Y: obj.y, X: obj.x, MOVEMENT: obj.movement,
        PALETTE: _palette(entry.args[PALETTE], obj.palette), PARAM: sight,
    }))
    return ctx.done(f"{cls} at ({obj.y}, {obj.x}) in {map_const} [party {party}]",
                    f"{cls} at ({obj.y}, {obj.x})")


def edit_signpost(root: Path, map_const: str, index: int, y: int, x: int, *,
                  facing: str | None = None, prose: str | None = None) -> Change:
    ctx = MapEdit(root, map_const)
    entry = ctx.entry(eh.ListKind.BG_EVENTS, index)
    if entry.arg(S_FACING) == "SIGNPOST_ITEM":
        raise EditError("that is a hidden item, not a signpost — edit it from Pickups")

    if prose is not None and (pointer := entry.pointer):
        ctx.reword(pointer, pointer, prose)

    entry = ctx.entry(eh.ListKind.BG_EVENTS, index)
    changed: dict[int, object] = {S_Y: y, S_X: x}
    if facing:
        changed[S_FACING] = facing
    ctx.replace_entry(eh.ListKind.BG_EVENTS, index, spliced(entry, changed))
    return ctx.done(f"sign at ({y}, {x}) in {map_const}", f"sign at ({y}, {x})")



def edit_trigger(root: Path, map_const: str, index: int, y: int, x: int) -> Change:
    """Where a trigger is. What it *runs* is a script somebody wrote, and picking
    a different one is not something a coordinate form should be able to do by
    accident — so the scene and the pointer are shown and left alone."""
    ctx = MapEdit(root, map_const)
    entry = ctx.entry(eh.ListKind.COORD_EVENTS, index)
    ctx.replace_entry(eh.ListKind.COORD_EVENTS, index,
                      spliced(entry, {T_Y: y, T_X: x}))
    return ctx.done(f"trigger at ({y}, {x}) in {map_const}", f"trigger at ({y}, {x})")


# --------------------------------------------------------------------------- #
# internals                                                                   #
# --------------------------------------------------------------------------- #


def _check_party(root: Path, cls: str, party: str) -> None:
    """The class must exist, and the party must be one it has.

    A party is a *position* in a class's group file, so #4 of a class with three
    is a battle against whatever happens to be assembled next — which is why this
    is checked rather than trusted.

    It may be written as a number or as a **constant** — `RIVAL1_3` — and both are
    real in this repo. A constant is resolved through `trainercite`, which is where
    `removal` reads them from, and it must name a party *of this class*: `RIVAL1_3`
    on a BEAUTY is a Beauty leading Silver's team.
    """
    try:
        group = trainerparty.group_for(root, cls)
    except trainerparty.TrainerPartyError as exc:
        raise EditError(str(exc)) from exc

    n = eh.as_int(party)
    if n is None:
        named = trainercite.party_consts(root).get(party)
        if named is None:
            raise EditError(f"{party} is not a party constant in this repo")
        owner, n = named
        if owner != cls:
            raise EditError(f"{party} is one of {owner}'s parties, not {cls}'s")
    if not 1 <= n <= group.count:
        raise EditError(f"{cls} party #{party} doesn't exist — "
                        f"{group.label} has {group.count}.")


def trainer_macro(ctx: MapEdit, label: str) -> tuple[int, list[str]]:
    """The `trainer FLAG, CLASS, PARTY, seen, defeated` line of a script block,
    and where it is."""
    for i in ctx.block(label):
        if m := _TRAINER_RE.match(ctx.lines[i]):
            args = [a.strip() for a in m.group("args").split(",")]
            if len(args) < 5:
                raise EditError(
                    f"{label}'s trainer macro has {len(args)} arguments, not five")
            return i, args
    raise EditError(f"{label} has no trainer macro — is this really a trainer?")


def _trainer_line(line: str, args: list[str], changed: dict[int, str]) -> str:
    """The macro line with only these arguments replaced.

    The same rule as :func:`spliced`, and it is needed for the same reason: the
    five-argument `trainer FLAG, CLASS, PARTY, seen, beaten` is the common shape
    and not the only one. Some carry a tail — `…, NULL, .script` — and rebuilding
    the line from the five we know about silently deletes the script the trainer
    runs when you talk to him.
    """
    m = _TRAINER_RE.match(line)
    if m is None:                              # pragma: no cover - located by the same re
        raise EditError("the trainer macro moved out from under the edit")
    out = list(args)
    for i, value in changed.items():
        if not same(out[i], value):
            out[i] = str(value).strip()
    return f"{m.group('head')}{', '.join(out)}{m.group('comment') or ''}"



