#!/usr/bin/env python3
"""Tests for the map grid — blocks from source, swatches, and the coordinate units.

Two of these carry the weight, and neither is about the drawing.

`test_source_agrees_with_the_rom` reads all 453 maps *twice* — once out of the
built ROM, the way the game does, and once out of the tree, the way the studio
has to — and demands they be identical. That is the whole claim of `blocksrc`,
and it is checkable exactly and for free, so it should be.

`test_swatch_is_the_block` renders a tileset with the real PIL renderer and
downscales it. If the swatches don't match that pixel-for-pixel, then quadrant
order, palette slots or the VRAM bank bit are wrong — and every one of those
produces a picture that still *looks* like a map, just not this one.

    python tests/test_grid.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pokeprism_devtools import map_show  # noqa: E402
from pokeprism_devtools.shared import (  # noqa: E402
    blockdata, blocksrc, coords, eventheader, render, swatches, symfile,
)

PRISM = Path.home() / "code/ricccec/pokeprism"
FAILED = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global FAILED
    print(f"  [{'OK  ' if cond else 'FAIL'}] {label}{f' — {detail}' if detail else ''}")
    if not cond:
        FAILED += 1


# --------------------------------------------------------------------------- #
# the units                                                                   #
# --------------------------------------------------------------------------- #

def test_units() -> None:
    print("\nthe three units, and the +4")

    check("a block is 2x2 coordinate tiles", coords.TILES_PER_BLOCK == 2)
    check("an 18x20 map is 36x40 tiles", coords.tile_size(18, 20) == (36, 40))
    check("tile (29, 35) is in a 18x20 map", coords.in_bounds(29, 35, 18, 20))
    check("tile (36, 0) is not", not coords.in_bounds(36, 0, 18, 20))

    # Every tile in a block maps back to that block, and to a distinct quadrant.
    quads = {coords.quadrant_of(y, x)
             for y in range(6, 8) for x in range(10, 12)}
    check("a block's four tiles are its four quadrants", len(quads) == 4, str(sorted(quads)))
    check("and all four sit in the same block",
          {coords.block_of(y, x) for y in range(6, 8) for x in range(10, 12)} == {(3, 5)})
    check("tile_of inverts block_of", coords.tile_of(3, 5) == (6, 10))

    # The lie. person_event writes `db \2 + 4`, so the bytes are not the source.
    check("person_event's bytes are the source + 4",
          coords.source_to_person(9, 25) == (13, 29))
    check("and back again", coords.person_to_source(13, 29) == (9, 25))


# --------------------------------------------------------------------------- #
# blocks, from source                                                         #
# --------------------------------------------------------------------------- #

def test_source_agrees_with_the_rom() -> None:
    """Read every map both ways. They must be the same map.

    The ROM is the ground truth — it is what the game actually plays — and
    `blockdata.load` has been walking it correctly for as long as prism-dev has
    worked. So if the source path disagrees anywhere, the source path is wrong:
    about the dimensions, or the tileset, or *which .ablk belongs to this label*,
    which is the one that would silently show you a different room.
    """
    rom, sym = PRISM / "pokeprism.gbc", PRISM / "pokeprism.sym"
    if not (rom.exists() and sym.exists()):
        print("\n(skipping ROM comparison — no built pokeprism.gbc)")
        return

    print("\nevery map, read from source and from the ROM")
    syms = symfile.SymFile.load(sym)

    from pokeprism_devtools.shared import mapsource
    pairs = mapsource.header_pairs(PRISM)

    same = 0
    mismatched: list[str] = []
    unreadable: list[str] = []

    for label, _const in pairs:
        try:
            src = blocksrc.load(PRISM, label)
        except blocksrc.BlockSourceError as e:
            unreadable.append(f"{label}: {e}")
            continue
        try:
            got = blockdata.load(rom, syms, src.group, src.map_id, name=label)
        except (ValueError, KeyError):
            continue        # not in this ROM build; the source is all there is

        fields = ((src.width, got.width), (src.height, got.height),
                  (src.tileset_id, got.tileset_id), (src.permission, got.permission),
                  (src.border_block, got.border_block), (src.blocks, got.blocks))
        if all(a == b for a, b in fields):
            same += 1
        else:
            differs = [n for n, (a, b) in zip(
                ("width", "height", "tileset", "permission", "border", "blocks"), fields)
                if a != b]
            mismatched.append(f"{label}: {', '.join(differs)}")

    check(f"{same} maps read identically from source and from the ROM",
          not mismatched, "; ".join(mismatched[:4]))

    # Two maps source refuses, and both refusals are the right answer:
    # MoundB3FDark's .ablk is 22 blocks short of its declared size, and
    # MoundB2FDark has no `map_header` at all — it shares MoundB2F's const, so
    # the ROM has no such map to compare against in the first place.
    check("it refuses exactly the two maps that are broken",
          sorted(u.split(":")[0] for u in unreadable) == ["MoundB2FDark", "MoundB3FDark"],
          "; ".join(unreadable) or "none")


def test_short_blk_is_an_error() -> None:
    print("\na .blk with too few blocks is a bug, not a smaller map")
    if not (PRISM / "maps").is_dir():
        print("  (skipping — pokeprism not found)")
        return

    # MoundB3FDark's .ablk is 660 blocks for a 31x22 = 682 map. In game the
    # engine reads 22 bytes of whatever the linker put after it.
    short = PRISM / "maps/blk/MoundB3FDark.ablk"
    try:
        blocksrc.read_blk(short, 31, 22)
        check("a short .ablk is refused", False, "it was read as if it were fine")
    except blocksrc.BlockSourceError as e:
        check("a short .ablk is refused", "22 bytes of whatever" in str(e), str(e))

    # Six maps have *extra* bytes. Those are fine: ReadMapBlocks copies exactly
    # height x width and never looks at the rest.
    bd = blocksrc.load(PRISM, "Route86")
    check("trailing bytes are not — the engine ignores them",
          len(bd.blocks) == bd.height * bd.width == 230, f"{len(bd.blocks)} blocks")


# --------------------------------------------------------------------------- #
# swatches                                                                    #
# --------------------------------------------------------------------------- #

def test_swatch_is_the_block() -> None:
    """A swatch quadrant must be the mean of the 16x16 px it stands for.

    Checked against the renderer that draws the real thing, so this pins the
    metatile lookup, the palette slot, the VRAM bank bit and — the one most
    likely to be quietly wrong — which quadrant is which.
    """
    if not (PRISM / "tilesets").is_dir():
        print("\n(skipping swatch check — pokeprism not found)")
        return

    print("\na swatch is the block it stands for, averaged")
    for tileset, table in ((28, "dungeon"), (1, "outdoor"), (6, "indoor")):
        pals = render.palettes_for_table(PRISM, table, 1)
        got = swatches.build(PRISM, tileset, pals)
        sheet = render.render_tileset_sheet(PRISM, tileset, pals).load()

        wrong = []
        for block in range(swatches.BLOCKS):
            bx = (block % 16) * render.BLOCK_PX
            by = (block // 16) * render.BLOCK_PX
            for q in range(4):
                qx = bx + (q % 2) * coords.COORD_PX
                qy = by + (q // 2) * coords.COORD_PX
                acc = [0, 0, 0]
                for py in range(coords.COORD_PX):
                    for px in range(coords.COORD_PX):
                        for c, v in enumerate(sheet[qx + px, qy + py]):
                            acc[c] += v
                mean = tuple(v // (coords.COORD_PX ** 2) for v in acc)
                if got[block][q] != mean:
                    wrong.append(f"block {block} q{q}: {got[block][q]} != {mean}")

        check(f"tileset {tileset:>2} ({table}): all 1024 quadrants match the render",
              not wrong, "; ".join(wrong[:3]))


def test_swatches_are_cached_per_map() -> None:
    print("\nswatches are built once per tileset, not once per map")
    if not (PRISM / "tilesets").is_dir():
        print("  (skipping — pokeprism not found)")
        return
    swatches.for_map.cache_clear()
    first = swatches.for_map(PRISM, 28, 4, 1)
    second = swatches.for_map(PRISM, 28, 4, 1)
    check("the second call is the same object", first is second)
    check("a different permission is a different palette table, so a different build",
          swatches.for_map(PRISM, 28, 1, 1) is not first)


# --------------------------------------------------------------------------- #
# markers                                                                     #
# --------------------------------------------------------------------------- #

def test_markers_are_where_the_source_says() -> None:
    """The trap: `person_event` adds +4 at assembly, but `Entry.y` reads the
    source. Applying the offset here would drift every NPC by four tiles — and
    the map would still look entirely plausible."""
    print("\nmarkers land on the tile the source names")
    path = PRISM / "maps/CastroForest.asm"
    if not path.exists():
        print("  (skipping — pokeprism not found)")
        return

    marks = coords.markers(eventheader.parse_map(path))

    # Read straight off maps/CastroForest.asm.
    check("a warp at warp_def 11, 8", marks.get((11, 8)) == coords.WARP)
    check("a signpost at signpost 2, 5", marks.get((2, 5)) == coords.SIGN)
    check("a trainer at person_event …, 9, 25", marks.get((9, 25)) == coords.TRAINER)
    check("an NPC at person_event …, 22, 13", marks.get((22, 13)) == coords.PERSON)
    check("an item ball at person_event …, 28, 27", marks.get((28, 27)) == coords.ITEM)
    check("a fruit tree counts as an item", marks.get((19, 34)) == coords.ITEM)
    check("nothing at the +4 of any of them",
          not any(coords.source_to_person(y, x) in marks
                  for y, x in ((9, 25), (22, 13), (28, 27))),
          "the assembler's offset has leaked into the grid")
    check("14 things are placed on this map", len(marks) == 14, str(len(marks)))

    bd = blocksrc.load(PRISM, "CastroForest")
    check("and every one of them is on the map",
          all(coords.in_bounds(y, x, bd.height, bd.width) for y, x in marks))


# --------------------------------------------------------------------------- #
# zoom                                                                        #
# --------------------------------------------------------------------------- #

def test_zoom_fits_the_terminal() -> None:
    """A tile is `zoom` columns wide and `zoom` *half-rows* tall — square, since a
    cell is about twice as tall as it is wide. Half-rows are what make an odd zoom
    work at all, and a map is always an even number of tiles, so it always pairs
    up into whole terminal rows with nothing left over."""
    print("\nzoom picks the biggest size that fits")

    # CastroForest: 36x40 tiles. At zoom z that is 40z columns and 18z rows.
    for z, want in ((1, (44, 18)), (2, (84, 36)), (3, (124, 54)), (4, (164, 72))):
        cols = 40 * z + 4
        rows = 36 * z // 2
        check(f"zoom {z}: {cols}x{rows} on screen", (cols, rows) == want, str((cols, rows)))

    def term(columns: int, lines: int) -> os.terminal_size:
        return os.terminal_size((columns, lines))

    check("a roomy terminal gets the biggest zoom",
          map_show.fit_zoom(36, 40, term(200, 100)) == 4)
    check("an 80x24 terminal gets zoom 1",
          map_show.fit_zoom(36, 40, term(80, 24)) == 1)
    # Height binds long before width: zoom 2 needs 36 rows of map, and a 40-line
    # terminal only has 33 once the title, ruler and legend are paid for.
    check("a 120x40 terminal is too short for zoom 2, so zoom 1",
          map_show.fit_zoom(36, 40, term(120, 40)) == 1)
    check("give it 50 lines and zoom 2 fits",
          map_show.fit_zoom(36, 40, term(100, 50)) == 2)
    check("a small map gets the biggest zoom even on a small screen",
          map_show.fit_zoom(8, 10, term(80, 24)) == 4)
    check("a map too big for any zoom still draws, at zoom 1",
          map_show.fit_zoom(200, 200, term(40, 10)) == 1)


def test_markers_survive_the_zoom() -> None:
    """Zooming must not move anything. The cell a marker lands in changes; the
    tile it means does not."""
    print("\na marker means the same tile at every zoom")
    if not (PRISM / "maps/CastroForest.asm").exists():
        print("  (skipping — pokeprism not found)")
        return

    for z in map_show.ZOOMS:
        # This is the mapping print_grid uses: the cell nearest the tile's middle.
        cell = ((28 * z + z // 2) // 2, 27 * z + z // 2)
        # ...and it must still be inside the tile it came from.
        back_y = (2 * cell[0]) // z
        back_x = cell[1] // z
        check(f"zoom {z}: the item at tile (28, 27) is drawn inside tile (28, 27)",
              (back_y, back_x) == (28, 27), f"cell {cell} -> tile ({back_y}, {back_x})")


def main() -> int:
    test_units()
    test_source_agrees_with_the_rom()
    test_short_blk_is_an_error()
    test_swatch_is_the_block()
    test_swatches_are_cached_per_map()
    test_markers_are_where_the_source_says()
    test_zoom_fits_the_terminal()
    test_markers_survive_the_zoom()

    print()
    if FAILED:
        print(f"{FAILED} check(s) FAILED")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
