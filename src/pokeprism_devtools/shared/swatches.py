"""One coordinate tile's colour, looked up — the renderer both grids share.

Building the swatches is each adapter's own business: prism averages real pixels
(`hacks/prism/swatches.py`), the family reads a palette without decoding a tile
(`hacks/vanilla/swatches.py`). What they hand back has the same shape — 256
blocks, each four quadrant colours — and drawing one tile from it is the same
lookup whichever tree filled it. That lookup is here, in `shared/`, so the grid
does not reach into one adapter to draw another's map.
"""

from __future__ import annotations

from . import coords

Rgb = tuple[int, int, int]
#: A block's four quadrant colors, in reading order: top-left, top-right,
#: bottom-left, bottom-right. Index a quadrant as `row * 2 + col`.
Swatch = tuple[Rgb, Rgb, Rgb, Rgb]


def tile_color(blocks: bytes, width: int, sw: tuple[Swatch, ...],
               marks: dict[tuple[int, int], str], ty: int, tx: int) -> Rgb:
    """The colour of one coordinate tile — the single answer both grids draw.

    An object's tile is its object's colour, **edge to edge**, not the terrain
    with a letter on it: a tile that is occupied is occupied, and if you want to
    see what's under an NPC you move the NPC. `width` is in blocks.
    """
    if (glyph := marks.get((ty, tx))) is not None:
        return coords.MARKER_BG[glyph]
    row, col = coords.block_of(ty, tx)
    qr, qc = coords.quadrant_of(ty, tx)
    return sw[blocks[row * width + col]][qr * coords.TILES_PER_BLOCK + qc]
