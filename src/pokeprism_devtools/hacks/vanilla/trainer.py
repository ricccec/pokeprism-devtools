"""The trainer — the first family adder that writes a block in *both* trees.

The item ball, the fruit tree and the hidden item cross into vanilla alone,
because polished bakes each of them into `object_event` arguments with no block
to write. A trainer is different: both trees point an `object_event` at a script
block and put the battle inside it, so the adder is real on both sides — and the
block it writes forks, because the two trees spell that battle differently.

    vanilla    trainer CLASS, PARTY, FLAG, Seen, Beaten, 0, .AfterScript
    polished   generictrainer CLASS, PARTY, FLAG, .SeenText, .BeatenText

Same three leading arguments — a class, one of its parties, and the flag that
remembers you won — and a different macro, a different arrangement of the three
texts, and a different `OBJECTTYPE_*` on the object line. That fork is the two
subclasses at the foot of this file; the mount registers one per dialect, so no
code here ever asks which tree it is looking at. Everything above the fork —
the fields, the party check, the object const, the flag, the splice — is shared,
because it is the same on both.

**Reuse-only, mirroring prism's own form.** You place an existing party; making
one is a change to the shared roster file and a different job (see
`asmedit/trainerroster`). The flag defaults to `EVENT_<MAP>_TRAINER`, prism's
map-named convention, allocated fresh — never the tree's `EVENT_BEAT_<CLASS>_
<PARTY>`, which two placements of one party would have to share.

The block shapes, and the sweeps of all 333 vanilla and 593 polished trainers
behind them, are in `asmedit/blocks.py`.
"""

from __future__ import annotations

from pathlib import Path

from ...contract import (CLASSES, FLAGS, MOVEMENTS, PALETTES, PARTIES,
                               SPRITES, ActionError, Field, Result)
from ...asmedit import blocks, flagalloc, regions, trainerroster
from . import eventblock as eb
from .entry import Entry

#: Where a trainer's beaten flag belongs by convention — the bucket the tree's
#: own `EVENT_BEAT_*` flags sit in. Preferred, not required: `_flag` says so out
#: loud when it falls back, the way the item ball does.
_TRAINER_BUCKET = "Trainer flags"


class AddTrainer(Entry):
    """A trainer who battles you — an `object_event` and the battle block it
    points at.

    The shared half of the two dialects. It writes the same two things the item
    ball does — a block in the scripts region and an object line in the event
    list — plus a beaten flag in a second file, and it minds the same three
    agreements: the block's label, the object's const, and the flag. What it
    leaves to the subclass is the block's *shape* and the object's `type`, the
    two things the trees spell differently. See :meth:`block`.
    """
    name = "trainer"
    title = "Add a trainer"
    list_kind = "object"

    #: The object's `OBJECTTYPE_*` — the dialect fork on the line. Set by the
    #: subclass the mount registers, never branched on here.
    objtype = ""

    FIELDS = (
        Field("cls", "Class", choices=CLASSES, default="",
              help="an existing trainer class"),
        Field("party", "Party", choices=PARTIES, depends=("cls",), default="",
              help="an existing party of this class — making a new one is a "
                   "different job, as it is in prism's own form"),
        Field("sprite", "Sprite", choices=SPRITES, default="SPRITE_YOUNGSTER"),
        Field("y", "Y", kind="int"),
        Field("x", "X", kind="int"),
        Field("movement", "Movement", choices=MOVEMENTS,
              default="SPRITEMOVEDATA_STANDING_DOWN"),
        Field("palette", "Palette", choices=PALETTES, default="PAL_NPC_RED"),
        Field("sight", "Sight", kind="int", default="1",
              help="tiles away they spot you; only a trainer object reads this"),
        Field("flag", "Beaten flag", choices=FLAGS, default="",
              help="blank and one is allocated. It is what stops them "
                   "re-battling you the moment you turn around."),
        Field("seen", "On spotting you", kind="lines"),
        Field("defeated", "On losing", kind="lines"),
        Field("after", "Afterwards", kind="lines"),
    )

    def describe(self) -> str:
        return (f"{self.text('cls')} {self.text('party')} at {self._where()} "
                f"in {self.map}")

    # -- the dialect fork ---------------------------------------------------- #
    #: What goes before the class+party in the block's label, so it reads as a
    #: trainer at a glance. The label is map-stem-prefixed (below) for global
    #: uniqueness, unlike the tree's bare `TrainerBugCatcherBenny`, so this need
    #: not carry the tree's `GenericTrainer` distinction — the label is ours,
    #: addressed only by the object line we write beside it.
    label_word = "Trainer"

    def block(self, text: str, label: str, cls: str, party: str, flag: str,
              seen: list[list[str]], defeated: list[list[str]],
              after: list[list[str]]) -> list[str]:
        """This dialect's battle block. Takes the file `text` because vanilla
        mints three more global labels here and polished mints none."""
        raise NotImplementedError

    # -- the shared write ---------------------------------------------------- #
    def run(self, root: Path) -> Result:
        cls, party = self.text("cls"), self.text("party")
        if not cls or not party:
            raise ActionError("a trainer is a class and one of its parties — "
                              "name both.")
        try:
            known = trainerroster.has(root, cls, party)
        except trainerroster.RosterError as exc:
            raise ActionError(str(exc)) from exc
        if not known:
            raise ActionError(
                f"{cls} has no party {party!r} in {trainerroster.CONSTANTS} — "
                "pick one of this class's parties. Making a new party is a "
                "change to a shared roster file, and a different job.")

        seen = self.pages("seen")
        defeated = self.pages("defeated")
        after = self.pages("after")

        path, stem = self._file(root)
        text = path.read_text()

        # The flag first: it is written into the macro line, so its name has to
        # be settled before the block can be spelled. It lands in a second file,
        # so it is a separate edit — no base clash with the block below.
        flag, flag_edit, note = self._flag(root)

        try:
            label = blocks.unique_label(
                text, f"{stem}{self.label_word}"
                      f"{blocks.plain_camel(cls)}{blocks.plain_camel(party)}")
            body = self.block(text, label, cls, party, flag,
                              seen, defeated, after)
        except blocks.BlockError as exc:
            raise ActionError(str(exc)) from exc

        # The block, then reparse, then let the object writer produce the single
        # Edit whose base is still what is on disk — the item ball's rule, and
        # for the same reason (an Edit carries the whole file). See
        # `regions.spliced`.
        try:
            staged = regions.spliced(text, regions.SCRIPTS, body,
                                     layout=self.layout)
            block = eb.parse_text(staged, path, self.anchor)
        except (regions.RegionError, eb.UnparseableEvents) as exc:
            raise ActionError(str(exc)) from exc

        sprite = self.text("sprite") or "SPRITE_YOUNGSTER"
        # Name the trainer only when the const list already names *every* object
        # — then a minted const keeps the list parallel, the way vanilla's
        # fully-named maps want. Where it names only its leading objects
        # (polished leaves its generic trainers unnamed, so most of its maps are
        # like this) a name would be refused for the wrong ordinal, and forcing
        # one unnamed onto a fully-named list would instead strip every existing
        # object of its handle. So a partial or absent list gets an unnamed
        # trainer, which is exactly what that map already does.
        objs = block.lists["object"].entries
        named = block.const_lineno is not None and len(block.names) == len(objs)
        const = (blocks.object_const([n for n, _ in block.names], stem,
                                     sprite.removeprefix("SPRITE_"))
                 if named else None)

        try:
            block.add_entry("object", self.shape.args({
                "y": self.text("y"), "x": self.text("x"),
                "sprite": sprite, "movement": self.text("movement"),
                "palette": self.text("palette") or "PAL_NPC_RED",
                "type": self.objtype, "sight": self.text("sight") or "1",
                # The object's *own* flag is when he is on the map at all, which
                # for a new trainer is always: `-1`. The beaten flag lives on
                # the macro line inside the block, not here.
                "script": label, "flag": "-1",
            }), name=const)
        except eb.UnparseableEvents as exc:
            raise ActionError(str(exc)) from exc

        edit = block.to_edit(root, self.describe())
        named_as = f"{const} names the trainer; " if const else \
            "the trainer is unnamed, like the rest of this map's; "
        return Result(self.describe(),
                      ([flag_edit] if flag_edit else []) + [edit],
                      [f"{label} is the battle; {named_as}"
                       f"{flag} remembers you won"] + note)

    def _flag(self, root: Path) -> tuple[str, object, list[str]]:
        """The beaten flag, and the edit that creates it when it is new.

        Like the item ball: a name **typed** into the box is used as it stands —
        two trainers sharing one is how "beating either counts" is written, and
        the twins in the tree do exactly that — and a name merely defaulted to
        gets a suffix if it collides. The default is `EVENT_<map>_TRAINER`,
        prism's map-named convention, reached through :func:`blocks.flag_name`.
        """
        try:
            flags = flagalloc.load(root)
        except flagalloc.FlagError as exc:
            raise ActionError(str(exc)) from exc

        typed = self.text("flag")
        wanted = typed or blocks.flag_name(self.map, "TRAINER", flags.names)
        if flags.has(wanted):
            return wanted, None, [f"{wanted} already exists — reusing it, so "
                                  "beating this trainer and whatever else it "
                                  "gates are remembered as one"]
        try:
            bucket = flags.allocate(wanted, prefer=_TRAINER_BUCKET)
        except flagalloc.FlagError as exc:
            raise ActionError(str(exc)) from exc
        note = [f"{wanted} allocated in {bucket.label!r}"]
        if bucket.label != _TRAINER_BUCKET:
            note.append(f"the {_TRAINER_BUCKET!r} bucket is full, so it went to "
                        f"{bucket.label!r} instead — the grouping is a comment, "
                        "not something the engine reads")
        return wanted, flags.to_edit(f"{wanted} in {bucket.label}"), note


class Trainer(AddTrainer):
    """pokecrystal's `OBJECTTYPE_TRAINER`: a `trainer` macro naming three global
    texts, with a local `.AfterScript` for the talk-again line. Named for the
    macro it writes, so the mount's fork stamps it `VanillaTrainer`."""
    objtype = "OBJECTTYPE_TRAINER"

    def block(self, text, label, cls, party, flag, seen, defeated, after):
        seen_l = blocks.unique_label(text, f"{label}SeenText")
        defeated_l = blocks.unique_label(text, f"{label}BeatenText")
        after_l = blocks.unique_label(text, f"{label}AfterBattleText")
        return blocks.trainer_block(
            label, cls, party, flag, seen_label=seen_l,
            defeated_label=defeated_l, after_label=after_l,
            seen=seen, defeated=defeated, after=after)


class GenericTrainer(AddTrainer):
    """polishedcrystal's `OBJECTTYPE_GENERICTRAINER`: a `generictrainer` macro
    and a self-contained block, local texts and the after-line falling through
    beneath it. Named for its macro, so the fork stamps it `PolishedGenericTrainer`."""
    objtype = "OBJECTTYPE_GENERICTRAINER"

    def block(self, text, label, cls, party, flag, seen, defeated, after):
        return blocks.generictrainer_block(
            label, cls, party, flag, seen=seen, defeated=defeated, after=after)
