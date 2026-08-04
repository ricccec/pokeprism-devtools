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

**The item ball is the first adder that writes a block.** Everything else here
splices one line into one list. :class:`AddItemball` writes two lines into the
scripts region as well, allocates an event flag in a second file, and mints
three names that have to agree with each other — and it is vanilla's alone,
because polished spells the same object as three extra `object_event`
arguments with no block anywhere. That is declared in :data:`VANILLA_ONLY`
rather than branched on, the same way the slot order is. Polished's own ball and
hidden item — line-only, the item baked in — are the mirror of it in
:data:`POLISHED_ONLY`, written by :mod:`.polisheditem`.

**The trainer is the first adder that writes a block in *both* trees.** Its
entry line is the small half; the content is a battle block plus the texts it
names — and those texts sit differently in each tree, so the block forks where
the item ball's did not. That fork lives in :mod:`.trainer` as two subclasses,
one registered per dialect, and it was pinned down by measuring all 333 vanilla
and 593 polished trainers rather than guessed at. It is reuse-only, mirroring
prism's own form: you place a party that exists, and the flag it allocates is
`EVENT_<MAP>_TRAINER`, never a beat flag two placements would share.
"""

from __future__ import annotations

from pathlib import Path

from ...contract import FACINGS, MAPS, ActionError, Field, Result
from ...wiring import regions
from . import eventblock as eb
from .entry import OBJECT_FIELDS
from .entry import Entry as _Entry
from .fruittree import AddFruittree
from .hiddenitem import AddHiddenitem
from .itemball import AddItemball
from .polisheditem import AddPolishedHiddenitem, AddPolishedItemball
from .shapes import POLISHED_OBJECT, VANILLA_OBJECT, ObjectShape, prefill
from .trainer import GenericTrainer, Trainer


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
    will not offer is a hidden item: `BGEVENT_ITEM` needs a `hiddenitem` block
    and a flag written beside its line, which is a whole adder's worth of work —
    `AddHiddenitem`, on the Objects tab, where the item reads back. This form
    writes one line and sends a hidden item there.
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
                "a hidden item needs a hiddenitem block and a flag written "
                "beside its line — its line alone would not assemble. Add it "
                "from the Objects tab, where 'Add a hidden item' writes all "
                "three.")
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
            OBJECT_FIELDS[s] for s in cls.shape.slots if s in _OBJECT_FIELDS)

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
            OBJECT_FIELDS[s] for s in cls.shape.slots if s in _OBJECT_FIELDS)

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
#: `Tab.adds`. The four lines-only adders, shared by both dialects. The trainer
#: is not here: it writes a block that forks between the trees, so it is
#: registered per dialect in the two `fork` calls below, not in this shared map.
ADDERS: dict[str, tuple[type[_Entry], ...]] = {
    "NPC": (AddNpc,),
    "warp": (AddWarp,),
    "signpost": (AddSignpost,),
    "trigger": (AddTrigger,),
}

#: And the adders that are one dialect's only. The item ball is vanilla's alone
#: because in polished it is not a block at all: polished bakes the item and
#: the quantity into three extra `object_event` arguments (`itemball_event`),
#: so there is nothing to point at and nothing to write beside the line. Same
#: object on screen, different half of the file — which is exactly the sort of
#: difference that has to be declared here rather than branched on down there.
#: The fruit tree is here for the same reason: polished has no `fruit_trees.asm`
#: and spells the tree as `fruittree_event` object arguments, so its block and
#: its two-file id table are vanilla's and nothing else's. The hidden item too:
#: polished bakes it into the `bg_event` (`BGEVENT_ITEM + NUGGET`) with no
#: `hiddenitem` block to write, so vanilla's block-and-flag adder has nothing to
#: cross the seam to. What is vanilla's alone here is the *block writer*, not the
#: object — polished offers its own ball and hidden item from :data:`POLISHED_ONLY`,
#: line-only where these write a block.
VANILLA_ONLY: dict[str, tuple[type[_Entry], ...]] = {
    "object": (AddItemball, AddFruittree, AddHiddenitem),
}

#: And polished's, the mirror image: the same two objects on screen — a ball on
#: the floor and a hidden item — but baked into the line itself, so each is one
#: `object_event` or `bg_event` with no block. Declared here rather than
#: branched on for the same reason `VANILLA_ONLY` is: what a tree does *not*
#: point a line at is as much a dialect fact as what it does. See
#: :mod:`.polisheditem`.
POLISHED_ONLY: dict[str, tuple[type[_Entry], ...]] = {
    "object": (AddPolishedItemball, AddPolishedHiddenitem),
}

#: And what `e` opens, keyed by the **list** the entry lives in rather than by
#: `Ref.what`. The tables' six kinds are a reading of the block an entry points
#: at; the four lists are what the file actually has, and a form that rewrites
#: a line belongs to the second carve.
EDITORS: dict[str, type[_Edit]] = {
    "warp": EditWarp, "coord": EditTrigger,
    "bg": EditSignpost, "object": EditObject,
}


def fork(anchor: str, shape: ObjectShape, tag: str, *,
         layout: regions.Layout = regions.VANILLA,
         extra: dict[str, tuple[type[_Entry], ...]] | None = None,
         ) -> tuple[dict, dict]:
    """This dialect's actions: the same classes, stamped with its two forks.

    Subclasses rather than arguments because the form builds an action as
    `cls(map_const, **values)` — there is no third argument to pass, and adding
    one would mean teaching a studio screen that some hacks have dialects.
    Stamped once at import from what the mount declares, so the fork stays data
    and no code branches on which tree it is looking at.
    """
    def stamp(cls: type) -> type:
        return type(f"{tag}{cls.__name__}", (cls,),
                    {"anchor": anchor, "shape": shape, "layout": layout,
                     "__doc__": cls.__doc__})
    from .mapactions import FamilyConnect
    adders = {**ADDERS, **(extra or {})}
    stamped = {k: tuple(stamp(c) for c in v) for k, v in adders.items()}
    # The connection adder forks on nothing — both trees write the same macro —
    # so it mounts as itself, without an event anchor stamped onto it. It lives in
    # `.mapactions` (map-to-map) rather than here (in-map), mirroring how prism
    # keeps its `Connect` out of `content.py`.
    stamped["connection"] = (FamilyConnect,)
    return (stamped, {k: stamp(c) for k, c in EDITORS.items()})


#: The trainer, forked. Both trees have it — the first block adder that does —
#: but each writes its own macro and `OBJECTTYPE_*`, so the dialect gets its own
#: subclass here rather than a shared entry in :data:`ADDERS`. Keyed "trainer",
#: the word the Trainers tab carries in `Tab.adds`.
VANILLA_ADDERS, VANILLA_EDITORS = fork("_MapEvents", VANILLA_OBJECT, "Vanilla",
                                       layout=regions.VANILLA,
                                       extra={**VANILLA_ONLY,
                                              "trainer": (Trainer,)})
POLISHED_ADDERS, POLISHED_EDITORS = fork("_MapScriptHeader", POLISHED_OBJECT,
                                         "Polished", layout=regions.POLISHED,
                                         extra={**POLISHED_ONLY,
                                                "trainer": (GenericTrainer,)})


#: Re-exported so a caller needing both the forms and the records they were
#: built from has one import. The records themselves live in `.shapes`.
__all__ = ["ObjectShape", "VANILLA_OBJECT", "POLISHED_OBJECT", "prefill",
           "AddItemball", "AddFruittree", "AddHiddenitem",
           "AddPolishedItemball", "AddPolishedHiddenitem", "Trainer",
           "GenericTrainer", "VANILLA_ADDERS", "VANILLA_EDITORS",
           "POLISHED_ADDERS", "POLISHED_EDITORS", "fork"]
