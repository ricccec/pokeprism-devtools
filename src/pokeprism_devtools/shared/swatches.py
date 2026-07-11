"""Each block of a tileset, boiled down to four colors.

The studio's grid does not draw tiles. You do not need to read the sign, you need
to see that there *is* a sign, that the path bends left, and that the water starts
here — and then put an NPC on it. So each block is reduced to a 2×2 array of RGB,
which is not an arbitrary choice: a block is 2×2 coordinate tiles, so one swatch
quadrant is exactly one place you can stand. The cursor lands on a quadrant.

Drawn as two terminal cells (one per column, split top/bottom with `▀`), a map
comes out at two columns per block, and water, paths, walls and doorways are all
plainly where they should be.

The cost is one pass per **tileset**, not per map — and barely that, because a
tile's average color doesn't depend on how it's flipped. The 4096 flip-variant
tile slots in a tileset collapse to a few hundred distinct (tile, palette) pairs,
each averaged once.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from . import coords, render

Rgb = tuple[int, int, int]
#: A block's four quadrant colors, in reading order: top-left, top-right,
#: bottom-left, bottom-right. Index a quadrant as `row * 2 + col`.
Swatch = tuple[Rgb, Rgb, Rgb, Rgb]

#: A tileset holds 256 blocks of 16 tiles (tilesets/NN_metatiles.bin is 4096 B).
BLOCKS = 256
_TILES = 16
_COLS = 4



@lru_cache(maxsize=8)
def for_map(root: Path, tileset_id: int, permission: int, time_of_day: int = 1) -> tuple[Swatch, ...]:
    """The 256 swatches a map with this tileset and permission would draw with.

    Cached on exactly what determines the answer — `permission` because it, not
    the tileset, picks the BG palette table (engine/color.asm), which is why two
    maps sharing a tileset can still look nothing alike.
    """
    palettes = render.get_map_palettes(root, tileset_id, permission, time_of_day)
    return build(root, tileset_id, palettes)


def build(root: Path, tileset_id: int, palettes: list[list[Rgb]]) -> tuple[Swatch, ...]:
    """The 256 swatches for a tileset against an explicit set of 8 BG palettes."""
    metatiles, attributes, gfx = render.load_tileset_files(root, tileset_id)

    #: (tile id including its VRAM bank, palette slot) -> its channel *totals*
    #: over 64 pixels. Totals, not means: a quadrant is four tiles, and averaging
    #: the averages floors twice, which lands a channel one off the true mean and
    #: makes this disagree with the renderer it is supposed to be a summary of.
    #:
    #: Flips are absent from the key on purpose — mirroring a tile doesn't move
    #: its average — which is what collapses 4096 flip-variant slots into a few
    #: hundred real ones.
    seen: dict[tuple[int, int], tuple[int, int, int]] = {}
    out: list[Swatch] = []

    for block in range(BLOCKS):
        base = block * _TILES
        tiles, attrs = metatiles[base:base + _TILES], attributes[base:base + _TILES]
        # Not every tileset defines all 256 blocks. A map using one that isn't
        # there is a bug, but it isn't *this* module's bug to report, and the
        # renderer already has an answer: tile 0 in palette 0. Give the same one,
        # so the grid and the picture never disagree about what they're showing.
        if len(tiles) < _TILES or len(attrs) < _TILES:
            tiles = attrs = bytes(_TILES)

        totals = [[0, 0, 0] for _ in range(4)]
        for i in range(_TILES):
            attr = attrs[i]
            key = (tiles[i] + ((attr >> 3) & 1) * 128, attr & 7)   # bit 3 = VRAM bank
            if (tile := seen.get(key)) is None:
                tile = seen[key] = _tile_total(gfx, key[0], palettes[key[1]])
            # tile i sits at row i//4, col i%4 of the block; halving each gives
            # the quadrant, which is the coordinate tile it belongs to.
            acc = totals[(i // _COLS // 2) * 2 + (i % _COLS // 2)]
            for c in range(3):
                acc[c] += tile[c]

        # Four tiles of 64 pixels each: the quadrant is 16x16 px.
        out.append(tuple(tuple(v // 256 for v in acc) for acc in totals))   # type: ignore[arg-type]

    return tuple(out)


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


def _tile_total(gfx: bytes, tile_id: int, palette: list[Rgb]) -> tuple[int, int, int]:
    """One tile's channel sums over its 64 pixels."""
    r = g = b = 0
    for row in render.decode_2bpp_tile(gfx, tile_id):
        for idx in row:
            cr, cg, cb = palette[idx]
            r += cr
            g += cg
            b += cb
    return r, g, b
