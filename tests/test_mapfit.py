#!/usr/bin/env python3
"""Tests for prism-mapfit: the bank packer, free-space model, wiring editors,
spec loader, and lzcomp sizing. No pytest, no full ROM build required.

    python tests/test_mapfit.py            # from the devtools repo

The packer/wiring/spec checks are hermetic (temp fixtures). The free-space and
lzcomp checks use the real pokeprism repo if one is reachable, and are skipped
(not failed) when it isn't.
"""

from __future__ import annotations

import contextlib
import io
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

# Allow running straight from a clone without installing.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pokeprism_devtools import mapfit  # noqa: E402
from pokeprism_devtools.mapfit import freespace, mapwire  # noqa: E402
from pokeprism_devtools.mapfit.packing import (  # noqa: E402
    FreeSpace, Item, NoFitError, pack_into_banks,
)
from pokeprism_devtools.hacks.prism import blobsizes, mapsource # noqa: E402
from pokeprism_devtools.shared import paths # noqa: E402
from pokeprism_devtools.shared.mapfile import Bank, MapFile, Section  # noqa: E402
from pokeprism_devtools.hacks.prism.mapspec import MapSpec  # noqa: E402

PRISM = Path.home() / "code/ricccec/pokeprism"

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
    pls = pack_into_banks([Item("a", 100)], fs, margin=0)
    check("best-fit picks tightest scrap", pls[0].bank == 0x11, f"${pls[0].bank:02x}")

    # Decreasing order: the big item is placed first and claims its exact-fit
    # bank, instead of the small item grabbing it and forcing the big to spill.
    fs = FreeSpace({0x10: 250, 0x11: 300, 0x76: 0x4000})
    pls = {p.item.key: p for p in pack_into_banks([Item("small", 50), Item("big", 250)], fs, margin=0)}
    check("big claims its exact-fit bank first", pls["big"].bank == 0x10)
    check("small placed elsewhere", pls["small"].bank == 0x11)

    # Spill: nothing fits in scraps -> empty high bank, lowest first.
    fs = FreeSpace({0x10: 30, 0x11: 30, 0x76: 0x4000, 0x77: 0x4000})
    pls = pack_into_banks([Item("x", 2000)], fs, margin=16)
    check("spills to empty high bank", pls[0].bank == 0x76 and pls[0].tier == "empty",
          f"${pls[0].bank:02x}/{pls[0].tier}")

    # Margin: 100-byte item must NOT take a 110-byte gap when margin=16.
    fs = FreeSpace({0x10: 110, 0x20: 200})
    pls = pack_into_banks([Item("x", 100)], fs, margin=16)
    check("margin keeps slack (skips 110 gap)", pls[0].bank == 0x20, f"${pls[0].bank:02x}")

    # No fit: item bigger than any bank (incl. empty) -> NoFitError.
    fs = FreeSpace({0x10: 30, 0x76: 0x4000})
    try:
        pack_into_banks([Item("toobig", 0x5000)], fs, margin=0)
        check("oversize raises NoFitError", False, "no exception")
    except NoFitError as e:
        check("oversize raises NoFitError", True, str(e)[:40])

    # Input order preserved in output.
    fs = FreeSpace({0x76: 0x4000})
    pls = pack_into_banks([Item("first", 10), Item("second", 5000)], fs, margin=0)
    check("output preserves input order", [p.item.key for p in pls] == ["first", "second"])


def test_strategies() -> None:
    print("\npacking.py strategies (tight vs park/loose)")
    # A 100-byte item: tight best-fits the scrap; park worst-fits the big empty.
    base = {0x30: 700, 0x76: 0x4000}
    tight = pack_into_banks([Item("x", 100)], FreeSpace(dict(base)), margin=16, strategy="tight")
    loose = pack_into_banks([Item("x", 100)], FreeSpace(dict(base)), margin=16, strategy="loose")
    check("tight -> scrap bank", tight[0].bank == 0x30 and tight[0].tier == "scrap",
          f"${tight[0].bank:02x}")
    check("park -> biggest chunk (empty high bank)",
          loose[0].bank == 0x76 and loose[0].tier == "empty", f"${loose[0].bank:02x}")

    # Park spreads a map's blobs across fresh empty banks for max headroom.
    fs = FreeSpace({0x76: 0x4000, 0x77: 0x4000, 0x30: 200})
    pls = pack_into_banks([Item("script", 600), Item("blk", 20)], fs, margin=16, strategy="loose")
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
    fs, _ = freespace._lift_free_space(mp, names, header_growth=0)
    check("parked banks fully credited back", fs.free[0x76] == 0x4000 and fs.free[0x77] == 0x4000)

    placements = pack_into_banks(items, fs, margin=16, strategy="tight")
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
    fs2, _ = freespace._lift_free_space(mp, {it.key for it in only_blk}, header_growth=0)
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
    declared = {n for (region, n) in mp.banks if region == "ROMX"}
    undeclared = [b for b in range(1, 0x80) if b not in declared]
    check("banks absent from the .map synthesised as empty",
          bool(undeclared)
          and all(fs.free.get(b) == 0x4000 for b in undeclared),
          f"{len(undeclared)} undeclared bank(s)")
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
    check("Map Headers bank not double-debited when already placed",
          fs.free[0x25] == 0x4000 - 0x107e, f"{fs.free[0x25]:#x}")
    check("Map Headers bank identified", hdr_bank == 0x25)

    # A *new* map (not in the .map) still gets the header debit and no
    # credit-back. The size is named, not restated: spelling it `8` here is how
    # the under-reservation stayed pinned while the macro emitted 9.
    growth = blobsizes.PRIMARY_HEADER_GROWTH
    fresh = MapSpec(**{**spec.__dict__, "label": "BrandNew", "const": "BRAND_NEW"})
    fs2, _ = mapfit.baseline_free_space(mp, fresh)
    check(f"new map: Map Headers debited by +{growth}",
          fs2.free[0x25] == 0x4000 - 0x107e - growth, f"{fs2.free[0x25]:#x}")
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
    check("no section override -> old TOML (missing the keys) still works",
          spec.blockdata_section == "" and spec.script_section == "" and spec.secondary_section == "")

    bad = tmp / "bad.toml"
    bad.write_text('label = "x"\nnonsense = 1\n')
    try:
        MapSpec.from_toml(bad)
        check("unknown keys rejected", False)
    except ValueError:
        check("unknown keys rejected", True)

    overridden = MapSpec(**{**spec.__dict__, "blockdata_section": "Map block data 12"})
    check("section override wins over the derived default",
          overridden.section_blockdata == "Map block data 12")
    check("un-overridden sections still derive from label",
          overridden.section_script == "Map Scripts MtEmberSmallRoom")

    m2 = tmp / "m2.toml"
    m2.write_text(overridden.to_toml())
    reloaded = MapSpec.from_toml(m2)
    check("section override round-trips through to_toml/from_toml",
          reloaded.section_blockdata == "Map block data 12")


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


def test_manual_placement(tmp: Path) -> None:
    """Phase 2b: auto bank-packing is now optional. A blob can join an existing
    shared section (inheriting its bank, touching no linker pin), or claim its
    own section pinned to a bank you name."""
    print("\nmanual placement: into an existing section")
    root = _fixture_repo(tmp, "manual")
    spec = _spec_for_fixture()
    spec.script_into = "Map Scripts 1"          # the fixture's shared section
    spec.blockdata_bank = 0x4D                  # own section, bank chosen by hand
    check("no validation problems", [p for p in spec.validate(root)
                                     if "not found" not in p] == [])

    check("script placement is 'into', and inherits — so no pin",
          (spec.placement("script").mode, spec.placement("script").needs_pin)
          == ("into", False))
    check("its section is the shared one, not a per-map name",
          spec.section_for("script") == "Map Scripts 1")
    check("blockdata placement is 'bank', own section, still pinned",
          (spec.placement("blockdata").mode, spec.placement("blockdata").bank,
           spec.placement("blockdata").needs_pin) == ("bank", 0x4D, True))
    check("secondary is left on auto", spec.placement("secondary").mode == "auto")
    check("only the auto blob goes to the packer",
          [i.key for i in mapfit.map_items(spec, mapfit.Sizes(10, 20, 30, True))]
          == [spec.section_secondary])

    print("\nthe editors write it where it says")
    e_script = mapwire.wire_script(root, spec)
    e_blk = mapwire.wire_blockdata(root, spec)
    mapwire.apply_edits(root, [e_script, e_blk], dry_run=False)

    scripts = (root / "maps" / "map_scripts.asm").read_text()
    check("the INCLUDE landed inside the existing section, no new SECTION",
          'SECTION "Map Scripts MtEmberSmallRoom"' not in scripts
          and 'INCLUDE "maps/MtEmberSmallRoom.asm"' in scripts, scripts)
    lines = scripts.split("\n")
    inc = lines.index('INCLUDE "maps/MtEmberSmallRoom.asm"')
    sec = lines.index('SECTION "Map Scripts 1", ROMX')
    guard = next(i for i, ln in enumerate(lines) if "DO NOT ADD" in ln)
    check("it sits under that section and above the guard banner",
          sec < inc < guard, f"section {sec}, include {inc}, guard {guard}")
    check("appended after the section's existing entry, not before it",
          lines.index('INCLUDE "maps/SaffronCity.asm"') < inc)

    blk = (root / "maps" / "blockdata.asm").read_text()
    check("the bank-pinned blob still gets its own section",
          'SECTION "Map block data MtEmberSmallRoom", ROMX' in blk)

    print("\nre-running is a no-op, as everywhere else")
    check("script editor is idempotent", not mapwire.wire_script(root, spec).changed)
    check("blockdata editor is idempotent", not mapwire.wire_blockdata(root, spec).changed)

    print("\nan into-placed blob is no longer a 'shared section' conflict")
    conflicts = mapsource.shared_section_conflicts(root, spec)
    check("the tool now manages it, because the spec asked for it",
          not [c for c in conflicts if c[0] == "script"], str(conflicts))

    print("\nnaming a section that doesn't exist is refused")
    bad = _spec_for_fixture()
    bad.script_into = "Map Scripts 99"
    try:
        mapwire.wire_script(_fixture_repo(tmp, "manual2"), bad)
        check("unknown section raises", False)
    except mapwire.WiringError as e:
        check("unknown section raises, and names it", "Map Scripts 99" in str(e))

    print("\nsetting both placements for one blob is a contradiction")
    both = _spec_for_fixture()
    both.script_into, both.script_bank = "Map Scripts 1", 0x4D
    check("validate() rejects it",
          any("not both" in p for p in both.validate(root)), str(both.validate(root)))


def test_reused_section_name_appends(tmp: Path) -> None:
    """An own-section placement (`*_section`, what the new-map form sets) whose
    name already exists must *append into* that section, not write a second
    `SECTION "<name>"` the linker would split back apart. A section name reused in
    the form is the studio's way of saying 'put it here', same as `*_into`."""
    print("\nreusing an existing section name appends, it does not duplicate")
    root = _fixture_repo(tmp, "reuse")
    spec = _spec_for_fixture()
    # Name each blob's own section after one the fixture already has.
    spec.blockdata_section = "Map block data 1"
    spec.script_section = "Map Scripts 1"
    spec.secondary_section = "Second Map Headers"

    e_blk = mapwire.wire_blockdata(root, spec)
    e_scr = mapwire.wire_script(root, spec)
    e_sec = mapwire.wire_secondary_header(root, spec)
    mapwire.apply_edits(root, [e_blk, e_scr, e_sec], dry_run=False)

    blk = (root / "maps" / "blockdata.asm").read_text()
    check("blockdata joined the existing section, no duplicate",
          blk.count('SECTION "Map block data 1"') == 1
          and "MtEmberSmallRoom_BlockData:" in blk, blk)

    scr = (root / "maps" / "map_scripts.asm").read_text()
    check("script joined the existing section, above the guard",
          scr.count('SECTION "Map Scripts 1"') == 1
          and scr.index('INCLUDE "maps/MtEmberSmallRoom.asm"') < scr.index("DO NOT ADD"),
          scr)

    sec = (root / "maps" / "second_map_headers.asm").read_text()
    check("secondary joined the existing section, no per-map name",
          sec.count('SECTION "Second Map Headers"') == 1
          and 'SECTION "Second Map Header MtEmberSmallRoom"' not in sec
          and "map_header_2 MtEmberSmallRoom," in sec, sec)

    check("each editor reports appending, not adding",
          all("appended into existing section" in e.detail
              for e in (e_blk, e_scr, e_sec)),
          str([e.detail for e in (e_blk, e_scr, e_sec)]))

    again = [mapwire.wire_blockdata(root, spec), mapwire.wire_script(root, spec),
             mapwire.wire_secondary_header(root, spec)]
    check("still idempotent on re-run", not any(e.changed for e in again))


def test_manual_placement_fit(tmp: Path) -> None:
    """A hand-placed blob skips the packer, so nothing else checks it fits —
    resolve_manual is the only thing standing between a bad bank and a confusing
    rgblink failure much later."""
    print("\nmanual placement: the bank is checked, and reserved")
    root = _fixture_repo(tmp, "fit")
    spec = _spec_for_fixture()
    spec.script_into = "Map Scripts 1"

    mp = MapFile({
        ("ROMX", 0x01): Bank("ROMX", 0x01, 16384, 16000, 384,
                             [Section("Map Scripts 1", "ROMX", 0x01, 0, 0, 500)]),
        ("ROMX", 0x4D): Bank("ROMX", 0x4D, 16384, 16000, 384, []),
    })
    sizes = mapfit.Sizes(blockdata=100, secondary=24, script=200, script_measured=True)

    fs = FreeSpace.from_mapfile(mp)
    placements = mapfit.resolve_manual(mp, spec, sizes, fs, margin=16)
    check("the into-blob resolves to its section's bank",
          [(p.item.key, p.bank, p.tier) for p in placements]
          == [("Map Scripts 1", 0x01, "shared")], str(placements))
    check("and its bytes are reserved, so the packer can't hand them out twice",
          fs.free[0x01] == 384 - 200, str(fs.free[0x01]))

    print("\na blob that doesn't fit is refused, naming the section and bank")
    tight = MapFile({
        ("ROMX", 0x01): Bank("ROMX", 0x01, 16384, 16300, 84,
                             [Section("Map Scripts 1", "ROMX", 0x01, 0, 0, 500)]),
    })
    try:
        mapfit.resolve_manual(tight, spec, sizes, FreeSpace.from_mapfile(tight),
                              margin=16)
        check("over-full bank raises", False)
    except mapfit.PlacementError as e:
        check("over-full bank raises, naming section and bank",
              "Map Scripts 1" in str(e) and "$01" in str(e), str(e))

    print("\nmeasuring a blob that has no section of its own")
    before = MapFile({("ROMX", 0x01): Bank("ROMX", 0x01, 16384, 16000, 384,
                                           [Section("Map Scripts 1", "ROMX", 0x01, 0, 0, 500)])})
    after = MapFile({("ROMX", 0x01): Bank("ROMX", 0x01, 16384, 16000, 384,
                                          [Section("Map Scripts 1", "ROMX", 0x01, 0, 0, 712)])})
    measured = mapfit.sizes_from_map(after, spec, sizes, before=before)
    check("its size is how much the shared section grew, not the section's size",
          measured.script == 212, str(measured.script))


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


BYTES_PER_ARGUMENT = {"db": 1, "dw": 2, "dl": 4, "dba": 3, "dab": 3, "dbw": 3}
NIBBLES_PER_BYTE = 2             # `dn` packs two nibbles into one byte


def _macro_body(text: str, macro: str) -> list[str]:
    """The lines between `MACRO <macro>` and its `ENDM`, comments stripped."""
    body: list[str] = []
    inside = False
    for line in text.splitlines():
        code = line.split(";")[0].strip()
        if re.fullmatch(rf"MACRO\s+{macro}", code):
            inside = True
        elif inside and code == "ENDM":
            return body
        elif inside and code:
            body.append(code)
    raise AssertionError(f"no `MACRO {macro}` in the file")


def _count_arguments(operands: str) -> int:
    """Comma-separated arguments, ignoring commas inside `BANK(…)`."""
    if not operands.strip():
        return 0
    depth, count = 0, 1
    for ch in operands:
        depth += (ch == "(") - (ch == ")")
        if ch == "," and depth == 0:
            count += 1
    return count


def _emitted_bytes(body: list[str]) -> int:
    """How many bytes one invocation of this macro body emits.

    An unrecognised directive raises rather than counting nothing: a silent
    zero is exactly the under-count this exists to catch. That also rules out
    rgbds conditionals — `connection`'s size depends on which branch its
    direction argument takes, which counting a body cannot answer.
    """
    total = 0
    for line in body:
        if line.endswith(":"):
            continue                                  # a label emits nothing
        directive, operands = (re.split(r"\s+", line, maxsplit=1) + [""])[:2]
        args = _count_arguments(operands)
        if directive == "dn":
            total += -(-args // NIBBLES_PER_BYTE)
        elif directive in BYTES_PER_ARGUMENT:
            total += BYTES_PER_ARGUMENT[directive] * args
        else:
            raise AssertionError(f"cannot size `{line}` — unknown directive")
    return total


def test_header_sizes_match_the_macros() -> None:
    """The header sizes `mapfit` reserves, counted from prism's own macros.

    `PRIMARY_HEADER_GROWTH` said 8 while `map_header` emits 9, so the packer
    under-reserved the shared `Map Headers` section by a byte for every map
    added. The constants are a transcription of the macros; nothing but a
    reader checked them.
    """
    print("\nblobsizes constants vs prism's macros/map.asm")
    macros = PRISM / "macros" / "map.asm"
    if not macros.exists():
        skip("header sizes against the macros", f"no pokeprism at {PRISM}")
        return
    text = macros.read_text()

    primary = _emitted_bytes(_macro_body(text, "map_header"))
    check("PRIMARY_HEADER_GROWTH is what `map_header` emits",
          primary == blobsizes.PRIMARY_HEADER_GROWTH,
          f"macro emits {primary}, constant says "
          f"{blobsizes.PRIMARY_HEADER_GROWTH}")

    secondary = _emitted_bytes(_macro_body(text, "map_header_2"))
    check("SECONDARY_BASE is what `map_header_2` emits",
          secondary == blobsizes.SECONDARY_BASE,
          f"macro emits {secondary}, constant says {blobsizes.SECONDARY_BASE}")


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


# --------------------------------------------------------------------------- #
# The command line
# --------------------------------------------------------------------------- #

#: A baseline .map with three ROMX banks of very different shapes, so best-fit
#: and worst-fit choose *different* banks and the goldens can tell the two
#: strategies apart: $01 nearly full, $02 with a middling hole, $03 wide open.
_BASELINE_MAP = """ROMX bank #1:
  SECTION: $4000-$7e7f ($3e80 bytes) ["Code 1"]
  TOTAL EMPTY: $0180 bytes
ROMX bank #2:
  SECTION: $4000-$5fff ($2000 bytes) ["Map Headers"]
  TOTAL EMPTY: $2000 bytes
ROMX bank #3:
  SECTION: $4000-$40ff ($0100 bytes) ["Sprites"]
  TOTAL EMPTY: $3f00 bytes
"""

#: The same ROM after the map has been built into it — what `consolidate`
#: needs, because it reads exact sizes out of the .map rather than estimating.
#:
#: The secondary header is deliberately in bank $01 already, sized so that a
#: tight re-pack puts it **back where it is**. A layout where every section
#: moves cannot tell "count the ones that moved" from "count them all", and
#: cannot tell "banks freed" from "banks touched" — two mutations that both
#: survived against a first draft where all three moved.
_BUILT_MAP = """ROMX bank #1:
  SECTION: $4000-$7dff ($3e00 bytes) ["Code 1"]
  SECTION: $7e00-$7e1a ($001b bytes) ["Second Map Header MtEmberSmallRoom"]
  TOTAL EMPTY: $01e5 bytes
ROMX bank #2:
  SECTION: $4000-$5fff ($2000 bytes) ["Map Headers"]
  TOTAL EMPTY: $2000 bytes
ROMX bank #3:
  SECTION: $4000-$40ff ($0100 bytes) ["Sprites"]
  SECTION: $4100-$45ff ($0500 bytes) ["Map Scripts MtEmberSmallRoom"]
  SECTION: $4600-$47ff ($0200 bytes) ["Map block data MtEmberSmallRoom"]
  TOTAL EMPTY: $3800 bytes
"""

#: `compressed_blk_size` shells out to `utils/lzcomp` and takes the size of
#: what it writes. Stubbing the binary keeps the test hermetic and its numbers
#: fixed; it stands in at a real process boundary, so the code under test runs
#: unchanged, subprocess and all. The ratio is arbitrary but constant.
_LZCOMP_STUB = """#!/bin/sh
# args: -- <src> <out>
wc -c < "$2" | awk '{ n = int($1 / 2); s = ""; while (length(s) < n) s = s "z"; \
printf "%s", s }' > "$3"
"""


def _cli_repo(tmp: Path, name: str) -> tuple[Path, Path]:
    """A fixture repo the command line can actually be run against.

    Adds to `_fixture_repo` the four things the CLI needs and the editors do
    not: the files the spec points at, a stub `lzcomp`, a `Makefile`/`main.asm`
    for `repo_root`, and the spec itself on disk.
    """
    root = _fixture_repo(tmp, name)
    (root / "Makefile").write_text("all:\n")
    (root / "main.asm").write_text('INCLUDE "constants.asm"\n')

    (root / "maps" / "MtEmberSmallRoom.asm").write_text(
        "MtEmberSmallRoom_MapScriptHeader:\n\tdb 0\n\tdb 0\n"
    )
    (root / "maps" / "blk").mkdir(exist_ok=True)
    (root / "maps" / "blk" / "MtEmberSmallRoom.blk").write_bytes(bytes(90))

    (root / "utils").mkdir()
    lzcomp = root / "utils" / "lzcomp"
    lzcomp.write_text(_LZCOMP_STUB)
    lzcomp.chmod(0o755)

    spec_path = root / "MtEmberSmallRoom.toml"
    spec_path.write_text(_spec_for_fixture().to_toml())
    return root, spec_path


def _run_cli(argv: list[str], cwd: Path) -> tuple[int, str, str]:
    """Run `prism-mapfit <argv>` with *cwd* as the repo.

    `_load_spec` reports a bad spec by calling `sys.exit` while everything else
    returns a code, so both ways out are read.
    """
    out, err = io.StringIO(), io.StringIO()
    old_cwd = Path.cwd()
    os.chdir(cwd)
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                rc = mapfit.main(argv)
            except SystemExit as e:
                rc = e.code if isinstance(e.code, int) else 0
    finally:
        os.chdir(old_cwd)
    return rc, out.getvalue(), err.getvalue()


#: (label, argv, expected rc, expected stdout, expected stderr). `{spec}` and
#: `{map}` are filled in per run. Recorded from the package as it stood.
#:
#: Every case is a `plan` or a `--dry-run`: those are the paths that neither
#: build nor write, and `run_make` is the one thing here that cannot be run in
#: a fixture. What a build would have measured is supplied by `--script-size`,
#: which is the flag that exists for exactly that reason.
_CLI_CASES: list[tuple[str, list[str], int, str, str]] = [
    (
        'plan',
        ['plan', '--spec', '{spec}', '--map', '{map}', '--script-size', '600'], 0,
        """Strategy: tight (best-fit)
Map: MtEmberSmallRoom  (MT_EMBER_SMALL_ROOM)  group 2  10x9

Blob sizes
  block data       45 bytes  (compressed, exact)
  secondary        24 bytes  (1 connections)
  script/event    600 bytes  (given)
  primary hdr       9 bytes  (in place, bank $02)

Placement
  $01  [scrap ]  Map block data MtEmberSmallRoom  (45 bytes)
  $02  [scrap ]  Map Scripts MtEmberSmallRoom  (600 bytes)
  $01  [scrap ]  Second Map Header MtEmberSmallRoom  (24 bytes)
""",
        "",
    ),
    (
        'plan --park picks the roomiest bank instead of the tightest',
        ['plan', '--spec', '{spec}', '--map', '{map}', '--script-size', '600', '--park'], 0,
        """Strategy: park (worst-fit, biggest chunk)
Map: MtEmberSmallRoom  (MT_EMBER_SMALL_ROOM)  group 2  10x9

Blob sizes
  block data       45 bytes  (compressed, exact)
  secondary        24 bytes  (1 connections)
  script/event    600 bytes  (given)
  primary hdr       9 bytes  (in place, bank $02)

Placement
  $05  [scrap ]  Map block data MtEmberSmallRoom  (45 bytes)
  $04  [scrap ]  Map Scripts MtEmberSmallRoom  (600 bytes)
  $06  [scrap ]  Second Map Header MtEmberSmallRoom  (24 bytes)
""",
        "",
    ),
    (
        'plan without a script size refuses rather than guessing',
        ['plan', '--spec', '{spec}', '--map', '{map}'], 2,
        "",
        """error: script size unknown — pass --script-size N or run `add` to measure it with a build.
""",
    ),
    (
        'plan with a blob appended into an existing section',
        ['plan', '--spec', '{spec}', '--map', '{map}', '--script-size', '600', '--blockdata-into', 'Sprites'], 0,
        """Strategy: tight (best-fit)
Map: MtEmberSmallRoom  (MT_EMBER_SMALL_ROOM)  group 2  10x9

Blob sizes
  block data       45 bytes  (compressed, exact)
  secondary        24 bytes  (1 connections)
  script/event    600 bytes  (given)
  primary hdr       9 bytes  (in place, bank $02)

Placement
  $03  [shared]  Sprites  (45 bytes) (appended into an existing section — not pinned)
  $02  [scrap ]  Map Scripts MtEmberSmallRoom  (600 bytes)
  $01  [scrap ]  Second Map Header MtEmberSmallRoom  (24 bytes)
""",
        "",
    ),
    (
        'add --dry-run',
        ['add', '--spec', '{spec}', '--map', '{map}', '--script-size', '600', '--dry-run'], 0,
        """  [edit] constants/map_dimension_constants.asm: added 'mapgroup MT_EMBER_SMALL_ROOM, 10, 9' to group 2
  [edit] maps/map_headers.asm: appended map_header MtEmberSmallRoom to MapGroup2
  [edit] maps/second_map_headers.asm: added section 'Second Map Header MtEmberSmallRoom'
  [edit] maps/blockdata.asm: added section 'Map block data MtEmberSmallRoom'
  [edit] maps/map_scripts.asm: added section 'Map Scripts MtEmberSmallRoom'

Strategy: tight (best-fit)
Map: MtEmberSmallRoom  (MT_EMBER_SMALL_ROOM)  group 2  10x9

Blob sizes
  block data       45 bytes  (compressed, exact)
  secondary        24 bytes  (1 connections)
  script/event    600 bytes  (given)
  primary hdr       9 bytes  (in place, bank $02)

Placement
  $01  [scrap ]  Map block data MtEmberSmallRoom  (45 bytes)
  $02  [scrap ]  Map Scripts MtEmberSmallRoom  (600 bytes)
  $01  [scrap ]  Second Map Header MtEmberSmallRoom  (24 bytes)

  [edit] contents/romx.link: Map block data MtEmberSmallRoom -> ROMX $01; Map Scripts MtEmberSmallRoom -> new ROMX $02; Second Map Header MtEmberSmallRoom -> ROMX $01

(dry run — no files written)
""",
        "",
    ),
    (
        'add with a hand-picked bank',
        ['add', '--spec', '{spec}', '--map', '{map}', '--script-size', '600', '--blockdata-bank', '0x03', '--dry-run'], 0,
        """  [edit] constants/map_dimension_constants.asm: added 'mapgroup MT_EMBER_SMALL_ROOM, 10, 9' to group 2
  [edit] maps/map_headers.asm: appended map_header MtEmberSmallRoom to MapGroup2
  [edit] maps/second_map_headers.asm: added section 'Second Map Header MtEmberSmallRoom'
  [edit] maps/blockdata.asm: added section 'Map block data MtEmberSmallRoom'
  [edit] maps/map_scripts.asm: added section 'Map Scripts MtEmberSmallRoom'

Strategy: tight (best-fit)
Map: MtEmberSmallRoom  (MT_EMBER_SMALL_ROOM)  group 2  10x9

Blob sizes
  block data       45 bytes  (compressed, exact)
  secondary        24 bytes  (1 connections)
  script/event    600 bytes  (given)
  primary hdr       9 bytes  (in place, bank $02)

Placement
  $03  [pinned]  Map block data MtEmberSmallRoom  (45 bytes) (bank chosen by hand)
  $02  [scrap ]  Map Scripts MtEmberSmallRoom  (600 bytes)
  $01  [scrap ]  Second Map Header MtEmberSmallRoom  (24 bytes)

  [edit] contents/romx.link: Map block data MtEmberSmallRoom -> new ROMX $03; Map Scripts MtEmberSmallRoom -> new ROMX $02; Second Map Header MtEmberSmallRoom -> ROMX $01

(dry run — no files written)
""",
        "",
    ),
    (
        'add with a $-hex bank, the spelling the linker script uses',
        ['add', '--spec', '{spec}', '--map', '{map}', '--script-size', '600', '--blockdata-bank', '$03', '--dry-run'], 0,
        """  [edit] constants/map_dimension_constants.asm: added 'mapgroup MT_EMBER_SMALL_ROOM, 10, 9' to group 2
  [edit] maps/map_headers.asm: appended map_header MtEmberSmallRoom to MapGroup2
  [edit] maps/second_map_headers.asm: added section 'Second Map Header MtEmberSmallRoom'
  [edit] maps/blockdata.asm: added section 'Map block data MtEmberSmallRoom'
  [edit] maps/map_scripts.asm: added section 'Map Scripts MtEmberSmallRoom'

Strategy: tight (best-fit)
Map: MtEmberSmallRoom  (MT_EMBER_SMALL_ROOM)  group 2  10x9

Blob sizes
  block data       45 bytes  (compressed, exact)
  secondary        24 bytes  (1 connections)
  script/event    600 bytes  (given)
  primary hdr       9 bytes  (in place, bank $02)

Placement
  $03  [pinned]  Map block data MtEmberSmallRoom  (45 bytes) (bank chosen by hand)
  $02  [scrap ]  Map Scripts MtEmberSmallRoom  (600 bytes)
  $01  [scrap ]  Second Map Header MtEmberSmallRoom  (24 bytes)

  [edit] contents/romx.link: Map block data MtEmberSmallRoom -> new ROMX $03; Map Scripts MtEmberSmallRoom -> new ROMX $02; Second Map Header MtEmberSmallRoom -> ROMX $01

(dry run — no files written)
""",
        "",
    ),
    (
        'consolidate --dry-run',
        ['consolidate', '--spec', '{spec}', '--map', '{built}', '--dry-run'], 0,
        """Consolidating 1 map(s), blobs: script, blk, secondary -> tightest existing space

MtEmberSmallRoom
  [scrap] Map block data MtEmberSmallRoom  (512 B)  $03 -> $02  *moved*
  [scrap] Map Scripts MtEmberSmallRoom  (1280 B)  $03 -> $02  *moved*
  [scrap] Second Map Header MtEmberSmallRoom  (27 B)  $01 -> $01

2 section(s) relocated; banks possibly freed: $03

  [edit] contents/romx.link: Map block data MtEmberSmallRoom -> new ROMX $02; Map Scripts MtEmberSmallRoom -> ROMX $02; Second Map Header MtEmberSmallRoom -> ROMX $01

(dry run — no files written)
""",
        "",
    ),
    (
        'consolidate before the map has been built',
        ['consolidate', '--spec', '{spec}', '--map', '{map}', '--dry-run'], 2,
        "",
        """error: MtEmberSmallRoom: not in the .map yet (Map Scripts MtEmberSmallRoom, Map block data MtEmberSmallRoom, Second Map Header MtEmberSmallRoom). Allocate and build it with `add` before consolidating.
""",
    ),
]


def test_cli(root: Path, spec: Path, baseline: Path, built: Path) -> None:
    print("\nprism-mapfit — exact output")
    for label, argv_t, want_rc, want_out, want_err in _CLI_CASES:
        argv = [a.format(spec=spec, map=baseline, built=built) for a in argv_t]
        rc, out, err = _run_cli(argv, root)
        check(f"{label}: exit code", rc == want_rc,
              "" if rc == want_rc else f"got {rc}, want {want_rc}")
        check(f"{label}: stdout", out == want_out,
              "" if out == want_out else f"\n--- got ---\n{out}--- want ---\n{want_out}")
        check(f"{label}: stderr", err == want_err,
              "" if err == want_err else f"\n--- got ---\n{err}--- want ---\n{want_err}")


#: `run_make` shells out to `make` in the repo root. A stub on PATH reaches
#: `cmd_add`'s two build branches — the measurement build and the verify build
#: — which are half the function and the half that is hard to reason about:
#: the measurement build only works because the map's sections are *unpinned*
#: first, so a map that outgrew its bank does not overflow on a stale pin.
#: Without this, the branch that unpins is untested and step 7 would be
#: rewriting it blind.
_MAKE_OK = "#!/bin/sh\nexit 0\n"
_MAKE_FAILS = "#!/bin/sh\necho 'section overflows bank' >&2\nexit 1\n"


@contextlib.contextmanager
def _make_on_path(root: Path, script: str):
    """Put a stub `make` first on PATH for the duration."""
    bindir = root / "stub-bin"
    bindir.mkdir(exist_ok=True)
    make = bindir / "make"
    make.write_text(script)
    make.chmod(0o755)
    old = os.environ["PATH"]
    os.environ["PATH"] = f"{bindir}:{old}"
    try:
        yield
    finally:
        os.environ["PATH"] = old


def _built_artifacts(root: Path) -> None:
    """What `paths.map_path()` looks for after a build: a ROM and its .map."""
    (root / "pokeprism_nodebug.gbc").write_bytes(bytes(64))
    (root / "pokeprism_nodebug.map").write_text(_BUILT_MAP)


def test_add_measures_the_script_with_a_build(tmp: Path) -> None:
    """No `--script-size`, so `add` must unpin, build to measure, then verify."""
    print("\nprism-mapfit add — the build path")
    root, spec = _cli_repo(tmp, "build")
    baseline = root / "baseline.map"
    baseline.write_text(_BASELINE_MAP)
    _built_artifacts(root)

    with _make_on_path(root, _MAKE_OK):
        rc, out, err = _run_cli(
            ["add", "--spec", str(spec), "--map", str(baseline)], root)

    check("exit code 0", rc == 0, f"got {rc}\n{err}")
    check("it measures before it places",
          "\nMeasuring script size (build with floating sections)…\n" in out, out[:400])
    check("the script size comes from the .map, marked measured",
          "script/event   1280 bytes  (measured)" in out, out[-600:])
    check("it verifies afterwards",
          "\nVerifying (make nodebug)…\nBuild OK. Map wired and placed.\n" in out,
          out[-200:])
    check("the wiring actually landed on disk",
          "mapgroup MT_EMBER_SMALL_ROOM, 10, 9"
          in (root / "constants" / "map_dimension_constants.asm").read_text())
    check("the sections were pinned in the linker script",
          "Map Scripts MtEmberSmallRoom"
          in (root / "contents" / "romx.link").read_text())


def test_add_unpins_before_measuring(tmp: Path) -> None:
    """A re-alloc: the map is already pinned, and the measurement build must
    float it first.

    This is the branch `commands.py`'s own header comment is about — a map that
    outgrew its bank would overflow the measurement build on its stale pin. It
    only runs when there *is* a pin to remove, so a fresh-map fixture never
    reaches it, and a mutation that skips the unpin survives everything else.
    """
    print("\nprism-mapfit add — re-allocating an already-pinned map")
    root, spec = _cli_repo(tmp, "repin")
    baseline = root / "baseline.map"
    baseline.write_text(_BASELINE_MAP)
    _built_artifacts(root)
    (root / "contents" / "romx.link").write_text(
        'ROMX $01\n\t"Code 1"\n\n'
        'ROMX $05\n\t"Map Scripts MtEmberSmallRoom"\n'
        '\t"Map block data MtEmberSmallRoom"\n\n'
        'ROMX $25\n\t"Sprites"\n'
    )

    with _make_on_path(root, _MAKE_OK):
        rc, out, err = _run_cli(
            ["add", "--spec", str(spec), "--map", str(baseline)], root)

    check("exit code 0", rc == 0, f"got {rc}\n{err}")
    link = (root / "contents" / "romx.link").read_text()
    check("it says it unpinned before measuring",
          "unpinned" in out.split("Measuring script size")[0], out[:800])
    check("nothing is left pinned to the stale $05",
          'ROMX $05\n\t"Map' not in link, link)
    check("the sections were re-pinned somewhere",
          '"Map Scripts MtEmberSmallRoom"' in link, link)


def test_add_sizes_a_blob_appended_into_a_section(tmp: Path) -> None:
    """A blob that joins an existing section has no section of its own, so its
    measured size is how much that section *grew* — which needs the pre-wiring
    .map to subtract. Without an INTO placement nothing reads that baseline,
    and dropping it survives every other case here.
    """
    print("\nprism-mapfit add — a blob appended into an existing section")
    root, spec = _cli_repo(tmp, "into")

    # "Map block data 1" is a real SECTION in the fixture's blockdata.asm —
    # the blob is appended into that, so its own section is never created.
    # It is $0100 before the build and $0300 after: the blob is the delta.
    baseline = root / "baseline.map"
    baseline.write_text(
        'ROMX bank #1:\n'
        '  SECTION: $4000-$7e7f ($3e80 bytes) ["Code 1"]\n'
        '  TOTAL EMPTY: $0180 bytes\n'
        'ROMX bank #2:\n'
        '  SECTION: $4000-$5fff ($2000 bytes) ["Map Headers"]\n'
        '  TOTAL EMPTY: $2000 bytes\n'
        'ROMX bank #3:\n'
        '  SECTION: $4000-$40ff ($0100 bytes) ["Map block data 1"]\n'
        '  TOTAL EMPTY: $3f00 bytes\n'
    )
    (root / "pokeprism_nodebug.gbc").write_bytes(bytes(64))
    (root / "pokeprism_nodebug.map").write_text(
        'ROMX bank #1:\n'
        '  SECTION: $4000-$7e7f ($3e80 bytes) ["Code 1"]\n'
        '  TOTAL EMPTY: $0180 bytes\n'
        'ROMX bank #2:\n'
        '  SECTION: $4000-$5fff ($2000 bytes) ["Map Headers"]\n'
        '  SECTION: $6000-$601a ($001b bytes) ["Second Map Header MtEmberSmallRoom"]\n'
        '  TOTAL EMPTY: $1fe5 bytes\n'
        'ROMX bank #3:\n'
        '  SECTION: $4000-$42ff ($0300 bytes) ["Map block data 1"]\n'
        '  SECTION: $4300-$47ff ($0500 bytes) ["Map Scripts MtEmberSmallRoom"]\n'
        '  TOTAL EMPTY: $3800 bytes\n'
    )

    with _make_on_path(root, _MAKE_OK):
        rc, out, err = _run_cli(
            ["add", "--spec", str(spec), "--map", str(baseline),
             "--blockdata-into", "Map block data 1"], root)

    check("exit code 0", rc == 0, f"got {rc}\n{err}")
    check("block data is sized as the section's growth, not its total",
          "block data      512 bytes" in out, out[:800])
    check("it is not pinned, having inherited the section's bank",
          "(appended into an existing section — not pinned)" in out, out[-800:])
    # The report saying "not pinned" and the linker script agreeing are two
    # different claims. Pinning a section shared with other maps would move
    # their block data too.
    link = (root / "contents" / "romx.link").read_text()
    check("the shared section is left out of the linker script",
          '"Map block data 1"' not in link, link)


def test_add_reports_a_failed_build(tmp: Path) -> None:
    """A build that fails is reported with its log, and does not read as success."""
    print("\nprism-mapfit add — a failing build")
    root, spec = _cli_repo(tmp, "buildfail")
    baseline = root / "baseline.map"
    baseline.write_text(_BASELINE_MAP)
    _built_artifacts(root)

    with _make_on_path(root, _MAKE_FAILS):
        rc, out, err = _run_cli(
            ["add", "--spec", str(spec), "--map", str(baseline),
             "--script-size", "600"], root)

    check("exit code 1", rc == 1, f"got {rc}")
    check("the build log is passed through", "section overflows bank" in err, err[-200:])
    check("it names the likely cause",
          "error: verify build failed. If a section overflowed its bank, "
          "re-run with a larger --margin or free a bank." in err, err[-200:])
    check("it does not claim success", "Build OK" not in out, out[-200:])


def test_dry_run_writes_nothing(tmp: Path) -> None:
    """`--dry-run` prints the whole plan and must leave the tree byte-identical.

    The check that matters is the negative one: `cmd_add` calls the same
    `apply_edits` and `pin_sections` the real run does, and the only thing
    standing between it and the files is the flag.
    """
    print("\nprism-mapfit add --dry-run")
    root, spec = _cli_repo(tmp, "dryrun")
    baseline = root / "baseline.map"
    baseline.write_text(_BASELINE_MAP)

    tracked = sorted(p for p in root.rglob("*") if p.is_file())
    before = {p: p.read_bytes() for p in tracked}

    rc, out, _err = _run_cli(
        ["add", "--spec", str(spec), "--map", str(baseline),
         "--script-size", "600", "--dry-run"], root)

    after = {p: p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}
    check("exit code 0", rc == 0, f"got {rc}")
    check("it says it wrote nothing", "\n(dry run — no files written)\n" in out, out[-200:])
    check("no file appeared or vanished", set(after) == set(before),
          str(set(after) ^ set(before)))
    changed = [p.name for p in before if p in after and after[p] != before[p]]
    check("every file is byte-identical", changed == [], str(changed))


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
        test_manual_placement(tmp)
        test_reused_section_name_appends(tmp)
        test_manual_placement_fit(tmp)
        test_shared_section_detection(tmp)
        test_pinning(tmp)
        test_header_sizes_match_the_macros()
        test_lzcomp_sizing()

        cli_root, cli_spec = _cli_repo(tmp, "cli")
        baseline, built = cli_root / "baseline.map", cli_root / "built.map"
        baseline.write_text(_BASELINE_MAP)
        built.write_text(_BUILT_MAP)
        test_cli(cli_root, cli_spec, baseline, built)
        test_add_measures_the_script_with_a_build(tmp)
        test_add_unpins_before_measuring(tmp)
        test_add_sizes_a_blob_appended_into_a_section(tmp)
        test_add_reports_a_failed_build(tmp)
        test_dry_run_writes_nothing(tmp)
    print()
    if _failures:
        print(f"{_failures} check(s) FAILED")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
