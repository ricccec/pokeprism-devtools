"""How prism answers a resize — the tree-specific half of `asmedit/mapresize.py`.

Nothing here is arithmetic. Every method is one prism fact: where the dimension
line lives and in which order it writes its two numbers, which file holds the
block grid, what a map's neighbours are. The geometry that uses these answers is
written once, next door, and does not know which tree it is running against.
"""

from __future__ import annotations

from pathlib import Path

from ...shared.edits import Edit
from ...contract import Action, ActionError, Field, Result
from ...asmedit import mapresize
from ...asmedit.mapresize import MapShape, Standing
from .objedit import MapEdit, S_X, S_Y, T_X, T_Y, W_X, W_Y, X, Y
from ...asmedit.editvocab import EditError, spliced
from . import blocksrc, eventheader as eh, mapsource

#: `mapgroup NAME, H, W` — height first. See `asmedit/mapresize`'s docstring for
#: why that one bit is worth a named field.
SHAPE = MapShape(path="constants/map_dimension_constants.asm",
                 macro="mapgroup", height_first=True)

#: Where y/x sit in each list's entry, per `hacks/prism/objedit.py`'s own constants —
#: the same ones `edit_npc`/`edit_signpost`/`edit_trigger` already splice.
_MOVES: dict[eh.ListKind, tuple[int, int]] = {
    eh.ListKind.WARPS: (W_Y, W_X),
    eh.ListKind.COORD_EVENTS: (T_Y, T_X),
    eh.ListKind.BG_EVENTS: (S_Y, S_X),
    eh.ListKind.OBJECT_EVENTS: (Y, X),
}


class PrismResize:
    """Prism's answers. Stateless — the caches live in the parsers it calls."""

    shape = SHAPE

    def label_of(self, root: Path, const: str) -> str:
        label = {c: l for l, c in mapsource.header_pairs(root)}.get(const)
        if label is None:
            raise EditError(
                f"{const} has no map_header_2 — wire the map first")
        return label

    def blk(self, root: Path, label: str) -> Path:
        labels = mapsource.blockdata_labels(root)
        target = labels.get(label)
        if target is None:
            raise EditError(
                f"no `{label}_BlockData:` in maps/blockdata.asm — the map has "
                f"no blocks wired to it")
        aliases = sorted(l for l, t in labels.items()
                         if t == target and l != label)
        if aliases:
            raise EditError(
                f"{label}'s block data is shared with {', '.join(aliases)} — "
                f"resizing it would corrupt every map that aliases it, since "
                f"their dimension constants don't change with it")
        return root / (target[:-3] if target.endswith(".lz") else target)

    def read_grid(self, path: Path, height: int, width: int) -> bytes:
        try:
            return blocksrc.read_blk(path, height, width)
        except blocksrc.BlockSourceError as exc:
            raise EditError(str(exc)) from exc

    def border_block(self, root: Path, label: str) -> str:
        return self._secondary(root, label).border_block

    def connections(self, root: Path, label: str) -> int:
        return len(self._secondary(root, label).connections)

    def standing(self, root: Path, label: str) -> list[Standing]:
        try:
            header = eh.parse_map(root / "maps" / f"{label}.asm")
        except eh.UnparseableHeader as exc:
            raise EditError(str(exc)) from exc
        out = []
        for kind in eh.LIST_ORDER:
            for entry in header.list_of(kind).entries:
                y, x = entry.coords
                if y is not None and x is not None:
                    out.append(Standing(entry.macro, y, x))
        return out

    def shift(self, root: Path, const: str, dy: int,
              dx: int) -> tuple[Edit, int]:
        ctx = MapEdit(root, const)
        moved = 0
        for kind in eh.LIST_ORDER:
            yi, xi = _MOVES[kind]
            for i in range(len(ctx.header.list_of(kind).entries)):
                entry = ctx.entry(kind, i)
                y, x = entry.int_arg(yi), entry.int_arg(xi)
                if y is None or x is None:
                    continue
                args = spliced(entry, {yi: y + dy, xi: x + dx})
                if args != entry.args:
                    ctx.replace_entry(kind, i, args)
                    moved += 1
        return ctx.done("", "").edits[0], moved

    def _secondary(self, root: Path, label: str):
        secondary = mapsource.secondary_header(root, label)
        if secondary is None:
            raise EditError(
                f"{label} has no map_header_2 in maps/second_map_headers.asm")
        return secondary


DIALECT = PrismResize()


class ResizeMap(Action):
    """Growing or shrinking a map from an edge — the form half of the above.

    `e` on the Attributes tab changes what a map is *called*, and
    `hacks/prism/mapedit.py` says why its size is not one of the fields there:
    changing it without resizing the `.blk` behind it corrupts the map. This is
    the `s` key that does the resize properly, keeping the dimension constant,
    the block grid and (at the top or left) every object's coordinates all
    moving together.

    Reached by its own binding, not by pointing at a row: a map's shape is not a
    thing you select on the grid, it is the grid.

    The family's copy is `hacks/vanilla/resize.py`, and the two are deliberate
    near-duplicates. They shared one class in `studio/` until prism importing it
    made prism depend on the IDE; the form is four fields and one call, and the
    plan's rule for adapters holds here — never compare across them.
    """
    name = "resize"
    title = "Resize the map"
    #: Which tree's answers the geometry runs against. A class attribute and not
    #: an argument, because a form is built as `action(map_const, **values)` and
    #: there is no third seat — the same reason `hacks/vanilla/actions.py`
    #: stamps its dialect forks rather than passing them. Prism has exactly one,
    #: so it is stamped here rather than by a factory.
    dialect = DIALECT
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
                self.integer("blocks", 1), self.text("fill") or None,
                dialect=self.dialect)
        except mapresize.EditError as exc:
            raise ActionError(str(exc)) from exc
        return Result(change.summary, change.changes, change.notes)
