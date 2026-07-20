#!/usr/bin/env python3
"""Tests for the polished (polishedcrystal) read adapter.

The fixture is a minimal tree in polished's dialect — the event block at the
head of the map file, twelve-arg object_events, inline hidden items, a
generictrainer, a formed wild mon, attribute-byte palettes. Everything the
feasibility doc picked as the stress test is asserted here as data crossing
the seam. If a real polishedcrystal checkout is sitting next to this repo,
the same questions are asked of it too.

    python tests/test_polished.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pokeprism_devtools.hacks import mount as hackmount  # noqa: E402
from pokeprism_devtools.studio import panels  # noqa: E402
from pokeprism_devtools.studio.session import Session  # noqa: E402

FAILED = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global FAILED
    print(f"  [{'OK  ' if cond else 'FAIL'}] {label}{f' — {detail}' if detail else ''}")
    if not cond:
        FAILED += 1


_MAP_FILE = """\
TownA_MapScriptHeader:
	def_scene_scripts

	def_callbacks

	def_warp_events
	warp_event  3,  5, HOUSE_A, 1

	def_coord_events

	def_bg_events
	bg_event  4,  2, BGEVENT_JUMPTEXT, TownASignText
	bg_event  9,  1, BGEVENT_ITEM + ELIXIR, EVENT_TOWN_A_HIDDEN_ELIXIR

	def_object_events
	object_event  7,  6, SPRITE_TEACHER, SPRITEMOVEDATA_STANDING_DOWN, 0, 0, -1, 0, OBJECTTYPE_COMMAND, jumptextfaceplayer, TownATeacherText, EVENT_TOWN_A_TEACHER
	object_event  2,  9, SPRITE_YOUNGSTER, SPRITEMOVEDATA_STANDING_DOWN, 0, 0, -1, 0, OBJECTTYPE_GENERICTRAINER, 2, GenericTrainerYoungsterZeke, -1
	object_event  5,  4, SPRITE_POKE_BALL, SPRITEMOVEDATA_STILL, 0, 0, -1, 0, OBJECTTYPE_ITEMBALL, PLAYEREVENT_ITEMBALL, POTION, 2, EVENT_TOWN_A_POTION
	object_event  1,  1, SPRITE_KURT, SPRITEMOVEDATA_STANDING_DOWN, 0, 0, -1, 0, OBJECTTYPE_SCRIPT, 0, TownAKurtScript, -1

TownAKurtScript:
	jumptextfaceplayer TownAKurtText

GenericTrainerYoungsterZeke:
	generictrainer YOUNGSTER, ZEKE, EVENT_BEAT_YOUNGSTER_ZEKE, .SeenText, .BeatenText

.SeenText:
	text "Go!"
	done

.BeatenText:
	text "Lost!"
	done

TownATeacherText:
	text "Hello there,"
	line "wanderer."
	done

TownAKurtText:
	text "I make balls."
	done

TownASignText:
	text "TOWN A"
	done
"""

_ROOFS_PAL = """\
;            morn/day,            nite,                eve
	RGB  21,21,21, 11,11,11,  21,21,21, 11,11,11,  18,16,16, 09,08,08  ; N/A
	RGB  14,17,31, 07,11,15,  09,09,17, 05,07,13,  12,13,23, 06,08,11  ; Town A
"""

_BG_TILES_PAL = """\
if !DEF(MONOCHROME)

; morn
	RGB 28,31,16, 21,21,21, 13,13,13, 07,07,07 ; gray
	RGB 28,31,16, 31,19,24, 30,10,06, 07,07,07 ; red
	RGB 22,31,10, 12,25,01, 05,14,00, 07,07,07 ; green
	RGB 28,31,16, 08,12,31, 01,04,31, 07,07,07 ; water
	RGB 28,31,16, 31,31,07, 31,16,01, 07,07,07 ; yellow
	RGB 28,31,16, 24,18,07, 20,15,03, 07,07,07 ; brown
	RGB 28,31,16, 15,31,31, 05,17,31, 07,07,07 ; roof
	RGB 31,31,31, 20,20,20, 10,10,10, 00,00,00 ; text
; day
	RGB 27,31,27, 21,21,21, 13,13,13, 07,07,07 ; gray
	RGB 27,31,27, 31,19,24, 30,10,06, 07,07,07 ; red
	RGB 22,31,10, 12,25,01, 05,14,00, 07,07,07 ; green
	RGB 27,31,27, 08,12,31, 01,04,31, 07,07,07 ; water
	RGB 27,31,27, 31,31,07, 31,16,01, 07,07,07 ; yellow
	RGB 27,31,27, 24,18,07, 20,15,03, 07,07,07 ; brown
	RGB 27,31,27, 15,31,31, 05,17,31, 07,07,07 ; roof
	RGB 31,31,31, 20,20,20, 10,10,10, 00,00,00 ; text
endc
"""

_GRASS = "\tdef_grass_wildmons TOWN_A\n\tdb 10 percent ; encounter rate\n" \
    + "".join(f"\twildmon {lvl}, RATTATA\n" for lvl in range(3, 10)) \
    + "".join(f"\twildmon {lvl}, HOOTHOOT\n" for lvl in range(3, 10)) \
    + "".join(f"\twildmon {lvl}, VULPIX, ALOLAN_FORM\n" for lvl in range(3, 10)) \
    + "\tend_grass_wildmons\n"


def _fixture(tmp: Path) -> Path:
    root = tmp / "polished"
    for rel, text in {
        "data/maps/maps.asm":
            "\tmap TownA, TILESET_JOHTO_MODERN, TOWN, SIGN_TOWN, TOWN_A_LM, "
            "MUSIC_TOWN_A, 0, PALETTE_AUTO\n",
        "data/maps/attributes.asm":
            "\tmap_attributes TownA, TOWN_A, $5\n"
            "\tconnection west, RouteX, ROUTE_X, -18\n",
        "constants/map_constants.asm":
            "\tnewgroup ; 1\n\n"
            "\tmap_const TOWN_A, 4, 3 ; 1\n",
        "constants/tileset_constants.asm":
            "\tconst_def\n\tconst ROOF_NEW_BARK  ; 0\n"
            "\tconst ROOF_VIOLET    ; 1\n",
        "data/maps/blocks.asm":
            "SECTION \"TownA_BlockData\", ROMX\n"
            "TownA_BlockData:\n\tINCBIN \"maps/TownA.ablk.lzp\"\n",
        "maps/TownA.asm": _MAP_FILE,
        "gfx/tilesets/bg_tiles.pal": _BG_TILES_PAL,
        "gfx/tilesets/roofs.pal": _ROOFS_PAL,
        "gfx/misc.asm":
            'NewBarkRoofGFX:: INCBIN "gfx/tilesets/roofs/new_bark.2bpp.lzp"\n'
            'VioletRoofGFX::  INCBIN "gfx/tilesets/roofs/violet.2bpp.lzp"\n',
        "data/maps/roofs.asm":
            "MapGroupRoofs:\n\ttable_width 1\n"
            "\tdb -1           ; 0\n\tdb ROOF_VIOLET  ; 1\n",
        "data/wild/johto_grass.asm": _GRASS,
        "data/wild/johto_water.asm":
            "\tdef_water_wildmons TOWN_A\n\tdb 2 percent\n"
            "\twildmon 15, WOOPER\n\twildmon 20, QUAGSIRE\n"
            "\twildmon 15, WOOPER\n\tend_water_wildmons\n",
    }.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    # Three blocks; the attribute bytes carry the palette class, low 3 bits.
    (root / "data/tilesets").mkdir(parents=True)
    (root / "data/tilesets/johto_modern_metatiles.bin").write_bytes(bytes(48))
    (root / "data/tilesets/johto_modern_attributes.bin").write_bytes(
        bytes([0] * 16) + bytes([6] * 16) + bytes([0, 6] * 8))
    (root / "maps/TownA.ablk").write_bytes(bytes([0, 1, 2, 1, 1, 0, 1, 2, 2, 1, 0, 1]))
    return root


def test_the_mount_tells_the_family_apart(root: Path) -> None:
    print("\nthe mount tells polished from vanilla by where the anchor sits")
    hack = hackmount.mount(root)
    check("mounted as polished", hack.name == "polished")
    check("no linter, the family write adapter, nothing else declared",
          hack.ctx is None and hack.writes is not None and not hack.plays
          and not hack.measures)
    check("the writer holds the head anchor",
          hack.writes.anchor == "_MapScriptHeader")


def test_the_head_of_file_events(root: Path) -> None:
    print("\nthe event block at the head of the file carves the same six lists")
    t = hackmount.mount(root).reads.tables("TownA")

    check("two NPCs, one trainer, two props, one sign, one warp",
          (len(t.npcs), len(t.trainers), len(t.props),
           len(t.signposts), len(t.warps), len(t.triggers)) == (2, 1, 2, 1, 1, 0))

    cmd = next(n for n in t.npcs if n.sprite == "TEACHER")
    check("an OBJECTTYPE_COMMAND object is an NPC whose command is the script",
          cmd.says == "Hello there,", cmd.says)
    check("and its twelve args still turn (x, y) around",
          (cmd.y, cmd.x) == (6, 7))
    kurt = next(n for n in t.npcs if n.sprite == "KURT")
    check("an OBJECTTYPE_SCRIPT NPC hops through its script to its words",
          kurt.says == "I make balls.", kurt.says)
    check("the flag is the last arg, wherever the type put it",
          cmd.flag == "EVENT_TOWN_A_TEACHER" and kurt.flag == "-1")

    tr = t.trainers[0]
    check("a generictrainer is a trainer — class, party, flag off its macro",
          (tr.cls, tr.party, tr.flag) ==
          ("YOUNGSTER", "ZEKE", "EVENT_BEAT_YOUNGSTER_ZEKE"))
    check("with the sight range off the object", tr.sight == "2")

    kinds = {p.kind: p for p in t.props}
    check("the item ball spends its args on command, item, quantity",
          (kinds["itemball"].what, kinds["itemball"].qty,
           kinds["itemball"].flag) == ("POTION", "2", "EVENT_TOWN_A_POTION"))
    check("a hidden item is inline: BGEVENT_ITEM + what, flag beside it",
          (kinds["hidden"].what, kinds["hidden"].flag) ==
          ("ELIXIR", "EVENT_TOWN_A_HIDDEN_ELIXIR"))
    check("no row is ever undeclared here either",
          not any(r.undeclared for rows in
                  (t.npcs, t.trainers, t.props, t.signposts, t.warps)
                  for r in rows))


def test_the_catalog_and_geometry(root: Path) -> None:
    print("\nwhat polished kept reads through vanilla's parsers")
    r = hackmount.mount(root).reads
    check("labels map to consts", r.maps() == {"TownA": "TOWN_A"})
    links = r.connections("TOWN_A")
    check("a negative offset crosses as written",
          links[0].offset == -18 and links[0].coord is None)

    a = r.attributes("TownA", "TOWN_A")
    check("a bare newgroup still counts",
          (a.group, a.map_id, a.height, a.width) == (1, 1, 3, 4))
    check("no fish group anywhere, so the row keeps its dash",
          a.fishgroup == "—")
    check("the blk column names the file the build uses",
          a.blk == "maps/TownA.ablk.lzp")

    g = r.geometry("TownA")
    check("the bytes come from the plain .ablk beside the .lzp",
          (g.height, g.width, len(g.blocks)) == (3, 4, 12))
    check("attribute bytes color the swatches: three distinct",
          len(set(g.swatches)) == 3)
    gray = 21 * 255 // 31
    check("an all-gray-attribute block averages gray",
          g.swatches[0] == ((gray,) * 3,) * 4, str(g.swatches[0]))


def test_wild_forms_and_roof(root: Path) -> None:
    print("\nthe form axis exists exactly when a row fills it")
    r = hackmount.mount(root).reads
    w = r.wild("TOWN_A")
    check("grass still splits by time", list(w["grass"]) == ["morn", "day", "nite"])
    check("a formed mon carries its form",
          w["grass"]["nite"][0].form == "ALOLAN_FORM")
    check("an unformed one carries nothing", w["grass"]["morn"][0].form == "")
    cols, _rows = panels.wild(w)
    check("so the form column appears", cols[-1] == "form", str(cols))
    check("water is three slots, no times", len(w["water"]["any"]) == 3)

    roof = r.roof("TOWN_A")
    check("the roof constants moved files and are still found",
          roof is not None and roof.tiles == 1
          and roof.tile_file == "gfx/tilesets/roofs/violet.2bpp.lzp")
    check("one packed line yields the four seam colors",
          roof.colors is not None and len(roof.colors) == 4
          and all(c.startswith("#") for c in roof.colors))


def test_the_session_sees_no_name(root: Path) -> None:
    print("\nthe session treats polished exactly like any family mount")
    s = Session(root)
    md = s.load("TownA")
    check("the map loads whole", md.error is None and md.geometry is not None)
    check("lint is empty, adders are empty",
          s.lint() == [] and s.adders("NPC") == ())


def test_deletion_splices_the_head(root: Path) -> None:
    print("\ndeleting through the head block leaves the scripts below untouched")
    src = root / "maps/TownA.asm"
    before = src.read_text()
    scripts_below = before[before.index("TownAKurtScript:"):]
    s = Session(root)

    # Polished names none of this fixture's objects, so the handle is the
    # unnamed shape — the list and the position, exactly what the read
    # adapter minted for the row.
    preview = s.preview(s.deletion("TownA", "TOWN_A",
                                   panels.Ref("npc", ("object", 0))))
    s.apply(preview)
    after = src.read_text()
    check("the object_event is gone",
          "SPRITE_TEACHER" not in after and "object_event  2,  9" in after)
    check("every byte below the block is untouched",
          after.endswith(scripts_below))
    npcs = next(t for t in s.load("TownA").tabs if t.name == "NPCs")
    check("the table agrees — Kurt remains", len(npcs.table[1]) == 1)

    s.undo()
    check("undo puts the head splice back to the byte",
          src.read_text() == before)


def test_real_tree() -> None:
    root = Path.home() / "code/ricccec/polishedcrystal"
    if not (root / "data/maps/maps.asm").exists():
        print("\n(no polishedcrystal checkout next door — skipping the real tree)")
        return
    print("\nthe real polishedcrystal answers the same questions")
    hack = hackmount.mount(root)
    check("it mounts as polished", hack.name == "polished")
    r = hack.reads
    check("the catalog outgrew the base game", len(r.maps()) > 500)

    t = r.tables("AzaleaTown")
    check("Azalea's eleven people and eight warps",
          len(t.npcs) == 11 and len(t.warps) == 8)
    check("the hidden FULL_HEAL is inline and found",
          any(p.kind == "hidden" and p.what == "FULL_HEAL" for p in t.props))

    t30 = r.tables("Route30")
    check("Joey is a trainer, Mikey a generictrainer, both battle",
          {tr.party for tr in t30.trainers} >= {"JOEY1", "MIKEY"})

    g = r.geometry("AzaleaTown")
    check("Azalea's shape reads from its plain .ablk",
          (g.width, g.height) == (20, 9) and len(g.blocks) == 180)
    check("its swatches vary", len(set(g.swatches)) > 1)

    w = r.wild("ICE_PATH_1F")
    check("an Alolan VULPIX carries its form across the seam",
          any(m.form == "ALOLAN_FORM" for times in w.values()
              for mons in times.values() for m in mons))


def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        root = _fixture(Path(d))
        test_the_mount_tells_the_family_apart(root)
        test_the_head_of_file_events(root)
        test_the_catalog_and_geometry(root)
        test_wild_forms_and_roof(root)
        test_the_session_sees_no_name(root)
        test_deletion_splices_the_head(root)
    test_real_tree()

    print()
    if FAILED:
        print(f"{FAILED} check(s) FAILED")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
