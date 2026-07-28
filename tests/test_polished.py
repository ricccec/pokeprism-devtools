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

import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pokeprism_devtools.hacks import mount as hackmount  # noqa: E402
from pokeprism_devtools.studio import panels  # noqa: E402
from pokeprism_devtools.studio.session import Session  # noqa: E402

FAILED = 0
KNOWN_GAP = 0
CLOSED_GAP = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global FAILED
    print(f"  [{'OK  ' if cond else 'FAIL'}] {label}{f' — {detail}' if detail else ''}")
    if not cond:
        FAILED += 1


def expected_gap(label: str, invariant_holds: bool, detail: str = "") -> None:
    """Assert an invariant we WANT but don't yet meet — an xfail by hand.

    The harness has no pytest, so a known gap can't be marked and skipped; it
    would just turn the suite red and get muted. Instead this states the correct
    invariant and, while it fails, records it as a known gap without touching
    FAILED. The day the invariant starts holding, it prints XPASS loudly so the
    gap's closure is noticed and the line gets promoted to a real check().
    """
    global KNOWN_GAP, CLOSED_GAP
    if invariant_holds:
        CLOSED_GAP += 1
        print(f"  [XPASS] {label} — gap closed; promote this to check()"
              f"{f' — {detail}' if detail else ''}")
    else:
        KNOWN_GAP += 1
        print(f"  [XFAIL] {label} — known gap{f': {detail}' if detail else ''}")


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
    # Polished now plays (Stage 1: a build-and-boot over its own save and block
    # codec). The missing tile ruler is this *fixture's* absence, not the tree's:
    # `measures` is asked of the tree, and this one ships no charmap and no n-gram
    # table to count tiles with. A real polishedcrystal measures; test_family_lint.py
    # checks it. The Player is constructed even on a fixture — it reads nothing
    # until asked to build or boot.
    check("a write adapter, a linter and a play adapter; it cannot measure a "
          "fixture with no text engine in it",
          hack.ctx is not None and hack.writes is not None
          and hack.plays is not None and not hack.measures)
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


def test_floor_shorthands_read_as_props() -> None:
    """A cut tree, the two boulders and a fruit tree are things on the floor,
    not people — but each expands to an `OBJECTTYPE_COMMAND` object exactly like
    an NPC that `jumptextfaceplayer`s, so the type byte cannot tell them apart.
    The reader reads the command instead: `fruittree` and the three `jumpstd`
    obstacles land in props; the nurse's `jumpstd pokecenternurse`, a command
    object too, stays a person — the guard that a command is not a prop by type.
    """
    from pokeprism_devtools.hacks.polished import events as pe
    src = (
        "Grove_MapScriptHeader:\n"
        "\tdef_scene_scripts\n\n\tdef_callbacks\n\n\tdef_warp_events\n\n"
        "\tdef_coord_events\n\n\tdef_bg_events\n\n\tdef_object_events\n"
        "\tcuttree_event  3,  4, EVENT_GROVE_CUT_TREE\n"
        "\tstrengthboulder_event  5,  6\n"
        "\tsmashrock_event  7,  8, EVENT_GROVE_ROCK\n"
        "\tfruittree_event  9, 10, FRUITTREE_GROVE, BERRY, PAL_NPC_ENV_WHITE\n"
        "\tpc_nurse_event 11, 12\n")
    print("\nthe floor shorthands read as props, the nurse stays a person")
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "Grove.asm"
        path.write_text(src)
        t = pe.tables(path)

    check("four floor props surface, one of each shorthand",
          {p.kind for p in t.props} == {"cuttree", "boulder", "rock", "fruittree"},
          str(sorted(p.kind for p in t.props)))
    tree = next((p for p in t.props if p.kind == "fruittree"), None)
    check("the fruit tree is named by the tree it is",
          tree is not None and tree.what == "FRUITTREE_GROVE",
          tree.what if tree else "no fruittree prop")
    rock = next((p for p in t.props if p.kind == "rock"), None)
    check("the smash rock reads back at its tile, its flag the last arg",
          rock is not None and (rock.y, rock.x, rock.flag) == (8, 7, "EVENT_GROVE_ROCK"),
          str((rock.y, rock.x, rock.flag)) if rock else "no rock prop")
    check("the nurse is still a person — a command is not a prop by its type",
          len(t.npcs) == 1 and t.npcs[0].sprite == "BOWING_NURSE",
          str([n.sprite for n in t.npcs]))


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
    check("lint is empty — there is no linter for this dialect", s.lint() == [])
    # The adder polished gets is *its own*: same class, stamped with the head
    # anchor and the twelve-slot object shape, so the form it builds has a
    # time-of-day box where vanilla's has two hour boxes.
    adder = s.adders("NPC")[0]
    slots = adder.shape.slots
    check("the NPC adder is polished's fork of it",
          adder.anchor == "_MapScriptHeader" and "time" in slots
          and "h1" not in slots)
    check("and its movement radius is the other way round",
          slots.index("radius_y") < slots.index("radius_x"))


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


def test_polished_offers_the_item_adders(root: Path) -> None:
    print("\npolished's Objects tab offers a ball and a hidden item of its own")
    s = Session(root)
    adders = s.adders("object")
    by = {a.name: a for a in adders}
    check("two line-only adders, no block between them",
          set(by) == {"itemball", "hiddenitem"}, str(set(by)))
    check("the ball's line is an object, the hidden item's a bg — the tab it "
          "reads onto is not the list its line lives in",
          by["itemball"].list_kind == "object"
          and by["hiddenitem"].list_kind == "bg")
    check("both carry polished's head anchor, not vanilla's tail",
          all(a.anchor == "_MapScriptHeader" for a in adders))


def test_real_item_adders() -> None:
    root = Path.home() / "code/ricccec/polishedcrystal"
    if not (root / "data/maps/maps.asm").exists():
        print("\n(no polishedcrystal checkout — skipping the item-adder round-trip)")
        return
    print("\nthe polished item ball and hidden item round-trip on the real tree")
    import shutil

    from pokeprism_devtools.hacks.polished import events as pe
    from pokeprism_devtools.hacks.vanilla import actions as fa
    from pokeprism_devtools.shared.edits import apply_edits
    ball, hidden = fa.POLISHED_ADDERS["object"]

    def run_into(mapfile, action, kind, want):
        with tempfile.TemporaryDirectory() as d:
            tree = Path(d)
            shutil.copytree(root, tree, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns(".git"))
            res = action.run(tree)
            apply_edits(tree, res.edits, dry_run=False)
            t = pe.tables(tree / f"maps/{mapfile}.asm")
            got = [p for p in t.props if p.kind == kind and p.what == want]
            flags = (tree / "constants/event_flags.asm").read_text()
            return res, got, bool(got) and got[0].flag in flags

    # BurnedTower1F interleaves an item ball and a smashrock among its objects —
    # exactly the block the splicer used to stop reading early. The new ball must
    # land after the real last object_event, not mid-list where it would steal a
    # const, and it must read back at the coordinates it was given.
    res, got, defined = run_into(
        "BurnedTower1F",
        ball("BURNED_TOWER_1F", y="5", x="6", item="MAX_REVIVE", quantity="1"),
        "itemball", "MAX_REVIVE")
    check("an item ball reads back with its item, quantity and coords",
          bool(got) and got[0].qty == "1" and (got[0].y, got[0].x) == (5, 6),
          str([(p.what, p.qty, p.y, p.x) for p in got]))
    check("its flag is a fresh EVENT_ the flag file now defines", defined)
    check("it writes two files — the map and the flag file",
          sorted(e.path for e in res.edits)
          == ["constants/event_flags.asm", "maps/BurnedTower1F.asm"])

    res2, got2, defined2 = run_into(
        "BeautifulBeach",
        hidden("BEAUTIFUL_BEACH", y="7", x="8", item="NUGGET"),
        "hidden", "NUGGET")
    check("a hidden item reads back inline, BGEVENT_ITEM + what at its tile",
          bool(got2) and (got2[0].y, got2[0].x) == (7, 8),
          str([(p.what, p.y, p.x) for p in got2]))
    check("its flag is a fresh EVENT_..._HIDDEN_ the file defines", defined2)


# Every ball macro that expands to an OBJECTTYPE_ITEMBALL object. The reader now
# expands each of these to the object_event it assembles to, so it sees a ball
# whether the source spells it long or reaches for one of these shorthands; this
# tuple is the oracle the census counts the raw source with, independent of it.
_BALL_SHORTHANDS = ("itemball_event", "keyitemball_event", "tmhmball_event")


def _raw_item_balls(text: str) -> tuple[int, int]:
    """Balls actually in a map's source: (long form, shorthand). The long form is
    what the reader reads; the shorthand is what it drops. This counts the source
    TEXT, not the reader, so it can catch what the reader silently omits."""
    longform = len(re.findall(r"^\s*object_event\b.*OBJECTTYPE_ITEMBALL", text, re.M))
    shorthand = sum(len(re.findall(rf"^\s*{m}\b", text, re.M))
                    for m in _BALL_SHORTHANDS)
    return longform, shorthand


def test_reader_sees_every_item_ball() -> None:
    """The reader surfaces every item ball that exists — long form and shorthand
    alike. It was blind to the `itemball_event` shorthand the tree overwhelmingly
    prefers until the parser learned to expand it (Phase 10); no earlier test
    caught the gap, because the fixtures write balls long (the form the reader
    read) and the real-tree assertions took their expected counts FROM the
    reader, so a dropped ball moved no number anyone checked. This cross-check
    counts the raw source, independent of the reader, so it stays honest whether
    the reader over- or under-counts."""
    root = Path.home() / "code/ricccec/polishedcrystal"
    if not (root / "data/maps/maps.asm").exists():
        print("\n(no polishedcrystal checkout — skipping the item-ball census)")
        return
    print("\nthe reader sees every item ball the source spells out")
    r = hackmount.mount(root).reads

    reader_total = longform_total = shorthand_total = maps_with_gap = 0
    for name in r.maps():
        src = root / "maps" / f"{name}.asm"
        if not src.exists():
            continue
        longform, shorthand = _raw_item_balls(src.read_text())
        seen = sum(1 for p in r.tables(name).props if p.kind == "itemball")
        reader_total += seen
        longform_total += longform
        shorthand_total += shorthand
        if seen != longform + shorthand:
            maps_with_gap += 1

    # The census: the reader must surface exactly the balls the raw source has,
    # long and shorthand together. Equality catches a drop and an over-count
    # alike; the per-map tally localises either to the map it happened on. The
    # shorthand count is the bulk of the tree, so this is mostly a test that the
    # parser's expansion (`hacks/polished/shorthand`) fires on every map.
    check("every item ball is surfaced, shorthand included",
          reader_total == longform_total + shorthand_total,
          f"reader {reader_total} vs source {longform_total} long "
          f"+ {shorthand_total} shorthand")
    check("and no single map hides one",
          maps_with_gap == 0, f"{maps_with_gap} maps disagree")


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
    # Eleven long-form objects, plus two `pokemon_event` and one `fruittree_event`
    # the reader was blind to before Phase 10 — fourteen objects, all on the
    # Objects tab. Thirteen are people: three `jumptextfaceplayer` command
    # objects, eight scripted NPCs and the two wild mons a `pokemon_event` reads
    # as. The fruit tree is not a person — it reads as a prop off its `fruittree`
    # command, filed with the balls, the same reading a long `object_event` with
    # that command would get.
    check("Azalea's fourteen objects and eight warps — thirteen people, one tree",
          len(t.npcs) == 13 and len(t.warps) == 8,
          f"{len(t.npcs)} npcs, {len(t.warps)} warps")
    check("the fruit tree reads as a prop, named by the tree it is",
          any(p.kind == "fruittree" and p.what == "FRUITTREE_AZALEA_TOWN"
              for p in t.props))
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
        test_floor_shorthands_read_as_props()
        test_the_catalog_and_geometry(root)
        test_wild_forms_and_roof(root)
        test_the_session_sees_no_name(root)
        test_deletion_splices_the_head(root)
        test_polished_offers_the_item_adders(root)
    test_real_tree()
    test_real_item_adders()
    test_reader_sees_every_item_ball()

    print()
    if CLOSED_GAP:
        print(f"{CLOSED_GAP} known gap(s) now hold (XPASS) — promote to check()")
    if KNOWN_GAP:
        print(f"{KNOWN_GAP} known gap(s) still open (xfail), not counted as failures")
    if FAILED:
        print(f"{FAILED} check(s) FAILED")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
