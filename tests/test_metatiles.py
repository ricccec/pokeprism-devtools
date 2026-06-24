#!/usr/bin/env python3
"""Tests for prism-metatiles: the pure analysis helpers (usage counting,
unused detection, top-k ordering, 8x8 tile coverage, TILESET->id resolution).
Hermetic — synthetic data and temp fixtures, no ROM/build.

    python tests/test_metatiles.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pokeprism_devtools.metatiles import (  # noqa: E402
    MapUse,
    TilesetAnalysis,
    _blob_sizes,
    _COLLISION_PER_METATILE,
    _TILES_PER_METATILE,
    blank_unused_metatiles,
    metatile_usage,
    metatile_users,
    script_block_ids,
    tile_coverage,
    tileset_id_map,
)
from pokeprism_devtools.shared.symfile import SymFile, Symbol  # noqa: E402

_failures = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global _failures
    mark = "OK  " if cond else "FAIL"
    print(f"  [{mark}] {label}{(': ' + detail) if detail else ''}")
    if not cond:
        _failures += 1


def test_metatile_usage() -> None:
    print("\nmetatile_usage")
    # 3 metatiles defined. Map A uses {0,1}, B uses {1}, C uses {1,2,2}.
    uses = [
        MapUse("A", bytes([0, 1, 0])),
        MapUse("B", bytes([1, 1])),
        MapUse("C", bytes([1, 2, 2])),
    ]
    usage = metatile_usage(uses, n_defined=3)
    check("distinct-map count, not occurrences", usage == [1, 3, 1], str(usage))

    # Block ids >= n_defined are ignored (out-of-range / border).
    usage2 = metatile_usage([MapUse("X", bytes([0, 5, 9]))], n_defined=3)
    check("out-of-range ids ignored", usage2 == [1, 0, 0], str(usage2))

    # Script-placed ids (changeblock) count even when absent from block data.
    usage3 = metatile_usage(
        [MapUse("S", bytes([0]), frozenset({2}))], n_defined=3
    )
    check("script-only id counted", usage3 == [1, 0, 1], str(usage3))


def test_metatile_users() -> None:
    print("\nmetatile_users")
    uses = [
        MapUse("A", bytes([0, 1])),
        MapUse("B", bytes([1]), frozenset({2})),
        MapUse("C", bytes([1])),
    ]
    users = metatile_users(uses, n_defined=3)
    check("metatile 0 -> [A]", users.get(0) == ["A"], str(users.get(0)))
    check("metatile 1 -> [A,B,C] sorted/deduped",
          users.get(1) == ["A", "B", "C"], str(users.get(1)))
    check("script-only id 2 -> [B]", users.get(2) == ["B"], str(users.get(2)))


def test_script_block_ids() -> None:
    print("\nscript_block_ids")
    text = (
        "\tchangeblock 48, 26, $cf\n"
        "\tchangeblock 46, 26, $5d ; trailing comment\n"
        "\teventflagchangeblock EVENT_DOOR_1, 4, 4, $57\n"
        "\tchangeblock 0, 0, 10\n"          # decimal literal
        "\tchangeblock 1, 1, SOME_CONST\n"  # symbolic — unresolved, skipped
        "\tobjectface PLAYER, DOWN\n"        # unrelated command
    )
    ids = script_block_ids(text)
    check("hex/decimal ids parsed, symbolic skipped",
          ids == {0xCF, 0x5D, 0x57, 10}, str(sorted(ids)))


def test_blob_bank() -> None:
    print("\n_blob_sizes bank lookup")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        syms = SymFile([
            Symbol("Tileset28Meta", 0x0C, 0x6055),
            Symbol("Tileset28Attr", 0x0C, 0x661E),
            # GFX/Coll absent → bank stays None.
        ])
        blobs = {b.name: b for b in _blob_sizes(root, 28, syms)}
        check("metatiles bank from sym", blobs["metatiles"].bank == 0x0C,
              str(blobs["metatiles"].bank))
        check("attributes bank from sym", blobs["attributes"].bank == 0x0C,
              str(blobs["attributes"].bank))
        check("missing label -> None", blobs["gfx"].bank is None,
              str(blobs["gfx"].bank))
        # No .sym at all → every bank is None.
        none_blobs = _blob_sizes(root, 28, None)
        check("no sym -> all banks None",
              all(b.bank is None for b in none_blobs),
              str([b.bank for b in none_blobs]))


def test_ranked_and_unused() -> None:
    print("\nTilesetAnalysis.ranked / unused")
    a = TilesetAnalysis(
        tileset_id=1, name="T", n_defined=5,
        map_labels=[], usage=[0, 4, 0, 2, 4],
        tiles_used=0, tiles_total=0, unused_tiles=[],
    )
    # most-used first; ties broken by metatile index ascending.
    check("ranked order", a.ranked() == [(1, 4), (4, 4), (3, 2)], str(a.ranked()))
    check("unused indices", a.unused == [0, 2], str(a.unused))


def test_tile_coverage() -> None:
    print("\ntile_coverage")
    # 1 metatile (16 entries). First entry tile 0, the rest tile 1.
    metatiles = bytes([0] + [1] * 15)
    attributes = bytes(16)  # all VRAM bank 0
    tiles_total = 4         # gfx has tiles 0..3
    used, unused = tile_coverage(metatiles, attributes, n_defined=1, tiles_total=tiles_total)
    check("distinct used tiles", used == 2, str(used))
    check("unused tiles 2,3", unused == [2, 3], str(unused))

    # VRAM bank bit (attr bit 3) bumps the tile id by 128.
    metatiles2 = bytes([5] + [0] * 15)
    attributes2 = bytes([0x08] + [0] * 15)  # entry 0 -> bank 1 -> tile 133
    used2, _ = tile_coverage(metatiles2, attributes2, n_defined=1, tiles_total=200)
    # entry 0 -> 5+128=133, entries 1..15 -> tile 0  => {133, 0}
    check("VRAM bank +128 applied", used2 == 2, str(used2))


def test_tileset_id_map() -> None:
    print("\ntileset_id_map")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "constants").mkdir()
        (root / "constants" / "tilemap_constants.asm").write_text(
            "LANDTILE EQU 0\n"
            "const_value = 1\n"
            "\tconst TILESET_NALJO_1 ;1\n"
            "\tconst TILESET_NALJO_2 ;2\n"
            "\tconst TILESET_RIJON ;3\n",
            encoding="utf-8",
        )
        m = tileset_id_map(root)
        check("NALJO_1 == 1", m.get("TILESET_NALJO_1") == 1, str(m.get("TILESET_NALJO_1")))
        check("RIJON == 3", m.get("TILESET_RIJON") == 3, str(m.get("TILESET_RIJON")))
        check("non-TILESET EQU excluded", "LANDTILE" not in m)


def test_blank_unused_metatiles() -> None:
    print("\nblank_unused_metatiles")
    n = 4
    metatiles  = bytes(range(256)) * (n * _TILES_PER_METATILE // 256 + 1)
    metatiles  = metatiles[: n * _TILES_PER_METATILE]
    attributes = bytes([0xFF] * n * _TILES_PER_METATILE)
    collision  = bytes([0x0A] * n * _COLLISION_PER_METATILE)

    new_mt, new_at, new_co = blank_unused_metatiles(metatiles, attributes, collision, unused=[1, 3])

    # Metatile 1 and 3 should be all-zero; 0 and 2 should be unchanged.
    check("used metatile 0 untouched",
          new_mt[:_TILES_PER_METATILE] == metatiles[:_TILES_PER_METATILE])
    check("unused metatile 1 zeroed (mt)",
          new_mt[_TILES_PER_METATILE : 2 * _TILES_PER_METATILE] == bytes(_TILES_PER_METATILE))
    check("used metatile 2 untouched",
          new_mt[2 * _TILES_PER_METATILE : 3 * _TILES_PER_METATILE] == metatiles[2 * _TILES_PER_METATILE : 3 * _TILES_PER_METATILE])
    check("unused metatile 3 zeroed (mt)",
          new_mt[3 * _TILES_PER_METATILE :] == bytes(_TILES_PER_METATILE))
    check("unused metatile 1 zeroed (attr)",
          new_at[_TILES_PER_METATILE : 2 * _TILES_PER_METATILE] == bytes(_TILES_PER_METATILE))
    check("unused metatile 1 zeroed (coll)",
          new_co[_COLLISION_PER_METATILE : 2 * _COLLISION_PER_METATILE] == bytes(_COLLISION_PER_METATILE))
    check("used metatile 0 collision untouched",
          new_co[:_COLLISION_PER_METATILE] == bytes([0x0A] * _COLLISION_PER_METATILE))

    # Empty unused list → identical copies.
    mt2, at2, co2 = blank_unused_metatiles(metatiles, attributes, collision, unused=[])
    check("empty unused → no change (mt)", mt2 == metatiles)
    check("empty unused → no change (at)", at2 == attributes)
    check("empty unused → no change (co)", co2 == collision)


def main() -> None:
    test_metatile_usage()
    test_metatile_users()
    test_script_block_ids()
    test_blob_bank()
    test_ranked_and_unused()
    test_tile_coverage()
    test_tileset_id_map()
    test_blank_unused_metatiles()
    print()
    if _failures:
        print(f"{_failures} check(s) failed.")
        sys.exit(1)
    print("All checks passed.")


if __name__ == "__main__":
    main()
