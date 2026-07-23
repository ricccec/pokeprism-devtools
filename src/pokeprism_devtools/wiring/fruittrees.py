"""The fruit-tree registry: one id, spread across two files that must agree.

A fruit tree on a map is a script block — `fruittree FRUITTREE_ROUTE_29` — and
the id it names is an index into two lists that live in two different files and
are coupled by *position*::

    constants/script_constants.asm     const FRUITTREE_ROUTE_29   ; 01
    data/items/fruit_trees.asm         db BERRY                   ; ROUTE_29

The const's ordinal — 1-based, from `const_def 1` — is the row the engine reads
in `FruitTreeItems` to learn which berry the tree drops. Add a const without its
row, or add the two out of step, and every tree past the break drops the wrong
item, silently, because both files still assemble. `assert_table_length
NUM_FRUIT_TREES` is the tree's own guard that the two counts match; :func:`load`
refuses unless they already do, so this writer never widens a gap the assert
would only catch later.

Both lists are append-only here. A new tree takes the next ordinal, its const
goes in just before `DEF NUM_FRUIT_TREES` and its row just before
`assert_table_length`, and because both are appends the ordinals stay in step
with no renumbering. There is no per-map grouping to honour — the list is global
and ordered by nothing but insertion — which is why appending is the whole of
the mechanism. The alignment columns are measured against the file (`const`
names to column 24, `db` items to 12) so a generated tree reads as if it were
typed beside the thirty already there.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..shared.edits import Edit

_CONST_REL = "constants/script_constants.asm"
_TABLE_REL = "data/items/fruit_trees.asm"
_INDENT = "\t"

_CONST = re.compile(r"^\s*const\s+(FRUITTREE_\w+)\b")
_NUM_DEF = re.compile(r"^\s*DEF\s+NUM_FRUIT_TREES\b")
_ROW = re.compile(r"^\s*db\s+\w+\s*;")
_ASSERT = re.compile(r"^\s*assert_table_length\s+NUM_FRUIT_TREES\b")
_ID = re.compile(r"^FRUITTREE_\w+$")


class FruitTreeError(RuntimeError):
    """The fruit-tree files are not shaped the way this writer can extend."""


@dataclass
class FruitTrees:
    """The two coupled files, and the append that adds one tree to both."""

    const_lines: list[str]
    table_lines: list[str]
    ids: list[str]              # FRUITTREE_* consts, in file order
    _num_line: int             # index of `DEF NUM_FRUIT_TREES` in the const file
    _assert_line: int          # index of `assert_table_length` in the table file
    _const_base: str
    _table_base: str

    def next_id(self, map_const: str) -> str:
        """The `FRUITTREE_` id for a new tree on `map_const`: `FRUITTREE_<MAP>`,
        then `_2`, `_3`.

        The bare name is a map's first tree; a second gets a suffix rather than
        renumbering the first. The id this returns is written into a script
        block and read as the row index into `FruitTreeItems`, so renumbering an
        existing one to keep a naming habit tidy would rewrite a reference for
        no gain — the same reason `blocks.object_const` leaves the names it finds
        alone. Real multi-tree maps number from `_1` with no bare name; this
        cannot reproduce that without the renumber, and does not try.
        """
        base = f"FRUITTREE_{map_const}"
        taken = set(self.ids)
        if base not in taken:
            return base
        return next(f"{base}_{n}" for n in range(2, len(taken) + 3)
                    if f"{base}_{n}" not in taken)

    def append(self, tree_id: str, item: str) -> None:
        """Add `tree_id` to the const list and `item` to the table, in step.

        One call adds one tree: the ordinal is read once off the current length,
        so the const's index and the row's position are the same number by
        construction rather than by hope.
        """
        if not _ID.match(tree_id):
            raise FruitTreeError(f"{tree_id!r} is not a FRUITTREE_ id")
        if tree_id in self.ids:
            raise FruitTreeError(f"{tree_id} is already a fruit tree")
        if not item:
            raise FruitTreeError("a fruit tree with no item drops item 0 — name "
                                 "the berry it bears")
        ordinal = len(self.ids) + 1
        suffix = tree_id.removeprefix("FRUITTREE_")
        self.const_lines.insert(
            self._num_line, f"{_INDENT}const {tree_id.ljust(23)} ; {ordinal:02x}")
        self.table_lines.insert(
            self._assert_line, f"{_INDENT}db {item.ljust(12)} ; {suffix}")
        self.ids.append(tree_id)
        # Keep the anchors valid even if this were ever called twice.
        self._num_line += 1
        self._assert_line += 1

    def to_edits(self, detail: str) -> list[Edit]:
        """One edit per file. Both carry the base they were computed from, so a
        file that moved under us raises rather than clobbers — the same contract
        every other edit in the tool keeps."""
        const = "\n".join(self.const_lines)
        table = "\n".join(self.table_lines)
        return [Edit(_CONST_REL, const != self._const_base, detail, const,
                     base=self._const_base),
                Edit(_TABLE_REL, table != self._table_base, detail, table,
                     base=self._table_base)]


def load(root: Path) -> FruitTrees:
    """Parse both files and refuse unless their counts already agree.

    The agreement is the precondition the whole append rests on: if the const
    list and the table are out of step before this writer touches them, the tree
    does not assemble and no append fixes it, so the honest move is to say so
    rather than add a thirty-first tree to a broken thirty.
    """
    cpath, tpath = root / _CONST_REL, root / _TABLE_REL
    if not cpath.exists():
        raise FruitTreeError(f"{cpath} not found")
    if not tpath.exists():
        raise FruitTreeError(f"{tpath} not found")

    const_base, table_base = cpath.read_text(), tpath.read_text()
    const_lines, table_lines = const_base.split("\n"), table_base.split("\n")

    ids = [m.group(1) for ln in const_lines if (m := _CONST.match(ln))]
    num_line = next((i for i, ln in enumerate(const_lines) if _NUM_DEF.match(ln)),
                    -1)
    if not ids or num_line < 0:
        raise FruitTreeError(
            f"{_CONST_REL} has no FRUITTREE_ list ending in DEF NUM_FRUIT_TREES "
            "— not a tree this writer recognises")

    rows = sum(1 for ln in table_lines if _ROW.match(ln))
    assert_line = next((i for i, ln in enumerate(table_lines)
                        if _ASSERT.match(ln)), -1)
    if assert_line < 0:
        raise FruitTreeError(
            f"{_TABLE_REL} has no 'assert_table_length NUM_FRUIT_TREES'")
    if rows != len(ids):
        raise FruitTreeError(
            f"{len(ids)} FRUITTREE_ consts but {rows} rows in {_TABLE_REL} — the "
            "two are already out of step, and appending would not close the gap")

    return FruitTrees(const_lines, table_lines, ids, num_line, assert_line,
                      const_base, table_base)
