"""What the studio stages: *actions*, not edits.

This is the one place the studio deliberately departs from the obvious design,
and the reason is written down in `shared/edits.py`: an :class:`Edit` carries the
**whole** file text plus the text it was derived from. Two edits built against
the same starting file and then applied one after the other do not merge — the
second overwrites the first, and the first silently never happened. Add two NPCs
before saving and the flag allocator hands both the same `const skip` slot,
because when the second one looked, the first hadn't been written yet.

So a queue of pending Edits — stage them all, flush on save — is precisely the
bug that module exists to prevent, and `apply_edits` raises `StaleEdit` rather
than let it happen.

What the studio stages instead is the *intent*: "put a Sage at (5, 7) in
CastroForest". An intent can be replayed, and replaying it is what makes a stack
of changes safe — each action is built against the tree as the previous ones left
it, which is the "build an edit, apply it, then build the next" rule holding by
construction rather than by hope. It also means the diff you approve comes out of
the identical code path that will run for real: the preview is a rehearsal, not a
model of one.

Each action declares its fields, so the TUI builds its own form and its own
autocomplete from that declaration and knows nothing about NPCs or connections.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ..shared import trainerparty
from ..shared.edits import Edit
from ..wiring import connections, removal, scaffold, warps

#: A field's `choices` names a set of constants the session can enumerate; the
#: form turns it into autocomplete. Empty means free text.
MAPS = "maps"
SPRITES = "sprites"
MOVEMENTS = "movements"
PALETTES = "palettes"
ITEMS = "items"
CLASSES = "classes"
DIRECTIONS = "directions"
FACINGS = "facings"


class ActionError(RuntimeError):
    """The action can't be built from what the form was given. Carries a message
    meant for a human — the wiring layer's errors already read that way."""


@dataclass(frozen=True)
class Field:
    name: str
    label: str
    kind: str = "text"          # text | int | lines
    default: str = ""
    choices: str = ""
    help: str = ""
    #: For `lines`: which box this text is drawn in, so the preview measures it
    #: against the right width. A sign is a different shape from a speech bubble
    #: and the same sentence fits one and not the other.
    box: str = "speech"


@dataclass
class Result:
    """What an action did once it ran. `notes` are things the wiring layer
    decided the human must know — an orphaned party, a flag left allocated."""
    summary: str
    edits: list[Edit] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


class Action:
    """One staged change. Subclasses declare FIELDS and implement `run`."""

    name = "action"
    title = "Action"
    FIELDS: tuple[Field, ...] = ()

    def __init__(self, **values: str) -> None:
        self.values = values

    def __str__(self) -> str:
        return self.describe()

    def describe(self) -> str:
        return self.title

    def run(self, root: Path) -> Result:
        raise NotImplementedError

    # -- reading the form ---------------------------------------------------- #
    def text(self, name: str) -> str:
        return (self.values.get(name) or "").strip()

    def integer(self, name: str) -> int:
        raw = self.text(name)
        try:
            return int(raw, 0)
        except ValueError:
            raise ActionError(f"{name} must be a number, not {raw!r}") from None

    def coords(self, y: str = "y", x: str = "x") -> tuple[int, int]:
        return self.integer(y), self.integer(x)

    def pages(self, name: str) -> list[list[str]]:
        """A text area into dialogue pages: one line per line, a blank line
        starts a new textbox. Empty is an error — every script here points at
        text, and text that doesn't exist assembles into a jump to nowhere."""
        raw = (self.values.get(name) or "").replace("\r\n", "\n")
        pages, current = [], []
        for line in raw.split("\n"):
            if line.strip():
                current.append(line.strip())
            elif current:
                pages.append(current)
                current = []
        if current:
            pages.append(current)
        if not pages:
            raise ActionError(f"{name} can't be empty — the script has to say something")
        return pages

    def obj(self) -> scaffold.Object:
        y, x = self.coords()
        return scaffold.Object(
            sprite=self.text("sprite"), y=y, x=x,
            movement=self.text("movement") or "SPRITEMOVEDATA_STANDING_DOWN",
            palette=self.text("palette") or "PAL_OW_RED",
        )


# --------------------------------------------------------------------------- #
# wiring                                                                      #
# --------------------------------------------------------------------------- #

class Connect(Action):
    name = "connect"
    title = "Connect a neighbouring map"
    FIELDS = (
        Field("b", "Neighbour", choices=MAPS, help="the map on the other side"),
        Field("direction", "Direction", choices=DIRECTIONS,
              help="which side of THIS map the neighbour sits on"),
        Field("offset", "Offset", kind="int", default="0",
              help="how far the neighbour slides along the shared edge, in blocks"),
    )

    def __init__(self, a: str, **values: str) -> None:
        super().__init__(**values)
        self.a = a

    def describe(self) -> str:
        return (f"connect {self.text('b')} {self.text('direction')} of {self.a} "
                f"at offset {self.text('offset')}")

    def run(self, root: Path) -> Result:
        try:
            edit, conns = connections.connect(
                root, self.a, self.text("direction"), self.text("b"), self.integer("offset"))
        except connections.WiringError as e:
            raise ActionError(str(e)) from e
        return Result(edit.detail, [edit] if edit.changed else [],
                      [] if edit.changed else ["already connected — nothing to do"])


class AddWarp(Action):
    name = "warp"
    title = "Add a warp (both ways)"
    FIELDS = (
        Field("y", "Y here", kind="int", help="where you step in on THIS map"),
        Field("x", "X here", kind="int"),
        Field("b", "Destination", choices=MAPS),
        Field("by", "Y there", kind="int", help="where you come out"),
        Field("bx", "X there", kind="int"),
    )

    def __init__(self, a: str, **values: str) -> None:
        super().__init__(**values)
        self.a = a

    def describe(self) -> str:
        return (f"warp {self.a} ({self.text('y')}, {self.text('x')}) <-> "
                f"{self.text('b')} ({self.text('by')}, {self.text('bx')})")

    def run(self, root: Path) -> Result:
        try:
            edits, (wa, wb) = warps.add_paired_warp(
                root, self.a, self.coords(), self.text("b"), self.coords("by", "bx"))
        except warps.WarpError as e:
            raise ActionError(str(e)) from e
        return Result(
            f"{self.a} warp #{wa.index} <-> {self.text('b')} warp #{wb.index}",
            [e for e in edits if e.changed],
        )


# --------------------------------------------------------------------------- #
# content                                                                     #
# --------------------------------------------------------------------------- #

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


class AddNpc(_Placed):
    name = "npc"
    title = "Add an NPC"
    FIELDS = _BODY + (
        Field("text", "What they say", kind="lines",
              help="one line per textbox line; a blank line starts a new box"),
    )

    def describe(self) -> str:
        return f"NPC {self.text('sprite')} at ({self.text('y')}, {self.text('x')})"

    def run(self, root: Path) -> Result:
        try:
            return self._scaffolded(
                scaffold.add_npc(root, self.map, self.obj(), self.pages("text")))
        except scaffold.ScaffoldError as e:
            raise ActionError(str(e)) from e


class AddTrainer(_Placed):
    name = "trainer"
    title = "Add a trainer"
    FIELDS = _BODY + (
        Field("cls", "Class", choices=CLASSES, default="YOUNGSTER"),
        Field("party", "Party", default="1",
              help="an existing party number, or `Name: 5 PIDGEY, 6 RATTATA` to append one"),
        Field("sight", "Sight", kind="int", default="1",
              help="tiles away they notice you; above 1 they WALK to you"),
        Field("seen", "On spotting you", kind="lines"),
        Field("defeated", "On losing", kind="lines"),
        Field("after", "Afterwards", kind="lines"),
    )

    def describe(self) -> str:
        return (f"{self.text('cls')} at ({self.text('y')}, {self.text('x')}) "
                f"[party {self.text('party')}]")

    def run(self, root: Path) -> Result:
        party, new_party = self._party()
        try:
            s = scaffold.add_trainer(
                root, self.map, self.obj(), self.text("cls"),
                seen=self.pages("seen"), defeated=self.pages("defeated"),
                after=self.pages("after"), party=party, new_party=new_party,
                sight=self.integer("sight"),
            )
        except scaffold.ScaffoldError as e:
            raise ActionError(str(e)) from e
        result = self._scaffolded(s)
        if new_party:
            result.notes.append(f"appended {self.text('cls')} party #{s.party}")
        return result

    def _party(self) -> tuple[int | None, tuple[str, list[trainerparty.Mon], str] | None]:
        """Either an existing party index, or a new one to append. Appending is
        the only way to make a party: inserting renumbers every party below it
        and re-teams every trainer citing them by position."""
        raw = self.text("party")
        if raw.isdigit():
            return int(raw), None
        if ":" not in raw:
            raise ActionError(
                f"{raw!r} is neither a party number nor a new party — write "
                f"`Name: 5 PIDGEY, 6 RATTATA` to append one"
            )
        name, _, roster = raw.partition(":")
        mons = [self._mon(part) for part in roster.split(",") if part.strip()]
        if not mons:
            raise ActionError(f"{name.strip()} has no Pokémon in it")
        return None, (name.strip(), mons, trainerparty.NORMAL)

    @staticmethod
    def _mon(part: str) -> trainerparty.Mon:
        m = re.fullmatch(r"\s*(\d+)\s+([A-Za-z_]\w*)\s*", part)
        if not m:
            raise ActionError(f"{part.strip()!r} should read like `5 PIDGEY` — level, then species")
        return trainerparty.Mon(level=int(m.group(1)), species=m.group(2).upper())


class AddItemball(_Placed):
    name = "itemball"
    title = "Add an item ball"
    FIELDS = (
        Field("y", "Y", kind="int"),
        Field("x", "X", kind="int"),
        Field("item", "Item", choices=ITEMS, default="POTION"),
    )

    def describe(self) -> str:
        return f"{self.text('item')} ball at ({self.text('y')}, {self.text('x')})"

    def run(self, root: Path) -> Result:
        y, x = self.coords()
        try:
            return self._scaffolded(
                scaffold.add_itemball(root, self.map, y, x, self.text("item")))
        except scaffold.ScaffoldError as e:
            raise ActionError(str(e)) from e


class AddHiddenItem(_Placed):
    name = "hidden"
    title = "Add a hidden item"
    FIELDS = AddItemball.FIELDS

    def describe(self) -> str:
        return f"hidden {self.text('item')} at ({self.text('y')}, {self.text('x')})"

    def run(self, root: Path) -> Result:
        y, x = self.coords()
        try:
            return self._scaffolded(
                scaffold.add_hidden_item(root, self.map, y, x, self.text("item")))
        except scaffold.ScaffoldError as e:
            raise ActionError(str(e)) from e


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


class Remove(_Placed):
    name = "remove"
    title = "Remove an object"
    FIELDS = (
        Field("label", "Label", help="the script label it points at"),
        Field("y", "Y", kind="int", default="", help="or its position, if it has no label"),
        Field("x", "X", kind="int", default=""),
    )

    def describe(self) -> str:
        what = self.text("label") or f"({self.text('y')}, {self.text('x')})"
        return f"remove {what} from {self.map}"

    def run(self, root: Path) -> Result:
        label = self.text("label") or None
        at = self.coords() if (self.text("y") and self.text("x")) else None
        if (label is None) == (at is None):
            raise ActionError("name the object by its label or by its position, not both")
        try:
            r = removal.remove(root, self.map, label=label, at=at)
        except removal.RemovalError as e:
            raise ActionError(str(e)) from e
        notes = list(r.warnings)
        if r.freed_flag:
            notes.append(f"freed {r.freed_flag}")
        return Result(r.summary, r.changes, notes)


#: Everything the studio can do to a map, in the order the palette offers it.
CATALOG: tuple[type[Action], ...] = (
    AddNpc, AddTrainer, AddItemball, AddHiddenItem, AddSignpost,
    Remove, Connect, AddWarp,
)
