"""Growing or shrinking a map from an edge.

Three things describe a map's shape, in three different files, and they must
move together or the map corrupts:

    a dimension constant     the declared `MapShape` — see below
    the block grid           H*W bytes, row-major
    the map's asm            every warp/signpost/trigger/person, each one a
                             coordinate *into* that grid

A block is 2x2 coordinate tiles (`shared/coords.TILES_PER_BLOCK`), and growing or
shrinking at the **top or left** moves the grid's origin — so every coordinate on
the map has to shift with it, by 2 tiles per block. Growing or shrinking at the
**bottom or right** leaves the origin exactly where it was, and nothing on the
map needs to move at all.

That much is geometry, and it is the same in every tree. What is *not* the same
is where those three things live and how they are spelled, so the tree answers
that through a :class:`Dialect` and the geometry stays here, written once.

The transposition this module exists to not get wrong
-----------------------------------------------------
The dimension macro takes its two numbers in a different order in each family::

    prism   mapgroup  NAME, H, W    ->  NAME_HEIGHT EQU \\2 , NAME_WIDTH  EQU \\3
    family  map_const NAME, W, H    ->  \\1_WIDTH    EQU \\2 , \\1_HEIGHT   EQU \\3

Measured, not assumed: `PlayersHouse1F` is `map_const …, 5, 4` and its `.blk` is
exactly 20 bytes. A resize that inherited the other tree's order would transpose
every map it touched, and a transposed height and width assembles perfectly —
it is the swapped movement radius of `hacks/vanilla/shapes.py` one file over.
So :class:`MapShape` owns the order and does *both* the reading and the writing
of that line, because the one way to guarantee they agree is to give them no
opportunity to disagree.

One entry point, taking only primitives and a dialect — no `Action`, no
`Session`, nothing from `studio/` — so a future `prism-resize` CLI is
`argparse` -> :func:`resize` -> `apply_edits(root, change.changes,
dry_run=...)`, the same shape as `prism-newmap`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..shared import coords
from ..shared.edits import Edit
from .objedit import Change, EditError

EDGES = ("top", "bottom", "left", "right")
MODES = ("grow", "shrink")


@dataclass(frozen=True)
class MapShape:
    """How a tree spells a map's height and width, and in which order.

    `height_first` is the whole point: see the module docstring. Everything
    that reads or writes the dimension line goes through here.
    """
    #: The constants file, relative to the repo root.
    path: str
    #: The macro that carries the two numbers.
    macro: str
    #: True when the macro is `NAME, H, W`; False when it is `NAME, W, H`.
    height_first: bool

    def _re(self, const: str) -> re.Pattern:
        return re.compile(
            rf"^(?P<head>\s*{re.escape(self.macro)}\s+{re.escape(const)}\s*,\s*)"
            r"(?P<a>-?\d+)(?P<mid>\s*,\s*)(?P<b>-?\d+)(?P<tail>.*)$")

    def read(self, root: Path, const: str) -> tuple[int, int]:
        """(height, width), whichever order the file writes them in."""
        rx = self._re(const)
        for line in (root / self.path).read_text().split("\n"):
            if m := rx.match(line):
                a, b = int(m.group("a")), int(m.group("b"))
                return (a, b) if self.height_first else (b, a)
        raise EditError(
            f"{const} has no `{self.macro}` line in {self.path}")

    def line(self, const: str, height: int, width: int) -> str:
        """The dimension line for a map that does not have one yet.

        Here rather than in `wiring/mapnew.py` for the reason the class exists:
        a *new* map is the one place a transposed height and width would not
        even contradict the grid it was measured from, since both are being
        written at once from the same two numbers. Three callers, one order.
        """
        first, second = ((height, width) if self.height_first
                         else (width, height))
        return f"\t{self.macro} {const}, {first}, {second}"

    def rewrite(self, root: Path, const: str, height: int, width: int) -> Edit:
        """The dimension line, renumbered. Keeps the line's own spacing and any
        trailing comment — the family aligns these into columns and writes a map
        index after them, and neither is ours to reflow."""
        path = root / self.path
        if not path.exists():
            raise EditError(f"{self.path} is missing")
        original = path.read_text()
        lines = original.split("\n")
        rx = self._re(const)
        first, second = ((height, width) if self.height_first
                         else (width, height))
        for i, line in enumerate(lines):
            m = rx.match(line)
            if not m:
                continue
            rebuilt = (f"{m.group('head')}{first}{m.group('mid')}"
                       f"{second}{m.group('tail')}")
            if rebuilt == line:
                return Edit(self.path, False, "unchanged", "", base=original)
            lines[i] = rebuilt
            return Edit(self.path, True, f"{const}: {height}x{width}",
                        "\n".join(lines), base=original)
        raise EditError(f"{self.path} has no `{self.macro}` line for {const}")


@dataclass(frozen=True)
class Standing:
    """One thing standing on the map, for the shrink refusal to name."""
    macro: str
    y: int
    x: int


class Dialect(Protocol):
    """What a resize has to ask the tree. Everything else on this page is
    arithmetic that does not care which hack it is running against."""

    #: How this tree spells the dimension constant.
    shape: MapShape

    def label_of(self, root: Path, const: str) -> str:
        """The map's asm/blk label. Raises `EditError` if the map is unwired."""

    def blk(self, root: Path, label: str) -> Path:
        """The block grid file. Raises `EditError` when the map has no blocks,
        or when it *shares* them with another map — resizing aliased block data
        corrupts every map that aliases it, since their dimension constants do
        not change with it."""

    def read_grid(self, path: Path, height: int, width: int) -> bytes:
        """`height * width` block bytes. Whether they are stored plain or
        compressed is the tree's business, which is why this is here and not
        a `read_bytes` on the page below."""

    def border_block(self, root: Path, label: str) -> str:
        """The block a grow fills new rows and columns with by default."""

    def connections(self, root: Path, label: str) -> int:
        """How many neighbours this map has, for the review note."""

    def standing(self, root: Path, label: str) -> list[Standing]:
        """Every entry's coordinates, so a shrink can refuse to bury them."""

    def shift(self, root: Path, const: str, dy: int,
              dx: int) -> tuple[Edit, int]:
        """Move every entry by (dy, dx). Returns the edit and how many moved."""


def resize(root: Path, map_const: str, edge: str, mode: str, blocks: int,
          fill: str | None = None, *, dialect: Dialect) -> Change:
    """Grow or shrink `map_const` by `blocks` blocks, from `edge`.

    Refuses (writing nothing) if the map's block grid is shared with another
    map, if the shrink would take the map below one block on that axis, or if
    anything on the map is standing in the strip being removed.
    """
    if edge not in EDGES:
        raise EditError(f"edge must be one of {', '.join(EDGES)}, not {edge!r}")
    if mode not in MODES:
        raise EditError(f"mode must be one of {', '.join(MODES)}, not {mode!r}")
    if blocks < 1:
        raise EditError("grow/shrink by at least one block")

    label = dialect.label_of(root, map_const)
    height, width = dialect.shape.read(root, map_const)

    blk_path = dialect.blk(root, label)
    grid = dialect.read_grid(blk_path, height, width)

    axis = height if edge in ("top", "bottom") else width
    if mode == "shrink" and blocks >= axis:
        raise EditError(
            f"{label} is only {axis} blocks on that axis — shrinking by "
            f"{blocks} would leave nothing")
    if mode == "shrink":
        orphans = _orphans(dialect.standing(root, label), edge, blocks,
                           height, width)
        if orphans:
            raise EditError(
                f"shrinking {label}'s {edge} by {blocks} block(s) would remove: "
                f"{', '.join(orphans)} — delete them first")

    if edge in ("top", "bottom"):
        new_height = height + blocks if mode == "grow" else height - blocks
        new_width = width
    else:
        new_height = height
        new_width = width + blocks if mode == "grow" else width - blocks

    fill_block = (_fill_value(fill, dialect.border_block(root, label))
                  if mode == "grow" else 0)
    new_grid = _reshape(grid, height, width, edge, mode, blocks, fill_block)

    edits = [
        dialect.shape.rewrite(root, map_const, new_height, new_width),
        Edit(_rel(root, blk_path), True,
             f"{new_height}x{new_width} blocks", f"{len(new_grid)} bytes",
             data=new_grid),
    ]
    notes: list[str] = []

    dy = dx = 0
    if edge == "top":
        dy = blocks * coords.TILES_PER_BLOCK * (1 if mode == "grow" else -1)
    elif edge == "left":
        dx = blocks * coords.TILES_PER_BLOCK * (1 if mode == "grow" else -1)
    if dy or dx:
        coord_edit, moved = dialect.shift(root, map_const, dy, dx)
        if coord_edit.changed:
            edits.append(coord_edit)
        if moved:
            amount = abs(dy or dx)
            direction = ("down" if dy > 0 else "up" if dy < 0 else
                        "right" if dx > 0 else "left")
            notes.append(f"shifted {moved} object(s) {amount} tiles {direction}")

    if n := dialect.connections(root, label):
        notes.append(
            f"{n} connection(s) may need review — a connection is aligned "
            f"against its neighbour's edge, and this map's edge just moved.")

    summary = (f"{label}: {mode} {edge} by {blocks} block(s) "
              f"({height}x{width} -> {new_height}x{new_width})")
    return Change(summary, edits, notes)


def _rel(root: Path, path: Path) -> str:
    return str(path.relative_to(root))


# --------------------------------------------------------------------------- #
# refusals                                                                    #
# --------------------------------------------------------------------------- #

def _orphans(standing: list[Standing], edge: str, blocks: int,
            height: int, width: int) -> list[str]:
    """Everything standing in the tile-strip a shrink would remove."""
    lo_y, hi_y = 0, 2 * height
    lo_x, hi_x = 0, 2 * width
    if edge == "top":
        hi_y = 2 * blocks
    elif edge == "bottom":
        lo_y = 2 * (height - blocks)
    elif edge == "left":
        hi_x = 2 * blocks
    else:
        lo_x = 2 * (width - blocks)

    on_the_y_axis = edge in ("top", "bottom")
    found = []
    for s in standing:
        in_strip = (lo_y <= s.y < hi_y if on_the_y_axis
                    else lo_x <= s.x < hi_x)
        if in_strip:
            found.append(f"{s.macro} at ({s.y}, {s.x})")
    return found


def _fill_value(fill: str | None, border_block: str) -> int:
    raw = (fill or "").strip()
    if raw:
        return _byte(raw, "fill block")
    return _byte(border_block, "border block")


def _byte(raw: str, what: str) -> int:
    try:
        n = int(raw.replace("$", "0x"), 0)
    except ValueError:
        raise EditError(
            f"{what} must be a plain block number, e.g. 62 or $3e — not {raw!r}"
        ) from None
    if not 0 <= n <= 255:
        raise EditError(f"a block is one byte — {n} does not fit ({what})")
    return n


# --------------------------------------------------------------------------- #
# the .ablk                                                                   #
# --------------------------------------------------------------------------- #

def _reshape(grid: bytes, height: int, width: int, edge: str, mode: str,
            blocks: int, fill: int) -> bytes:
    rows = [grid[r * width:(r + 1) * width] for r in range(height)]

    if edge in ("top", "bottom"):
        if mode == "grow":
            new_row = bytes([fill]) * width
            new_rows = ([new_row] * blocks + rows if edge == "top"
                       else rows + [new_row] * blocks)
        else:
            new_rows = rows[blocks:] if edge == "top" else rows[:height - blocks]
        return b"".join(new_rows)

    if mode == "grow":
        pad = bytes([fill]) * blocks
        new_rows = ([pad + row for row in rows] if edge == "left"
                   else [row + pad for row in rows])
    else:
        new_rows = ([row[blocks:] for row in rows] if edge == "left"
                   else [row[:width - blocks] for row in rows])
    return b"".join(new_rows)


# The dimension constant is `MapShape`'s job, at the head of this module, and
# shifting coordinates is the dialect's — both because both differ per tree.
# What is left here is arithmetic, and arithmetic has no dialect.
