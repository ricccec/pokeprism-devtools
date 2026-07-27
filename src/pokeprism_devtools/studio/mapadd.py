"""Adding a map to a family tree — the form half of `wiring/mapnew.py`.

The sibling of `studio/resize.py`, and it is instructive that this one could not
be written the same way. A resize form is dialect-*free*: an edge, a mode and a
count mean the same thing in every tree, so only what it resizes through forks.
A new map is the opposite — the questions themselves differ, because the `map`
macro does not take the same arguments in the two family trees and the blocks
are not placed by the same kind of answer.

So the fields are **built from the dialect** rather than written out. Three
groups of them:

    what the map is         label, id, group, height, width, the grid
    what its header says    one field per argument this tree's macro takes
    where its blobs go      one field per blob that has a question — which is
                            not always two, since a `MINT` has nothing to ask

That last one is the point of the whole phase. Polished mints a section per map
for its blocks, so there is no placement to choose and the form simply does not
have the field. A field offering exactly one answer is worse than no field: it
implies a decision that was never available.

**This form sketches**, the way `hacks/prism/newmap.py` does: the grid you
pointed at, at the height and width you typed, drawn on the studio's grid while
the form is still open. The mistake worth seeing is the one that otherwise
builds — a grid that is not `height x width` — and `wiring/mapnew.read_grid`
already refused it in words. Now it refuses in a picture, which is the same
check told better: a wrong `height` looks like a map cut off or skewed, and you
fix the number rather than reading arithmetic about it.

It draws through the *same* `read_grid` the write goes through, so the two can
never disagree about what the file holds. What it cannot do alone is colour:
the grid is bytes anywhere, but a tileset constant means something only to the
tree that defines it. So this answers with a neutral `panels.Sketch` — grid,
size, and the tileset name as typed — and each family reader turns that into
`panels.Blocks` with its own swatches. Prism has no such split because its
action and its reader are the same adapter.
"""

from __future__ import annotations

from pathlib import Path

from . import panels
from ..wiring import mapnew
from ..wiring.placement import Placement
from .actions import (BLOCK_SECTIONS, BLOCKS, GROUPS, SCRIPT_SECTIONS, Action,
                      ActionError, Field, Result)

#: The blobs a family map places, and the field and choice-kind each one gets.
_PLACES = {"script": ("script_section", "Script section", SCRIPT_SECTIONS),
           "blocks": ("blocks_section", "Blocks section", BLOCK_SECTIONS)}

_BASE = (
    Field("label", "Label", help="CamelCase — its asm labels, its .blk, its "
                                 "section"),
    Field("const", "Map id", help="SCREAMING_SNAKE — the MAP_ enum and the "
                                  "dimensions"),
    Field("group", "Group", kind="int", default="1", choices=GROUPS,
          help="an existing group; making a new one is not this tool's job"),
    Field("height", "Height", kind="int", help="in blocks — a block is 2x2 tiles"),
    Field("width", "Width", kind="int"),
    Field("blk", "Blocks", choices=BLOCKS,
          help="the grid you drew — it must be exactly height x width bytes"),
    Field("border_block", "Border block", default="0",
          help="the block the world is made of past the edge"),
)


class AddMap(Action):
    name = "newmap"
    title = "Add a new map"
    sketches = True
    #: The tree's answers. A class attribute for the reason `studio/resize.py`
    #: gives: a form is built as `action(map_const, **values)` and there is no
    #: third seat. Stamped by :func:`newmap_for`.
    dialect = None
    FIELDS: tuple[Field, ...] = _BASE

    def __init__(self, map_const: str = "", **values: str) -> None:
        # The map you were looking at when you pressed the key. A new map has
        # nothing to do with it; the palette hands it to every action.
        super().__init__(**values)
        self.map = map_const

    def describe(self) -> str:
        return f"add {self.text('const')} ({self.text('label')})"

    def selects(self) -> str | None:
        return self.text("label") or None

    # -- the picture ---------------------------------------------------------- #
    def sketch(self, root: Path) -> panels.Sketch | None:
        """The map on the grid, before any of it is written down.

        Everything it needs is on the form, so it can be wrong in every way the
        form can be wrong — and each of those is worth seeing rather than being
        told. It refuses only what it cannot draw at all: a size that is not a
        size, and a grid file whose length disagrees with it.

        The tileset is *not* refused when it is empty or half-typed. It is the
        one answer that only colours the picture, and a form is half-typed for
        as long as you are typing into it; withholding the shape until the
        spelling is finished would hide the mistake this exists to show.
        """
        blk = self.text("blk")
        if not blk:
            raise ActionError("point at the grid you drew")
        height, width = self.integer("height"), self.integer("width")
        if height < 1 or width < 1:
            raise ActionError("a map is at least one block by one block")
        try:
            grid = mapnew.read_grid(Path(blk).expanduser(), height, width)
        except mapnew.EditError as exc:
            raise ActionError(str(exc)) from exc
        return panels.Sketch(blocks=grid, height=height, width=width,
                             tileset=self.text("tileset"),
                             label=self.text("label"))

    def run(self, root: Path) -> Result:
        blk = self.text("blk")
        if not blk:
            raise ActionError("point at the grid you drew")
        spec = mapnew.NewMap(
            label=self.text("label"), const=self.text("const"),
            group=self.integer("group", 1),
            height=self.integer("height"), width=self.integer("width"),
            blk=Path(blk).expanduser(),
            border_block=self.text("border_block") or "0",
            header={name: self.text(name) for name in self.dialect.header_args},
        )
        answers = {blob: self.text(field)
                   for blob, (field, _, _) in _PLACES.items()}
        try:
            change = mapnew.add_map(root, spec, answers, dialect=self.dialect)
        except (mapnew.EditError, KeyError) as exc:
            raise ActionError(str(exc).strip("'")) from exc
        return Result(change.summary, change.changes, change.notes)


def newmap_for(dialect, tag: str, header_fields: tuple[Field, ...],
               asks: tuple[str, ...]) -> type[AddMap]:
    """This form, bound to one tree.

    `header_fields` is the tree's own `map` macro, one field per argument, in
    the order the macro takes them — the adapter writes them down because the
    adapter is the only thing entitled to know them. `asks` names the blobs
    whose placement is a question; the rest are mints and get no field.
    """
    places = tuple(Field(field, label, choices=kind,
                         help="which SECTION it is appended into")
                   for blob, (field, label, kind) in _PLACES.items()
                   if blob in asks)
    return type(f"{tag}AddMap", (AddMap,),
                {"dialect": dialect, "__doc__": AddMap.__doc__,
                 "FIELDS": _BASE + header_fields + places})


def grids(folders, suffixes: tuple[str, ...]) -> list[str]:
    """Every grid file within reach, **newest first**.

    Deliberately uncached and deliberately not sorted by name: the file you are
    looking for is the one you drew in polished-map ninety seconds ago, so it is
    the newest thing here by definition, and a list cached at startup would be a
    list with exactly that file missing from it.

    Both `folders` and `suffixes` are the caller's because both fork. Prism
    keeps its grids in `maps/blk/`; the family keeps them in `maps/`, and
    polished's are `.ablk` beside a `.ablk.lzp` the build makes. A folder that
    is not there is not an error — most of these are somebody's habit rather
    than part of the tree.
    """
    seen: dict[Path, float] = {}
    for folder in folders:
        try:
            entries = list(Path(folder).iterdir())
        except OSError:
            continue
        for f in entries:
            # The same suffixes the action will *check* the answer against — a
            # list that offered a file the action then refused would be worse
            # than no list at all.
            if f.suffix.lower() in suffixes and f.is_file():
                seen.setdefault(f.resolve(), f.stat().st_mtime)
    return [str(p) for p in sorted(seen, key=lambda p: -seen[p])]


def section_choices(placements: tuple[Placement, ...], kind: str) -> list[str]:
    """The sections on offer for a `SCRIPT_SECTIONS`/`BLOCK_SECTIONS` field.

    Empty for a blob the tree mints — which is not a failure to enumerate but
    the reason that field is not on the form in the first place.
    """
    want = next((blob for blob, (_, _, k) in _PLACES.items() if k == kind), None)
    for p in placements:
        if p.blob == want and p.asks:
            return [s.name for s in p.choices]
    return []
