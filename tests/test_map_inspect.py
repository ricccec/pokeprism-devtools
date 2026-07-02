#!/usr/bin/env python3
"""Tests for prism-maps: the used/RAW/LZ detection in map_inspect.collect().
Hermetic — temp fixtures, no ROM/build.

    python tests/test_map_inspect.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pokeprism_devtools import map_inspect  # noqa: E402

_failures = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global _failures
    mark = "OK  " if cond else "FAIL"
    print(f"  [{mark}] {label}{(': ' + detail) if detail else ''}")
    if not cond:
        _failures += 1


def _fixture_repo(tmp: Path) -> Path:
    root = tmp / "repo"
    (root / "constants").mkdir(parents=True)
    (root / "maps" / "blk").mkdir(parents=True)

    (root / "constants" / "map_dimension_constants.asm").write_text(
        "\tconst_def\n"
        "\tnewgroup ; 1\n"
        "\tmapgroup CAPER_RIDGE, 10, 9\n"          # fully wired, normal
        "\tmapgroup MT_EMBER_SOUTH, 15, 52\n"       # merged blk filename
        "\tmapgroup MOUND_B2F, 8, 8\n"              # aliased labels
        "\tmapgroup GHOST_TOWN, 4, 4\n"              # never wired
        "\tmapgroup OLD_LAB, 4, 4\n"                 # commented-out blockdata
    )

    (root / "maps" / "second_map_headers.asm").write_text(
        'SECTION "Second Map Header CaperRidge", ROMX\n'
        "\tmap_header_2 CaperRidge, CAPER_RIDGE, 0, NORTH\n"
        'SECTION "Second Map Header MtEmberSouth", ROMX\n'
        "\tmap_header_2 MtEmberSouth, MT_EMBER_SOUTH, $43, NORTH | EAST\n"
        'SECTION "Second Map Header MoundB2F", ROMX\n'
        "\tmap_header_2 MoundB2FDark, MOUND_B2F, $9, 0\n"
        "\tmap_header_2 MoundB2F, MOUND_B2F, 9, 0\n"
        'SECTION "Second Map Header OldLab", ROMX\n'
        "\tmap_header_2 OldLab, OLD_LAB, 0, 0\n"
        "\t; map_header_2 CommentedOut, GHOST_TOWN, 0, 0\n"
    )

    (root / "maps" / "blockdata.asm").write_text(
        'SECTION "Map block data 1", ROMX\n'
        "CaperRidge_BlockData:\n"
        '\tINCBIN "maps/blk/CaperRidge.blk.lz"\n'
        'SECTION "Map block data MtEmberSouth", ROMX\n'
        "MtEmberSouth_BlockData:\n"
        '\tINCBIN "maps/blk/MtEmberSouthKindleRoadMerge.blk.lz"\n'
        'SECTION "Map block data Mound", ROMX\n'
        "MoundB2FDark_BlockData:\n"
        '\tINCBIN "maps/blk/MoundB2FDark.blk.lz"\n'
        "MoundB2F_BlockData:\n"
        '\tINCBIN "maps/blk/MoundB2F.blk.lz"\n'
        'SECTION "Map block data Old", ROMX\n'
        ";OldLab_BlockData:\n"
        '\t;INCBIN "maps/blk/OldLab.blk.lz"\n'
    )

    (root / "maps" / "map_scripts.asm").write_text(
        'SECTION "Map Scripts", ROMX\n'
        'INCLUDE "maps/CaperRidge.asm"\n'
        'INCLUDE "maps/MtEmberSouth.asm"\n'
        'INCLUDE "maps/MoundB2F.asm"\n'
        # MoundB2FDark and OldLab are intentionally NOT included.
    )

    (root / "maps" / "CaperRidge.asm").write_text(
        "CaperRidge_MapScriptHeader:\n\tdb 0\n\tdb 0\n"
    )
    (root / "maps" / "MtEmberSouth.asm").write_text(
        "MtEmberSouth_MapScriptHeader:\n\tdb 0\n\tdb 0\n"
    )
    (root / "maps" / "MoundB2F.asm").write_text(
        "MoundB2F_MapScriptHeader:\n\tdb 0\n\tdb 0\n"
    )

    # Real block-data bytes on disk (raw + compressed), including the
    # merged/aliased filenames the labels above actually point at.
    for stem, raw_size, lz_size in [
        ("CaperRidge", 90, 40),
        ("MtEmberSouthKindleRoadMerge", 780, 300),
        ("MoundB2FDark", 64, 30),
        ("MoundB2F", 64, 30),
    ]:
        (root / "maps" / "blk" / f"{stem}.blk").write_bytes(bytes(raw_size))
        (root / "maps" / "blk" / f"{stem}.blk.lz").write_bytes(bytes(lz_size))

    return root


def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        root = _fixture_repo(Path(d))
        rows = {r.name: r for r in map_inspect.collect(root)}

        print("\nmap_inspect.collect() — used detection")
        check("CAPER_RIDGE (normal) used=True", rows["CAPER_RIDGE"].used)
        check(
            "MT_EMBER_SOUTH used=True despite merged blk filename",
            rows["MT_EMBER_SOUTH"].used,
        )
        check(
            "MT_EMBER_SOUTH RAW/LZ resolved via the merged blk file",
            rows["MT_EMBER_SOUTH"].blk_raw == 780 and rows["MT_EMBER_SOUTH"].blk_lz == 300,
            f"raw={rows['MT_EMBER_SOUTH'].blk_raw} lz={rows['MT_EMBER_SOUTH'].blk_lz}",
        )
        check(
            "MOUND_B2F used=True via the fully-wired MoundB2F label "
            "(ignoring the partial MoundB2FDark alias)",
            rows["MOUND_B2F"].used,
        )
        check("GHOST_TOWN (no map_header_2 at all) used=False", not rows["GHOST_TOWN"].used)
        check(
            "GHOST_TOWN RAW/LZ are None",
            rows["GHOST_TOWN"].blk_raw is None and rows["GHOST_TOWN"].blk_lz is None,
        )
        check(
            "OLD_LAB (commented-out _BlockData:) used=False",
            not rows["OLD_LAB"].used,
        )

    print()
    if _failures:
        print(f"{_failures} check(s) FAILED")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
