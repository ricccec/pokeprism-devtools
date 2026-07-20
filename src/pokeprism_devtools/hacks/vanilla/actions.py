"""The family's adders and editors — one form per event list, not per row kind.

The write half of what `hacks/vanilla/events.py` and `hacks/polished/events.py`
read. They carve four lists into *six* tables (npc, trainer, prop, signpost,
warp, trigger) by walking the block each entry points at; this module carves
back the other way, because a **line** is what `add_entry` and `replace_entry`
splice and a line belongs to exactly one list. An NPC and a fruit tree are one
`object_event` with the same thirteen slots — what makes one a tree is the
`fruittree` macro in the block it names, and that block is not this line's to
rewrite. So there are four editors, one per list, and the shape of a form
follows the list rather than the row you happened to click.

**What the argument order costs if you assume it.** Both dialects write
`object_event` and neither writes it the same way:

    vanilla   x y sprite movement radius_x radius_y h1 h2 palette type …
    polished  x y sprite movement radius_y radius_x time    palette type …

Arguments 5 and 6 are the movement radius in both — and they are *swapped*.
Vanilla's macro emits `dn \\6, \\5`, polished's `dn \\5, \\6`, so the same two
numbers in the same two columns mean opposite axes. 153 vanilla lines and 250
polished lines write an asymmetric radius, and every one of them would have had
its pacing box reflected across the diagonal by a writer that copied the other
tree's order — the identical failure the `(x, y)` ↔ `Tile(y, x)` turn exists to
prevent, one column further along. Hence :class:`ObjectShape`: the slot order is
declared per dialect and the form is built from the declaration, so the fork is
data the mount hands over rather than a branch anybody writes twice.

What does **not** cross here, and why it is an absence rather than a gap:
adding a trainer or a prop. Their entry line is the small half — the real
content is a `trainer` / `itemball` / `fruittree` / `hiddenitem` block written
beside it, which is family scaffolding and the same project rewording is.
`add_entry` splices one line; a line pointing at a block nobody wrote does not
assemble, so the adder that would write one refuses by name instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ...studio import panels
from ...studio.actions import (FACINGS, FLAGS, MAPS, MOVEMENTS, PALETTES,
                               SPRITES, Action, ActionError, Field, Result)
from . import eventblock as eb
from .shapes import POLISHED_OBJECT, VANILLA_OBJECT, ObjectShape, prefill


#: The boxes an `object_event` slot gets, by slot name. Built into a form in
#: the dialect's own order, so neither tree is offered the other's columns —
#: a `time` box on vanilla would write a valid number into an hour limit.
_OBJECT_FIELDS: dict[str, Field] = {
    "y": Field("y", "Y", kind="int"),
    "x": Field("x", "X", kind="int"),
    "sprite": Field("sprite", "Sprite", choices=SPRITES, default="SPRITE_GRAMPS"),
    "movement": Field("movement", "Movement", choices=MOVEMENTS,
                      default="SPRITEMOVEDATA_STANDING_DOWN"),
    "radius_y": Field("radius_y", "Radius Y", kind="int", default="0",
                      help="tiles it wanders up and down; 0 stays put"),
    "radius_x": Field("radius_x", "Radius X", kind="int", default="0"),
    "h1": Field("h1", "From hour", kind="int", default="-1",
                help="-1, -1 means always. Otherwise 0-23."),
    "h2": Field("h2", "To hour", kind="int", default="-1"),
    "time": Field("time", "Time of day", default="-1",
                  help="-1 is always; else MORN, DAY and/or NITE"),
    "palette": Field("palette", "Palette", choices=PALETTES,
                     default="PAL_NPC_RED"),
    "type": Field("type", "Type", default="OBJECTTYPE_SCRIPT",
                  help="what the engine does when you press A on it"),
    "sight": Field("sight", "Sight", kind="int", default="0",
                   help="only OBJECTTYPE_TRAINER reads this"),
    "script": Field("script", "Points at", default="",
                    help="a label already in this file — this form writes the "
                         "line, not the block it names"),
    "flag": Field("flag", "Event flag", choices=FLAGS, default="-1",
                  help="-1 is always there; a flag gates them on it"),
}


class _Entry(Action):
    """One line in one of the four lists, on the map you are looking at.

    The two dialect forks arrive as class attributes rather than as arguments,
    because the form builds its action with `cls(map_const, **values)` and has
    nowhere to put a third thing. :func:`fork` stamps them on, once per
    dialect, from what the mount declared — so this class never learns a hack's
    name and never asks the tree which one it is.
    """

    #: `_MapEvents` for vanilla's tail block, `_MapScriptHeader` for polished's
    #: head. The same parameter `events.parse` takes, for the same reason.
    anchor = "_MapEvents"
    shape = VANILLA_OBJECT
    #: Which of the four lists this action's line lives in.
    list_kind = "object"

    def __init__(self, map_const: str, **values: str) -> None:
        super().__init__(**values)
        self.map = map_const

    # -- the file ------------------------------------------------------------- #
    def _block(self, root: Path) -> tuple[eb.EventBlock, str]:
        """This map's event block, freshly parsed. The label comes from the
        catalog rather than from the form: you picked a map, and the file it
        lives in is the tree's business, not a string anybody typed."""
        from .read import label_of
        label = label_of(root).get(self.map)
        if label is None:
            raise ActionError(f"{self.map} is not a map in this tree.")
        try:
            return eb.parse_map(root / f"maps/{label}.asm", self.anchor), label
        except (eb.UnparseableEvents, panels.Unreadable) as exc:
            raise ActionError(str(exc)) from exc

    def _written(self, block: eb.EventBlock, root: Path) -> Result:
        """The staged change. Unchanged text is no edit at all — an editor you
        opened, looked at and submitted should write nothing, and say so."""
        edit = block.to_edit(root, self.describe())
        return Result(edit.detail, [edit] if edit.changed else [],
                      [] if edit.changed else ["unchanged — nothing to write"])

    def _where(self) -> str:
        return f"({self.text('y')}, {self.text('x')})"


# --------------------------------------------------------------------------- #
# the four lists, added to                                                    #
# --------------------------------------------------------------------------- #

class AddWarp(_Entry):
    """A door. The one entry in this dialect that points at nothing local —
    its target is a map and a position in *that* map's warp list — so it is
    also the one that can be added complete, with no block to write beside it.

    Nothing renumbers on the way in: a warp is appended, so it becomes the
    highest-numbered warp on this map and no door in the repo that counted its
    way to an existing one counts differently afterwards. That asymmetry with
    `RemoveWarp` is real — deleting is the operation with the repo-wide blast
    radius, and adding simply is not.
    """
    name = "warp"
    title = "Add a warp"
    list_kind = "warp"
    FIELDS = (
        Field("y", "Y", kind="int"),
        Field("x", "X", kind="int"),
        Field("to_map", "To map", choices=MAPS, default=""),
        Field("their_warp", "Their warp #", kind="int", default="1",
              help="which warp on that map you come out of, counting from 1"),
    )

    def describe(self) -> str:
        return (f"warp at {self._where()} to {self.text('to_map')} "
                f"#{self.text('their_warp')} in {self.map}")

    def run(self, root: Path) -> Result:
        if not self.text("to_map"):
            raise ActionError("a warp with no destination is a warp to nowhere "
                              "— name the map it leads to")
        block, label = self._block(root)
        block.add_entry("warp", [self.text("x"), self.text("y"),
                                 self.text("to_map"), self.text("their_warp")])
        return self._written(block, root)


class AddTrigger(_Entry):
    """A `coord_event`: a script that runs when you step on the tile.

    Its scene id is the half people get wrong — a trigger only fires while its
    map is in that scene, so one written against a scene the map never enters
    is a trigger that is never once reached. The field is free text rather than
    a list because scenes are per-map constants, and which map you are on is
    not something `choices()` is told.
    """
    name = "trigger"
    title = "Add a trigger"
    list_kind = "coord"
    FIELDS = (
        Field("y", "Y", kind="int"),
        Field("x", "X", kind="int"),
        Field("scene", "Scene", default="0",
              help="the SCENE_* this map must be in for the trigger to fire"),
        Field("script", "Runs", default="",
              help="a label already in this file"),
    )

    def describe(self) -> str:
        return f"trigger at {self._where()} in {self.map}"

    def run(self, root: Path) -> Result:
        if not self.text("script"):
            raise ActionError("a trigger that runs nothing assembles into a "
                              "jump to address zero — name the label it runs")
        block, label = self._block(root)
        block.add_entry("coord", [self.text("x"), self.text("y"),
                                  self.text("scene"), self.text("script")])
        return self._written(block, root)


class AddSignpost(_Entry):
    """A `bg_event`: something to read.

    The kind decides what the fourth argument *is* — a script label for
    `BGEVENT_READ`, a text label for polished's `BGEVENT_JUMPTEXT`, a std
    script for `BGEVENT_JUMPSTD` — and the form does not try to tell them
    apart, because all three are a name already in the tree either way. What it
    will not offer is a hidden item: `BGEVENT_ITEM + NUGGET` needs a
    `hiddenitem` block on vanilla, and the adder that writes blocks does not
    exist yet.
    """
    name = "signpost"
    title = "Add a signpost"
    list_kind = "bg"
    FIELDS = (
        Field("y", "Y", kind="int"),
        Field("x", "X", kind="int"),
        Field("kind", "Kind", choices=FACINGS, default="BGEVENT_READ",
              help="which sides it reads from, and what it reads"),
        Field("points_at", "Points at", default="",
              help="a label already in this file"),
    )

    def describe(self) -> str:
        return f"signpost at {self._where()} in {self.map}"

    def run(self, root: Path) -> Result:
        kind = self.text("kind") or "BGEVENT_READ"
        if kind.startswith("BGEVENT_ITEM"):
            raise ActionError(
                "a hidden item needs a hiddenitem block written beside its "
                "line, and writing script blocks is not wired for this "
                "dialect yet. Its line alone would not assemble.")
        if not self.text("points_at"):
            raise ActionError("a signpost that points at nothing assembles "
                              "into a jump to address zero")
        block, label = self._block(root)
        block.add_entry("bg", [self.text("x"), self.text("y"), kind,
                               self.text("points_at")])
        return self._written(block, root)


class AddNpc(_Entry):
    """An `object_event` that points at a script somebody already wrote.

    The form is built from :attr:`_Entry.shape`, so it is the dialect's own
    columns in the dialect's own order — and the radius pair in particular
    lands the way this tree reads it rather than the way the other one does.

    Naming it is a box rather than a certainty, and blank is a real answer.
    The consts are positional, so `add_entry` refuses a name on a list that
    names only its leading objects — polished has many — and the message it
    refuses with explains the ordinal better than a hidden box could. It
    refuses at *preview*, with everything you typed still on screen and not one
    byte written, which is the moment the form exists to reach. Offering the
    box only when the list is fully named would need `adders()` to be told
    which map you are on, and it is told a tab's name and nothing else.
    """
    name = "npc"
    title = "Add an NPC"
    list_kind = "object"

    _CONST = Field("const", "Name", default="",
                   help="the object_const_def name scripts will address it by; "
                        "blank appends it unnamed")

    @classmethod
    def fields_for(cls, values: dict[str, str]) -> tuple[Field, ...]:
        return (cls._CONST,) + tuple(
            _OBJECT_FIELDS[s] for s in cls.shape.slots if s in _OBJECT_FIELDS)

    def describe(self) -> str:
        who = self.text("const") or self.text("sprite")
        return f"{who} at {self._where()} in {self.map}"

    def run(self, root: Path) -> Result:
        if not self.text("script"):
            raise ActionError("an object that points at nothing assembles into "
                              "a jump to address zero — name the label it runs")
        block, label = self._block(root)
        const = self.text("const") or None
        if const and block.index_of(const) is not None:
            raise ActionError(
                f"{label} already declares {const} — object consts are the "
                "names scripts address, so two of them is one name pointing "
                "at two objects.")
        try:
            block.add_entry("object", self.shape.args(self.values), name=const)
        except eb.UnparseableEvents as exc:
            raise ActionError(str(exc)) from exc
        return self._written(block, root)


# --------------------------------------------------------------------------- #
# the four lists, edited                                                      #
# --------------------------------------------------------------------------- #

class _Edit(_Entry):
    """Rewrite one line in place.

    Editing is the safe half of this module and deleting is the dangerous one,
    for a reason worth stating: one line becomes another line, so nothing moves,
    no const's ordinal changes, and no warp in the repo counts differently
    afterwards. It is also why *every* list gets an editor while only four
    kinds get an adder — the block this line points at already exists, so
    rewriting the line asks nobody to write one.
    """

    #: Which entry, carried from the row you pointed at and never from a box.
    FIXED = (Field("index", "Entry", kind="fixed"),)

    def _target(self, block: eb.EventBlock) -> int:
        index = self.integer("index")
        if block.entry_at(self.list_kind, index) is None:
            raise ActionError(
                f"{self.map} no longer has a {self.list_kind} entry there — "
                "the map changed under the form. Nothing was written.")
        return index

    def _replaced(self, root: Path, args: list[str]) -> Result:
        block, _ = self._block(root)
        block.replace_entry(self.list_kind, self._target(block), args)
        return self._written(block, root)


class EditWarp(_Edit):
    name = "warp"
    title = "Edit a warp"
    list_kind = "warp"
    FIELDS = _Edit.FIXED + AddWarp.FIELDS

    def describe(self) -> str:
        return (f"warp #{self.integer('index') + 1} in {self.map} → "
                f"{self.text('to_map')} #{self.text('their_warp')}")

    def run(self, root: Path) -> Result:
        return self._replaced(root, [self.text("x"), self.text("y"),
                                     self.text("to_map"),
                                     self.text("their_warp")])


class EditTrigger(_Edit):
    name = "trigger"
    title = "Edit a trigger"
    list_kind = "coord"
    FIELDS = _Edit.FIXED + AddTrigger.FIELDS

    def describe(self) -> str:
        return f"trigger #{self.integer('index') + 1} in {self.map}"

    def run(self, root: Path) -> Result:
        return self._replaced(root, [self.text("x"), self.text("y"),
                                     self.text("scene"), self.text("script")])


class EditSignpost(_Edit):
    """A `bg_event`, including the hidden items polished writes inline.

    Polished spells one `BGEVENT_ITEM + NUGGET` where vanilla spells a kind and
    a block, so on that tree the kind box holds an expression rather than a
    constant — which is why it is a combo over the known kinds and not a list
    you are held to. Editing one is safe in a way *adding* one is not: the
    block, where there is one, is already there.

    The fifth argument is the part that had to be found. Polished's macro reads
    `if _NARG == 5` and spends the extra on a `BGEVENT_JUMPSTD`'s argument —
    35 lines, every one of them a hidden grotto — where the four-argument form
    writes a zero in its place. A form that showed four boxes would have
    quietly turned each of those grottoes into grotto 0 on the first edit, so
    the box appears exactly when the line has one, and vanilla (whose macro
    takes four, full stop) never sees it.
    """
    name = "signpost"
    title = "Edit a signpost"
    list_kind = "bg"

    _EXTRA = Field("extra", "Std argument", default="",
                   help="what this BGEVENT_JUMPSTD is about — a grotto id")

    @classmethod
    def fields_for(cls, values: dict[str, str]) -> tuple[Field, ...]:
        base = cls.FIXED + AddSignpost.FIELDS
        return base + (cls._EXTRA,) if values.get("extra") else base

    def describe(self) -> str:
        return f"signpost #{self.integer('index') + 1} in {self.map}"

    def run(self, root: Path) -> Result:
        args = [self.text("x"), self.text("y"), self.text("kind"),
                self.text("points_at")]
        if extra := self.text("extra"):
            args.append(extra)
        return self._replaced(root, args)


class EditObject(_Edit):
    """Every `object_event`, whatever the tables decided it was.

    One editor for NPCs, trainers, item balls and fruit trees, because they are
    one line with one set of slots — what makes a line a fruit tree lives in
    the block it names, and this form does not touch that block. Editing the
    *tree* means editing `fruittree`'s argument, which is a different job in a
    different file and is not offered here rather than half-offered.
    """
    name = "object"
    title = "Edit an object"
    list_kind = "object"

    @classmethod
    def fields_for(cls, values: dict[str, str]) -> tuple[Field, ...]:
        return cls.FIXED + tuple(
            _OBJECT_FIELDS[s] for s in cls.shape.slots if s in _OBJECT_FIELDS)

    def describe(self) -> str:
        return (f"{self.text('sprite') or 'object'} #"
                f"{self.integer('index') + 1} at {self._where()} in {self.map}")

    def run(self, root: Path) -> Result:
        block, label = self._block(root)
        index = self._target(block)
        entry = block.lists["object"].entries[index]
        if len(entry.args) != len(self.shape.slots):
            # polished writes a 13-argument `object_event` for an item ball —
            # the trailing three are item, quantity and flag where the ordinary
            # twelve spend two on a pointer and a flag. Rewriting it with the
            # twelve-slot shape would move the flag into the quantity and hand
            # you some number of a mistake, so it refuses and says which line.
            raise ActionError(
                f"{label}'s object #{index + 1} has {len(entry.args)} "
                f"arguments where this dialect's object_event takes "
                f"{len(self.shape.slots)} — its trailing arguments mean "
                "something else, so this form will not rewrite it.")
        block.replace_entry("object", index, self.shape.args(self.values))
        return self._written(block, root)


# --------------------------------------------------------------------------- #
# the two dialects                                                            #
# --------------------------------------------------------------------------- #

#: What the tab-foot "Add new…" row opens, keyed by the word the tab carries in
#: `Tab.adds`. Trainers and objects are *absent*, and the absence is the honest
#: answer rather than an oversight: both need a script block written beside the
#: entry line, and `add_entry` splices lines. See this module's docstring.
ADDERS: dict[str, tuple[type[_Entry], ...]] = {
    "NPC": (AddNpc,),
    "warp": (AddWarp,),
    "signpost": (AddSignpost,),
    "trigger": (AddTrigger,),
}

#: And what `e` opens, keyed by the **list** the entry lives in rather than by
#: `Ref.what`. The tables' six kinds are a reading of the block an entry points
#: at; the four lists are what the file actually has, and a form that rewrites
#: a line belongs to the second carve.
EDITORS: dict[str, type[_Edit]] = {
    "warp": EditWarp, "coord": EditTrigger,
    "bg": EditSignpost, "object": EditObject,
}


def fork(anchor: str, shape: ObjectShape, tag: str) -> tuple[dict, dict]:
    """This dialect's actions: the same classes, stamped with its two forks.

    Subclasses rather than arguments because the form builds an action as
    `cls(map_const, **values)` — there is no third argument to pass, and adding
    one would mean teaching a studio screen that some hacks have dialects.
    Stamped once at import from what the mount declares, so the fork stays data
    and no code branches on which tree it is looking at.
    """
    def stamp(cls: type) -> type:
        return type(f"{tag}{cls.__name__}", (cls,),
                    {"anchor": anchor, "shape": shape,
                     "__doc__": cls.__doc__})
    return ({k: tuple(stamp(c) for c in v) for k, v in ADDERS.items()},
            {k: stamp(c) for k, c in EDITORS.items()})


VANILLA_ADDERS, VANILLA_EDITORS = fork("_MapEvents", VANILLA_OBJECT, "Vanilla")
POLISHED_ADDERS, POLISHED_EDITORS = fork("_MapScriptHeader", POLISHED_OBJECT,
                                         "Polished")


#: Re-exported so a caller needing both the forms and the records they were
#: built from has one import. The records themselves live in `.shapes`.
__all__ = ["ObjectShape", "VANILLA_OBJECT", "POLISHED_OBJECT", "prefill",
           "VANILLA_ADDERS", "VANILLA_EDITORS",
           "POLISHED_ADDERS", "POLISHED_EDITORS", "fork"]
