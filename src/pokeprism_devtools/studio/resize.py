"""Growing or shrinking a map from an edge — the form half of `wiring/mapresize.py`.

`e` on the Attributes tab changes what a map is *called* (`edits.EditMap`), and
`wiring/mapedit.py` says why its size is not one of the fields there: changing
it without resizing the `.blk` behind it corrupts the map. This is the key that
does that resize properly, keeping the dimension constant, the block grid and
(at the top or left) every object's coordinates all moving together — see
`wiring/mapresize.py`, which is where the actual splicing happens.

Reached by its own binding, not by pointing at a row: a map's shape is not a
thing you select on the grid, it is the grid.
"""

from __future__ import annotations

from pathlib import Path

from ..wiring import mapresize
from .actions import Action, ActionError, Field, Result


class ResizeMap(Action):
    name = "resize"
    title = "Resize the map"
    FIELDS = (
        Field("edge", "Edge", options=("top", "bottom", "left", "right"),
              help="which side of the map to change"),
        Field("mode", "Grow or shrink", options=("grow", "shrink"), default="grow"),
        Field("blocks", "Blocks", kind="int", default="1",
              help="how many blocks — a block is 2x2 tiles"),
        Field("fill", "Fill block", default="",
              help="block for new rows/columns (grow only); blank = the border block"),
    )

    def __init__(self, map_const: str, **values: str) -> None:
        super().__init__(**values)
        self.map = map_const

    def describe(self) -> str:
        return (f"{self.text('mode') or 'grow'} {self.map} {self.text('edge')} "
                f"by {self.integer('blocks', 1)} block(s)")

    def run(self, root: Path) -> Result:
        if not self.text("edge"):
            raise ActionError("pick an edge")
        try:
            change = mapresize.resize(
                root, self.map, self.text("edge"), self.text("mode") or "grow",
                self.integer("blocks", 1), self.text("fill") or None)
        except mapresize.EditError as exc:
            raise ActionError(str(exc)) from exc
        return Result(change.summary, change.changes, change.notes)
