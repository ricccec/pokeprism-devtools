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
from collections import Counter
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
    check("with the family write adapter, and nothing else declared",
          hack.writes is not None and not hack.plays and not hack.measures)


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
    print("\nabove the seam an undeclared capability is absence, not error")
    s = Session(root)
    md = s.load("TownA")
    check("the map loads whole", md.error is None and md.geometry is not None)
    check("its tabs are all present",
          [t.name for t in md.tabs] ==
          ["Attributes", "NPCs", "Trainers", "Objects", "Warps", "Signposts",
           "Triggers", "Connections", "Roof", "Wild"])
    check("lint finds nothing because there is no linter", s.lint() == [])
    check("and the panes can ask before drawing a verdict",
          s.lints is False and s.measures is False)
    # Four tabs offer to add and one does not. Objects joined the four when the
    # item ball got a block writer; a trainer's entry line still points at a
    # block nobody writes, and that absence is measured rather than pending.
    check("the addable tabs offer one form each",
          all(len(s.adders(k)) == 1
              for k in ("NPC", "warp", "signpost", "object")))
    check("trainers still offer nothing, having no block writer",
          s.adders("trainer") == ())
    check("the sprite hint is silence", s.sprite_hint("TOWN_A", "SPRITE_TEACHER") == "")
    try:
        s.measure("Hello.")
        check("measuring refuses with a sentence", False)
    except SessionError as exc:
        check("measuring refuses with a sentence", "vanilla" in str(exc))
    check("reword is still absent — it is the text project",
          s.form("reword") is None)
    check("resize crosses, and carries the family's width-first shape",
          s.form("resize").dialect.shape.height_first is False)
    check("newmap crosses too, asking this tree's own header arguments",
          "fishgroup" in [f.name for f in s.form("newmap").FIELDS])
    # Editing an entry now crosses; editing the *map* does not, and the refusal
    # is the interesting half — an absent key would say nothing.
    action, values, _ = s.editor("TownA", "TOWN_A",
                                 panels.Ref("npc", "TOWNA_TEACHER"))
    check("editing an npc opens the object editor on what is there",
          action.title == "Edit an object"
          and values["sprite"] == "SPRITE_TEACHER")
    try:
        s.editor("TownA", "TOWN_A", panels.Ref("map", "TOWN_A"))
        check("editing the map itself refuses with a sentence", False)
    except SessionError as exc:
        check("editing the map itself refuses with a sentence",
              "not wired" in str(exc))


def test_deletion_crosses_the_seam(root: Path) -> None:
    print("\ndeletion crosses the seam: the entry goes, the const goes with it")
    src = root / "maps/TownA.asm"
    before = src.read_text()
    s = Session(root)

    act = s.deletion("TownA", "TOWN_A", panels.Ref("trainer", "TOWNA_YOUNGSTER"))
    check("the action names the thing on the confirm screen",
          "TOWNA_YOUNGSTER" in act.describe())
    preview = s.preview(act)
    check("the preview is one file", [e.path for e in preview.edits]
          == ["maps/TownA.asm"] and preview.edits[0].changed)
    check("the orphaned script is a note, not a silence",
          any("TrainerYoungsterZeke" in n for n in preview.notes))
    check("nothing has been written yet", src.read_text() == before)

    s.apply(preview)
    after = src.read_text()
    check("the entry line and its const are gone, in one splice",
          "TrainerYoungsterZeke, EVENT_TOWN_A_YOUNGSTER" not in after
          and "const TOWNA_YOUNGSTER" not in after)
    check("the trainer's script block stays", "TrainerYoungsterZeke:" in after)
    t = s.load("TownA").tabs
    trainers = next(tab for tab in t if tab.name == "Trainers")
    check("the table agrees", len(trainers.table[1]) == 0)

    check("a stale name refuses instead of guessing",
          _refused(s, "TownA", "TOWN_A", panels.Ref("trainer", "TOWNA_YOUNGSTER"),
                   "no longer"))
    check("a connection refuses with the neighbour reason",
          _refused(s, "TownA", "TOWN_A",
                   panels.Ref("connection", key="west"), "neighbour"))

    s.undo()
    check("undo puts the file back to the byte", src.read_text() == before)


# --------------------------------------------------------------------------- #
# warp deletion                                                               #
# --------------------------------------------------------------------------- #

#: TownA's five warps, and one neighbour holding every macro that counts into
#: them. The numbers are chosen so each leg of the triad can be reached alone:
#: nothing names warp #2 (a clean renumber across all three macros), #1 is what
#: a door leads to, #3 what a `warpmod` re-points, #4 what an `elevfloor` lists,
#: and #5 what polished's `digmod` names and vanilla's grammar cannot see.
_TOWNA_WARPS = """\
	def_warp_events
	warp_event  3,  5, HOUSE_A, 1
	warp_event  4,  5, HOUSE_A, 1
	warp_event  5,  5, HOUSE_A, 1
	warp_event  6,  5, HOUSE_A, 1
	warp_event  7,  5, HOUSE_A, 1
"""

_HOUSE_A = """\
	object_const_def

HouseA_MapScripts:
	def_scene_scripts

	def_callbacks

HouseAElevatorScript:
	warpmod 3, TOWN_A
	digmod 5, TOWN_A
	end

HouseAFloors:
	elevfloor FLOOR_1F, 4, TOWN_A

HouseA_MapEvents:
	db 0, 0 ; filler

	def_warp_events
	warp_event  1,  1, TOWN_A, 1
	warp_event  2,  1, TOWN_A, 3
	warp_event  3,  1, TOWN_A, 5

	def_coord_events

	def_bg_events

	def_object_events
"""


def _warp_fixture(tmp: Path) -> Path:
    """The read fixture, plus the warps that make deletion interesting."""
    root = _fixture(tmp)
    src = root / "maps/TownA.asm"
    src.write_text(src.read_text().replace(
        "\tdef_warp_events\n\twarp_event  3,  5, HOUSE_A, 1\n", _TOWNA_WARPS))
    (root / "maps/HouseA.asm").write_text(_HOUSE_A)
    return root


def test_warp_deletion_crosses(root: Path) -> None:
    """The renumber/refuse triad, and the grammar proved to be data.

    Prism's version of this test asserts a door whose destination was deleted
    becomes a `dummy_warp`. The family's asserts it *refuses* — the dialect has
    no dead door to write, and that difference is the whole reason the grammar
    is a record rather than a constant.
    """
    print("\ndeleting a warp: the renumber crosses, the door goes nowhere, two refuse")
    from pokeprism_devtools.hacks.vanilla import write as VW
    from pokeprism_devtools.wiring import warpdel

    house = root / "maps/HouseA.asm"
    town = root / "maps/TownA.asm"
    before_house, before_town = house.read_text(), town.read_text()

    def refuse(index: int, grammar=VW.WARPS) -> str:
        try:
            VW.delete_warp(root, "TownA", "TOWN_A", index, grammar=grammar)
            return ""
        except warpdel.WarpDelError as exc:
            return str(exc)

    # -- the clean renumber: nothing names #2, so all three macros just move --- #
    d = VW.delete_warp(root, "TownA", "TOWN_A", 1)
    text = next(e.new_text for e in d.changes if e.path == "maps/HouseA.asm")
    check("a warp_event that counted past the hole comes back one",
          "warp_event  2,  1, TOWN_A, 2" in text, _warp_lines(text))
    check("...and so does the one further down",
          "warp_event  3,  1, TOWN_A, 4" in text, _warp_lines(text))
    check("the warp that counted short of the hole does not move",
          "warp_event  1,  1, TOWN_A, 1" in text)
    check("a warpmod is renumbered too — it counts the same list",
          "warpmod 2, TOWN_A" in text)
    check("and an elevfloor, the macro prism has never heard of",
          "elevfloor FLOOR_1F, 3, TOWN_A" in text)
    check("the deletion says how many moved", d.renumbered == 4, str(d.renumbered))
    check("nothing has been written yet",
          house.read_text() == before_house and town.read_text() == before_town)

    # -- every line the deletion did not claim is byte-identical ---------------- #
    moved = [(a, b) for a, b in zip(before_house.split("\n"), text.split("\n"))
             if a != b]
    check("exactly the four counting lines changed, and nothing else",
          len(moved) == 4, str(moved))

    # -- a door to the deleted warp becomes the family's dead door -------------- #
    # `warp_event x, y, NONE, -1` is byte-for-byte prism's `dummy_warp y, x`:
    # GROUP_NONE and MAP_NONE are both 0, so `map_id NONE` emits `db 0, 0`.
    dd = VW.delete_warp(root, "TownA", "TOWN_A", 0)
    door_text = next(e.new_text for e in dd.changes if e.path == "maps/HouseA.asm")
    check("a door leading to the deleted warp is sent nowhere, not deleted",
          "warp_event  1,  1, NONE, -1" in door_text, _warp_lines(door_text))
    check("...keeping its own place in HouseA's list, so nobody else moves",
          sum(ln.strip().startswith("warp_event")
              for ln in door_text.split("\n")) == 3)
    check("...and its coordinates verbatim, padding and all",
          "  1,  1, NONE" in door_text)
    check("the deletion says so, and says what nowhere is really worth",
          any("door to nowhere" in w and "backup warp" in w for w in dd.warnings),
          str(dd.warnings[-1])[:100])

    # -- the two macros with no dummy form ------------------------------------- #
    check("a warpmod aimed at the deleted warp refuses",
          "`warpmod`" in refuse(2), refuse(2)[:80])
    check("an elevfloor aimed at it refuses too — the family's third surface",
          "`elevfloor`" in refuse(3), refuse(3)[:80])

    # -- the grammar is data: the same tree, two answers ------------------------ #
    vanilla_text = text
    dp = VW.delete_warp(root, "TownA", "TOWN_A", 1, grammar=VW.POLISHED_WARPS)
    polished_text = next(e.new_text for e in dp.changes
                         if e.path == "maps/HouseA.asm")
    check("vanilla's grammar cannot see a digmod, so it leaves it alone",
          "digmod 5, TOWN_A" in vanilla_text)
    check("polished's grammar counts it, and pulls it back one",
          "digmod 4, TOWN_A" in polished_text)
    check("...which is the only line the two grammars disagree about",
          sum(a != b for a, b in zip(vanilla_text.split("\n"),
                                     polished_text.split("\n"))) == 1)
    check("and polished warns about the table it cannot check",
          any("grottoes.asm" in w for w in dp.warnings), str(dp.warnings))
    check("...which vanilla, having no such table, does not",
          not any("grottoes" in w for w in d.warnings))

    # -- end to end, through the seam ------------------------------------------ #
    s = Session(root)
    act = s.deletion("TownA", "TOWN_A", panels.Ref("warp", ("warp", 1)))
    check("the seam hands back an action, not a refusal",
          "warp #2" in act.describe(), act.describe())
    preview = s.preview(act)
    check("the preview spans both files",
          sorted(e.path for e in preview.edits)
          == ["maps/HouseA.asm", "maps/TownA.asm"],
          str([e.path for e in preview.edits]))
    s.apply(preview)
    check("TownA has one warp fewer",
          sum(ln.strip().startswith("warp_event")
              for ln in town.read_text().split("\n")) == 4)
    check("and HouseA's counting lines followed it",
          "warp_event  2,  1, TOWN_A, 2" in house.read_text())
    s.undo()
    check("undo restores both files to the byte",
          house.read_text() == before_house and town.read_text() == before_town)


def _warp_lines(text: str) -> str:
    return " | ".join(ln.strip() for ln in text.split("\n")
                      if "TOWN_A" in ln and ln.strip())


def _refused(s: Session, label: str, const: str, ref, phrase: str) -> bool:
    try:
        s.deletion(label, const, ref)
        return False
    except SessionError as exc:
        return phrase in str(exc)


# --------------------------------------------------------------------------- #
# the real tree, when it is around                                            #
# --------------------------------------------------------------------------- #

def test_the_base_imports_no_adapter() -> None:
    """The rule Phase 6 was carved for: adapters import the base, the base
    imports no adapter.

    Asserted statically, over the module's own import lines, because the
    runtime version of this question cannot be asked — importing
    `studio.actions` runs `studio/__init__`, which imports `session`, which
    imports `maplint`, which is written against prism. That chain is real and
    predates this phase; what the carve fixed is the *direct* one, and a static
    check is what distinguishes them.
    """
    import ast
    print("\nthe neutral base stays neutral")
    src = Path(__file__).resolve().parent.parent / "src/pokeprism_devtools"
    tree = ast.parse((src / "studio/actions.py").read_text())
    deps = []
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            deps.append("." * n.level + (n.module or ""))
        elif isinstance(n, ast.Import):
            deps += [a.name for a in n.names]
    bad = [d for d in deps if "hacks" in d or "wiring" in d]
    check("studio/actions.py imports no adapter and no wiring", not bad, str(bad))
    check("it still exports what a family action needs",
          all(hasattr(__import__(
              "pokeprism_devtools.studio.actions", fromlist=["x"]), n)
              for n in ("Action", "ActionError", "Field", "Result", "ITEMS")))


def test_reading_a_declared_const_set() -> None:
    """`ConstSet` over the four spellings a gen-2 tree actually uses."""
    from pokeprism_devtools.shared.constants import ConstSet, read_set
    print("\na declared constant set is read in whatever way it is spelled")
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "constants").mkdir()
        (root / "constants/s.asm").write_text(
            "\tconst_def\n"
            "\tconst PAL_NPC_RED   ; 0\n"
            "\tconst PAL_NPC_BLUE  ; 1\n"
            "\tconst OTHER_THING\n"
            "DEF PAL_NPC_DEFAULT EQU 0\n"
            "MACRO ow_npc_pal_const\n"
            "\tconst PAL_NPC_\\1\n"
            "ENDM\n"
            "\tow_npc_pal_const GREEN\n"
            "\tow_npc_pal_const YELLOW\n"
            "PURGE PAL_NPC_YELLOW\n")

        plain = read_set(root, ConstSet("constants/s.asm", "PAL_NPC_"))
        check("`const` lines are read, and the prefix filters",
              plain == ("PAL_NPC_BLUE", "PAL_NPC_DEFAULT", "PAL_NPC_RED"), str(plain))

        viamacro = read_set(root, ConstSet("constants/s.asm", "PAL_NPC_",
                                           macro="ow_npc_pal_const"))
        check("a macro's argument becomes a name, prefix pasted on",
              "PAL_NPC_GREEN" in viamacro, str(viamacro))
        check("and the longhand member survives alongside it — the union is "
              "what polished's PAL_NPC_DEFAULT needs",
              "PAL_NPC_DEFAULT" in viamacro)
        check("a PURGEd name is not offered, in either mode",
              "PAL_NPC_YELLOW" not in viamacro and "PAL_NPC_YELLOW" not in plain)
        check("the macro's own body is not mistaken for a definition",
              not any(n.rstrip("_").endswith("PAL_NPC") or n == "PAL_NPC_"
                      for n in viamacro), str(viamacro))
        check("a file that isn't there is an empty set, not a crash",
              read_set(root, ConstSet("constants/nope.asm")) == ())


def test_real_choices(root: Path, name: str) -> None:
    """What the family offers, checked against what its maps actually use.

    The assertion that matters, and the one that caught a wrong prefix twice:
    every constant a real map file writes must be a constant the form would
    have offered. A set read from the wrong file, or under the prefix the tree
    *defines* rather than the one it *uses*, still returns a plausible list —
    it just has none of the right names in it, and nothing but this comparison
    says so.
    """
    import re
    if not (root / "data/maps/maps.asm").exists():
        print(f"\n(no {name} checkout next door — skipping its choices)")
        return
    print(f"\n{name}: every constant its maps use is a constant it offers")
    from pokeprism_devtools.studio import actions

    hack = hackmount.mount(root)
    consts = tuple(hack.reads.maps().values())
    patterns = {
        actions.SPRITES:   r"\bSPRITE_[A-Z0-9_]+\b",
        actions.MOVEMENTS: r"\bSPRITEMOVEDATA_[A-Z0-9_]+\b",
        actions.PALETTES:  r"\bPAL_NPC_[A-Z0-9_]+\b",
        actions.FACINGS:   r"\bBGEVENT_[A-Z0-9_]+\b",
        actions.FLAGS:     r"\bEVENT_[A-Z0-9_]+\b",
    }
    used: dict[str, set[str]] = {k: set() for k in patterns}
    for f in (root / "maps").glob("*.asm"):
        for line in f.read_text(errors="replace").split("\n"):
            s = line.strip()
            if not s.startswith(("object_event", "bg_event", "coord_event",
                                 "warp_event")):
                continue
            for kind, pat in patterns.items():
                used[kind] |= set(re.findall(pat, s))

    for kind, seen in used.items():
        offered = set(hack.writes.choices(kind, consts))
        missing = sorted(seen - offered)
        check(f"every {kind[:-1] if kind.endswith('s') else kind} in use is offered",
              not missing and bool(seen),
              f"{len(seen)} used, {len(offered)} offered"
              + (f", MISSING {missing[:5]}" if missing else ""))

    check("maps are offered from the catalog it was handed",
          hack.writes.choices(actions.MAPS, consts) == list(consts))
    check("a kind this dialect cannot enumerate is empty, not invented",
          hack.writes.choices(actions.PARTIES, consts) == []
          and hack.writes.choices(actions.CLASSES, consts) == [])
    hack.writes.warm()
    hack.writes.forget()
    check("warm and forget both run, and forget really drops the cache",
          hack.writes.choices(actions.SPRITES, consts) == sorted(
              set(hack.writes.choices(actions.SPRITES, consts))))


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


def test_real_warp_deletion(root: Path, name: str, anchor: str, grammar,
                            label: str, const: str) -> None:
    """A warp out of a real tree, and the 2,000-odd files that must not move.

    The fixture proves the rule; this proves the *scan* — that on a tree nobody
    wrote for this test, the only lines that change are lines that count into
    the map in question, and every one of the thousands that doesn't is
    byte-identical.
    """
    if not (root / "data/maps/maps.asm").exists():
        print(f"\n(no {name} checkout next door — skipping its real warps)")
        return
    print(f"\na warp comes out of the real {name}, and nothing else moves")
    import shutil
    from pokeprism_devtools.hacks.vanilla import eventblock as EB
    from pokeprism_devtools.hacks.vanilla import write as VW
    from pokeprism_devtools.shared.edits import apply_edits
    from pokeprism_devtools.wiring import warpdel

    with tempfile.TemporaryDirectory() as d:
        scratch = Path(d) / name
        shutil.copytree(root, scratch, ignore=shutil.ignore_patterns(
            ".git", "build", "*.gbc", "*.gb", "*.o", "*.2bpp", "*.png"))
        before = {p.relative_to(scratch).as_posix(): p.read_text(errors="replace")
                  for p in scratch.rglob("*.asm")}

        block = EB.parse_map(scratch / f"maps/{label}.asm", anchor)
        n = len(block.lists["warp"].entries)
        # Walk to a warp the tree lets go of: on a real map most warps are the
        # far side of somebody's door, and refusing those is the point.
        d_ = None
        for i in range(n):
            try:
                d_ = VW.delete_warp(scratch, label, const, i, anchor, grammar)
                break
            except warpdel.WarpDelError:
                continue
        if d_ is None:
            check(f"some warp of {label} can be deleted", False,
                  f"all {n} refused — every one is led to, or named by a "
                  f"macro with no dummy form")
            return

        touched = {e.path for e in d_.changes}
        own = f"maps/{label}.asm"
        check(f"the deletion touches {len(touched)} of {len(before)} .asm files",
              len(touched) >= 1 and len(touched) < 40, str(sorted(touched)[:5]))

        # By multiset, not by position: the splice shifts every line below it,
        # so a line-for-line diff would call the whole tail of the cut file
        # "changed". And the test has to read the lines that *went away* — a
        # dead door stops naming the map, which is the entire point of it.
        for e in d_.changes:
            gone = Counter(before[e.path].split("\n")) - \
                Counter(e.new_text.split("\n"))
            claimed = [ln for ln in gone.elements() if const not in ln]
            if e.path == own:
                check(f"the only line to leave {own} without naming {const} "
                      f"is the warp itself",
                      len(claimed) == 1 and claimed[0].strip().startswith(
                          "warp_event"), str(claimed))
            else:
                check(f"every line that changed in {e.path} named {const}",
                      not claimed, str(claimed[:3]))

        apply_edits(scratch, d_.changes, dry_run=False)
        after = {p.relative_to(scratch).as_posix(): p.read_text(errors="replace")
                 for p in scratch.rglob("*.asm")}
        moved = {rel for rel in before if before[rel] != after.get(rel)}
        check("no file the deletion did not claim moved by a byte",
              moved == touched, str(sorted(moved - touched)[:5]))
        check("and the map it cut still parses, one warp shorter",
              len(EB.parse_map(scratch / f"maps/{label}.asm",
                               anchor).lists["warp"].entries) == n - 1)


def test_editing_round_trips(root: Path, name: str, anchor: str, shape) -> None:
    """Prefill every entry in every real map, hand it straight back unchanged,
    and demand the file come back the way it went in.

    The one check that can catch a wrong slot order, because a wrong order is
    not a crash — it is a plausible line with two arguments swapped. It caught
    two things nothing else would have: `replace_entry` dropping every comment
    (its regex consumed the comment before it measured where the arguments
    stopped, so the slice was always empty), and polished's five-argument
    `BGEVENT_JUMPSTD` losing its grotto id.
    """
    from pokeprism_devtools.hacks.vanilla import actions as fa
    from pokeprism_devtools.hacks.vanilla import eventblock as EB
    print(f"\nevery entry in {name} survives being edited into itself")
    tail = {"warp": ("to_map", "their_warp"), "coord": ("scene", "script"),
            "bg": ("kind", "points_at")}
    total = shifted = refused = 0
    moved: list[str] = []
    for path in sorted((root / "maps").glob("*.asm")):
        try:
            probe = EB.parse_map(path, anchor)
        except Exception:
            continue
        for kind in ("warp", "coord", "bg", "object"):
            for i in range(len(probe.lists[kind].entries)):
                block = EB.parse_map(path, anchor)
                entry = block.lists[kind].entries[i]
                values = fa.prefill(block, kind, i, shape)
                if kind == "object":
                    if len(entry.args) != len(shape.slots):
                        refused += 1
                        continue
                    args = shape.args(values)
                else:
                    a, b = tail[kind]
                    args = [values["x"], values["y"], values[a], values[b]]
                    if values.get("extra"):
                        args.append(values["extra"])
                before = block.to_text()
                block.replace_entry(kind, i, args)
                total += 1
                if block.to_text() == before:
                    continue
                # Only `format_entry`'s two-column padding may differ, and only
                # on the line that was edited. Anything else is a lost argument.
                was, now = entry.raw, block.lines[entry.lineno]
                if was.split() == now.split():
                    shifted += 1
                else:
                    moved.append(f"{path.name} {kind}#{i}: {was!r} -> {now!r}")
    check(f"{total} entries edited into themselves, none lost an argument",
          not moved, "; ".join(moved[:3]))
    check("comments survive the rewrite",
          all("; hole" not in m for m in moved))
    check(f"{shifted} differ only by the writer's own column padding",
          shifted < total // 100,
          f"{shifted}/{total} — house style, not data")
    print(f"  ({refused} object lines refused: their trailing args mean "
          f"something else)")


def test_a_line_the_editor_will_not_rewrite(root: Path) -> None:
    """Polished's thirteen-argument `object_event` spends its last three on an
    item, a quantity and a flag where the ordinary twelve spend two on a
    pointer and a flag. Rewriting one with the twelve-slot shape would slide
    the flag into the quantity, so it refuses and names the line — the same
    choice `read_set` makes about a constant `PURGE` took away."""
    from pokeprism_devtools.hacks.vanilla import actions as fa
    from pokeprism_devtools.studio.actions import ActionError
    print("\nan object_event whose trailing args mean something else refuses")
    src = root / "maps/TownA.asm"
    text = src.read_text()
    long_line = ("\tobject_event  1,  1, SPRITE_GRAMPS, "
                 "SPRITEMOVEDATA_STANDING_DOWN, 0, 0, -1, PAL_NPC_RED, "
                 "OBJECTTYPE_ITEMBALL, PLAYEREVENT_ITEMBALL, POTION, 1, -1")
    src.write_text(text.replace("\tdef_object_events",
                                "\tdef_object_events\n" + long_line, 1))
    try:
        editor = fa.POLISHED_EDITORS["object"]
        act = editor("TOWN_A", index="0")
        act.anchor = "_MapEvents"      # the fixture is a vanilla-shaped file
        try:
            act.run(root)
            check("a 13-argument line is refused by the 12-slot editor", False)
        except ActionError as exc:
            check("a 13-argument line is refused by the 12-slot editor",
                  "13 arguments" in str(exc) and "will not rewrite" in str(exc),
                  str(exc))
    finally:
        src.write_text(text)


def test_adding_an_entry(root: Path) -> None:
    """The three adders that cross, and the one refusal that keeps a map
    assembling: a name on a partially-named const list would take an ordinal
    that belongs to somebody else."""
    from pokeprism_devtools.hacks.vanilla import actions as fa
    from pokeprism_devtools.studio.actions import ActionError
    print("\nadding an entry: three lists cross, and the fourth says why not")

    warp = fa.VANILLA_ADDERS["warp"][0]("TOWN_A", y="3", x="4",
                                        to_map="HOUSE_A", their_warp="1")
    result = warp.run(root)
    check("a warp is appended, one file touched", len(result.edits) == 1)
    check("and it is written x-first, the way the macro reads it",
          "warp_event  4,  3, HOUSE_A, 1" in result.edits[0].new_text)

    trigger = fa.VANILLA_ADDERS["trigger"][0]("TOWN_A", y="2", x="2", scene="0")
    try:
        trigger.run(root)
        check("a trigger that runs nothing is refused", False)
    except ActionError as exc:
        check("a trigger that runs nothing is refused", "jump to" in str(exc))

    sign = fa.VANILLA_ADDERS["signpost"][0](
        "TOWN_A", y="1", x="1", kind="BGEVENT_ITEM + NUGGET", points_at="X")
    try:
        sign.run(root)
        check("a hidden item is refused — its block is nobody's to write", False)
    except ActionError as exc:
        check("a hidden item is refused — its block is nobody's to write",
              "hiddenitem" in str(exc))

    npc = fa.VANILLA_ADDERS["NPC"][0]("TOWN_A", y="5", x="5",
                                      sprite="SPRITE_GRAMPS",
                                      script="TownATeacherScript")
    written = npc.run(root).edits[0].new_text
    check("an unnamed NPC gets this dialect's thirteen slots in its order",
          "object_event  5,  5, SPRITE_GRAMPS, SPRITEMOVEDATA_STANDING_DOWN, "
          "0, 0, -1, -1, PAL_NPC_RED, OBJECTTYPE_SCRIPT, 0, "
          "TownATeacherScript, -1" in written, written)


def test_resizing_crosses(root: Path) -> None:
    """TOWN_A is `map_const TOWN_A,  4, 3` — width 4, height 3, twelve blocks."""
    print("\nresizing crosses the seam")
    from pokeprism_devtools.hacks.vanilla.resize import VANILLA
    from pokeprism_devtools.wiring import mapresize as MR

    DIMS = "constants/map_constants.asm"
    before = (root / DIMS).read_text()

    change = MR.resize(root, "TOWN_A", "bottom", "grow", 1, dialect=VANILLA)
    edits = {e.path: e for e in change.changes}
    check("growing the bottom touches the constant and the grid, nothing else",
          set(edits) == {DIMS, "maps/TownA.blk"}, str(sorted(edits)))
    check("the grid grew by one row of width 4",
          len(edits["maps/TownA.blk"].data) == 16,
          str(len(edits["maps/TownA.blk"].data)))

    line = [l for l in edits[DIMS].new_text.split("\n") if "TOWN_A" in l][0]
    check("the dimension line keeps width first — 4 wide, now 4 tall",
          line.strip().startswith("map_const TOWN_A,") and ", 4" in line
          and line.rstrip().endswith("; 1"), line)
    check("and its trailing comment and column padding survive",
          line == "\tmap_const TOWN_A,  4, 4 ; 1", repr(line))

    check("growing the bottom moves nothing, so no map file is rewritten",
          "maps/TownA.asm" not in edits)

    # Growing the *top* moves the origin: every coordinate shifts down 2 tiles.
    change = MR.resize(root, "TOWN_A", "top", "grow", 1, dialect=VANILLA)
    edits = {e.path: e for e in change.changes}
    check("growing the top rewrites the map file too", "maps/TownA.asm" in edits)
    moved = [l for l in edits["maps/TownA.asm"].new_text.split("\n")
             if l.strip().startswith("warp_event ")]
    check("the warp moved down two tiles and stayed in its column",
          moved and moved[0].split()[1:3] == ["3,", "7,"], str(moved[:1]))
    check("the shift is reported rather than done silently",
          any("shifted" in n for n in change.notes), str(change.notes))

    # Growing the left moves it the other way, and only in x.
    change = MR.resize(root, "TOWN_A", "left", "grow", 1, dialect=VANILLA)
    warp = [l for l in
            {e.path: e for e in change.changes}["maps/TownA.asm"].new_text.split("\n")
            if l.strip().startswith("warp_event ")][0]
    check("growing the left moves the warp two columns and no rows",
          warp.split()[1:3] == ["5,", "5,"], warp)

    check("none of that touched the tree — a Change is a proposal",
          (root / DIMS).read_text() == before)

    print("\nand it refuses what it cannot do safely")
    try:
        MR.resize(root, "TOWN_A", "left", "shrink", 1, dialect=VANILLA)
        check("shrinking onto something standing there refuses", False)
    except MR.EditError as exc:
        check("shrinking onto something standing there refuses",
              "would remove" in str(exc), str(exc)[:70])
    try:
        MR.resize(root, "TOWN_A", "top", "shrink", 3, dialect=VANILLA)
        check("shrinking a map out of existence refuses", False)
    except MR.EditError as exc:
        check("shrinking a map out of existence refuses",
              "would leave nothing" in str(exc), str(exc)[:60])


def test_shared_blocks_refuse(tmp: Path) -> None:
    """The family stacks several labels on one INCBIN constantly — resizing one
    of a pair would corrupt the other, whose dimension constant does not move."""
    print("\ntwo maps sharing one grid refuse to be resized")
    from pokeprism_devtools.hacks.vanilla.resize import VANILLA
    from pokeprism_devtools.wiring import mapresize as MR

    root = _fixture(tmp / "shared")
    (root / "data/maps/blocks.asm").write_text(
        'TownA_Blocks:\nHouseA_Blocks:\n\tINCBIN "maps/TownA.blk"\n')
    from pokeprism_devtools.hacks.vanilla import read as r
    r._blk.cache_clear()
    try:
        MR.resize(root, "TOWN_A", "bottom", "grow", 1, dialect=VANILLA)
        check("a shared grid refuses the whole resize", False)
    except MR.EditError as exc:
        check("a shared grid refuses the whole resize, naming the twin",
              "shared with HouseA" in str(exc), str(exc)[:70])
    r._blk.cache_clear()


def test_real_resize(name: str, dialect) -> None:
    """The orientation check, on every real map.

    A byte count cannot catch a transposed height and width, because `h*w` is
    `w*h` — so the check that matters is whether the things standing on the map
    fit inside it. They do under the declared order and mostly do not under the
    transposed one, which is the whole argument for `MapShape` in one number.
    """
    root = Path.home() / "code/ricccec" / name
    if not root.exists():
        print(f"\n({name} not checked out — skipping)")
        return
    print(f"\nevery {name} map, against both readings of its dimension line")
    from pokeprism_devtools.hacks.vanilla import read as r
    from pokeprism_devtools.wiring.mapresize import MapShape

    flipped = MapShape(dialect.shape.path, dialect.shape.macro, height_first=True)
    fits = flips = maps = 0
    resizable = shared = 0
    for const, label in r.label_of(root).items():
        try:
            h, w = dialect.shape.read(root, const)
        except Exception:
            continue
        try:
            grid = dialect.read_grid(dialect.blk(root, label), h, w)
            resizable += 1
            if len(grid) != h * w:
                check(f"{label} grid is h*w", False)
        except Exception as exc:
            if "shared with" in str(exc):
                shared += 1
            else:
                check(f"{label} refuses for a reason we know", False, str(exc)[:60])
        standing = dialect.standing(root, label)
        if not standing:
            continue
        maps += 1
        H, W = flipped.read(root, const)
        fits += all(s.y < 2 * h and s.x < 2 * w for s in standing)
        flips += all(s.y < 2 * H and s.x < 2 * W for s in standing)

    check(f"{resizable} maps resize and {shared} refuse for sharing a grid — "
          f"and nothing refuses for any other reason", True)
    check("nearly every map's entries fit inside it as declared",
          fits >= maps - 4, f"{fits}/{maps}")
    check("but only about half fit under the transposed reading — the order "
          "is load-bearing, not cosmetic",
          flips < maps * 0.6, f"{flips}/{maps} would still fit")


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
        test_a_line_the_editor_will_not_rewrite(root)
        test_adding_an_entry(root)
        test_resizing_crosses(root)
        test_shared_blocks_refuse(Path(d))
        test_deletion_crosses_the_seam(root)
    # Its own tree: this fixture gives HouseA a map file, and the catalog test
    # above rests on HouseA *not* having one.
    with tempfile.TemporaryDirectory() as d:
        test_warp_deletion_crosses(_warp_fixture(Path(d)))
    test_the_base_imports_no_adapter()
    test_reading_a_declared_const_set()
    test_real_tree()
    test_real_choices(Path.home() / "code/ricccec/pokecrystal", "pokecrystal")
    test_real_choices(Path.home() / "code/ricccec/polishedcrystal",
                      "polishedcrystal")

    from pokeprism_devtools.hacks.vanilla import actions as FA
    test_editing_round_trips(Path.home() / "code/ricccec/pokecrystal",
                             "pokecrystal", "_MapEvents", FA.VANILLA_OBJECT)
    test_editing_round_trips(Path.home() / "code/ricccec/polishedcrystal",
                             "polishedcrystal", "_MapScriptHeader",
                             FA.POLISHED_OBJECT)

    from pokeprism_devtools.hacks.vanilla.resize import VANILLA, polished
    test_real_resize("pokecrystal", VANILLA)
    test_real_resize("polishedcrystal", polished())

    from pokeprism_devtools.hacks.vanilla import write as VW
    test_real_warp_deletion(Path.home() / "code/ricccec/pokecrystal", "pokecrystal",
                            "_MapEvents", VW.WARPS, "AzaleaTown", "AZALEA_TOWN")
    test_real_warp_deletion(Path.home() / "code/ricccec/polishedcrystal",
                            "polishedcrystal", "_MapScriptHeader",
                            VW.POLISHED_WARPS, "AzaleaTown", "AZALEA_TOWN")

    print()
    if FAILED:
        print(f"{FAILED} check(s) FAILED")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
