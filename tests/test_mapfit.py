#!/usr/bin/env python3
"""Tests for prism-mapfit: the bank packer, free-space model, wiring editors,
spec loader, and lzcomp sizing. No pytest, no full ROM build required.

    python tests/test_mapfit.py            # from the devtools repo

The packer/wiring/spec checks are hermetic (temp fixtures). The free-space and
lzcomp checks use the real pokeprism repo if one is reachable, and are skipped
(not failed) when it isn't.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

# Allow running straight from a clone without installing.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pokeprism_devtools import mapfit, mapsource, mapwire, paths  # noqa: E402
from pokeprism_devtools.mapfile import Bank, MapFile, Section  # noqa: E402
from pokeprism_devtools.mapspec import MapSpec  # noqa: E402
from pokeprism_devtools.packing import (  # noqa: E402
    FreeSpace, Item, NoFitError, pack,
)

_failures = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global _failures
    mark = "OK  " if cond else "FAIL"
    print(f"  [{mark}] {label}{(': ' + detail) if detail else ''}")
    if not cond:
        _failures += 1


def skip(label: str, why: str) -> None:
    print(f"  [skip] {label}: {why}")


# --------------------------------------------------------------------------- #

def test_packing() -> None:
    print("\npacking.py")

    # Best fit: a 100-byte item should take the tightest scrap (120), not 500.
    fs = FreeSpace({0x10: 500, 0x11: 120, 0x76: 0x4000})
    pls = pack([Item("a", 100)], fs, margin=0)
    check("best-fit picks tightest scrap", pls[0].bank == 0x11, f"${pls[0].bank:02x}")

    # Decreasing order: the big item is placed first and claims its exact-fit
    # bank, instead of the small item grabbing it and forcing the big to spill.
    fs = FreeSpace({0x10: 250, 0x11: 300, 0x76: 0x4000})
    pls = {p.item.key: p for p in pack([Item("small", 50), Item("big", 250)], fs, margin=0)}
    check("big claims its exact-fit bank first", pls["big"].bank == 0x10)
    check("small placed elsewhere", pls["small"].bank == 0x11)

    # Spill: nothing fits in scraps -> empty high bank, lowest first.
    fs = FreeSpace({0x10: 30, 0x11: 30, 0x76: 0x4000, 0x77: 0x4000})
    pls = pack([Item("x", 2000)], fs, margin=16)
    check("spills to empty high bank", pls[0].bank == 0x76 and pls[0].tier == "empty",
          f"${pls[0].bank:02x}/{pls[0].tier}")

    # Margin: 100-byte item must NOT take a 110-byte gap when margin=16.
    fs = FreeSpace({0x10: 110, 0x20: 200})
    pls = pack([Item("x", 100)], fs, margin=16)
    check("margin keeps slack (skips 110 gap)", pls[0].bank == 0x20, f"${pls[0].bank:02x}")

    # No fit: item bigger than any bank (incl. empty) -> NoFitError.
    fs = FreeSpace({0x10: 30, 0x76: 0x4000})
    try:
        pack([Item("toobig", 0x5000)], fs, margin=0)
        check("oversize raises NoFitError", False, "no exception")
    except NoFitError as e:
        check("oversize raises NoFitError", True, str(e)[:40])

    # Input order preserved in output.
    fs = FreeSpace({0x76: 0x4000})
    pls = pack([Item("first", 10), Item("second", 5000)], fs, margin=0)
    check("output preserves input order", [p.item.key for p in pls] == ["first", "second"])


def test_strategies() -> None:
    print("\npacking.py strategies (tight vs park/loose)")
    # A 100-byte item: tight best-fits the scrap; park worst-fits the big empty.
    base = {0x30: 700, 0x76: 0x4000}
    tight = pack([Item("x", 100)], FreeSpace(dict(base)), margin=16, strategy="tight")
    loose = pack([Item("x", 100)], FreeSpace(dict(base)), margin=16, strategy="loose")
    check("tight -> scrap bank", tight[0].bank == 0x30 and tight[0].tier == "scrap",
          f"${tight[0].bank:02x}")
    check("park -> biggest chunk (empty high bank)",
          loose[0].bank == 0x76 and loose[0].tier == "empty", f"${loose[0].bank:02x}")

    # Park spreads a map's blobs across fresh empty banks for max headroom.
    fs = FreeSpace({0x76: 0x4000, 0x77: 0x4000, 0x30: 200})
    pls = pack([Item("script", 600), Item("blk", 20)], fs, margin=16, strategy="loose")
    banks = {p.item.key: p.bank for p in pls}
    check("park spreads blobs across empty banks", banks["script"] != banks["blk"]
          and banks["script"] >= 0x76 and banks["blk"] >= 0x76,
          f"script ${banks['script']:02x}, blk ${banks['blk']:02x}")


def test_consolidate_core() -> None:
    print("\nmapfit consolidate core (lift all + tight re-pack)")
    a = MapSpec(**{**_spec_for_fixture().__dict__, "label": "Alpha", "const": "ALPHA"})
    b = MapSpec(**{**_spec_for_fixture().__dict__, "label": "Beta", "const": "BETA"})
    mp = _synthetic_map([
        ("Map Headers", 0x25, 0x107e),
        ("Filler30", 0x30, 0x4000 - 700),   # bank $30 has 700 free
        ("Filler31", 0x31, 0x4000 - 500),   # bank $31 has 500 free
        ("Map Scripts Alpha", 0x76, 600), ("Map block data Alpha", 0x76, 20),
        ("Second Map Header Alpha", 0x76, 12),
        ("Map Scripts Beta", 0x77, 400), ("Map block data Beta", 0x77, 18),
        ("Second Map Header Beta", 0x77, 12),
    ])
    items, names = [], set()
    for spec in (a, b):
        sizes = mapfit.sizes_from_map_strict(mp, spec)
        for it in mapfit.map_items(spec, sizes):
            items.append(it)
            names.add(it.key)
    fs, _ = mapfit._lift_free_space(mp, names, header_growth=0)
    check("parked banks fully credited back", fs.free[0x76] == 0x4000 and fs.free[0x77] == 0x4000)

    placements = pack(items, fs, margin=16, strategy="tight")
    by = {p.item.key: p for p in placements}
    check("Alpha script best-fits the 700 scrap", by["Map Scripts Alpha"].bank == 0x30)
    check("Beta script best-fits the 500 scrap", by["Map Scripts Beta"].bank == 0x31)
    check("nothing left in the parked high banks",
          all(p.bank < 0x76 for p in placements),
          f"max bank ${max(p.bank for p in placements):02x}")

    # A map that isn't in the .map can't be consolidated — must be built first.
    missing = MapSpec(**{**_spec_for_fixture().__dict__, "label": "Ghost", "const": "GHOST"})
    try:
        mapfit.sizes_from_map_strict(mp, missing)
        check("unbuilt map rejected", False)
    except ValueError:
        check("unbuilt map rejected", True)

    # Selective move: --blobs blk relocates only the block data; script stays.
    sel = mapfit.selected_section_names(a, mapfit.parse_blobs("blk"))
    check("blk selects only the block-data section",
          sel == {"Map block data Alpha"}, str(sel))
    sized = mapfit.map_items(a, mapfit.sizes_from_map_strict(mp, a))
    only_blk = [it for it in sized if it.key in sel]
    check("only one item selected for blk-only move", len(only_blk) == 1)
    fs2, _ = mapfit._lift_free_space(mp, {it.key for it in only_blk}, header_growth=0)
    check("script's parked bank NOT credited back when moving only blk",
          fs2.free[0x76] == 0x4000 - (600 + 20 + 12) + 20, f"{fs2.free[0x76]:#x}")

    # Alias + bad-kind handling.
    check("blockdata alias == blk", mapfit.parse_blobs("blockdata") == ["blockdata"]
          and mapfit.selected_section_names(a, ["blockdata"]) == {"Map block data Alpha"})
    try:
        mapfit.parse_blobs("bogus")
        check("bad blob kind rejected", False)
    except ValueError:
        check("bad blob kind rejected", True)


def test_freespace_real_map() -> None:
    print("\npacking.FreeSpace (real .map)")
    try:
        root = paths.repo_root()
        mp = MapFile.parse(paths.map_path())
    except (paths.RepoNotFound, FileNotFoundError) as e:
        skip("free-space from real .map", str(e))
        return
    fs = FreeSpace.from_mapfile(mp)
    check("high banks $76-$7f synthesised as empty",
          all(fs.free.get(b) == 0x4000 for b in range(0x76, 0x80)))
    check("declared banks present", 0x25 in fs.free and fs.free[0x25] > 0)
    check("no bank exceeds 16 KiB free", all(v <= 0x4000 for v in fs.free.values()))


def _synthetic_map(sections: list[tuple[str, int, int]]) -> MapFile:
    """Build a MapFile from (name, bank, size) tuples, accumulating multiple
    sections into the same bank (used == sum of its sections)."""
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


def test_baseline_credit_back() -> None:
    print("\nmapfit.baseline_free_space (re-run of an already-placed map)")
    spec = _spec_for_fixture()
    mp = _synthetic_map([
        ("Map Headers", 0x25, 0x107e),
        (spec.section_script, 0x30, 640),
        (spec.section_blockdata, 0x31, 18),
        (spec.section_secondary, 0x32, 12),
    ])
    fs, hdr_bank = mapfit.baseline_free_space(mp, spec)
    check("script bytes credited back to its bank",
          fs.free[0x30] == 0x4000, f"{fs.free[0x30]:#x}")
    check("blk bytes credited back", fs.free[0x31] == 0x4000)
    check("Map Headers bank not double-debited (+8) when already placed",
          fs.free[0x25] == 0x4000 - 0x107e, f"{fs.free[0x25]:#x}")
    check("Map Headers bank identified", hdr_bank == 0x25)

    # A *new* map (not in the .map) still gets the +8 debit and no credit-back.
    fresh = MapSpec(**{**spec.__dict__, "label": "BrandNew", "const": "BRAND_NEW"})
    fs2, _ = mapfit.baseline_free_space(mp, fresh)
    check("new map: Map Headers debited by +8",
          fs2.free[0x25] == 0x4000 - 0x107e - 8, f"{fs2.free[0x25]:#x}")
    check("new map: unrelated bank untouched", fs2.free[0x30] == 0x4000 - 640)


def test_mapspec(tmp: Path) -> None:
    print("\nmapspec.py")
    spec_toml = tmp / "m.toml"
    spec_toml.write_text(
        'label = "MtEmberSmallRoom"\n'
        'const = "MT_EMBER_SMALL_ROOM"\n'
        'group = 12\n'
        'height = 10\n'
        'width = 9\n'
        'tileset = "TILESET_CAVE4"\n'
        'permission = "INDOOR"\n'
        'landmark = "MT_EMBER"\n'
        'music = "MUSIC_NONE"\n'
        'palette = "PALETTE_NITE"\n'
        'fishgroup = "FISHGROUP_NONE"\n'
        'border_block = "0"\n'
        'connections = ["north, MT_EMBER, MtEmber, 0, 0, 9, MT_EMBER_SMALL_ROOM"]\n'
        'script_asm = "maps/MtEmberSmallRoom.asm"\n'
        'blk = "maps/blk/MtEmberSmallRoom.blk"\n'
    )
    spec = MapSpec.from_toml(spec_toml)
    check("section names derived", spec.section_blockdata == "Map block data MtEmberSmallRoom")
    check("blk_lz derived", spec.blk_lz == "maps/blk/MtEmberSmallRoom.blk.lz")
    check("one connection parsed", len(spec.connections) == 1)

    bad = tmp / "bad.toml"
    bad.write_text('label = "x"\nnonsense = 1\n')
    try:
        MapSpec.from_toml(bad)
        check("unknown keys rejected", False)
    except ValueError:
        check("unknown keys rejected", True)


def _fixture_repo(tmp: Path, name: str = "repo") -> Path:
    """A minimal repo with just the files the editors touch."""
    root = tmp / name
    (root / "constants").mkdir(parents=True)
    (root / "maps").mkdir()
    (root / "contents").mkdir()

    (root / "constants" / "map_dimension_constants.asm").write_text(
        "\tconst_def\n"
        "\tnewgroup ; 1\n"
        "\tmapgroup INTRO_OUTSIDE, 18, 11\n"
        "\n"
        "\tnewgroup ; 2\n"
        "\tmapgroup CAPER_RIDGE, 9, 20\n"
        "\tmapgroup CAPER_HOUSE, 4, 4\n"
    )
    (root / "maps" / "map_headers.asm").write_text(
        "SECTION \"Map Headers\", ROMX\n"
        "MapGroup1:\n"
        "\tmap_header IntroOutside, TILESET_RIJON, ROUTE, DUMMY2, MUSIC_NONE, 0, PALETTE_NITE, FISHGROUP_NONE\n"
        "MapGroup2:\n"
        "\tmap_header CaperRidge, TILESET_NALJO_2, TOWN, CAPER_RIDGE, MUSIC_NEW_BARK_TOWN, 0, PALETTE_AUTO, FISHGROUP_SHORE\n"
        "\tmap_header CaperHouse, TILESET_HOUSE_1, INDOOR, CAPER_RIDGE, MUSIC_NEW_BARK_TOWN, 1, PALETTE_DAY, FISHGROUP_NONE\n"
    )
    (root / "maps" / "second_map_headers.asm").write_text(
        "SECTION \"Second Map Headers\", ROMX\n"
        "\tmap_header_2 IntroOutside, INTRO_OUTSIDE, 15, 0\n"
    )
    (root / "maps" / "blockdata.asm").write_text(
        "SECTION \"Map block data 1\", ROMX\n"
        "SaffronCity_BlockData:\n"
        "\tINCBIN \"maps/blk/SaffronCity.ablk.lz\"\n"
    )
    (root / "maps" / "map_scripts.asm").write_text(
        "SECTION \"Map Scripts 1\", ROMX\n"
        "INCLUDE \"maps/SaffronCity.asm\"\n"
        "\n"
        "; DO NOT ADD ANYTHING BELOW THIS LINE\n"
        "; if you need to add new map scripts, find a section where they fit\n"
    )
    (root / "contents" / "romx.link").write_text(
        "ROMX $01\n\t\"Code 1\"\n\nROMX $25\n\t\"Sprites\"\n"
    )
    return root


def _spec_for_fixture() -> MapSpec:
    return MapSpec(
        label="MtEmberSmallRoom", const="MT_EMBER_SMALL_ROOM", group=2,
        height=10, width=9, tileset="TILESET_CAVE4", permission="INDOOR",
        landmark="MT_EMBER", music="MUSIC_NONE", palette="PALETTE_NITE",
        fishgroup="FISHGROUP_NONE", border_block="0", conn_flags="0",
        connections=["north, MT_EMBER, MtEmber, 0, 0, 9, MT_EMBER_SMALL_ROOM"],
        script_asm="maps/MtEmberSmallRoom.asm", blk="maps/blk/MtEmberSmallRoom.blk",
    )


def test_wiring(tmp: Path) -> None:
    print("\nmapwire.py")
    root = _fixture_repo(tmp, "wire")
    spec = _spec_for_fixture()

    edits = [ed(root, spec) for ed in mapwire.ALL_ASM_EDITORS]
    mapwire.apply_edits(root, edits, dry_run=False)
    check("all 5 asm editors changed", all(e.changed for e in edits),
          f"{sum(e.changed for e in edits)}/5")

    dim = (root / "constants" / "map_dimension_constants.asm").read_text().splitlines()
    # mapgroup must land inside group 2 (after CAPER_HOUSE), before EOF.
    idx_new = next(i for i, l in enumerate(dim) if "MT_EMBER_SMALL_ROOM" in l)
    idx_house = next(i for i, l in enumerate(dim) if "CAPER_HOUSE" in l)
    check("mapgroup appended into group 2", idx_new == idx_house + 1)

    hdr = (root / "maps" / "map_headers.asm").read_text().splitlines()
    i_new = next(i for i, l in enumerate(hdr) if "map_header MtEmberSmallRoom" in l)
    i_house = next(i for i, l in enumerate(hdr) if "map_header CaperHouse" in l)
    check("map_header appended to MapGroup2 (after CaperHouse)", i_new == i_house + 1)

    sec = (root / "maps" / "second_map_headers.asm").read_text()
    check("secondary in own section",
          'SECTION "Second Map Header MtEmberSmallRoom", ROMX' in sec
          and "map_header_2 MtEmberSmallRoom, MT_EMBER_SMALL_ROOM, 0, 0" in sec
          and "\tconnection north, MT_EMBER" in sec)

    blk = (root / "maps" / "blockdata.asm").read_text()
    check("blockdata section + INCBIN .lz",
          'SECTION "Map block data MtEmberSmallRoom", ROMX' in blk
          and 'INCBIN "maps/blk/MtEmberSmallRoom.blk.lz"' in blk)

    scr = (root / "maps" / "map_scripts.asm").read_text().splitlines()
    i_sec = next(i for i, l in enumerate(scr) if 'Map Scripts MtEmberSmallRoom' in l)
    i_guard = next(i for i, l in enumerate(scr) if mapwire.SCRIPTS_GUARD in l)
    check("script section inserted before the guard", i_sec < i_guard)

    # Idempotency: re-running every editor is a no-op.
    again = [ed(root, spec) for ed in mapwire.ALL_ASM_EDITORS]
    check("editors idempotent on re-run", not any(e.changed for e in again),
          f"{sum(e.changed for e in again)} changed")


def test_shared_section_detection(tmp: Path) -> None:
    print("\nmapsource.shared_section_conflicts")
    root = _fixture_repo(tmp, "shared")
    spec = _spec_for_fixture()  # MtEmberSmallRoom, script_asm maps/MtEmberSmallRoom.asm

    # Clean fixture: map not wired at all -> no conflicts.
    check("unwired map: no conflict", mapsource.shared_section_conflicts(root, spec) == [])

    # Hand-add the script INCLUDE into the SHARED "Map Scripts 1" section.
    sp = root / "maps" / "map_scripts.asm"
    txt = sp.read_text().replace(
        'INCLUDE "maps/SaffronCity.asm"',
        'INCLUDE "maps/SaffronCity.asm"\nINCLUDE "maps/MtEmberSmallRoom.asm"')
    sp.write_text(txt)
    conflicts = mapsource.shared_section_conflicts(root, spec)
    names = {(b, actual) for b, actual, _ in conflicts}
    check("script in shared section detected",
          ("script", "Map Scripts 1") in names, str(conflicts))

    # Proper per-map section is NOT flagged.
    sp.write_text(sp.read_text().replace(
        'INCLUDE "maps/MtEmberSmallRoom.asm"',
        'SECTION "Map Scripts MtEmberSmallRoom", ROMX\nINCLUDE "maps/MtEmberSmallRoom.asm"'))
    after = [c for c in mapsource.shared_section_conflicts(root, spec) if c[0] == "script"]
    check("dedicated per-map section: not flagged", after == [], str(after))


def test_pinning(tmp: Path) -> None:
    print("\nmapwire.pin_sections")
    root = _fixture_repo(tmp, "pin")
    link = root / "contents" / "romx.link"

    # Pin one into an existing declared bank ($25), one into a new high bank ($76).
    pin = mapwire.pin_sections(root, {"Map block data X": 0x25, "Map Scripts X": 0x76})
    link.write_text(pin.new_text)
    txt = link.read_text()
    check("declared-bank pin under ROMX $25", '\t"Map block data X"' in txt)
    check("high bank ROMX $76 declared", "ROMX $76" in txt and '\t"Map Scripts X"' in txt)

    # Re-pin to different banks: stale entries removed, no duplicates.
    pin2 = mapwire.pin_sections(root, {"Map block data X": 0x76, "Map Scripts X": 0x77})
    link.write_text(pin2.new_text)
    txt2 = link.read_text()
    check("re-pin leaves no duplicate", txt2.count('"Map block data X"') == 1,
          f"count={txt2.count(chr(34)+'Map block data X'+chr(34))}")
    check("idempotent re-pin reports current",
          not mapwire.pin_sections(root, {"Map block data X": 0x76, "Map Scripts X": 0x77}).changed)

    # Unpin (used before a re-alloc measurement build) removes the pins; the
    # sections then float. No-op when nothing is pinned.
    unpin = mapwire.unpin_sections(root, ["Map block data X", "Map Scripts X"])
    link.write_text(unpin.new_text)
    txt3 = link.read_text()
    check("unpin removes both pins", unpin.changed
          and '"Map block data X"' not in txt3 and '"Map Scripts X"' not in txt3)
    check("unpin is a no-op when nothing pinned",
          not mapwire.unpin_sections(root, ["Map block data X"]).changed)


def test_lzcomp_sizing() -> None:
    print("\nmapfit.compressed_blk_size (lzcomp)")
    try:
        root = paths.repo_root()
    except paths.RepoNotFound as e:
        skip("lzcomp sizing", str(e))
        return
    lzcomp = root / "utils" / "lzcomp"
    if not lzcomp.exists():
        skip("lzcomp sizing", "utils/lzcomp not built")
        return
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "x.blk"
        src.write_bytes(bytes(90))  # 10x9 of zeroes — should compress well
        out = Path(d) / "x.blk.lz"
        subprocess.run([str(lzcomp), "--", str(src), str(out)], check=True,
                       capture_output=True)
        check("lzcomp produced a smaller stream", 0 < out.stat().st_size < 90,
              f"{out.stat().st_size} bytes")


def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        test_packing()
        test_strategies()
        test_consolidate_core()
        test_freespace_real_map()
        test_baseline_credit_back()
        test_mapspec(tmp)
        test_wiring(tmp)
        test_shared_section_detection(tmp)
        test_pinning(tmp)
        test_lzcomp_sizing()
    print()
    if _failures:
        print(f"{_failures} check(s) FAILED")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
