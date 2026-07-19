#!/usr/bin/env python3
"""Tests for the vanilla (pokecrystal) read adapter.

The fixture is a minimal tree in the modern `def_*` dialect — enough of one
to exercise every turn the adapter makes at the seam: the (x, y) → (y, x)
flip, the walk from an object to the `trainer`/`itemball`/`fruittree`/
`hiddenitem` line that classifies it, the offset-only connections, and the
palette-class swatches. If a real pokecrystal checkout is sitting next to
this repo, the same questions are asked of it too.

    python tests/test_vanilla.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pokeprism_devtools.hacks import mount as hackmount  # noqa: E402
from pokeprism_devtools.shared.coords import Tile  # noqa: E402
from pokeprism_devtools.studio import panels  # noqa: E402
from pokeprism_devtools.studio.session import Session, SessionError  # noqa: E402

FAILED = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global FAILED
    print(f"  [{'OK  ' if cond else 'FAIL'}] {label}{f' — {detail}' if detail else ''}")
    if not cond:
        FAILED += 1


# --------------------------------------------------------------------------- #
# the fixture                                                                 #
# --------------------------------------------------------------------------- #

_MAP_FILE = """\
	object_const_def
	const TOWNA_TEACHER
	const TOWNA_YOUNGSTER
	const TOWNA_POKE_BALL
	const TOWNA_FRUIT_TREE

TownA_MapScripts:
	def_scene_scripts

	def_callbacks

TownATeacherScript:
	jumptextfaceplayer TownATeacherText

TrainerYoungsterZeke:
	trainer YOUNGSTER, ZEKE, EVENT_BEAT_YOUNGSTER_ZEKE, ZekeSeenText, ZekeBeatenText, 0, .Script

.Script:
	end

TownAPotion:
	itemball POTION, 2

TownAFruitTree:
	fruittree FRUITTREE_TOWN_A

TownAHiddenElixer:
	hiddenitem ELIXER, EVENT_TOWN_A_HIDDEN_ELIXER

TownASign:
	jumptext TownASignText

TownATeacherText:
	text "Hello there,"
	line "wanderer."

	para "Nice day."
	done

TownASignText:
	text "TOWN A"
	done

ZekeSeenText:
	text "Go!"
	done

ZekeBeatenText:
	text "Lost!"
	done

TownA_MapEvents:
	db 0, 0 ; filler

	def_warp_events
	warp_event  3,  5, HOUSE_A, 1

	def_coord_events
	coord_event  6,  8, SCENE_DEFAULT, TownASceneScript

	def_bg_events
	bg_event  4,  2, BGEVENT_READ, TownASign
	bg_event  9,  1, BGEVENT_ITEM, TownAHiddenElixer

	def_object_events
	object_event  7,  6, SPRITE_TEACHER, SPRITEMOVEDATA_STANDING_DOWN, 0, 0, -1, -1, 0, OBJECTTYPE_SCRIPT, 0, TownATeacherScript, EVENT_TOWN_A_TEACHER
	object_event  2,  9, SPRITE_YOUNGSTER, SPRITEMOVEDATA_SPINRANDOM_SLOW, 0, 0, -1, -1, 0, OBJECTTYPE_TRAINER, 3, TrainerYoungsterZeke, EVENT_TOWN_A_YOUNGSTER
	object_event  5,  4, SPRITE_POKE_BALL, SPRITEMOVEDATA_STILL, 0, 0, -1, -1, 0, OBJECTTYPE_ITEMBALL, 0, TownAPotion, EVENT_TOWN_A_POTION
	object_event  1,  1, SPRITE_FRUIT_TREE, SPRITEMOVEDATA_STILL, 0, 0, -1, -1, 0, OBJECTTYPE_SCRIPT, 0, TownAFruitTree, -1
"""

_BG_TILES_PAL = """\
; morn
	RGB 28,31,16, 21,21,21, 13,13,13, 07,07,07 ; gray
	RGB 28,31,16, 31,19,24, 30,10,06, 07,07,07 ; red
	RGB 22,31,10, 12,25,01, 05,14,00, 07,07,07 ; green
	RGB 31,31,31, 08,12,31, 01,04,31, 07,07,07 ; water
	RGB 28,31,16, 31,31,07, 31,16,01, 07,07,07 ; yellow
	RGB 28,31,16, 24,18,07, 20,15,03, 07,07,07 ; brown
	RGB 28,31,16, 15,31,31, 05,17,31, 07,07,07 ; roof
	RGB 31,31,16, 31,31,16, 14,09,00, 00,00,00 ; text

; day
	RGB 27,31,27, 21,21,21, 13,13,13, 07,07,07 ; gray
	RGB 27,31,27, 31,19,24, 30,10,06, 07,07,07 ; red
	RGB 22,31,10, 12,25,01, 05,14,00, 07,07,07 ; green
	RGB 31,31,31, 08,12,31, 01,04,31, 07,07,07 ; water
	RGB 27,31,27, 31,31,07, 31,16,01, 07,07,07 ; yellow
	RGB 27,31,27, 24,18,07, 20,15,03, 07,07,07 ; brown
	RGB 27,31,27, 15,31,31, 05,17,31, 07,07,07 ; roof
	RGB 31,31,16, 31,31,16, 14,09,00, 00,00,00 ; text

; nite
	RGB 15,14,24, 11,11,19, 07,07,12, 00,00,00 ; gray
	RGB 15,14,24, 14,07,17, 13,00,08, 00,00,00 ; red
	RGB 15,14,24, 08,13,19, 00,11,13, 00,00,00 ; green
	RGB 15,14,24, 05,05,17, 03,03,10, 00,00,00 ; water
	RGB 30,30,11, 16,14,18, 16,14,10, 00,00,00 ; yellow
	RGB 15,14,24, 12,09,15, 08,04,05, 00,00,00 ; brown
	RGB 15,14,24, 13,12,23, 11,09,20, 00,00,00 ; roof
	RGB 31,31,16, 31,31,16, 14,09,00, 00,00,00 ; text
"""

_ROOFS_ASM = """\
; MapGroupRoofs values; Roofs indexes
	const_def
	const ROOF_NEW_BARK  ; 0
	const ROOF_VIOLET    ; 1
DEF NUM_ROOFS EQU const_value

MapGroupRoofs:
	table_width 1
	db -1             ;  0
	db ROOF_VIOLET    ;  1
	assert_table_length NUM_MAP_GROUPS + 1

Roofs:
	table_width ROOF_LENGTH * TILE_SIZE
INCBIN "gfx/tilesets/roofs/new_bark.2bpp"
INCBIN "gfx/tilesets/roofs/violet.2bpp"
	assert_table_length NUM_ROOFS
"""

_ROOFS_PAL = """\
; group 0 (unused)
	RGB 21,21,21, 11,11,11 ; morn/day
	RGB 21,21,21, 11,11,11 ; nite

; group 1 (Town A)
	RGB 14,17,31, 07,11,15 ; morn/day
	RGB 09,09,17, 05,07,13 ; nite
"""

_GRASS = "JohtoGrassWildMons:\n\n\tdef_grass_wildmons TOWN_A\n" \
    "\tdb 2 percent, 2 percent, 2 percent ; encounter rates: morn/day/nite\n" \
    + "".join(f"\tdb {lvl}, RATTATA\n" for lvl in range(3, 10)) \
    + "".join(f"\tdb {lvl}, HOOTHOOT\n" for lvl in range(3, 10)) \
    + "".join(f"\tdb {lvl}, GASTLY\n" for lvl in range(3, 10)) \
    + "\tend_grass_wildmons\n"

_WATER = "JohtoWaterWildMons:\n\n\tdef_water_wildmons TOWN_A\n" \
    "\tdb 2 percent ; encounter rate\n" \
    "\tdb 15, WOOPER\n\tdb 20, QUAGSIRE\n\tdb 15, QUAGSIRE\n" \
    "\tend_water_wildmons\n"


def _fixture(tmp: Path) -> Path:
    root = tmp / "crystal"
    for rel, text in {
        "data/maps/maps.asm":
            "\tmap TownA, TILESET_JOHTO, TOWN, LANDMARK_TOWN_A, "
            "MUSIC_TOWN_A, FALSE, PALETTE_AUTO, FISHGROUP_SHORE\n"
            "\tmap HouseA, TILESET_HOUSE, INDOOR, LANDMARK_TOWN_A, "
            "MUSIC_HOUSE, FALSE, PALETTE_DAY, FISHGROUP_SHORE\n",
        "data/maps/attributes.asm":
            "\tmap_attributes TownA, TOWN_A, $05, WEST\n"
            "\tconnection west, RouteX, ROUTE_X, 2\n\n"
            "\tmap_attributes HouseA, HOUSE_A, $00\n",
        "constants/map_constants.asm":
            "\tnewgroup TOWN_GROUP ; 1\n\n"
            "\tmap_const TOWN_A,  4, 3 ; 1\n"
            "\tmap_const HOUSE_A, 2, 2 ; 2\n",
        "data/maps/blocks.asm":
            "TownA_Blocks:\n\tINCBIN \"maps/TownA.blk\"\n\n"
            "HouseA_Blocks:\n\tINCBIN \"maps/HouseA.blk\"\n",
        "maps/TownA.asm": _MAP_FILE,
        "gfx/tilesets/bg_tiles.pal": _BG_TILES_PAL,
        "gfx/tilesets/johto_palette_map.asm":
            "\ttilepal 0, GRAY, RED, GREEN, WATER, YELLOW, BROWN, ROOF, TEXT\n"
            "\ttilepal 0, ROOF, ROOF, ROOF, ROOF, WATER, WATER, WATER, WATER\n",
        "data/maps/roofs.asm": _ROOFS_ASM,
        "gfx/tilesets/roofs.pal": _ROOFS_PAL,
        "data/wild/johto_grass.asm": _GRASS,
        "data/wild/johto_water.asm": _WATER,
    }.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    # 4×3 blocks; block 0 is all-GRAY tiles, block 1 all-ROOF, block 2 mixed.
    (root / "data/tilesets/johto_metatiles.bin").parent.mkdir(parents=True)
    (root / "data/tilesets/johto_metatiles.bin").write_bytes(
        bytes([0] * 16) + bytes([6] * 16) + bytes([0, 6] * 8))
    (root / "maps/TownA.blk").write_bytes(bytes([0, 1, 2, 1, 1, 0, 1, 2, 2, 1, 0, 1]))
    return root


# --------------------------------------------------------------------------- #
# the fixture tests                                                           #
# --------------------------------------------------------------------------- #

def test_the_mount_recognises_vanilla(root: Path) -> None:
    print("\nthe mount recognises a vanilla tree by its tail anchor")
    hack = hackmount.mount(root)
    check("mounted as vanilla", hack.name == "vanilla")
    check("with no linter", hack.ctx is None)
    check("and every capability off",
          not hack.writes and not hack.plays and not hack.measures)


def test_the_six_lists(root: Path) -> None:
    print("\none map file carves into the six lists")
    t = hackmount.mount(root).reads.tables("TownA")

    check("one NPC, one trainer, three props, one sign, one warp, one trigger",
          (len(t.npcs), len(t.trainers), len(t.props),
           len(t.signposts), len(t.warps), len(t.triggers)) == (1, 1, 3, 1, 1, 1))

    npc = t.npcs[0]
    check("the (x, y) the macro wrote crossed as (y, x)",
          (npc.y, npc.x) == (6, 7), f"got ({npc.y}, {npc.x})")
    check("its handle is the object_const_def name",
          npc.handle == "TOWNA_TEACHER")
    check("it says its text's first words, not its script's name",
          npc.says == "Hello there,", npc.says)
    check("its movement crossed stripped", npc.movement == "STANDING_DOWN")

    tr = t.trainers[0]
    check("the trainer's class, party and flag come off the trainer line",
          (tr.cls, tr.party, tr.flag) ==
          ("YOUNGSTER", "ZEKE", "EVENT_BEAT_YOUNGSTER_ZEKE"))
    check("his sight range comes off the object_event", tr.sight == "3")

    kinds = {p.kind: p for p in t.props}
    check("the item ball carries its item and count",
          (kinds["itemball"].what, kinds["itemball"].qty) == ("POTION", "2"))
    check("the fruit tree names its tree",
          kinds["fruittree"].what == "FRUITTREE_TOWN_A")
    check("the hidden item was walked out of its BGEVENT_ITEM block",
          (kinds["hidden"].what, kinds["hidden"].flag) ==
          ("ELIXER", "EVENT_TOWN_A_HIDDEN_ELIXER"))
    check("and stands where its bg_event stands, turned",
          (kinds["hidden"].y, kinds["hidden"].x) == (1, 9))

    check("the sign reads, the warp leads, the trigger fires",
          t.signposts[0].kind == "READ"
          and (t.warps[0].to_map, t.warps[0].their_warp) == ("HOUSE_A", "1")
          and t.triggers[0].scene == "SCENE_DEFAULT")
    check("no row is ever undeclared — def_* lists self-count",
          not any(r.undeclared for rows in
                  (t.npcs, t.trainers, t.props, t.signposts, t.warps, t.triggers)
                  for r in rows))
    check("the marks glyph everything, objects last",
          t.marks[Tile(y=6, x=7)] == "N" and t.marks[Tile(y=9, x=2)] == "T"
          and t.marks[Tile(y=4, x=5)] == "I" and t.marks[Tile(y=5, x=3)] == "W"
          and t.marks[Tile(y=2, x=4)] == "S" and t.marks[Tile(y=8, x=6)] == "X"
          and t.marks[Tile(y=1, x=9)] == "S")


def test_the_catalog(root: Path) -> None:
    print("\nthe catalog is read from the three files that own it")
    r = hackmount.mount(root).reads
    check("labels map to consts", r.maps() == {"TownA": "TOWN_A",
                                               "HouseA": "HOUSE_A"})
    check("a map with a file parses, one without doesn't",
          r.parses("TOWN_A") and not r.parses("HOUSE_A"))

    links = r.connections("TOWN_A")
    check("a connection declares only its offset",
          len(links) == 1 and (links[0].direction, links[0].target,
                               links[0].offset) == ("west", "ROUTE_X", 2)
          and links[0].coord is None)
    cols, _rows = panels.connections(links)
    check("so the table narrows to the three written columns",
          cols == ["direction", "to map", "offset"], str(cols))

    a = r.attributes("TownA", "TOWN_A")
    check("attributes assemble from three files",
          (a.group, a.map_id, a.height, a.width, a.tileset, a.permission,
           a.border_block, a.blk) ==
          (1, 1, 3, 4, "TILESET_JOHTO", "TOWN", "$05", "maps/TownA.blk"))
    check("and no section is pinned anywhere — vanilla has no link file",
          a.banks == {})


def test_geometry_and_swatches(root: Path) -> None:
    print("\ngeometry comes as blocks plus palette-class swatches")
    r = hackmount.mount(root).reads
    g = r.geometry("TownA")
    check("the blk bytes and the declared size agree",
          (g.height, g.width, len(g.blocks)) == (3, 4, 12))
    check("one swatch per metatile", len(g.swatches) == 3)
    gray = 21 * 255 // 31
    check("an all-GRAY block averages to the gray class's day color",
          g.swatches[0] == ((gray,) * 3,) * 4, str(g.swatches[0]))
    check("different palette classes give different swatches",
          len(set(g.swatches)) == 3)

    (root / "maps/TownA.blk").write_bytes(b"\x00\x01")
    from pokeprism_devtools.shared import caches
    caches.clear()
    try:
        hackmount.mount(root).reads.geometry("TownA")
        check("a short blk file is refused loudly", False)
    except panels.Unreadable as exc:
        check("a short blk file is refused loudly", "2 bytes" in str(exc), str(exc))
    (root / "maps/TownA.blk").write_bytes(bytes(12))


def test_wild_and_roof(root: Path) -> None:
    print("\nwild slots and the group roof cross as data")
    r = hackmount.mount(root).reads
    w = r.wild("TOWN_A")
    check("grass splits seven slots by time of day",
          list(w["grass"]) == ["morn", "day", "nite"]
          and all(len(m) == 7 for m in w["grass"].values()))
    check("nite belongs to the ghosts", w["grass"]["nite"][0].species == "GASTLY")
    check("water is three slots, one time", len(w["water"]["any"]) == 3)
    check("no form column — vanilla's mon is a scalar",
          all(m.form == "" for m in w["grass"]["morn"]))
    check("an indoor map has none", r.wild("HOUSE_A") == {})

    roof = r.roof("TOWN_A")
    check("the group's roof index resolves to its tiles file",
          roof is not None and roof.tiles == 1
          and roof.tile_file == "gfx/tilesets/roofs/violet.2bpp")
    check("its colors come from the group's rows of roofs.pal",
          roof.colors is not None and len(roof.colors) == 4
          and all(c.startswith("#") for c in roof.colors))
    check("and vanilla's table has no pathologies to report",
          roof.mislabelled is None and not roof.past_end)


def test_texts(root: Path) -> None:
    print("\ndialogue crosses as prose")
    tx = hackmount.mount(root).reads.texts("TownA")
    by_label = {t.label: t for t in tx}
    check("every text block is found", set(by_label) ==
          {"TownATeacherText", "TownASignText", "ZekeSeenText", "ZekeBeatenText"})
    teacher = by_label["TownATeacherText"]
    check("a para is a blank line, like any box break",
          teacher.prose == "Hello there,\nwanderer.\n\nNice day.")
    check("everything is speech — vanilla has one box",
          all(t.box == "speech" for t in tx))


def test_the_session_degrades_to_absence(root: Path) -> None:
    print("\nabove the seam a read-only mount is absence, not error")
    s = Session(root)
    md = s.load("TownA")
    check("the map loads whole", md.error is None and md.geometry is not None)
    check("its tabs are all present",
          [t.name for t in md.tabs] ==
          ["Attributes", "NPCs", "Trainers", "Objects", "Warps", "Signposts",
           "Triggers", "Connections", "Roof", "Wild"])
    check("lint finds nothing because there is no linter", s.lint() == [])
    check("no tab offers to add", s.adders("NPC") == ())
    check("the sprite hint is silence", s.sprite_hint("TOWN_A", "SPRITE_TEACHER") == "")
    try:
        s.measure("Hello.")
        check("measuring refuses with a sentence", False)
    except SessionError as exc:
        check("measuring refuses with a sentence", "vanilla" in str(exc))
    try:
        s.entry("TownA", panels.Ref("npc", "TOWNA_TEACHER"))
        check("editing refuses with a sentence", False)
    except SessionError as exc:
        check("editing refuses with a sentence", "read-only" in str(exc))


# --------------------------------------------------------------------------- #
# the real tree, when it is around                                            #
# --------------------------------------------------------------------------- #

def test_real_tree() -> None:
    root = Path.home() / "code/ricccec/pokecrystal"
    if not (root / "data/maps/maps.asm").exists():
        print("\n(no pokecrystal checkout next door — skipping the real tree)")
        return
    print("\nthe real pokecrystal answers the same questions")
    hack = hackmount.mount(root)
    check("it mounts as vanilla", hack.name == "vanilla")
    r = hack.reads
    check("the catalog is the whole game", len(r.maps()) > 300)

    t = r.tables("AzaleaTown")
    check("Azalea's people and warps are all there",
          len(t.npcs) == 11 and len(t.warps) == 8)
    check("Kurt's neighbour hides a FULL_HEAL",
          any(p.kind == "hidden" and p.what == "FULL_HEAL" for p in t.props))

    t30 = r.tables("Route30")
    check("Joey and his rattata are a trainer, not an NPC",
          any(tr.party == "JOEY1" for tr in t30.trainers))

    g = r.geometry("AzaleaTown")
    check("Azalea is 20×9 blocks", (g.width, g.height, len(g.blocks)) == (20, 9, 180))
    check("its swatches vary", len(set(g.swatches)) > 1)

    w = r.wild("ROUTE_30")
    check("Route 30's mornings have seven grass slots",
          len(w["grass"]["morn"]) == 7)

    roof = r.roof("AZALEA_TOWN")
    check("Azalea wears the azalea roof",
          roof is not None and roof.tile_file == "gfx/tilesets/roofs/azalea.2bpp")


def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        root = _fixture(Path(d))
        test_the_mount_recognises_vanilla(root)
        test_the_six_lists(root)
        test_the_catalog(root)
        test_geometry_and_swatches(root)
        test_wild_and_roof(root)
        test_texts(root)
        test_the_session_degrades_to_absence(root)
    test_real_tree()

    print()
    if FAILED:
        print(f"{FAILED} check(s) FAILED")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
