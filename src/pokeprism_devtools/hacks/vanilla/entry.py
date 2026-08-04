"""One entry line, on the map you are looking at — the base every form shares.

Split out of :mod:`.actions` when the item ball arrived and took that module
past the size a file should be. The seam is a real one rather than a cut made
to hit a number: everything here is what an action needs *before* it knows
which list it writes to — the boxes an `object_event` slot gets, and the two
dialect forks stamped onto a class so no form ever asks the tree which tree it
is. :mod:`.actions` builds the line-only forms on it and :mod:`.itemball`
builds the one that writes a block, and neither imports the other.
"""

from __future__ import annotations

from pathlib import Path

from ... import contract
from ...contract import (FLAGS, MOVEMENTS, PALETTES, SPRITES, Action,
                               ActionError, Field, Result)
from ...asmedit import regions
from . import eventblock as eb
from .shapes import VANILLA_OBJECT


#: The boxes an `object_event` slot gets, by slot name. Built into a form in
#: the dialect's own order, so neither tree is offered the other's columns —
#: a `time` box on vanilla would write a valid number into an hour limit.
OBJECT_FIELDS: dict[str, Field] = {
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
class Entry(Action):
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
    #: Where in the file a *block* goes, for the adders that write one. The
    #: third fork, and the one with no visible symptom when it is wrong: the
    #: two trees put their scripts on opposite sides of the event header, and a
    #: block appended on the wrong side lands inside the warp list, which
    #: assembles and gives the map the wrong doors. See `asmedit/regions.py`.
    layout = regions.VANILLA
    #: Which of the four lists this action's line lives in.
    list_kind = "object"

    def __init__(self, map_const: str, **values: str) -> None:
        super().__init__(**values)
        self.map = map_const

    # -- the file ------------------------------------------------------------- #
    def _file(self, root: Path) -> tuple[Path, str]:
        """This map's file, and the label its blocks are named after. The label
        comes from the catalog rather than from the form: you picked a map, and
        the file it lives in is the tree's business, not a string anybody
        typed."""
        from .read import label_of
        label = label_of(root).get(self.map)
        if label is None:
            raise ActionError(f"{self.map} is not a map in this tree.")
        return root / f"maps/{label}.asm", label

    def _block(self, root: Path) -> tuple[eb.EventBlock, str]:
        """This map's event block, freshly parsed off disk."""
        path, label = self._file(root)
        try:
            return eb.parse_map(path, self.anchor), label
        except (eb.UnparseableEvents, contract.Unreadable) as exc:
            raise ActionError(str(exc)) from exc

    def _written(self, block: eb.EventBlock, root: Path) -> Result:
        """The staged change. Unchanged text is no edit at all — an editor you
        opened, looked at and submitted should write nothing, and say so."""
        edit = block.to_edit(root, self.describe())
        return Result(edit.detail, [edit] if edit.changed else [],
                      [] if edit.changed else ["unchanged — nothing to write"])

    def _where(self) -> str:
        return f"({self.text('y')}, {self.text('x')})"

