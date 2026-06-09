#!/usr/bin/env python3
"""Tests for prism-map: the asm-source parsers (mapsource), MapSpec.to_toml
round-trip, and build_spec. Hermetic — temp fixtures, no ROM/build.

    python tests/test_mapsource.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pokeprism_devtools import map_show, mapsource  # noqa: E402
from pokeprism_devtools.mapfile import Bank, MapFile, Section  # noqa: E402
from pokeprism_devtools.mapspec import MapSpec  # noqa: E402

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
        "\tmapgroup INTRO_OUTSIDE, 18, 11\n"
        "\tnewgroup ; 2\n"
        "\tmapgroup MT_EMBER_SMALL_ROOM, 10, 9\n"
    )
    (root / "maps" / "map_headers.asm").write_text(
        'SECTION "Map Headers", ROMX\n'
        "MapGroup1:\n"
        "\tmap_header IntroOutside, TILESET_RIJON, ROUTE, DUMMY2, MUSIC_NONE, 0, PALETTE_NITE, FISHGROUP_NONE\n"
        "MapGroup2:\n"
        "\tmap_header MtEmberSmallRoom, TILESET_CAVE4, INDOOR, MT_EMBER, MUSIC_NONE, 0, PALETTE_NITE, FISHGROUP_NONE\n"
    )
    (root / "maps" / "second_map_headers.asm").write_text(
        'SECTION "Second Map Header MtEmberSmallRoom", ROMX\n'
        "\tmap_header_2 MtEmberSmallRoom, MT_EMBER_SMALL_ROOM, 0, NORTH\n"
        "\tconnection north, MT_EMBER, MtEmber, 0, 0, 9, MT_EMBER_SMALL_ROOM\n"
        "\n"
        "\tmap_header_2 IntroOutside, INTRO_OUTSIDE, 15, 0\n"
    )
    (root / "maps" / "blockdata.asm").write_text(
        'SECTION "Map block data 1", ROMX\n'
        "SaffronCity_BlockData:\n"
        '\tINCBIN "maps/blk/SaffronCity.ablk.lz"\n'
        'SECTION "Map block data MtEmberSmallRoom", ROMX\n'
        "MtEmberSmallRoom_BlockData:\n"
        '\tINCBIN "maps/blk/MtEmberSmallRoom.blk.lz"\n'
    )
    (root / "maps" / "map_scripts.asm").write_text(
        'SECTION "Map Scripts MtEmberSmallRoom", ROMX\n'
        'INCLUDE "maps/MtEmberSmallRoom.asm"\n'
    )
    # Authored content the spec points at (existence is checked by gather_blobs).
    (root / "maps" / "MtEmberSmallRoom.asm").write_text("; script\n")
    (root / "maps" / "blk" / "MtEmberSmallRoom.blk").write_bytes(bytes(90))
    return root


def test_parsers(root: Path) -> None:
    print("\nmapsource parsers")
    prim = mapsource.primary_header(root, "MtEmberSmallRoom")
    check("primary_header found", prim is not None)
    check("primary fields", prim and prim.tileset == "TILESET_CAVE4"
          and prim.permission == "INDOOR" and prim.landmark == "MT_EMBER"
          and prim.music == "MUSIC_NONE" and prim.phone == 0
          and prim.palette == "PALETTE_NITE" and prim.fishgroup == "FISHGROUP_NONE",
          str(prim))

    sec = mapsource.secondary_header(root, "MtEmberSmallRoom")
    check("secondary_header found", sec is not None)
    check("secondary const + border + flags",
          sec and sec.const == "MT_EMBER_SMALL_ROOM" and sec.border_block == "0"
          and sec.conn_flags == "NORTH", str(sec))
    check("connections parsed (1, raw)",
          sec and sec.connections == ["north, MT_EMBER, MtEmber, 0, 0, 9, MT_EMBER_SMALL_ROOM"],
          str(sec and sec.connections))
    # The next map_header_2 (IntroOutside) must NOT bleed into the connections.
    intro = mapsource.secondary_header(root, "IntroOutside")
    check("IntroOutside has no connections", intro and intro.connections == [])

    check("blk_path strips .lz",
          mapsource.blk_path(root, "MtEmberSmallRoom") == "maps/blk/MtEmberSmallRoom.blk")
    check("blk_path handles .ablk.lz",
          mapsource.blk_path(root, "SaffronCity") == "maps/blk/SaffronCity.ablk")
    check("script_path by filename-stem",
          mapsource.script_path(root, "MtEmberSmallRoom") == "maps/MtEmberSmallRoom.asm")

    check("missing map -> None", mapsource.primary_header(root, "Nope") is None
          and mapsource.secondary_header(root, "Nope") is None
          and mapsource.blk_path(root, "Nope") is None
          and mapsource.script_path(root, "Nope") is None)


def test_enclosing_section(root: Path) -> None:
    print("\nmapsource.enclosing_section")
    sec = mapsource.enclosing_section(
        root / "maps/blockdata.asm",
        lambda ln: ln.strip() == "MtEmberSmallRoom_BlockData:")
    check("blk label -> dedicated section", sec == "Map block data MtEmberSmallRoom", str(sec))
    sec2 = mapsource.enclosing_section(
        root / "maps/blockdata.asm",
        lambda ln: ln.strip() == "SaffronCity_BlockData:")
    check("first label -> its section", sec2 == "Map block data 1", str(sec2))


def test_build_spec_and_toml(root: Path) -> None:
    print("\nmap_show.build_spec + MapSpec.to_toml round-trip")
    spec = map_show.build_spec(root, "MtEmberSmallRoom")
    check("group/dims from dimension constants",
          spec.group == 2 and spec.height == 10 and spec.width == 9,
          f"group {spec.group} {spec.height}x{spec.width}")
    check("header fields carried", spec.tileset == "TILESET_CAVE4" and spec.const == "MT_EMBER_SMALL_ROOM")
    check("paths resolved", spec.script_asm == "maps/MtEmberSmallRoom.asm"
          and spec.blk == "maps/blk/MtEmberSmallRoom.blk")
    check("connections carried", spec.connections and spec.conn_flags == "NORTH")

    with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as f:
        f.write(spec.to_toml())
        toml_path = Path(f.name)
    try:
        back = MapSpec.from_toml(toml_path)
        check("to_toml -> from_toml round-trips equal", back == spec,
              "differs" if back != spec else "")
    finally:
        toml_path.unlink(missing_ok=True)

    # Unbuilt map raises a clear error.
    try:
        map_show.build_spec(root, "Ghost")
        check("unwired label rejected", False)
    except map_show.MapNotFound:
        check("unwired label rejected", True)


def test_gather_blobs(root: Path) -> None:
    print("\nmap_show.gather_blobs (no .map)")
    spec = map_show.build_spec(root, "MtEmberSmallRoom")
    blobs = {b.blob: b for b in map_show.gather_blobs(root, spec, None)}
    check("primary is 8 B in 'Map Headers'",
          blobs["primary"].size == 8 and blobs["primary"].section == "Map Headers")
    check("secondary size = 12 + 12*conns = 24",
          blobs["secondary"].size == 24, str(blobs["secondary"].size))
    check("blk size unknown when lzcomp unavailable (graceful)",
          blobs["blk"].size is None, str(blobs["blk"].size))
    check("blk in its dedicated section",
          blobs["blk"].section == "Map block data MtEmberSmallRoom")
    check("script falls back to source size (proxy) without a .map",
          blobs["script"].size == len("; script\n") and blobs["script"].exact is False,
          str(blobs["script"].size))
    check("nothing flagged shared (all dedicated)",
          not any(b.shared for b in blobs.values()))


def _synthetic_map(sections: list[tuple[str, int, int]]) -> MapFile:
    banks: dict = {}
    for name, bank, size in sections:
        b = banks.get(("ROMX", bank))
        if b is None:
            b = Bank(region="ROMX", number=bank, capacity=0x4000, used=0, free=0x4000)
            banks[("ROMX", bank)] = b
        start = 0x4000 + b.used
        b.sections.append(Section(name, "ROMX", bank, start, start + size - 1, size))
        b.used += size
        b.free = 0x4000 - b.used
    return MapFile(banks)


def test_gather_blobs_with_map(root: Path) -> None:
    print("\nmap_show.gather_blobs (with a .map)")
    spec = map_show.build_spec(root, "MtEmberSmallRoom")
    mp = _synthetic_map([
        ("Map Headers", 0x25, 100),
        ("Map block data MtEmberSmallRoom", 0x1a, 30),
        ("Second Map Header MtEmberSmallRoom", 0x47, 24),
        ("Map Scripts MtEmberSmallRoom", 0x40, 512),
    ])
    blobs = {b.blob: b for b in map_show.gather_blobs(root, spec, mp)}
    check("primary bank from .map", blobs["primary"].bank == 0x25)
    check("secondary bank from .map", blobs["secondary"].bank == 0x47)
    check("blk bank from .map", blobs["blk"].bank == 0x1a)
    check("script bank from .map", blobs["script"].bank == 0x40)
    check("script size EXACT from dedicated .map section",
          blobs["script"].size == 512 and blobs["script"].exact is True,
          f"{blobs['script'].size}/{blobs['script'].exact}")


def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        root = _fixture_repo(Path(d))
        test_parsers(root)
        test_enclosing_section(root)
        test_build_spec_and_toml(root)
        test_gather_blobs(root)
        test_gather_blobs_with_map(root)
    print()
    if _failures:
        print(f"{_failures} check(s) FAILED")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
