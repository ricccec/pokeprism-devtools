"""Draw a map in the terminal, with everything placed on it.

Reads the block data out of the `.ablk` in the tree rather than out of the built
game, which is the point: the map you are authoring is the one that isn't in the
ROM yet.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from ..hacks.prism import blocksrc, eventheader, render, swatches
from ..shared import coords

#: Half-block: the foreground paints the top of the cell, the background the
#: bottom. So a terminal cell holds *two* stacked pixels, and the vertical
#: resolution of the grid is half-rows — which is what lets an odd zoom work.
_HALF = "▀"
_RESET = "\033[0m"

#: Columns per coordinate tile. A tile is drawn `zoom` columns wide and `zoom`
#: half-rows tall: square, because a terminal cell is about twice as tall as it
#: is wide. Zoom 1 is a block per two columns — dense, but the markers have to
#: share a cell with the terrain. From zoom 3 a tile has a cell of its own and
#: the letter sits in the middle of it.
ZOOMS = (1, 2, 3, 4)
_GUTTER = 4          # width of the row-number column
_CHROME = 7          # title, ruler, legend — rows that aren't map

_LEGEND = ((coords.WARP, "warp"), (coords.SIGN, "signpost"), (coords.PERSON, "npc"),
           (coords.TRAINER, "trainer"), (coords.ITEM, "item"))


def fit_zoom(rows: int, cols: int, size: os.terminal_size | None = None) -> int:
    """The biggest zoom whose map still fits the terminal. `rows`/`cols` in tiles."""
    term = size or shutil.get_terminal_size((80, 24))
    for z in sorted(ZOOMS, reverse=True):
        if cols * z + _GUTTER <= term.columns and rows * z // 2 <= term.lines - _CHROME:
            return z
    return min(ZOOMS)


def _paint(fg: swatches.Rgb, bg: swatches.Rgb, ch: str) -> str:
    return (f"\033[38;2;{fg[0]};{fg[1]};{fg[2]}m"
            f"\033[48;2;{bg[0]};{bg[1]};{bg[2]}m{ch}")


def _cell(top: swatches.Rgb, bottom: swatches.Rgb, glyph: str | None) -> str:
    if glyph is None:
        return _paint(top, bottom, _HALF)
    # A marker needs a whole cell — there is no half a character — so it costs the
    # terrain underneath either way. Spend that on a colour that says *what it is*:
    # a fill you can read from across the room, rather than a letter you have to
    # go looking for.
    return "\033[1m" + _paint(coords.MARKER_INK[glyph], coords.MARKER_BG[glyph], glyph)


def _ruler(cols: int, zoom: int) -> str:
    """Tile numbers along the top — the unit you type into a macro, not blocks."""
    every = 10 if zoom < 2 else 5
    out = [" "] * (cols * zoom)
    for x in range(0, cols, every):
        for i, ch in enumerate(str(x)):
            if x * zoom + i < len(out):
                out[x * zoom + i] = ch
    return "".join(out)


def print_grid(root: Path, label: str, time_of_day: int = 1, zoom: int | None = None) -> None:
    """Draw the map, in colour, with everything that's been placed on it."""
    bd = blocksrc.load(root, label)
    sw = swatches.for_map(root, bd.tileset_id, bd.permission, time_of_day)

    marks: dict[tuple[int, int], str] = {}
    try:
        marks = eventheader.markers(eventheader.parse_map(root / f"maps/{label}.asm"))
    except (eventheader.UnparseableHeader, FileNotFoundError) as e:
        print(f"  (no objects drawn — {e})\n", file=sys.stderr)

    rows, cols = coords.tile_size(bd.height, bd.width)
    z = zoom or fit_zoom(rows, cols)

    def color(ty: int, tx: int) -> swatches.Rgb:
        return swatches.tile_color(bd.blocks, bd.width, sw, marks, ty, tx)

    glyphs = coords.glyph_cells(marks, z)

    print(f"{bd.name}  {bd.height}x{bd.width} blocks · {rows}x{cols} tiles · "
          f"tileset {bd.tileset_id} · {render.table_for_permission(bd.permission)} "
          f"palette · zoom {z}\n")
    print(" " * _GUTTER + _ruler(cols, z))

    last = None
    for r in range(rows * z // 2):
        ty = (2 * r) // z                      # the tile this row starts in
        out = [f"{ty:>3} " if ty != last else " " * _GUTTER]
        last = ty
        for c in range(cols * z):
            out.append(_cell(color((2 * r) // z, c // z),
                             color((2 * r + 1) // z, c // z),
                             glyphs.get((r, c))))
        print("".join(out) + _RESET)

    legend = "  ".join(
        f"{_cell((0, 0, 0), (0, 0, 0), g)}{_RESET} {name}" for g, name in _LEGEND)
    print(f"\n  {legend}\n  ({len(marks)} placed)")
