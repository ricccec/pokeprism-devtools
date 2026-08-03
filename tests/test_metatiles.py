#!/usr/bin/env python3
"""Tests for prism-metatiles: the pure analysis helpers (usage counting,
unused detection, top-k ordering, 8x8 tile coverage, TILESET->id resolution),
and the exact output of the command that prints them.
Hermetic — synthetic data and temp fixtures, no ROM/build.

    python tests/test_metatiles.py

The CLI half is characterization, added before `main` and `render_report` are
shortened: measured against the whole suite, `main`'s 69 lines and
`render_report`'s 65 ran none of themselves. Goldens are recorded from the
behaviour as it stood, not written by hand.
"""

from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pokeprism_devtools import metatiles  # noqa: E402
from pokeprism_devtools.metatiles import (  # noqa: E402
    MapUse,
    TilesetAnalysis,
    blank_unused_metatiles,
    metatile_usage,
    metatile_users,
    script_block_ids,
    tile_coverage,
    tileset_id_map,
)
from pokeprism_devtools.metatiles.tileset import (  # noqa: E402
    _blob_sizes,
    _COLLISION_PER_METATILE,
    _TILES_PER_METATILE,
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


_TILES = 16          # 8x8 tile references per metatile
_COLL = 4            # collision bytes per metatile
_BYTES_PER_TILE = 16  # a 2bpp 8x8 tile


#: Tileset 00's shape. Every number here is load-bearing for the report, and
#: the report is what these goldens pin:
#:
#: - 20 metatiles is **more than one heatmap row** (16 per row), so a change to
#:   the row width shows up.
#: - 8 metatiles end up referenced, which is **more than `--top 3`**, so a
#:   change to the top-k slice shows up.
#: - the unused ones fall in two runs, `5-9` and `12-18`, so **range compaction
#:   has something to compact**.
#: - 24 gfx tiles against 20 referenced leaves `20-23` unused, a third range.
#:
#: A 4-metatile tileset — the first draft — executed every line of the report
#: and could not tell any of those three mutations from correct output.
_N_DEFINED = 20
_TILES_TOTAL = 24


def _fixture_repo(tmp: Path) -> Path:
    """A two-tileset tree: one in use by three maps, one used by nothing.

    Metatile 19 is reached *solely* by a `changeblock` in a script, which is
    the case `collect` exists to get right; two labels share one INCBIN, which
    is the case `blockdata_index` exists to get right.
    """
    root = tmp / "repo"
    (root / "constants").mkdir(parents=True)
    (root / "maps" / "blk").mkdir(parents=True)
    (root / "tilesets").mkdir()
    (root / "gfx" / "tilesets").mkdir(parents=True)

    (root / "Makefile").write_text("all:\n")
    (root / "main.asm").write_text('INCLUDE "constants.asm"\n')

    (root / "constants" / "tilemap_constants.asm").write_text(
        "const_value = 0\n"
        "\tconst TILESET_CAPER ;0\n"
        "\tconst TILESET_EMBER ;1\n",
        encoding="utf-8",
    )

    (root / "maps" / "map_headers.asm").write_text(
        "\tmap_header CaperRidge, TILESET_CAPER, PALETTE_AUTO, FISHGROUP_SHORE\n"
        "\tmap_header MoundB2F, TILESET_CAPER, PALETTE_AUTO, FISHGROUP_SHORE\n"
        "\tmap_header KindleRoad, TILESET_CAPER, PALETTE_AUTO, FISHGROUP_SHORE\n"
        # Two maps the tool must complain about rather than silently drop.
        "\tmap_header GhostTown, TILESET_NOSUCH, PALETTE_AUTO, FISHGROUP_SHORE\n"
        "\tmap_header OldLab, TILESET_EMBER, PALETTE_AUTO, FISHGROUP_SHORE\n",
        encoding="utf-8",
    )

    (root / "maps" / "blockdata.asm").write_text(
        'SECTION "Map block data 1", ROMX\n'
        "CaperRidge_BlockData:\n"
        '\tINCBIN "maps/blk/CaperRidge.blk"\n'
        'SECTION "Map block data 2", ROMX\n'
        # Two labels sharing one INCBIN — the aliasing run blockdata_index
        # emits an entry for every label of.
        "MoundB2F_BlockData:\n"
        "KindleRoad_BlockData:\n"
        '\tINCBIN "maps/blk/MoundB2F.blk"\n',
        encoding="utf-8",
    )

    # Between them these leave 5-9 and 12-18 referenced by nothing.
    (root / "maps" / "blk" / "CaperRidge.blk").write_bytes(bytes([0, 1, 2, 3, 4]))
    (root / "maps" / "blk" / "MoundB2F.blk").write_bytes(bytes([1, 2, 10, 11]))

    # Metatile 19 appears nowhere in the block data; only this places it.
    (root / "maps" / "CaperRidge.asm").write_text(
        "CaperRidge_MapScriptHeader:\n\tchangeblock 4, 6, 19\n", encoding="utf-8"
    )

    # Metatile m points every one of its 16 sub-tiles at gfx tile m, so tiles
    # 0-19 are used and 20-23 are not.
    (root / "tilesets" / "00_metatiles.bin").write_bytes(
        bytes(m for m in range(_N_DEFINED) for _ in range(_TILES))
    )
    (root / "tilesets" / "00_attributes.bin").write_bytes(bytes(_N_DEFINED * _TILES))
    (root / "tilesets" / "00_collision.bin").write_bytes(
        bytes([0x0A] * _N_DEFINED * _COLL)
    )
    (root / "gfx" / "tilesets" / "00.2bpp").write_bytes(
        bytes(_TILES_TOTAL * _BYTES_PER_TILE)
    )

    # Tileset 01 exists so the summary has a second row, and is used by a map
    # with no block data at all.
    (root / "tilesets" / "01_metatiles.bin").write_bytes(bytes(_TILES))
    (root / "tilesets" / "01_attributes.bin").write_bytes(bytes(_TILES))
    (root / "gfx" / "tilesets" / "01.2bpp").write_bytes(bytes(2 * _BYTES_PER_TILE))

    return root


def _run_cli(argv: list[str], cwd: Path) -> tuple[int, str, str]:
    """Run `prism-metatiles <argv>` with *cwd* as the repo.

    `main` takes its argv and returns an exit code, which is what the console
    script uses — but argparse still reports a bad flag by raising, so both
    ways out are read.
    """
    out, err = io.StringIO(), io.StringIO()
    old_cwd = Path.cwd()
    os.chdir(cwd)
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                rc = metatiles.main(argv)
            except SystemExit as e:
                rc = e.code if isinstance(e.code, int) else 0
    finally:
        os.chdir(old_cwd)
    return rc, out.getvalue(), err.getvalue()


#: (label, argv, expected rc, expected stdout, expected stderr). Recorded from
#: the package as it stood, not written by hand.
_CLI_CASES: list[tuple[str, list[str], int, str, str]] = [
    (
        'summary of every tileset', [], 0,
        """ ID  NAME                     META MAPS UNUSED     RAW      LZ
--------------------------------------------------------------
  0  TILESET_CAPER              20    3     12     320       —
  1  TILESET_EMBER               1    0      1      16       —
""",
        """  warning: GhostTown: unknown tileset TILESET_NOSUCH
  warning: OldLab: no block-data file
""",
    ),
    (
        'summary as JSON', ['--json'], 0,
        """[
  {
    "tileset_id": 0,
    "name": "TILESET_CAPER",
    "n_defined": 20,
    "maps": [
      "CaperRidge",
      "KindleRoad",
      "MoundB2F"
    ],
    "usage": [
      1,
      3,
      3,
      1,
      1,
      0,
      0,
      0,
      0,
      0,
      2,
      2,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      1
    ],
    "unused_metatiles": [
      5,
      6,
      7,
      8,
      9,
      12,
      13,
      14,
      15,
      16,
      17,
      18
    ],
    "tiles_used": 20,
    "tiles_total": 24,
    "unused_tiles": [
      20,
      21,
      22,
      23
    ],
    "users": {
      "0": [
        "CaperRidge"
      ],
      "1": [
        "CaperRidge",
        "KindleRoad",
        "MoundB2F"
      ],
      "2": [
        "CaperRidge",
        "KindleRoad",
        "MoundB2F"
      ],
      "3": [
        "CaperRidge"
      ],
      "4": [
        "CaperRidge"
      ],
      "10": [
        "KindleRoad",
        "MoundB2F"
      ],
      "11": [
        "KindleRoad",
        "MoundB2F"
      ],
      "19": [
        "CaperRidge"
      ]
    },
    "blobs": [
      {
        "name": "metatiles",
        "raw": 320,
        "lz": null,
        "bank": null
      },
      {
        "name": "attributes",
        "raw": 320,
        "lz": null,
        "bank": null
      },
      {
        "name": "collision",
        "raw": 80,
        "lz": null,
        "bank": null
      },
      {
        "name": "gfx",
        "raw": 384,
        "lz": null,
        "bank": null
      }
    ]
  },
  {
    "tileset_id": 1,
    "name": "TILESET_EMBER",
    "n_defined": 1,
    "maps": [],
    "usage": [
      0
    ],
    "unused_metatiles": [
      0
    ],
    "tiles_used": 1,
    "tiles_total": 2,
    "unused_tiles": [
      1
    ],
    "users": {},
    "blobs": [
      {
        "name": "metatiles",
        "raw": 16,
        "lz": null,
        "bank": null
      },
      {
        "name": "attributes",
        "raw": 16,
        "lz": null,
        "bank": null
      },
      {
        "name": "collision",
        "raw": null,
        "lz": null,
        "bank": null
      },
      {
        "name": "gfx",
        "raw": 32,
        "lz": null,
        "bank": null
      }
    ]
  }
]
""",
        """  warning: GhostTown: unknown tileset TILESET_NOSUCH
  warning: OldLab: no block-data file
""",
    ),
    (
        "one tileset's report", ['0', '--top', '3'], 0,
        """Tileset 0 (0x00)  TILESET_CAPER
  metatiles defined: 20/256    maps using it: 3

Maps using this tileset:
  CaperRidge                KindleRoad                MoundB2F

Metatile usage heatmap (maps referencing each metatile):
  █████·····██····
  ···█
  legend: · 0 (unused)  █ 1  █ 2  █ 3  █ 4  █ 5  █ 6+

Top 3 most-used metatiles:
  #1×3, #2×3, #10×2
Top 3 least-used (referenced) metatiles:
  #0 ×1  CaperRidge
  #3 ×1  CaperRidge
  #4 ×1  CaperRidge

Unused metatiles: 12 of 20
  5-9, 12-18

8x8 tile coverage: 20/24 used  (4 unused)
  unused tiles: 20-23

Blob sizes (bytes):
  BLOB            RAW      LZ  RATIO  BANK
  metatiles       320       —      —  —
  attributes      320       —      —  —
  collision        80       —      —  —
  gfx             384       —      —  —
""",
        """  warning: GhostTown: unknown tileset TILESET_NOSUCH
  warning: OldLab: no block-data file
""",
    ),
    (
        'one tileset as JSON', ['0', '--json'], 0,
        """{
  "tileset_id": 0,
  "name": "TILESET_CAPER",
  "n_defined": 20,
  "maps": [
    "CaperRidge",
    "KindleRoad",
    "MoundB2F"
  ],
  "usage": [
    1,
    3,
    3,
    1,
    1,
    0,
    0,
    0,
    0,
    0,
    2,
    2,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    1
  ],
  "unused_metatiles": [
    5,
    6,
    7,
    8,
    9,
    12,
    13,
    14,
    15,
    16,
    17,
    18
  ],
  "tiles_used": 20,
  "tiles_total": 24,
  "unused_tiles": [
    20,
    21,
    22,
    23
  ],
  "users": {
    "0": [
      "CaperRidge"
    ],
    "1": [
      "CaperRidge",
      "KindleRoad",
      "MoundB2F"
    ],
    "2": [
      "CaperRidge",
      "KindleRoad",
      "MoundB2F"
    ],
    "3": [
      "CaperRidge"
    ],
    "4": [
      "CaperRidge"
    ],
    "10": [
      "KindleRoad",
      "MoundB2F"
    ],
    "11": [
      "KindleRoad",
      "MoundB2F"
    ],
    "19": [
      "CaperRidge"
    ]
  },
  "blobs": [
    {
      "name": "metatiles",
      "raw": 320,
      "lz": null,
      "bank": null
    },
    {
      "name": "attributes",
      "raw": 320,
      "lz": null,
      "bank": null
    },
    {
      "name": "collision",
      "raw": 80,
      "lz": null,
      "bank": null
    },
    {
      "name": "gfx",
      "raw": 384,
      "lz": null,
      "bank": null
    }
  ]
}
""",
        """  warning: GhostTown: unknown tileset TILESET_NOSUCH
  warning: OldLab: no block-data file
""",
    ),
    (
        'a tileset nothing uses', ['1'], 0,
        """Tileset 1 (0x01)  TILESET_EMBER
  metatiles defined: 1/256    maps using it: 0

Maps using this tileset:
  (none)

Metatile usage heatmap (maps referencing each metatile):
  ·
  legend: · 0 (unused)  █ 1  █ 2  █ 3  █ 4  █ 5  █ 6+

Top 10 most-used metatiles:
  (none)
Top 10 least-used (referenced) metatiles:
  (none)

Unused metatiles: 1 of 1
  0

8x8 tile coverage: 1/2 used  (1 unused)
  unused tiles: 1

Blob sizes (bytes):
  BLOB            RAW      LZ  RATIO  BANK
  metatiles        16       —      —  —
  attributes       16       —      —  —
  collision         —       —      —  —
  gfx              32       —      —  —
""",
        """  warning: GhostTown: unknown tileset TILESET_NOSUCH
  warning: OldLab: no block-data file
""",
    ),
    (
        '--blank-unused without an id is refused', ['--blank-unused'], 2,
        "",
        """  warning: GhostTown: unknown tileset TILESET_NOSUCH
  warning: OldLab: no block-data file
prism-metatiles: --blank-unused requires a tileset id
""",
    ),
]


def test_cli(root: Path) -> None:
    print("\nprism-metatiles — exact output")
    for label, argv, want_rc, want_out, want_err in _CLI_CASES:
        rc, out, err = _run_cli(argv, root)
        check(f"{label}: exit code", rc == want_rc,
              "" if rc == want_rc else f"got {rc}, want {want_rc}")
        check(f"{label}: stdout", out == want_out,
              "" if out == want_out else f"\n--- got ---\n{out}--- want ---\n{want_out}")
        check(f"{label}: stderr", err == want_err,
              "" if err == want_err else f"\n--- got ---\n{err}--- want ---\n{want_err}")


def test_blank_unused_writes_only_with_write() -> None:
    """The dry-run/write pair, on its own tree because it mutates one.

    Metatiles 5-9 and 12-18 are the unused ones, so exactly their bytes may
    change — and only under `--write`. Checking the untouched ones matters as
    much as the blanked ones: a blanker with the wrong stride passes any test
    that only looks at what it was told to zero.
    """
    print("\nprism-metatiles --blank-unused")
    unused = [*range(5, 10), *range(12, 19)]
    kept = [m for m in range(_N_DEFINED) if m not in unused]
    for write in (False, True):
        with tempfile.TemporaryDirectory() as td:
            root = _fixture_repo(Path(td))
            mt_path = root / "tilesets" / "00_metatiles.bin"
            co_path = root / "tilesets" / "00_collision.bin"
            before_mt, before_co = mt_path.read_bytes(), co_path.read_bytes()

            argv = ["0", "--blank-unused"] + (["--write"] if write else [])
            rc, out, _err = _run_cli(argv, root)
            after_mt, after_co = mt_path.read_bytes(), co_path.read_bytes()

            what = "--write" if write else "dry-run"
            written = "Written: 00_metatiles.bin, 00_attributes.bin, 00_collision.bin"
            check(f"{what}: exit code 0", rc == 0, f"got {rc}")
            check(f"{what}: counts the unused metatiles and names their runs",
                  f"\nUnused metatiles to blank: {len(unused)}\n  5-9, 12-18\n" in out,
                  out[-300:])
            check(f"{what}: reports writing only when it wrote",
                  (written in out) == write, out[-200:])
            check(f"{what}: the dry-run notice appears only without --write",
                  ("(dry-run — pass --write to apply changes)" in out) != write)
            if write:
                check("--write: every unused metatile is zeroed",
                      all(after_mt[m * _TILES:(m + 1) * _TILES] == bytes(_TILES)
                          for m in unused))
                check("--write: every used metatile is untouched",
                      all(after_mt[m * _TILES:(m + 1) * _TILES]
                          == before_mt[m * _TILES:(m + 1) * _TILES] for m in kept))
                check("--write: unused collision is zeroed",
                      all(after_co[m * _COLL:(m + 1) * _COLL] == bytes(_COLL)
                          for m in unused))
                check("--write: used collision is untouched",
                      all(after_co[m * _COLL:(m + 1) * _COLL]
                          == before_co[m * _COLL:(m + 1) * _COLL] for m in kept))
            else:
                check("dry-run: the .bin files are byte-identical",
                      after_mt == before_mt and after_co == before_co)


def test_cli_outside_a_repo(tmp: Path) -> None:
    print("\nprism-metatiles — run from outside a game repo")
    outside = tmp / "elsewhere"
    outside.mkdir()
    rc, out, err = _run_cli([], outside)
    check("exit code is 2", rc == 2, f"got {rc}")
    check("stdout is empty", out == "", out)
    check("stderr names the tool", err.startswith("prism-metatiles: Could not find "),
          repr(err))


def main() -> None:
    test_metatile_usage()
    test_metatile_users()
    test_script_block_ids()
    test_blob_bank()
    test_ranked_and_unused()
    test_tile_coverage()
    test_tileset_id_map()
    test_blank_unused_metatiles()
    with tempfile.TemporaryDirectory() as td:
        test_cli(_fixture_repo(Path(td)))
        test_cli_outside_a_repo(Path(td))
    test_blank_unused_writes_only_with_write()
    print()
    if _failures:
        print(f"{_failures} check(s) failed.")
        sys.exit(1)
    print("All checks passed.")


if __name__ == "__main__":
    main()
