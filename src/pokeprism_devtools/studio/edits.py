"""`e` on a row: the form you added it with, opened on the thing itself.

What each of them *writes* is here. What the form is *filled in with* when it
opens — the row read back out of the source — is `prefill.py`, next door.

Every action here is a subclass of the action that *adds* the same kind, and that
is the whole design. The fields, the shapes an object's form takes, the sprite a
trainer class fills in for itself — all of it is inherited, because the questions
you ask about an NPC do not change depending on whether the NPC exists yet. What
changes is the verb, and the verb is one method.

The one thing an edit has and an add cannot is a **target**: *which* NPC. It is
not a field and it never appears on the form — you did not type which warp you
meant, you pointed at it — so it rides on :attr:`Action.target`, put there by the
form out of the row you were standing on. See `screens/forms.py`.

Two forms deliberately refuse to ask something the add form asks:

* an **object's kind** is shown and not editable. An item ball and a hidden item
  are not two settings of one thing — one is a `person_event` and the other a
  `signpost`, in different lists — so turning one into the other is a delete and
  an add, and a dropdown that quietly did both would be a dropdown that lied.
* a **trigger's script** is shown and not editable, for the same reason a text
  block's label is: you can move the trigger, and pointing it at a different
  script is not something a coordinate form should be able to do by accident.
"""

from __future__ import annotations

from pathlib import Path

from ..hacks.prism.actions import AddWarp, Connect
from ..hacks.prism.eventflags import FlagError
from ..hacks.prism.trainerparty import TrainerPartyError
from ..wiring import mapedit, objedit, props, warps
from ..wiring.scaffold import ScaffoldError
from ..wiring.text import TextError
from .actions import (FISHGROUPS, LANDMARKS, MAPS, MUSIC, PERMISSIONS, TILESETS,
                      TIMES, Action, ActionError, Field, Result)
from .content import (BOULDER, HIDDEN, ITEMBALL, ROCK, TMHM, TREE, AddNpc,
                      AddProp, AddSignpost, AddTrainer, _Placed)

#: Everything the wiring layer raises when it refuses. All of it already reads
#: like a sentence meant for a person — `removal`, `scaffold` and `objedit` are
#: careful about that — so the studio's job is to put it on the form, not to
#: reword it. Named rather than caught as `Exception`, because a TypeError in here
#: is a bug and must not be shown to the user as if it were their mistake.
REFUSALS = (objedit.EditError, warps.WarpError, ScaffoldError, TextError,
            FlagError, TrainerPartyError)


class _Edited(_Placed):
    """An action on something already in the map."""

    @property
    def at(self) -> int:
        """Which one. Absent means the form was opened without a row under it,
        which is a bug rather than a mistake — but a bell beats a traceback.

        The handle is spelled out here, into the position the wiring functions
        take — wiring is the write half of the adapter that minted it, so this
        is the handle going home, not the port reading it. Each editor already
        knows its own list; the position is the part the row contributed."""
        if self.target is None or self.target.handle is None:
            raise ActionError("nothing is selected to edit")
        return self.target.handle.index

    def _done(self, change: objedit.Change) -> Result:
        return Result(change.summary, change.changes, change.notes)

    def _prose(self, name: str) -> str | None:
        """The words out of a `lines` field, **exactly as they stand**.

        Not `Action.pages()`, which strips every line — right for an add, where
        leading spaces are a slip, and wrong for an edit, where they are somebody's
        centring: `next "  Closed due to"` on the Azalea sign is two spaces that
        mean something, and an editor that quietly removed them would be rewriting
        the words you came to read.

        None when the object has no text block at all — the form never showed the
        field, and there is nothing to reword. Not the same as *empty*, which is an
        error: a script that says nothing assembles into a jump to nowhere.
        """
        if name not in self.values:
            return None
        prose = (self.values.get(name) or "").replace("\r\n", "\n")
        if not prose.strip():
            raise ActionError(f"{name} can't be empty — the script has to say something")
        return prose


class EditNpc(_Edited, AddNpc):
    name = "editnpc"
    title = "Edit an NPC"

    @classmethod
    def fields_for(cls, values: dict[str, str]) -> tuple[Field, ...]:
        return _present(cls.FIELDS, values, "text")

    def describe(self) -> str:
        return f"edit NPC at ({self.text('y')}, {self.text('x')})"

    def run(self, root: Path) -> Result:
        try:
            return self._done(objedit.edit_npc(
                root, self.map, self.at, self.obj(),
                flag=self.text("flag") or None, prose=self._prose("text")))
        except REFUSALS as e:
            raise ActionError(str(e)) from e


class EditTrainer(_Edited, AddTrainer):
    name = "edittrainer"
    title = "Edit a trainer"

    @property
    def _party(self) -> str:
        """Not `AddTrainer._party`, which insists on a number.

        A party that is already in the file may be written as a **constant** —
        `RIVAL1_3` — and 40 trainers here are. Demanding an integer would refuse to
        open half the rivals in the game, so the text goes through as it stands and
        `objedit` resolves it. The combo still *offers* the numbered rows.
        """
        raw = self.text("party")
        if not raw:
            raise ActionError("a trainer needs a party")
        return raw.split()[0]

    @classmethod
    def fields_for(cls, values: dict[str, str]) -> tuple[Field, ...]:
        # Three texts, and 35 trainers in this repo are missing one of them — a
        # `.defeated_text` the macro names but nothing defines, an after-battle
        # text nobody ever wrote. The form asks about the ones that are there.
        return _present(cls.FIELDS, values, "seen", "defeated", "after")

    def describe(self) -> str:
        return f"edit {self.text('cls')} at ({self.text('y')}, {self.text('x')})"

    def run(self, root: Path) -> Result:
        try:
            return self._done(objedit.edit_trainer(
                root, self.map, self.at, self.obj(), self.text("cls"), self._party,
                flag=self.text("flag") or None, sight=self.integer("sight", 1),
                seen=self._prose("seen"), defeated=self._prose("defeated"),
                after=self._prose("after")))
        except REFUSALS as e:
            raise ActionError(str(e)) from e


class EditProp(_Edited, AddProp):
    """The object form, minus the one question it must not ask twice."""

    name = "editprop"
    title = "Edit an object"

    @classmethod
    def fields_for(cls, values: dict[str, str]) -> tuple[Field, ...]:
        # The kind still decides the shape — it just isn't yours to change any
        # more. Shown as `fixed`, which is what a decision made by pointing at
        # something looks like on a form.
        shape = AddProp.fields_for(values)
        return tuple(Field("kind", "Kind", kind="fixed") if f.name == "kind" else f
                     for f in shape)

    def describe(self) -> str:
        return f"edit {self._kind} at ({self.text('y')}, {self.text('x')})"

    def run(self, root: Path) -> Result:
        y, x = self.coords()
        flag = self.text("flag") or None
        try:
            if self._kind == TMHM:
                c = props.edit_tmhm_ball(root, self.map, self.at, y, x,
                                         self.text("item"), flag=flag)
            elif self._kind == TREE:
                c = props.edit_fruit_tree(root, self.map, self.at, y, x,
                                          self.text("tree"))
            elif self._kind == HIDDEN:
                c = props.edit_hidden_item(root, self.map, self.at, y, x,
                                           self.text("item"), flag=flag)
            elif self._kind == ITEMBALL:
                c = props.edit_itemball(root, self.map, self.at, y, x,
                                        self.text("item"),
                                        quantity=self.integer("quantity", 1),
                                        flag=flag)
            elif self._kind in (ROCK, BOULDER):
                c = props.edit_prop(root, self.map, self.at, y, x, self._kind,
                                    palette=self.text("palette"))
            else:
                raise ActionError(f"{self._kind!r} is not a kind of object")
        except REFUSALS as e:
            raise ActionError(str(e)) from e
        return self._done(c)


class EditSignpost(_Edited, AddSignpost):
    name = "editsign"
    title = "Edit a signpost"

    @classmethod
    def fields_for(cls, values: dict[str, str]) -> tuple[Field, ...]:
        return _present(cls.FIELDS, values, "text")

    def describe(self) -> str:
        return f"edit sign at ({self.text('y')}, {self.text('x')})"

    def run(self, root: Path) -> Result:
        y, x = self.coords()
        try:
            return self._done(objedit.edit_signpost(
                root, self.map, self.at, y, x,
                facing=self.text("facing") or None, prose=self._prose("text")))
        except REFUSALS as e:
            raise ActionError(str(e)) from e


class EditWarp(_Edited):
    """Not `AddWarp` in edit mode, and this is the one place the pattern breaks.

    Adding a warp adds *two* — the door and the way back — because a one-way door
    is almost never what anybody meant. But a warp that is already there is one
    line: where you stand, and which warp of which map you come out on. Editing it
    renumbers nothing, and its far end is somebody else's line to edit.
    """

    name = "editwarp"
    title = "Edit a warp"
    FIELDS = (
        Field("y", "Y here", kind="int", help="where you step in on THIS map"),
        Field("x", "X here", kind="int"),
        Field("b", "Destination", choices=MAPS,
              help="leave blank for a door to nowhere"),
        Field("bw", "Warp # there", kind="int", default="1",
              help="which warp of that map you come out on — its position in "
                   "that map's list, counting from 1"),
    )

    def describe(self) -> str:
        where = f"{self.text('b')} #{self.text('bw')}" if self.text("b") else "nowhere"
        return f"warp at ({self.text('y')}, {self.text('x')}) -> {where}"

    def run(self, root: Path) -> Result:
        y, x = self.coords()
        try:
            return self._done(warps.edit_warp(
                root, self.map, self.at, y, x, dest=self.text("b"),
                dest_warp=self.integer("bw", 1)))
        except REFUSALS as e:
            raise ActionError(str(e)) from e


class EditTrigger(_Edited):
    name = "edittrigger"
    title = "Edit a trigger"
    FIELDS = (
        Field("y", "Y", kind="int"),
        Field("x", "X", kind="int"),
        Field("script", "Runs", kind="fixed"),
    )

    def describe(self) -> str:
        return f"trigger at ({self.text('y')}, {self.text('x')})"

    def run(self, root: Path) -> Result:
        y, x = self.coords()
        try:
            return self._done(objedit.edit_trigger(root, self.map, self.at, y, x))
        except REFUSALS as e:
            raise ActionError(str(e)) from e


class EditMap(Action):
    """`e` on the Attributes tab. See `wiring/mapedit.py` for what is *not* here
    and why — the label, the map id, the group, the size and the conn_flags."""

    name = "editmap"
    title = "Edit the map header"
    FIELDS = (
        Field("label", "Map", kind="fixed"),
        Field("const", "Constant", kind="fixed"),
        Field("tileset", "Tileset", choices=TILESETS),
        Field("permission", "Permission", choices=PERMISSIONS,
              help="what kind of place this is — it decides bike, fly and escape rope"),
        Field("landmark", "Landmark", choices=LANDMARKS),
        Field("music", "Music", choices=MUSIC),
        Field("phone", "Phone", kind="int", default="0",
              help="the phone service group; 0 for almost everything"),
        Field("palette", "Time palette", choices=TIMES,
              help="PALETTE_DAY, PALETTE_NITE — not a sprite's palette"),
        Field("fishgroup", "Fish group", choices=FISHGROUPS),
        Field("border_block", "Border block",
              help="the block drawn outside the map's edge"),
    )

    def __init__(self, map_const: str, **values: str) -> None:
        super().__init__(**values)
        self.map = map_const

    def describe(self) -> str:
        return f"edit {self.text('label')}'s header"

    def run(self, root: Path) -> Result:
        label = self.text("label")
        new = {f: self.text(f) for f in (*mapedit.FIELDS, "border_block")}
        try:
            was = mapedit.values(root, label)
            if problems := self._unknown(root, was, new):
                raise ActionError("; ".join(problems))
            c = mapedit.edit_map(root, label, new)
        except mapedit.EditError as e:
            raise ActionError(str(e)) from e
        return Result(c.summary, c.changes, c.notes)

    def _unknown(self, root: Path, was: dict[str, str],
                 new: dict[str, str]) -> list[str]:
        """Every constant this would write must exist — **that it is now writing**.

        Only the fields that actually moved. `IntroCave`'s music is `MUSIC_NONE`,
        which is not in the music enum this checks against, and eleven maps are like
        it; validating the whole header would refuse to let you change the *tileset*
        of a map on the grounds that somebody else, years ago, wrote a music
        constant we cannot find. You are not required to fix what you did not touch
        — the same rule `objedit` keeps on the bytes.
        """
        from . import newmap
        from ..hacks.prism import consts

        out = []
        if new["permission"] != was["permission"] \
                and new["permission"] not in newmap.PERMS:
            out.append(f"permission must be one of {', '.join(newmap.PERMS)}")
        for name, (rel, prefix) in newmap.ENUMS.items():
            value = new.get(name, "")
            if not value or value == was.get(name):
                continue
            known = consts.with_prefix(root, rel, prefix)
            if value not in known:
                near = consts.suggest(value, known)
                hint = f" Did you mean {' or '.join(near)}?" if near else ""
                out.append(f"{value} is not a {name} in this repo "
                           f"({len(known)} exist).{hint}")
        return out


# --------------------------------------------------------------------------- #
# what a row opens                                                            #
# --------------------------------------------------------------------------- #

#: What each tab's dim "Add new…" row opens, keyed by the word the tab carries in
#: `Tab.adds`. One action per tab, including Objects — the six kinds are one form
#: that changes shape, rather than a menu you must choose from before you know what
#: the fields are. See `content.AddProp`.
ADDERS: dict[str, tuple[type[Action], ...]] = {
    "NPC": (AddNpc,),
    "trainer": (AddTrainer,),
    "object": (AddProp,),
    "warp": (AddWarp,),
    "signpost": (AddSignpost,),
    "connection": (Connect,),
}

#: And what `e` opens on a row that is already there, keyed by `Ref.what`.
EDITORS: dict[str, type[Action]] = {
    "npc": EditNpc,
    "trainer": EditTrainer,
    "prop": EditProp,
    "signpost": EditSignpost,
    "warp": EditWarp,
    "trigger": EditTrigger,
    "map": EditMap,
}

#: The rows `e` cannot act on yet, and why — which is the useful half, and is why
#: these are messages rather than a key that does nothing.
NOT_YET = {
    "connection": ("editing a connection means rewriting the neighbour's side and "
                   "both flag nibbles. Not wired up yet — but you can delete it "
                   "and connect it again."),
}


def _present(fields: tuple[Field, ...], values: dict[str, str],
             *prose: str) -> tuple[Field, ...]:
    """Drop the prose fields this object has no prose for.

    An NPC's `person_event` can point at a script rather than a text block; a
    signpost can be a JUMPSTD, which points at nothing at all; and a trainer can
    name a `.defeated_text` that nobody ever wrote. The prefill knows — it simply
    has no value for those — and a box offering to reword a block that does not
    exist could only fail on submit, after you had typed into it.
    """
    absent = {name for name in prose if name not in values}
    return tuple(f for f in fields if f.name not in absent)
