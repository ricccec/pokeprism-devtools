"""The actions that put something *in* a map: people, props, signs, words.

Split from :mod:`.actions`, which keeps the base class and the two actions that
wire maps to each other. The line between them is the one the tabs already draw:
a connection or a warp is about two maps, and everything here is about one.

The interesting one is :class:`AddProp`. An item ball, a TM ball, a fruit tree, a
hidden item, a rock and a boulder are one thing to a person and six things to the
engine — see `wiring/props.py` — so this is one form whose *shape* follows from
the kind you pick. That is what `fields_for` is for, and it is the reason a TM ball
has no quantity box to get wrong and a boulder has no dialogue box at all.

The kinds are a *closed list*, on purpose. The studio does not offer to place "an
object" and then ask you thirteen questions about it; it offers the half-dozen
objects it knows how to place correctly, each with everything the engine has
already decided filled in. A seventh kind is a `Prop` in `hacks/prism/eventmodel.py`
plus a branch here — which is a change to make deliberately, rather than a form
that lets you assemble a broken one out of dropdowns.
"""

from __future__ import annotations

import re

from pathlib import Path

from ..hacks.prism import eventmodel, trainerstats
from ..hacks.prism.eventflags import FlagError
from ..hacks.prism.eventheader import ListKind
from ..wiring import connections, props, removal, scaffold, warpdel
# By name, not by module: `Action.text()` is a method, and `text.reword(...)`
# sitting next to `self.text("label")` in the same three lines is a trap.
from ..wiring.text import TextError, reword
from .actions import (CLASSES, FACINGS, FLAGS, ITEMS, MOVEMENTS, PALETTES,
                      PARTIES, SPRITES, TMHMS, TREES, Action, ActionError,
                      Field, Result)

#: The kinds of prop, as the form names them. The value is the whole discriminator:
#: `fields_for` reads it, `run` dispatches on it, and it is the one string in the
#: studio that decides how the engine will read two bytes.
ITEMBALL, TMHM, TREE, HIDDEN = "item ball", "TM/HM ball", "fruit tree", "hidden item"
#: The two that are not people and never were. Their names are the keys of
#: `eventmodel.PROPS`, which is where everything about them is written down.
ROCK, BOULDER = "rock", "boulder"
PROP_KINDS = (ITEMBALL, TMHM, TREE, HIDDEN, ROCK, BOULDER)


class _Placed(Action):
    """An action that puts a body somewhere on this map."""

    def __init__(self, map_const: str, **values: str) -> None:
        super().__init__(**values)
        self.map = map_const

    def _scaffolded(self, s: scaffold.Scaffold) -> Result:
        notes = []
        if s.flag:
            notes.append(f"allocated {s.flag}")
        return Result(s.summary, s.changes, notes)


_BODY = (
    Field("sprite", "Sprite", choices=SPRITES, default="SPRITE_GRAMPS"),
    Field("y", "Y", kind="int"),
    Field("x", "X", kind="int"),
    Field("movement", "Movement", choices=MOVEMENTS,
          default="SPRITEMOVEDATA_STANDING_DOWN"),
    Field("palette", "Palette", choices=PALETTES, default="PAL_OW_RED"),
)

#: An object's event flag. Blank is not "none" — it is `-1`, which the engine reads
#: as "always here", and which is the right answer for most people in most towns.
#: A name that already exists is reused (two objects can share a flag, and in this
#: repo some do); a name that doesn't is allocated. That is why the field is a
#: combo over the flags rather than a list of them: the list is where you look, not
#: what you are held to.
_FLAG_HELP = ("blank = always there. An existing flag gates them on it; "
              "a new name creates the flag.")


class AddNpc(_Placed):
    name = "npc"
    title = "Add an NPC"
    FIELDS = _BODY + (
        Field("flag", "Event flag", choices=FLAGS, help=_FLAG_HELP),
        Field("text", "What they say", kind="lines",
              help="one line per textbox line; a blank line starts a new box"),
    )

    def describe(self) -> str:
        return f"NPC {self.text('sprite')} at ({self.text('y')}, {self.text('x')})"

    def run(self, root: Path) -> Result:
        try:
            return self._scaffolded(scaffold.add_npc(
                root, self.map, self.obj(), self.pages("text"),
                flag=self.text("flag") or None))
        except scaffold.ScaffoldError as e:
            raise ActionError(str(e)) from e


class AddTrainer(_Placed):
    name = "trainer"
    title = "Add a trainer"
    FIELDS = (
        Field("cls", "Class", choices=CLASSES, default="YOUNGSTER",
              help="picking one dresses them the way this class is usually dressed"),
        Field("party", "Party", choices=PARTIES, depends=("cls",), default="1",
              help="an existing party of this class — the number is what gets written"),
        *_BODY,
        Field("flag", "Beaten flag", choices=FLAGS,
              help="blank and one is generated. It is what stops them re-battling you."),
        Field("sight", "Sight", kind="int", default="1",
              help="tiles away they notice you; above 1 they WALK to you"),
        Field("seen", "On spotting you", kind="lines"),
        Field("defeated", "On losing", kind="lines"),
        Field("after", "Afterwards", kind="lines"),
    )

    @classmethod
    def follows(cls, root: Path, changed: str, values: dict[str, str]) -> dict[str, str]:
        """A class knows what it wears. Counted from the repo, not from the name —
        `SKIER` is `SPRITE_BUENA` in all three of the ones that exist."""
        if changed != "cls":
            return {}
        return trainerstats.defaults(root, values.get("cls", "").strip())

    def describe(self) -> str:
        return (f"{self.text('cls')} at ({self.text('y')}, {self.text('x')}) "
                f"[party {self.text('party')}]")

    def run(self, root: Path) -> Result:
        try:
            s = scaffold.add_trainer(
                root, self.map, self.obj(), self.text("cls"),
                seen=self.pages("seen"), defeated=self.pages("defeated"),
                after=self.pages("after"), party=self._party(),
                flag=self.text("flag") or None, sight=self.integer("sight"),
            )
        except scaffold.ScaffoldError as e:
            raise ActionError(str(e)) from e
        return self._scaffolded(s)

    def _party(self) -> int:
        """The party's 1-based ordinal, off the front of whatever the combo left in
        the box — the rows read `3  Joey — RATTATA 4`, and only the 3 is written.

        **Making a party is not offered here**, deliberately: a party is appended to
        a class's group file and every trainer in the repo cites parties by
        position, so a new one is a change to a shared file made in passing while
        you were placing an NPC. Pick an existing one; `trainers/groups/` is where
        you write a new one, and it is a different job.
        """
        raw = self.text("party")
        if m := re.match(r"\s*(\d+)", raw):
            return int(m.group(1))
        raise ActionError(
            f"{raw!r} is not a party — pick one of this class's parties from the "
            f"list. (Making a new party isn't done from here.)"
        )


class AddProp(_Placed):
    """The one form for everything on a map that is not a person.

    Six kinds, six shapes. The kind is the first field and it `reveals` the rest —
    because the fields a kind doesn't have are exactly the fields that are a bug if
    you fill them in: a quantity on a TM ball is read by the engine as the *item*,
    and an item ball with a TM in its item slot hands you zero of it.

    A rock and a boulder are the extreme case of that, and the reason they are
    here rather than under NPCs. They *are* `person_event`s — the engine has one
    list of things that stand on tiles — so the studio offered them a sprite, a
    movement, an event flag and a box to type their dialogue into, all four of
    which are wrong. What a boulder actually has is a position and a colour. The
    rest was decided by whoever wrote `strengthboulder`.
    """

    name = "prop"
    title = "Add an object"

    #: The six, on a list you pick from — because they are not a thing you could
    #: know to type. Still a combo and not a `Select`, so the six are an offer and
    #: a seventh word is refused by `run` with the list in the message, which is
    #: the one place that can say *why* there is no seventh.
    _KIND = Field("kind", "Kind", options=PROP_KINDS, default=ITEMBALL, reveals=True,
                  help="what it is decides the rest of the form")
    _WHERE = (Field("y", "Y", kind="int"), Field("x", "X", kind="int"))
    _FLAG = Field("flag", "Event flag", choices=FLAGS,
                  help="blank and one is generated. It is what remembers you took it.")

    FIELDS = (_KIND, *_WHERE,
              Field("item", "Item", choices=ITEMS, default="POTION"),
              Field("quantity", "How many", kind="int", default="1"),
              _FLAG)

    @classmethod
    def fields_for(cls, values: dict[str, str]) -> tuple[Field, ...]:
        kind = (values.get("kind") or ITEMBALL).strip()
        if kind == TMHM:
            # No quantity: the engine reads one byte, out of the slot an item ball
            # keeps its count in. A TM is one TM.
            return (cls._KIND, *cls._WHERE,
                    Field("item", "TM or HM", choices=TMHMS, default="TM_HEADBUTT"),
                    cls._FLAG)
        if kind == TREE:
            # No flag: a tree regrows. A flag would make the tree itself disappear
            # the first time you shook it.
            return (cls._KIND, *cls._WHERE,
                    Field("tree", "Tree", choices=TREES, default="RED_APRICORN_TREE_1",
                          help="the id decides the fruit — and its regrow timer, "
                               "which trees sharing an id share"))
        if kind == HIDDEN:
            # No sprite, because there is nothing to draw: it's a signpost.
            return (cls._KIND, *cls._WHERE,
                    Field("item", "Item", choices=ITEMS, default="NUGGET"),
                    cls._FLAG)
        if kind in (ROCK, BOULDER):
            # No flag, no script, no dialogue, and no movement. All four are the
            # engine's, and every one of them the form offered was a way to write a
            # boulder that is not a boulder. See `wiring/props.add_prop`.
            return (cls._KIND, *cls._WHERE,
                    Field("palette", "Palette", choices=PALETTES,
                          default=eventmodel.PROPS[kind].palette,
                          help="the only thing about one of these that is yours"))
        return cls.FIELDS

    def describe(self) -> str:
        what = self.text("tree") or self.text("item")
        where = f"({self.text('y')}, {self.text('x')})"
        return f"{self._kind} {what} at {where}".replace("  ", " ")

    @property
    def _kind(self) -> str:
        return self.text("kind") or ITEMBALL

    def run(self, root: Path) -> Result:
        y, x = self.coords()
        flag = self.text("flag") or None
        try:
            if self._kind == TMHM:
                s = props.add_tmhm_ball(root, self.map, y, x, self.text("item"),
                                        flag=flag)
            elif self._kind == TREE:
                s = props.add_fruit_tree(root, self.map, y, x, self.text("tree"))
            elif self._kind == HIDDEN:
                s = props.add_hidden_item(root, self.map, y, x, self.text("item"),
                                          flag=flag)
            elif self._kind == ITEMBALL:
                s = props.add_itemball(root, self.map, y, x, self.text("item"),
                                       quantity=self.integer("quantity", 1),
                                       flag=flag)
            elif self._kind in (ROCK, BOULDER):
                s = props.add_prop(root, self.map, y, x, self._kind,
                                   palette=self.text("palette") or None)
            else:
                raise ActionError(
                    f"{self._kind!r} is not a kind of object — "
                    f"it is one of: {', '.join(PROP_KINDS)}")
        except scaffold.ScaffoldError as e:
            raise ActionError(str(e)) from e
        return self._scaffolded(s)


class AddSignpost(_Placed):
    name = "sign"
    title = "Add a signpost"
    FIELDS = (
        Field("y", "Y", kind="int"),
        Field("x", "X", kind="int"),
        Field("facing", "Read when facing", choices=FACINGS, default="",
              help="leave blank and it reads from any side, like a gym sign"),
        # A sign's text is measured in the *speech* box, not the signpost one,
        # obvious as the opposite sounds. SIGNPOST_TEXT and the facing signs both
        # end in a `jumptext`, which draws in the ordinary bubble. Only
        # SIGNPOST_LOAD opens the full-screen signpost window — see
        # `dialogue.sign_owners`. Measure this against 17 columns and every sign
        # you write is one tile too wide, in-game, and nowhere else.
        Field("text", "What it says", kind="lines",
              help="one line per textbox line; a blank line starts a new box"),
    )

    def describe(self) -> str:
        return f"sign at ({self.text('y')}, {self.text('x')})"

    def run(self, root: Path) -> Result:
        y, x = self.coords()
        try:
            return self._scaffolded(scaffold.add_signpost(
                root, self.map, y, x, self.pages("text"),
                facing=self.text("facing") or None))
        except scaffold.ScaffoldError as e:
            raise ActionError(str(e)) from e


class EditText(_Placed):
    """Reword a text block that is already in the game.

    Reached by *picking one* — `e` on a row whose object says something. What
    arrives here is prose; the macros come back from the block itself.
    """

    name = "reword"
    title = "Edit dialogue"
    FIELDS = (
        Field("label", "Text block", kind="fixed"),
        Field("text", "What it says", kind="lines"),
    )

    def describe(self) -> str:
        return f"reword {self.text('label')}"

    def run(self, root: Path) -> Result:
        try:
            edit = reword(root, self.map, self.text("label"),
                          self.values.get("text", ""))
        except TextError as e:
            raise ActionError(str(e)) from e
        return Result(edit.detail, [edit] if edit.changed else [],
                      [] if edit.changed else ["unchanged — nothing to write"])


class Remove(_Placed):
    """Take one object out of a map.

    `index` + `kind` say **which** object, and `label`/`y`/`x` only say what to
    *call* it on the confirm screen. That split matters: Owsauri's game corner has
    sixteen slot machines running the identical script, so the name is not an
    identity and never was. You did not describe the thing you want gone — you
    pointed at it, and the row you pointed at knows its own position.
    """
    name = "remove"
    title = "Remove an object"
    FIELDS = (
        Field("index", "Entry", kind="fixed", default="",
              help="its position in the list — which is what identifies it"),
        Field("kind", "List", kind="fixed", default="",
              help="which event list it lives in"),
        Field("label", "Label", help="the script label it points at"),
        Field("y", "Y", kind="int", default="", help="or its position, if it has no label"),
        Field("x", "X", kind="int", default=""),
    )

    def describe(self) -> str:
        what = (self.text("label") or f"({self.text('y')}, {self.text('x')})"
                if self.text("label") or self.text("y")
                else f"entry #{self.integer('index') + 1}")
        return f"remove {what} from {self.map}"

    def run(self, root: Path) -> Result:
        try:
            r = removal.remove(root, self.map, kind=self._kind(), **self._named())
        except (removal.RemovalError, FlagError) as e:
            # A FlagError is a refusal too. It reached the app as a crash until a
            # sweep of every deletable row in the repo found the two people whose
            # flag is written `EVENT_X | $8000` — a name the allocator has never
            # heard of, because it is an expression and not a name.
            raise ActionError(str(e)) from e
        notes = list(r.warnings)
        if r.freed_flag:
            notes.append(f"freed {r.freed_flag}")
        return Result(r.summary, r.changes, notes)

    def _named(self) -> dict:
        """How to find it. The index wins when there is one, because it is the only
        one of these that cannot be ambiguous."""
        if self.text("index"):
            return {"index": self.integer("index")}
        label = self.text("label") or None
        at = self.coords() if (self.text("y") and self.text("x")) else None
        if (label is None) == (at is None):
            raise ActionError("name the object by its label or by its position, not both")
        return {"label": label} if label else {"at": at}

    def _kind(self) -> ListKind | None:
        """Which list to look in. A name is only unique *within* one — CaperRidge
        runs the same script from a trigger and from an NPC — so the row you
        pointed at says which, and without it neither could be deleted."""
        raw = self.text("kind")
        try:
            return ListKind(raw) if raw else None
        except ValueError:
            raise ActionError(f"{raw!r} is not an event list") from None


class RemoveWarp(_Placed):
    """A warp is the one thing whose deletion is not local to its map.

    `warp_to` is a *position* in this map's warp list, so every door in the repo
    that counted its way past this one has to be pulled back a step. The preview
    shows every file that touches, which for a busy map is a dozen — and that is
    not the preview being noisy, it is the true cost of the operation.
    """
    name = "remove warp"
    title = "Remove a warp"
    FIELDS = (Field("index", "Warp", kind="fixed"),)

    def describe(self) -> str:
        return f"remove warp #{self.integer('index') + 1} from {self.map}"

    def run(self, root: Path) -> Result:
        # Splicing the entry out of prism's own map file is prism's job — only
        # prism parses prism's event header — and `warpdel` fixes the repo
        # behind it from a grammar prism declares. That split is exactly what
        # lets the family reuse the rule through a grammar of its own.
        from ..hacks.prism import write as prism_write
        try:
            d = prism_write.delete_warp(root, self.map, self.integer("index"))
        except warpdel.WarpDelError as e:
            raise ActionError(str(e)) from e
        return Result(d.summary, d.changes, d.warnings)


class Disconnect(_Placed):
    """The mirror of `Connect`, and safe for the same reason adding one is: a
    connection is named by its direction, not by a position, so nothing in the
    repo counts its way to it and removing one renumbers nothing."""
    name = "disconnect"
    title = "Remove a connection"
    FIELDS = (Field("direction", "Direction", kind="fixed"),)

    def describe(self) -> str:
        return f"remove {self.map}'s {self.text('direction')} connection"

    def run(self, root: Path) -> Result:
        try:
            edit, notes = connections.disconnect(root, self.map,
                                                 self.text("direction"))
        except connections.WiringError as e:
            raise ActionError(str(e)) from e
        return Result(edit.detail, [edit] if edit.changed else [],
                      notes or ([] if edit.changed else ["unchanged"]))
