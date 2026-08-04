"""The fruit tree — the adder whose block points into another file.

Its own module for the same reason the item ball has one: it is a different
*kind* of write from the line-splicers in :mod:`.actions`. Like the item ball it
writes a block into the map and mints an `object_const` for the object that
points at it. Unlike the item ball, the id that block names — `FRUITTREE_ROUTE_29`
— is not local to the map at all: it is a constant indexing a table two files
away, and adding a tree means extending that const list and that table in step.
So this action returns three edits — the map, `constants/script_constants.asm`,
and `data/items/fruit_trees.asm` — and the coupling between the last two is
`asmedit/fruittrees.py`'s to keep, not this module's.

It is vanilla's alone. Polished has no `fruit_trees.asm` and calls `fruittree`
nowhere; it bakes the dropped item into three `fruittree_event` object arguments
instead, so there is no block and no table for it to reuse — which is why this
lands in :data:`.actions.VANILLA_ONLY` as declared data, not as a branch.

Nine of the object's thirteen slots are not offered and are not defaults either:
every fruit tree in the tree is `SPRITE_FRUIT_TREE, SPRITEMOVEDATA_STILL, 0, 0,
-1, -1, 0, OBJECTTYPE_SCRIPT, 0, <block>, -1` — 30 of 30, no exceptions. The flag
is `-1` on purpose: a fruit tree is not gated on an event, it regrows, and the
engine tracks whether today's fruit is still there by the `tree_id` itself, not
by a `EVENT_` bit. So unlike the item ball there is no flag to allocate.
"""

from __future__ import annotations

from pathlib import Path

from ...contract import ITEMS, ActionError, Field, Result
from ...asmedit import blocks, fruittrees, regions
from . import eventblock as eb
from .entry import Entry


class AddFruittree(Entry):
    """A berry tree on the ground — an object, a block, and a row in a table.

    The block is two lines and the object is thirteen slots of which four are
    asked. What is actually being written is the fourth thing, the one with no
    line of its own: a new `FRUITTREE_` constant and the `db <item>` that sits at
    its ordinal in `FruitTreeItems`. Get those two out of step and the tree drops
    the next tree's berry, so the table math lives in one place —
    `asmedit/fruittrees.py` — and this class only asks it for the id and hands it
    the item.
    """

    name = "fruittree"
    title = "Add a fruit tree"
    list_kind = "object"

    FIELDS = (
        Field("y", "Y", kind="int"),
        Field("x", "X", kind="int"),
        Field("item", "Berry", choices=ITEMS, default="BERRY",
              help="what the tree bears. Vanilla trees carry berries and "
                   "apricorns; any item assembles."),
    )

    def describe(self) -> str:
        return f"a {self.text('item')} tree at {self._where()} in {self.map}"

    def run(self, root: Path) -> Result:
        item = self.text("item")
        if not item:
            raise ActionError("a fruit tree with no item drops item 0 — name "
                              "the berry it bears")

        # The two registry files first, and the id they will hold — read before
        # the map is touched so a malformed or out-of-step registry refuses
        # here, with nothing half-written.
        try:
            trees = fruittrees.load(root)
        except fruittrees.FruitTreeError as exc:
            raise ActionError(str(exc)) from exc
        tree_id = trees.next_id(self.map)

        path, label = self._file(root)
        text = path.read_text()

        # The block, then the object that points at it — both land in this one
        # file, so they cannot be two edits off the same base. Splice, reparse,
        # then let the entry writer produce the single map edit. Mirrors the
        # item ball; see `regions.spliced`.
        try:
            script = blocks.unique_label(text, f"{label}FruitTree")
            body = blocks.fruittree(script, tree_id)
            staged = regions.spliced(text, regions.SCRIPTS, body,
                                     layout=self.layout)
            block = eb.parse_text(staged, path, self.anchor)
        except (blocks.BlockError, regions.RegionError,
                eb.UnparseableEvents) as exc:
            raise ActionError(str(exc)) from exc

        const = blocks.object_const([n for n, _ in block.names], label,
                                    "FRUIT_TREE")
        if block.const_lineno is None:
            # Same corner as the item ball: a map with no object has no
            # object_const_def header to hang a positional name on, and this
            # adder extends a const list, it does not start one.
            raise ActionError(
                f"{label} has no objects yet, so there is no object_const_def "
                "block to name this tree in. Adding the header is not wired up "
                "— this adder extends a const list, it does not start one.")

        try:
            block.add_entry("object", self.shape.args({
                "y": self.text("y"), "x": self.text("x"),
                "sprite": "SPRITE_FRUIT_TREE",
                "movement": "SPRITEMOVEDATA_STILL",
                # A fruit tree's palette is its sprite's; all 30 write a bare 0.
                "palette": "0",
                "type": "OBJECTTYPE_SCRIPT",
                # -1: not gated on an event. The tree regrows.
                "script": script, "flag": "-1",
            }), name=const)
        except eb.UnparseableEvents as exc:
            raise ActionError(str(exc)) from exc

        # Only now extend the registry — after the map write is known to parse,
        # so a failure above leaves the two table files untouched.
        try:
            trees.append(tree_id, item)
        except fruittrees.FruitTreeError as exc:
            raise ActionError(str(exc)) from exc

        edit = block.to_edit(root, self.describe())
        return Result(self.describe(),
                      [edit] + trees.to_edits(self.describe()),
                      [f"{script} bears {tree_id}; {const} names the tree; "
                       f"{item} added at index {len(trees.ids)} of "
                       "FruitTreeItems"])
