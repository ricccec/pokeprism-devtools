"""How the pokecrystal family answers a resize.

The mirror of `hacks/prism/resize.py`, and the same shape: no arithmetic, only
this family's answers to the questions `wiring/mapresize.py` asks. Two of those
answers are transpositions of prism's, and both are the kind that assembles
perfectly while being wrong:

* the **dimension macro** is `map_const NAME, W, H` — width first, where prism's
  `mapgroup` is height first. `MapShape` carries that bit; see the argument in
  `wiring/mapresize.py`.
* the **coordinate args** are `x, y` — x first, where prism's entries lead with
  y. Every family list agrees on it (`shapes.VANILLA_OBJECT.slots` opens
  `("x", "y", …)` and warp/coord/bg all read `_at(a, 0), _at(a, 1)` the same
  way), so it is one pair of constants rather than a table.

One dialect serves both trees, forked on two things the mount declares: the
anchor a map file opens with, and **where a map's blocks are indexed** — the
two trees do not spell the block label the same way (`<Label>_Blocks:` against
`<Label>_BlockData:`) and do not organise `data/maps/blocks.asm` the same way,
so each read adapter already owns a `_blk` and the dialect is handed the right
one rather than guessing from the anchor, which does not imply it.

That fork is load-bearing in a second way. Both trees let several maps stack
their labels on one `INCBIN`, and vanilla does it *constantly*: 436 labels
against 302 INCBINs, so roughly 40% of its maps share a grid with a twin
(`NationalPark` and `NationalParkBugContest` are the same blocks). Resizing one
would silently corrupt the other, whose dimension constant does not move with
it — so shared blocks refuse, and for this family that refusal is the common
case rather than a guard on an edge.
"""

from __future__ import annotations

from pathlib import Path

from ...contract import Action, ActionError, Field, Result
from ...shared.edits import Edit
from ...wiring import mapresize
from ...wiring.mapresize import MapShape, Standing
from ...wiring.editvocab import EditError
from . import read as r
from . import eventblock as eb

#: `map_const NAME, W, H` — width first. Measured, not assumed: PlayersHouse1F
#: is `map_const …, 5, 4` and its .blk is exactly 20 bytes.
SHAPE = MapShape(path="constants/map_constants.asm",
                 macro="map_const", height_first=False)

#: Where x and y sit in a family entry — every list, both trees.
_X, _Y = 0, 1


class FamilyResize:
    """The family's answers, holding the two forks its tree declares."""

    shape = SHAPE

    def __init__(self, anchor: str = "_MapEvents", blk_index=None) -> None:
        self.anchor = anchor
        #: `label -> the blocks file its INCBIN names`, this tree's own.
        self.blk_index = blk_index or r._blk

    def label_of(self, root: Path, const: str) -> str:
        label = r.label_of(root).get(const)
        if label is None:
            raise EditError(
                f"{const} has no map in data/maps/maps.asm — wire the map first")
        return label

    def blk(self, root: Path, label: str) -> Path:
        blocks = self.blk_index(root)
        target = blocks.get(label)
        if target is None:
            raise EditError(
                f"no blocks are wired to {label} in data/maps/blocks.asm")
        aliases = sorted(l for l, t in blocks.items()
                         if t == target and l != label)
        if aliases:
            raise EditError(
                f"{label}'s block data is shared with {', '.join(aliases)} — "
                f"resizing it would corrupt every map that aliases it, since "
                f"their dimension constants don't change with it")
        # Polished INCBINs the *compressed* grid (`<Label>.ablk.lzp`), which the
        # build generates; the file a human draws and this tool must rewrite is
        # the `.ablk` beside it. Vanilla INCBINs its `.blk` directly and this
        # strips nothing. Same move prism makes for `.lz`, one suffix along.
        return root / (target[:-4] if target.endswith(".lzp") else target)

    def read_grid(self, path: Path, height: int, width: int) -> bytes:
        """Plain bytes: this family stores block data uncompressed, so unlike
        prism there is no `.lz` to fall back to."""
        try:
            data = path.read_bytes()
        except FileNotFoundError as exc:
            raise EditError(f"{path} does not exist") from exc
        need = height * width
        if len(data) < need:
            raise EditError(
                f"{path} is {len(data)} bytes but the map is {height}x{width} "
                f"= {need} — the engine would read past the end of it")
        return data[:need]

    def border_block(self, root: Path, label: str) -> str:
        a = r.attrs(root).get(label)
        if a is None or not a.border:
            raise EditError(
                f"{label} has no border block in data/maps/attributes.asm — "
                f"name a fill block instead")
        return a.border

    def connections(self, root: Path, label: str) -> int:
        a = r.attrs(root).get(label)
        return len(a.connections) if a else 0

    def standing(self, root: Path, label: str) -> list[Standing]:
        block = self._block(root, label)
        out = []
        for kind in eb.LIST_ORDER:
            for entry in block.lists[kind].entries:
                y, x = _int(entry.args, _Y), _int(entry.args, _X)
                if y is not None and x is not None:
                    out.append(Standing(eb.LIST_MACROS[kind], y, x))
        return out

    def shift(self, root: Path, const: str, dy: int,
              dx: int) -> tuple[Edit, int]:
        label = self.label_of(root, const)
        block = self._block(root, label)
        moved = 0
        for kind in eb.LIST_ORDER:
            for i, entry in enumerate(list(block.lists[kind].entries)):
                y, x = _int(entry.args, _Y), _int(entry.args, _X)
                if y is None or x is None:
                    continue
                args = list(entry.args)
                args[_Y], args[_X] = str(y + dy), str(x + dx)
                if args != entry.args:
                    block.replace_entry(kind, i, args)
                    moved += 1
        return block.to_edit(root, f"{moved} coordinate(s) shifted"), moved

    def _block(self, root: Path, label: str) -> eb.EventBlock:
        try:
            return eb.parse_map(root / f"maps/{label}.asm", self.anchor)
        except eb.UnparseableEvents as exc:
            raise EditError(str(exc)) from exc


def _int(args: list[str], i: int) -> int | None:
    """The coordinate at `i`, or None when it is not a plain number — a
    constant-valued coordinate is not ours to do arithmetic on."""
    if len(args) <= i:
        return None
    try:
        return int(args[i].strip())
    except ValueError:
        return None


def polished() -> FamilyResize:
    """Polished's fork. A function so that importing this module does not drag
    in the polished read adapter for a vanilla tree."""
    from ..polished import read as pr
    return FamilyResize("_MapScriptHeader", pr._blk)


VANILLA = FamilyResize("_MapEvents", r._blk)


class ResizeMap(Action):
    """Growing or shrinking a map from an edge — the form half of the above.

    `e` on the Attributes tab changes what a map is *called*, and
    `hacks/vanilla/mapedit.py` says why its size is not one of the fields there:
    changing it without resizing the `.blk` behind it corrupts the map. This is
    the `s` key that does the resize properly, keeping the dimension constant,
    the block grid and (at the top or left) every object's coordinates all
    moving together.

    Reached by its own binding, not by pointing at a row: a map's shape is not a
    thing you select on the grid, it is the grid.

    Prism's copy is `hacks/prism/resize.py`, and the two are deliberate
    near-duplicates. They shared one class in `studio/` until prism importing it
    made prism depend on the IDE; the form is four fields and one call, and the
    plan's rule for adapters holds here — never compare across them.
    """
    name = "resize"
    title = "Resize the map"
    #: Which tree's answers the geometry runs against. A class attribute and not
    #: an argument, because a form is built as `action(map_const, **values)` and
    #: there is no third seat — the same reason `.actions` stamps its dialect
    #: forks rather than passing them. Stamped by :func:`resize_for`, because
    #: this one class serves both family trees and they answer differently.
    dialect = None
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


def resize_for(dialect, tag: str) -> type[ResizeMap]:
    """This form, bound to one family tree's answers. The form itself is
    dialect-free — an edge, a mode and a count mean the same thing in every tree
    — so what forks is only what it resizes *through*."""
    return type(f"{tag}ResizeMap", (ResizeMap,),
                {"dialect": dialect, "__doc__": ResizeMap.__doc__})
