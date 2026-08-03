#!/usr/bin/env python3
"""Tests for prism-newmap: content authoring + repo introspection helpers,
and the full wiring integration via mapwire. Hermetic — temp fixtures, no
ROM/build. Interactive `questionary` prompts aren't driven here (see
map_new._gather_spec's docstring) — this exercises the data + side-effect
helpers the wizard calls, plus builds a MapSpec directly to stand in for
what the wizard would have produced.

    python tests/test_map_new.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pokeprism_devtools import map_new  # noqa: E402
from pokeprism_devtools.map_new import repoquery  # noqa: E402
from pokeprism_devtools.mapfit import mapwire  # noqa: E402
from pokeprism_devtools.hacks.prism.mapspec import MapSpec  # noqa: E402

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
        'SECTION "Map Headers", ROMX\n'
        "MapGroup1:\n"
        "\tmap_header IntroOutside, TILESET_RIJON, ROUTE, DUMMY2, MUSIC_NONE, 0, PALETTE_NITE, FISHGROUP_NONE\n"
        "MapGroup2:\n"
        "\tmap_header CaperRidge, TILESET_NALJO_2, TOWN, CAPER_RIDGE, MUSIC_NEW_BARK_TOWN, 0, PALETTE_AUTO, FISHGROUP_SHORE\n"
        "\tmap_header CaperHouse, TILESET_HOUSE_1, INDOOR, CAPER_RIDGE, MUSIC_NEW_BARK_TOWN, 1, PALETTE_DAY, FISHGROUP_NONE\n"
    )
    (root / "maps" / "second_map_headers.asm").write_text(
        'SECTION "Second Map Headers", ROMX\n'
        "\tmap_header_2 IntroOutside, INTRO_OUTSIDE, 15, 0\n"
        "\tmap_header_2 CaperRidge, CAPER_RIDGE, 53, NORTH\n"
    )
    (root / "maps" / "blockdata.asm").write_text(
        'SECTION "Map block data 1", ROMX\n'
        "CaperRidge_BlockData:\n"
        '\tINCBIN "maps/blk/CaperRidge.blk.lz"\n'
    )
    (root / "maps" / "map_scripts.asm").write_text(
        'SECTION "Map Scripts 1", ROMX\n'
        'INCLUDE "maps/CaperRidge.asm"\n'
        "\n"
        "; DO NOT ADD ANYTHING BELOW THIS LINE\n"
        "; if you need to add new map scripts, find a section where they fit\n"
    )
    (root / "contents" / "romx.link").write_text(
        'ROMX $01\n\t"Code 1"\n\nROMX $25\n\t"Sprites"\n'
    )

    (root / "constants" / "tilemap_constants.asm").write_text(
        "\tconst_def\n"
        "\tconst TILESET_NALJO_1 ;1\n"
        "\tconst TILESET_NALJO_2 ;2\n"
        "\tconst TILESET_CAVE4 ;3\n"
    )
    (root / "constants" / "map_constants.asm").write_text(
        "; permissions\n"
        "const_value = 1\n"
        "\tconst TOWN\n"
        "\tconst ROUTE\n"
        "\tconst INDOOR\n"
        "\tconst CAVE\n"
        "\n"
        "\tconst_def\n"
        "\tconst PALETTE_AUTO\n"
        "\tconst PALETTE_DAY\n"
        "\tconst PALETTE_NITE\n"
    )
    (root / "constants" / "music_constants.asm").write_text(
        "\tconst_def\n"
        "\tconst MUSIC_NONE\n"
        "\tconst MUSIC_NEW_BARK_TOWN\n"
    )
    (root / "constants" / "misc_constants.asm").write_text(
        "\tconst_def\n"
        "\tconst FISHGROUP_NONE\n"
        "\tconst FISHGROUP_SHORE\n"
    )
    return root


def _spec(**overrides) -> MapSpec:
    base = dict(
        label="OneIsland", const="ONE_ISLAND", group=2, height=11, width=18,
        tileset="TILESET_NALJO_2", permission="TOWN", landmark="ONE_ISLAND",
        music="MUSIC_NONE", palette="PALETTE_AUTO", fishgroup="FISHGROUP_NONE",
        phone=0, border_block="0", conn_flags="0", connections=[],
        script_asm="maps/OneIsland.asm", blk="maps/blk/OneIsland.blk",
    )
    base.update(overrides)
    return MapSpec(**base)


def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        root = _fixture_repo(tmp)

        print("\nmap_new: repo introspection")
        tilesets = repoquery._consts(root / "constants" / "tilemap_constants.asm", "TILESET_")
        check("tileset consts parsed", tilesets == ["TILESET_NALJO_1", "TILESET_NALJO_2", "TILESET_CAVE4"],
              str(tilesets))

        musics = repoquery._consts(root / "constants" / "music_constants.asm", "MUSIC_")
        check("music consts parsed", musics == ["MUSIC_NONE", "MUSIC_NEW_BARK_TOWN"], str(musics))

        groups = repoquery._existing_groups(root)
        check("groups parsed", groups == {1: ["INTRO_OUTSIDE"], 2: ["CAPER_RIDGE", "CAPER_HOUSE"]},
              str(groups))

        labels, consts = repoquery._existing_labels_consts(root)
        check("existing labels", labels == {"IntroOutside", "CaperRidge"}, str(labels))
        check("existing consts", consts == {"INTRO_OUTSIDE", "CAPER_RIDGE", "CAPER_HOUSE"}, str(consts))

        print("\nmap_new: write_template")
        rel = map_new.write_template(root, "OneIsland")
        check("template written at right path", rel == "maps/OneIsland.asm")
        text = (root / rel).read_text()
        check("template has script header", "OneIsland_MapScriptHeader:" in text)
        check("template has event header", "OneIsland_MapEventHeader:: db 0, 0" in text)
        check("template has empty Warps/CoordEvents/BGEvents/ObjectEvents",
              all(f".{s}\n\tdb 0" in text for s in ("Warps", "CoordEvents", "BGEvents", "ObjectEvents")))
        try:
            map_new.write_template(root, "OneIsland")
            check("re-writing template raises FileExistsError", False)
        except FileExistsError:
            check("re-writing template raises FileExistsError", True)

        print("\nmap_new: place_blk")
        src_blk = tmp / "source.blk"
        src_blk.write_bytes(bytes(18 * 11))
        rel = map_new.place_blk(root, src_blk, "OneIsland")
        check("blk copied to right path", rel == "maps/blk/OneIsland.blk")
        check("blk content matches", (root / rel).read_bytes() == src_blk.read_bytes())

        src_ablk = tmp / "source.ablk"
        src_ablk.write_bytes(bytes(20))
        rel = map_new.place_blk(root, src_ablk, "SecondMap")
        check("ablk extension preserved", rel == "maps/blk/SecondMap.ablk")

        try:
            map_new.place_blk(root, src_blk, "OneIsland")
            check("re-placing blk raises FileExistsError", False)
        except FileExistsError:
            check("re-placing blk raises FileExistsError", True)

        bad_ext = tmp / "source.png"
        bad_ext.write_bytes(b"x")
        try:
            map_new.place_blk(root, bad_ext, "Bogus")
            check("wrong extension raises ValueError", False)
        except ValueError:
            check("wrong extension raises ValueError", True)

        print("\nMapSpec: section name overrides")
        default_spec = _spec()
        check("default blockdata section", default_spec.section_blockdata == "Map block data OneIsland")
        check("default script section", default_spec.section_script == "Map Scripts OneIsland")
        check("default secondary section", default_spec.section_secondary == "Second Map Header OneIsland")

        custom_spec = _spec(blockdata_section="Map block data 12", script_section="Map Scripts small 3")
        check("custom blockdata section wins", custom_spec.section_blockdata == "Map block data 12")
        check("custom script section wins", custom_spec.section_script == "Map Scripts small 3")
        check("un-overridden secondary still defaults",
              custom_spec.section_secondary == "Second Map Header OneIsland")

        print("\nMapSpec: section overrides round-trip through to_toml/from_toml")
        toml_path = tmp / "spec.toml"
        toml_path.write_text(custom_spec.to_toml())
        loaded = MapSpec.from_toml(toml_path)
        check("blockdata override round-trips", loaded.section_blockdata == "Map block data 12")
        check("script override round-trips", loaded.section_script == "Map Scripts small 3")

        print("\nmapwire: full wiring with custom section names")
        spec = custom_spec
        edits = [ed(root, spec) for ed in mapwire.ALL_ASM_EDITORS]
        check("all 5 asm editors changed", all(e.changed for e in edits),
              f"{sum(e.changed for e in edits)}/5")
        mapwire.apply_edits(root, edits, dry_run=False)

        blockdata_text = (root / "maps" / "blockdata.asm").read_text()
        check("custom blockdata SECTION name written",
              'SECTION "Map block data 12", ROMX' in blockdata_text)
        check("blockdata INCBIN targets the placed blk",
              'INCBIN "maps/blk/OneIsland.blk.lz"' in blockdata_text)

        scripts_text = (root / "maps" / "map_scripts.asm").read_text()
        check("custom script SECTION name written",
              'SECTION "Map Scripts small 3", ROMX' in scripts_text)
        check("script INCLUDE added", 'INCLUDE "maps/OneIsland.asm"' in scripts_text)

        second_headers_text = (root / "maps" / "second_map_headers.asm").read_text()
        check("un-overridden secondary section uses mapfit default",
              'SECTION "Second Map Header OneIsland", ROMX' in second_headers_text)
        check("map_header_2 line written",
              "map_header_2 OneIsland, ONE_ISLAND, 0, 0" in second_headers_text)

        dim_text = (root / "constants" / "map_dimension_constants.asm").read_text()
        check("mapgroup line added to group 2", "mapgroup ONE_ISLAND, 11, 18" in dim_text)

        headers_text = (root / "maps" / "map_headers.asm").read_text()
        check("map_header line added under MapGroup2",
              "map_header OneIsland, TILESET_NALJO_2, TOWN, ONE_ISLAND, MUSIC_NONE, 0, PALETTE_AUTO, FISHGROUP_NONE"
              in headers_text)

    print()
    if _failures:
        print(f"{_failures} check(s) FAILED")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
