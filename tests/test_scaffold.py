#!/usr/bin/env python3
"""Tests for the content scaffolds: NPCs, trainers, item balls, hidden items,
signs, and the trainer-party and wild-data editors underneath them.

The unit tests are hermetic. The ones that matter most aren't: they parse every
real trainer group and every real wild table, because these files are read
*positionally* by the engine — a party is found by counting, and a wild block by
its fixed stride — so a parser that miscounts by one is a parser that silently
rewrites somebody else's trainer.

    python tests/test_scaffold.py
"""

from __future__ import annotations

import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pokeprism_devtools.hacks.prism import (  # noqa: E402
    consts, eventheader as eh, landmarks, trainercite as tc, trainerparty as tp,
    wilddata as wd)
from pokeprism_devtools.shared.edits import StaleEdit, apply_edits  # noqa: E402
from pokeprism_devtools.wiring import (  # noqa: E402
    props as pk, removal as rm, scaffold as sc)

_failures = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global _failures
    mark = "OK  " if cond else "FAIL"
    print(f"  [{mark}] {label}{(': ' + detail) if detail else ''}")
    if not cond:
        _failures += 1


def raises(label: str, fn, *, wanted: str = "") -> None:
    """Check that `fn` refuses, and that it says why."""
    try:
        fn()
        check(label, False, "no error raised")
    except (sc.ScaffoldError, tp.TrainerPartyError, wd.WildDataError,
            rm.RemovalError, StaleEdit) as e:
        check(label, wanted in str(e), str(e) if wanted not in str(e) else "")


# --------------------------------------------------------------------------- #
# fixture                                                                     #
# --------------------------------------------------------------------------- #

def _fixture(tmp: Path) -> Path:
    root = tmp / "repo"
    for d in ("constants", "maps", "trainers/groups", "data/wild"):
        (root / d).mkdir(parents=True)

    (root / "constants.asm").write_text(
        '\tconst_def\n\tconst EVENT_0\n\tINCLUDE "constants/event_flags.asm"\n'
    )
    (root / "constants/event_flags.asm").write_text(
        "\tconst EVENT_1\n\tconst skip\n\tconst skip\n\tconst skip\n\tconst skip\n"
    )
    (root / "constants/pokemon_constants.asm").write_text(
        "\tconst_def\n\tconst PIDGEY\n\tconst SENTRET\n\tconst ZUBAT\n"
    )
    # The TMs are not `const`s: `add_tm HEADBUTT` pastes the name together at
    # assembly time (macros/basestats.asm), so `TM_HEADBUTT` appears nowhere in the
    # source and a constant-scanner cannot find it. The fixture has to have that
    # shape or the thing it is testing isn't here.
    (root / "constants/item_constants.asm").write_text(
        "\tconst_def\n\tconst ULTRA_BALL\n\tconst RARE_CANDY\n\tconst ORAN_BERRY\n"
        "\tconst POTION\n\tconst TM_CASE\n"
        "\tadd_tm HEADBUTT\n\tadd_tm HAIL\n\tadd_hm CUT\n"
    )
    (root / "constants/move_constants.asm").write_text(
        "\tconst_def\n\tconst TACKLE\n\tconst GROWL\n\tconst NO_MOVE\n"
    )
    (root / "constants/landmark_constants.asm").write_text(
        "\tconst_def\n\tregion_def JOHTO\n\tconst LM_A\n"
        "\tregion_def NALJO\n\tconst LM_B\n"
    )
    (root / "constants/map_constants.asm").write_text(
        "\tconst_def\n\tconst TOWN\n\tconst ROUTE\n"
        "\nconst_value = 1\n\tconst RED_APRICORN_TREE_1\n\tconst BLUE_APRICORN_TREE_1\n"
    )

    # sprites: ids, movement data, palettes — the enums an Object is checked against
    (root / "constants/sprite_constants.asm").write_text(
        "\tconst_def\n"
        "\tconst SPRITE_SAGE\n\tconst SPRITE_YOUNGSTER\n\tconst SPRITE_POKE_BALL\n"
        "\tconst SPRITE_FRUIT_TREE\n\tconst SPRITE_ROCK\n\tconst SPRITE_BOULDER\n"
        "SPRITE_POKEMON EQU const_value\nSPRITE_VARS EQU const_value + 10\n"
        "\n\tconst_def\n\tconst SPRITE_ANIM_FRAMESET_DECOY\n"
        "\n\tconst_def\n"
        "\tconst SPRITEMOVEDATA_STANDING_DOWN\n\tconst SPRITEMOVEDATA_ITEM_TREE\n"
        "\tconst SPRITEMOVEDATA_WALK_UP_DOWN\n"
        "\tconst SPRITEMOVEDATA_SMASHABLE_ROCK\n"
        "\tconst SPRITEMOVEDATA_STRENGTH_BOULDER\n"
        "\n\tconst_def\n\tconst PAL_OW_RED\n\tconst PAL_OW_BLUE\n"
        "\tconst PAL_OW_YELLOW\n\tconst PAL_OW_SILVER\n\tconst PAL_OW_BROWN\n"
    )
    (root / "maps/map_headers.asm").write_text(
        "\tmap_header TownA, TS, TOWN, LM_A, MU, 0, PAL, F0\n"
        "\tmap_header RouteB, TS, ROUTE, LM_B, MU, 0, PAL, F0\n"
    )
    (root / "maps/second_map_headers.asm").write_text(
        "\tmap_header_2 TownA, TOWN_A, $f, 0\n"
        "\tmap_header_2 RouteB, ROUTE_B, $f, 0\n"
    )
    (root / "maps/TownA.asm").write_text(
        "TownAGreeter:\n\tctxt \"Hello.\"\n\tdone\n\n"
        "TownA_MapEventHeader:: db 0, 0\n\n"
        ".Warps\n\tdb 0\n\n.CoordEvents\n\tdb 0\n\n"
        ".BGEvents\n\tdb 0\n\n.ObjectEvents\n\tdb 0\n"
    )

    # one trainer class, with the pointer table that binds it
    (root / "constants/trainer_constants.asm").write_text(
        "\tconst_def\n\ttrainerclass TRAINER_NONE\n"
        "\ttrainerclass YOUNGSTER\n\ttrainerclass SAGE\n\ttrainerclass GHOST\n"
    )
    (root / "trainers/trainer_pointers.asm").write_text(
        "TrainerGroups:\n\tdw YoungsterGroup\n\tdw NULL ;Sage\n"
    )
    (root / "trainers/groups/youngster.asm").write_text(
        'YoungsterGroup:\n\t; 1\n\tdb "Jordan@"\n\n\tdb TRAINERTYPE_NORMAL\n\n'
        "\tdb 4, PIDGEY\n\tdb -1\n\n"
        '\t; 2\n\tdb "Wilson@"\n\n\tdb TRAINERTYPE_ITEM\n\n'
        "\tdb 5, ZUBAT, ORAN_BERRY\n\tdb -1\n"
    )

    (root / "data/wild/naljo_grass.asm").write_text(
        "\twildmap ROUTE_B\n\tdb 5 percent, 5 percent, 5 percent\n"
        + "\t; morn\n" + "".join(f"\tdb {i}, PIDGEY\n" for i in range(1, 8))
        + "\t; day\n" + "".join(f"\tdb {i}, ZUBAT\n" for i in range(1, 8))
        + "\t; nite\n" + "".join(f"\tdb {i}, ZUBAT\n" for i in range(1, 8))
        + "\n\tendwildmap\n"
    )
    return root


# --------------------------------------------------------------------------- #
# trainer parties — read positionally, so counting is the whole game          #
# --------------------------------------------------------------------------- #

def test_parties(root: Path) -> None:
    print("\nparties are found by counting, so appending is the only safe edit")
    group = tp.group_for(root, "YOUNGSTER")
    check("resolved through TrainerGroups, not by name", group.label == "YoungsterGroup")
    check("two parties", group.count == 2)
    check("party 1 is 1-based", group.party(1).name == "Jordan")
    check("a TRAINERTYPE_ITEM mon keeps its held item",
          group.party(2).mons[0].item == "ORAN_BERRY")

    added = group.add_party("Testy", [tp.Mon(9, "SENTRET")], tp.NORMAL)
    check("a new party lands at the end, with the next index", added.index == 3)
    check("the existing parties keep their indices",
          [p.index for p in group.parties] == [1, 2, 3])
    check("the `; n` comment is regenerated from position",
          "\t; 3\n" in group.to_text())
    check("Jordan is untouched", group.party(1).name == "Jordan")

    raises("an empty party is refused",
           lambda: group.add_party("Empty", [], tp.NORMAL), wanted="no Pokemon")
    raises("a MOVES party must carry exactly four moves",
           lambda: group.add_party("M", [tp.Mon(5, "PIDGEY", moves=("TACKLE",))], tp.MOVES),
           wanted="exactly 4 moves")
    raises("an ITEM party must carry a held item on every mon",
           lambda: group.add_party("I", [tp.Mon(5, "PIDGEY")], tp.ITEM),
           wanted="held item")


def test_unbacked_classes(root: Path) -> None:
    print("\na class with no parties behind it cannot be battled")
    unbacked = tp.unbacked_classes(root)
    check("a `dw NULL` slot is unbacked", "SAGE" in unbacked)
    check("a class past the end of the table is unbacked", "GHOST" in unbacked)
    check("and it says the table ran out", "runs out" in unbacked.get("GHOST", ""))
    check("a real class is not", "YOUNGSTER" not in unbacked)


# --------------------------------------------------------------------------- #
# wild data — fixed stride, and the region comes from the landmark            #
# --------------------------------------------------------------------------- #

def test_wild(root: Path) -> None:
    print("\nwild blocks are fixed-size, and the region is not the caller's choice")
    check("the region comes from the map's landmark",
          landmarks.region_of_map(root, "ROUTE_B") == "naljo")

    table = wd.table_for(root, "ROUTE_B", wd.GRASS)
    check("which picks the file", table.path.name == "naljo_grass.asm")
    block = table.find("ROUTE_B")
    check("the existing block parses", block is not None and block.rates == [5, 5, 5])
    check("7 slots per time of day", all(len(block.mons[t]) == 7 for t in table.times))

    mons = {t: [wd.Encounter(3, "ZUBAT")] * 7 for t in table.times}
    table.set_block("ROUTE_B", [10, 10, 10], mons)
    check("an existing block is replaced, not duplicated", len(table.blocks) == 1)
    check("with the new rate", table.find("ROUTE_B").rates == [10, 10, 10])

    table.set_block("TOWN_A", [4, 4, 4], mons)
    check("a new block appends before endwildmap", len(table.blocks) == 2)
    check("and stays inside the table",
          table.to_text().index("wildmap TOWN_A") < table.to_text().index("endwildmap"))

    raises("a short block is refused — it would shift every map below it",
           lambda: table.set_block("TOWN_A", [4, 4, 4],
                                   {t: [wd.Encounter(3, "ZUBAT")] for t in table.times}),
           wanted="fixed-size")

    print("\n  a bare `db 3` rate is 3/255, not 3%")
    raw = wd.WildBlock("X", [3, 3, 3], raw_rates=True)
    pct = wd.WildBlock("X", [3, 3, 3], raw_rates=False)
    check("bare bytes mean themselves", raw.rate_bytes == [3, 3, 3])
    check("`3 percent` scales by 255/100", pct.rate_bytes == [7, 7, 7])


# --------------------------------------------------------------------------- #
# the scaffolds                                                               #
# --------------------------------------------------------------------------- #

def _reset(root: Path, saved: dict[str, str]) -> None:
    for rel, text in saved.items():
        (root / rel).write_text(text)


def _snapshot(root: Path) -> dict[str, str]:
    rels = ["maps/TownA.asm", "constants/event_flags.asm", "trainers/groups/youngster.asm"]
    return {rel: (root / rel).read_text() for rel in rels}


def test_npc(root: Path) -> None:
    print("\nan NPC: a text block above the header, a person_event below it")
    saved = _snapshot(root)
    s = sc.add_npc(root, "TOWN_A",
                   sc.Object("SPRITE_YOUNGSTER", 5, 6, palette="PAL_OW_BLUE"),
                   pages=[["Hi there,", "traveller."], ["Mind the", "grass."]])
    apply_edits(root, s.edits, dry_run=False)
    text = (root / "maps/TownA.asm").read_text()

    check("the label is <Map>_NPC_<n>", s.label == "TownA_NPC_1")
    check("dialogue opens with ctxt", '\tctxt "Hi there,"' in text)
    check("the second row is `line`", '\tline "traveller."' in text)
    check("a new textbox is `para`", '\tpara "Mind the"' in text)
    check("a blank line separates the para from the box above it",
          '\tline "traveller."\n\n\tpara "Mind the"' in text)
    check("and it ends with done", text.count("\tdone") == 2)
    check("the text block sits above the event header",
          text.index("TownA_NPC_1:") < text.index("TownA_MapEventHeader::"))
    check("the person_event points at it, facing the player",
          "PERSONTYPE_TEXTFP, 0, TownA_NPC_1, -1" in text)
    check("the object count went 0 -> 1",
          eh.parse_map(root / "maps/TownA.asm").lists[eh.ListKind.OBJECT_EVENTS].declared_count == 1)
    check("no flag was allocated for an always-there NPC", s.flag is None)
    _reset(root, saved)


def test_npc_below_a_header_first_map(root: Path) -> None:
    print("\na header-first map keeps its object list on top, its scripts below")
    saved = _snapshot(root)
    # RouteB laid out the way MtEmberWest and every studio-written map are: the
    # event header up top, then a scripts section for the content to live in.
    (root / "maps/RouteB.asm").write_text(
        "RouteB_MapScriptHeader:\n\tdb 0\n\tdb 0\n\n"
        "; ***** Event header *****\n"
        "RouteB_MapEventHeader:: db 0, 0\n\n"
        ".Warps\n\tdb 0\n\n.CoordEvents\n\tdb 0\n\n"
        ".BGEvents\n\tdb 0\n\n.ObjectEvents\n\tdb 0\n\n"
        "; ***** Map callbacks *****\n\n; ***** Scripts *****\n"
    )
    s = sc.add_npc(root, "ROUTE_B", sc.Object("SPRITE_YOUNGSTER", 5, 6),
                   pages=[["Hi."]])
    apply_edits(root, s.edits, dry_run=False)
    text = (root / "maps/RouteB.asm").read_text()

    check("the person_event joined the object list up top",
          text.index("PERSONTYPE_TEXTFP, 0, RouteB_NPC_1, -1")
          < text.index("; ***** Scripts *****"))
    check("but the text block itself went below the event header",
          text.index("RouteB_MapEventHeader::") < text.index("RouteB_NPC_1:"))
    check("under the scripts section, where the content half lives",
          text.index("; ***** Scripts *****") < text.index("RouteB_NPC_1:"))
    check("the object count still went 0 -> 1",
          eh.parse_map(root / "maps/RouteB.asm")
            .lists[eh.ListKind.OBJECT_EVENTS].declared_count == 1)
    _reset(root, saved)
    (root / "maps/RouteB.asm").unlink(missing_ok=True)


def test_trainer(root: Path) -> None:
    print("\na trainer: flag + party + macro + three texts, or nothing at all")
    saved = _snapshot(root)
    s = sc.add_trainer(root, "TOWN_A",
                       sc.Object("SPRITE_YOUNGSTER", 7, 8, behind_bg=True),
                       cls="YOUNGSTER",
                       new_party=("Testy", [tp.Mon(9, "SENTRET")], tp.NORMAL),
                       seen=[["You!"]], defeated=[["Ugh."]], after=[["Nice."]], sight=2)
    check("it touches three files", len(s.changes) == 3)
    apply_edits(root, s.edits, dry_run=False)

    text = (root / "maps/TownA.asm").read_text()
    check("the party was appended, not inserted", s.party == 3)
    check("the flag reused a `const skip` slot",
          "\tconst EVENT_TOWN_A_TRAINER_1\n" in (root / "constants/event_flags.asm").read_text())
    check("the macro cites flag, class and party",
          f"\ttrainer {s.flag}, YOUNGSTER, 3, .before_battle_text, .defeated_text" in text)
    check("the talk-again text falls through under the macro",
          text.index('ctxt "Nice."') < text.index("\n.before_battle_text\n"))
    check("both other texts are local labels",
          "\n.before_battle_text\n" in text and "\n.defeated_text\n" in text)
    check("behind_bg becomes the OAM-priority bit", "8 + PAL_OW_RED" in text)
    check("the person_event carries the sight radius",
          f"PERSONTYPE_GENERICTRAINER, 2, {s.label}, -1" in text)

    raises("a class whose TrainerGroups slot is NULL is refused",
           lambda: sc.add_trainer(root, "TOWN_A", sc.Object("SPRITE_SAGE", 1, 1),
                                  cls="SAGE", party=1,
                                  seen=[["a"]], defeated=[["b"]], after=[["c"]]),
           wanted="NULL")
    raises("a party index past the end is refused",
           lambda: sc.add_trainer(root, "TOWN_A", sc.Object("SPRITE_YOUNGSTER", 1, 1),
                                  cls="YOUNGSTER", party=99,
                                  seen=[["a"]], defeated=[["b"]], after=[["c"]]),
           wanted="doesn't exist")
    _reset(root, saved)


def test_items(root: Path) -> None:
    print("\nitem balls and hidden items")
    saved = _snapshot(root)
    s = pk.add_itemball(root, "TOWN_A", 3, 4, "ULTRA_BALL")
    apply_edits(root, s.edits, dry_run=False)
    text = (root / "maps/TownA.asm").read_text()
    check("the flag is named for map and item",
          s.flag == "EVENT_TOWN_A_ITEM_ULTRA_BALL")
    check("the item const sits where a script pointer would",
          f"PERSONTYPE_ITEMBALL, 1, ULTRA_BALL, {s.flag}" in text)

    h = pk.add_hidden_item(root, "TOWN_A", 9, 10, "RARE_CANDY")
    apply_edits(root, h.edits, dry_run=False)
    text = (root / "maps/TownA.asm").read_text()
    check("a hidden item gets a flag+item record",
          f"{h.label}:\n\tdw {h.flag}\n\tdb RARE_CANDY" in text)
    check("and a SIGNPOST_ITEM pointing at it",
          f"signpost 9, 10, SIGNPOST_ITEM, {h.label}" in text)
    check("which lands in BGEvents, count 0 -> 1",
          eh.parse_map(root / "maps/TownA.asm").lists[eh.ListKind.BG_EVENTS].declared_count == 1)
    _reset(root, saved)


def test_the_other_two_pickups(root: Path) -> None:
    print("\nTM balls and fruit trees: the same two bytes, read differently")
    saved = _snapshot(root)

    # An item ball's 11th argument is the quantity. A TM ball's is the *item* —
    # the engine reads one byte out of that slot (engine/events.asm:529). Put a TM
    # in an item ball and it assembles, and hands you `0` of it.
    s = pk.add_itemball(root, "TOWN_A", 3, 4, "ULTRA_BALL", quantity=6)
    apply_edits(root, s.edits, dry_run=False)
    check("an item ball's quantity goes in the sight slot",
          f"PERSONTYPE_ITEMBALL, 6, ULTRA_BALL, {s.flag}"
          in (root / "maps/TownA.asm").read_text())

    t = pk.add_tmhm_ball(root, "TOWN_A", 5, 5, "TM_HEADBUTT")
    apply_edits(root, t.edits, dry_run=False)
    check("a TM ball's item goes there instead, and the pointer slot is dead",
          f"PERSONTYPE_TMHMBALL, TM_HEADBUTT, 0, {t.flag}"
          in (root / "maps/TownA.asm").read_text())

    check("a TM is not in the item enum — the macro builds the name",
          "TM_HEADBUTT" not in consts.names(root, consts.ITEMS)
          and "TM_HEADBUTT" in pk.tmhms(root))
    check("so a Potion in a TM ball is refused, though it would assemble",
          _raises(lambda: pk.add_tmhm_ball(root, "TOWN_A", 6, 6, "POTION"),
                  sc.ScaffoldError))

    f = pk.add_fruit_tree(root, "TOWN_A", 7, 7, "RED_APRICORN_TREE_1")
    apply_edits(root, f.edits, dry_run=False)
    check("a tree's id goes in the pointer slot, and it never gets a flag",
          "PERSONTYPE_FRUITTREE, 0, RED_APRICORN_TREE_1, -1"
          in (root / "maps/TownA.asm").read_text())
    check("which is why nothing was written to the flag enum",
          f.flag is None and len(f.edits) == 1)

    _reset(root, saved)


def test_a_rock_is_not_a_person(root: Path) -> None:
    """A boulder has no dialogue, no flag, no script and no movement to choose.

    It is a `person_event` because the engine has one list of things that stand on
    tiles — not because it is a person. Everything on the line but the position and
    the colour was decided by whoever wrote `strengthboulder`, and the studio used
    to offer all of it: a sprite box, a movement box, an event flag, and an empty
    field asking what the boulder says.
    """
    print("\na rock and a boulder are objects, not people")
    saved = _snapshot(root)

    b = pk.add_prop(root, "TOWN_A", 3, 4, "boulder")
    apply_edits(root, b.edits, dry_run=False)
    check("a boulder is the one line every boulder in the repo is",
          "person_event SPRITE_BOULDER, 3, 4, SPRITEMOVEDATA_STRENGTH_BOULDER, "
          "0, 0, -1, -1, PAL_OW_BROWN, PERSONTYPE_JUMPSTD, 0, strengthboulder, -1"
          in (root / "maps/TownA.asm").read_text())
    check("and it allocates no flag: a rock you had smashed would not come back",
          b.flag is None and len(b.edits) == 1)

    r = pk.add_prop(root, "TOWN_A", 5, 6, "rock", palette="PAL_OW_BLUE")
    apply_edits(root, r.edits, dry_run=False)
    check("a rock is the same line with the other std script",
          "person_event SPRITE_ROCK, 5, 6, SPRITEMOVEDATA_SMASHABLE_ROCK, "
          "0, 0, -1, -1, PAL_OW_BLUE, PERSONTYPE_JUMPSTD, 0, smashrock, -1"
          in (root / "maps/TownA.asm").read_text())

    hdr = eh.parse_map(root / "maps/TownA.asm")
    rock = hdr.object_events[-1]
    boulder = hdr.object_events[-2]
    check("and the pair of them are recognisable as props afterwards",
          (boulder.prop, rock.prop) == ("boulder", "rock"),
          f"{boulder.prop}, {rock.prop}")

    # The three-way test, and the reason it is not the sprite alone: five rocks in
    # pokeprism are PERSONTYPE_SCRIPT and run a script somebody wrote. A studio
    # that read the sprite would offer to overwrite it with `smashrock`.
    scripted = eh.Entry(
        macro="person_event", lineno=0, raw="",
        args=["SPRITE_ROCK", "1", "1", "SPRITEMOVEDATA_ITEM_TREE", "0", "0",
              "-1", "-1", "PAL_OW_BLUE", "PERSONTYPE_SCRIPT", "0",
              "ExplodingRock", "-1"])
    check("a SPRITE_ROCK with a script of its own is NOT a prop — it is a person",
          scripted.prop is None)

    # Moving one rewrites the two arguments that are yours, and not one byte more.
    was = (root / "maps/TownA.asm").read_text()
    c = pk.edit_prop(root, "TOWN_A", len(hdr.object_events) - 1, 9, 9, "rock",
                     palette="PAL_OW_BLUE")
    apply_edits(root, c.changes, dry_run=False)
    now = (root / "maps/TownA.asm").read_text()
    check("moving a rock moves the rock and nothing else",
          now == was.replace("SPRITE_ROCK, 5, 6,", "SPRITE_ROCK, 9, 9,"),
          "something other than the coordinates changed")

    check("and editing a thing that is not a rock is refused",
          _raises(lambda: pk.edit_prop(root, "TOWN_A", 0, 1, 1, "rock",
                                       palette="PAL_OW_RED"), pk.EditError))

    _reset(root, saved)


def _raises(fn, exc) -> bool:
    try:
        fn()
    except exc:
        return True
    return False


def test_signpost(root: Path) -> None:
    print("\na sign: text if it reads from any side, a script if it reads from one")
    saved = _snapshot(root)

    s = sc.add_signpost(root, "TOWN_A", 4, 11,
                        pages=[["Town A", "Pop. 12"], ["Mind the", "grass."]])
    apply_edits(root, s.edits, dry_run=False)
    text = (root / "maps/TownA.asm").read_text()

    check("the label is named for the map", s.label == "TownASign")
    check("a plain sign is SIGNPOST_TEXT, which jumps straight into text",
          f"signpost 4, 11, SIGNPOST_TEXT, {s.label}" in text)
    check("so the pointer is the text block itself, with no script above it",
          f"{s.label}:\n\tctxt \"Town A\"" in text)
    check("a sign is always there, so no flag", s.flag is None)
    check("it lands in BGEvents, count 0 -> 1",
          eh.parse_map(root / "maps/TownA.asm").lists[eh.ListKind.BG_EVENTS].declared_count == 1)

    # The whole reason this function has two shapes. SIGNPOST_UP/DOWN/LEFT/RIGHT
    # all fall through to `.read` in engine/events.asm, which *calls* the pointer
    # as a script. Point one at a bare text block and the engine executes the
    # prose as bytecode.
    f = sc.add_signpost(root, "TOWN_A", 6, 2, pages=[["Vending", "machine."]],
                        facing="up")
    apply_edits(root, f.edits, dry_run=False)
    text = (root / "maps/TownA.asm").read_text()

    check("a facing sign is SIGNPOST_UP", f"signpost 6, 2, SIGNPOST_UP, {f.label}" in text)
    check("and its pointer is a script, because .read calls it",
          f"{f.label}:\n\tjumptext .text\n" in text)
    check("with the text hanging off it as a local label",
          '\n.text\n\tctxt "Vending"' in text)
    check("the second sign gets a distinct label", f.label == "TownASign2")
    check("both are in BGEvents now",
          eh.parse_map(root / "maps/TownA.asm").lists[eh.ListKind.BG_EVENTS].declared_count == 2)

    raises("a direction the engine has no signpost for",
           lambda: sc.add_signpost(root, "TOWN_A", 1, 1, [["x"]], facing="sideways"),
           wanted="up, down, left, right")
    raises("a sign that says nothing",
           lambda: sc.add_signpost(root, "TOWN_A", 1, 1, []), wanted="at least one line")
    _reset(root, saved)


def test_rejects_unknown_consts(root: Path) -> None:
    print("\nan unknown constant is caught here, not by rgblink five minutes later")
    npc = lambda **kw: sc.add_npc(root, "TOWN_A", sc.Object(**kw), pages=[["hi"]])
    raises("a sprite that doesn't exist",
           lambda: npc(sprite="SPRITE_YOUNGSTR", y=1, x=1), wanted="Did you mean SPRITE_YOUNGSTER")
    raises("a movement that doesn't exist",
           lambda: npc(sprite="SPRITE_SAGE", y=1, x=1, movement="SPRITEMOVEDATA_NOPE"),
           wanted="not a movement")
    raises("a palette that doesn't exist",
           lambda: npc(sprite="SPRITE_SAGE", y=1, x=1, palette="PAL_OW_PINK"),
           wanted="not a palette")
    raises("an item that doesn't exist",
           lambda: pk.add_itemball(root, "TOWN_A", 1, 1, "ULTRABALL"),
           wanted="Did you mean ULTRA_BALL")
    raises("a species this fork doesn't have",
           lambda: sc.add_trainer(root, "TOWN_A", sc.Object("SPRITE_SAGE", 1, 1),
                                  cls="YOUNGSTER",
                                  new_party=("T", [tp.Mon(5, "RATTATA")], tp.NORMAL),
                                  seen=[["a"]], defeated=[["b"]], after=[["c"]]),
           wanted="not a species")

    print("\n  and nothing is written when it is")
    before = _snapshot(root)
    try:
        pk.add_itemball(root, "TOWN_A", 1, 1, "NOPE_BALL")
    except sc.ScaffoldError:
        pass
    check("the map is untouched", _snapshot(root) == before)


def test_stale_edit(root: Path) -> None:
    print("\nan Edit carries the whole file, so a stale one must not be applied")
    saved = _snapshot(root)

    a = pk.add_itemball(root, "TOWN_A", 3, 4, "ULTRA_BALL")
    b = pk.add_itemball(root, "TOWN_A", 5, 6, "RARE_CANDY")   # built from the SAME text
    apply_edits(root, a.edits, dry_run=False)

    check("both edits allocated the same flag slot — which is the danger",
          a.flag != b.flag and
          _snapshot(root)["constants/event_flags.asm"] != saved["constants/event_flags.asm"])
    raises("applying the second overwrites the first, so it is refused",
           lambda: apply_edits(root, b.edits, dry_run=False),
           wanted="has changed since this edit was computed")

    _reset(root, saved)
    print("  (build an edit, apply it, then build the next)")


# --------------------------------------------------------------------------- #
# removal — the safe half                                                     #
# --------------------------------------------------------------------------- #

def test_removal(root: Path) -> None:
    print("\nadding and then removing leaves the file exactly as it was")
    saved = _snapshot(root)

    def add_and_remove(what, add, **how):
        s = add()
        apply_edits(root, s.edits, dry_run=False)
        r = rm.remove(root, "TOWN_A", **(how or {"label": s.label}))
        apply_edits(root, r.edits, dry_run=False)
        check(f"{what}: back to byte-for-byte identical", _snapshot(root) == saved)
        return s, r

    npc, _ = add_and_remove(
        "NPC", lambda: sc.add_npc(root, "TOWN_A", sc.Object("SPRITE_YOUNGSTER", 5, 6),
                                  pages=[["Hi."]]))

    _, r = add_and_remove(
        "trainer",
        lambda: sc.add_trainer(root, "TOWN_A", sc.Object("SPRITE_YOUNGSTER", 7, 8),
                               cls="YOUNGSTER", party=1,
                               seen=[["You!"]], defeated=[["Ugh."]], after=[["GG."]]))
    check("the trainer's flag is freed back to `const skip`",
          r.freed_flag == "EVENT_TOWN_A_TRAINER_1")
    check("even though a person_event's own flag arg says -1 — it lives in the "
          "`trainer` macro", r.freed_flag is not None)

    ball, r = add_and_remove(
        "item ball", lambda: pk.add_itemball(root, "TOWN_A", 3, 4, "ULTRA_BALL"),
        flag="EVENT_TOWN_A_ITEM_ULTRA_BALL")
    check("an item ball has no label, so it is found by its flag",
          r.freed_flag == "EVENT_TOWN_A_ITEM_ULTRA_BALL")

    _, r = add_and_remove(
        "hidden item", lambda: pk.add_hidden_item(root, "TOWN_A", 9, 10, "RARE_CANDY"),
        at=(9, 10))
    check("a hidden item's flag lives in the record, not the signpost",
          r.freed_flag == "EVENT_TOWN_A_HIDDENITEM_RARE_CANDY")

    _reset(root, saved)


def test_removal_leaves_what_it_must(root: Path) -> None:
    print("\nremoval refuses to free anything somebody else is still using")
    saved = _snapshot(root)

    s = sc.add_trainer(root, "TOWN_A", sc.Object("SPRITE_YOUNGSTER", 7, 8),
                       cls="YOUNGSTER",
                       new_party=("Testy", [tp.Mon(9, "SENTRET")], tp.NORMAL),
                       seen=[["You!"]], defeated=[["Ugh."]], after=[["GG."]])
    apply_edits(root, s.edits, dry_run=False)

    r = rm.remove(root, "TOWN_A", label=s.label)
    apply_edits(root, r.edits, dry_run=False)
    check("the party is left in place — deleting it would renumber the group",
          tp.group_for(root, "YOUNGSTER").find("Testy") is not None)
    check("and the caller is told so",
          any("orphan" in w for w in r.warnings), str(r.warnings))
    _reset(root, saved)

    # A flag another map reads must survive, or the allocator would hand it out
    # again while that map still gates on it.
    shared = "EVENT_TOWN_A_GUARD"
    (root / "constants/event_flags.asm").write_text(
        (root / "constants/event_flags.asm").read_text().replace(
            "\tconst skip\n", f"\tconst {shared}\n", 1))
    (root / "maps/RouteB.asm").write_text(
        "RouteB_MapEventHeader:: db 0, 0\n\n.Warps\n\tdb 0\n\n.CoordEvents\n\tdb 0\n\n"
        ".BGEvents\n\tdb 0\n\n.ObjectEvents\n\tdb 1\n"
        f"\tperson_event SPRITE_SAGE, 1, 1, SPRITEMOVEDATA_STANDING_DOWN, 0, 0, -1, -1, "
        f"PAL_OW_RED, PERSONTYPE_TEXT, 0, RouteBSign, {shared}\n"
    )
    s = sc.add_npc(root, "TOWN_A", sc.Object("SPRITE_YOUNGSTER", 5, 6),
                   pages=[["Hi."]], flag=shared)
    apply_edits(root, s.edits, dry_run=False)

    r = rm.remove(root, "TOWN_A", label=s.label)
    check("a flag another map still gates on is left allocated", r.freed_flag is None)
    check("and the caller is told why",
          any("still gates something else" in w for w in r.warnings), str(r.warnings))

    _reset(root, saved)
    (root / "maps/RouteB.asm").unlink(missing_ok=True)


# --------------------------------------------------------------------------- #
# the real repo                                                               #
# --------------------------------------------------------------------------- #

def _real_repo() -> Path | None:
    for cand in (Path.home() / "code/ricccec/pokeprism",
                 Path(__file__).resolve().parent.parent.parent / "pokeprism"):
        if (cand / "maps/map_headers.asm").exists():
            return cand
    return None


def test_real_parsers(tmp: Path) -> None:
    root = _real_repo()
    if root is None:
        print("\n(no pokeprism checkout found — skipping the real-repo checks)")
        return

    print("\nevery real trainer group, read positionally")
    groups = tp.load(root)
    parties = sum(g.count for g in groups.values())
    check(f"{len(groups)} groups, {parties} parties", parties > 300)
    check("every group file round-trips byte-for-byte",
          all(g.to_text() == g.path.read_text() for g in groups.values()))

    misnumbered = [
        f"{g.label}#{p.index}"
        for g in groups.values() for p in g.parties
        if (m := re.match(r"^;\s*(\d+)$", g.lines[p.start - 1].strip())) and int(m.group(1)) != p.index
    ]
    check("every `; n` comment agrees with the party's real position",
          not misnumbered, ", ".join(misnumbered[:3]))

    cited = 0
    for f in sorted((root / "maps").glob("*.asm")):
        for line in f.read_text().split("\n"):
            m = re.match(r"^\s*trainer\s+\w+\s*,\s*(\w+)\s*,\s*(\w+)\s*,", line)
            if not m:
                continue
            cited += 1
            group = groups.get(tp.class_groups(root).get(m.group(1)) or "")
            if group is None or not m.group(2).isdigit():
                continue
            if not 1 <= int(m.group(2)) <= group.count:
                check(f"{f.name}: {m.group(1)} #{m.group(2)}", False, "out of range")
    check(f"all {cited} trainer citations in the repo resolve to a real party", cited > 250)

    print("\nevery real wild table, read at its fixed stride")
    blocks = 0
    for path in sorted((root / "data/wild").glob("*.asm")):
        if path.stem == "fish":
            continue
        region, _, kind = path.stem.rpartition("_")
        table = wd.load(root, region, kind)
        if table.to_text() != path.read_text():
            check(f"{path.name} round-trips", False)
        blocks += len(table.blocks)
    check(f"{blocks} wildmap blocks parse and round-trip byte-for-byte", blocks > 150)


def test_real_scaffold(tmp: Path) -> None:
    """Scaffold real content into a real map, and check the linter finds nothing
    new — the tool built to find broken maps is the one that should judge this."""
    root = _real_repo()
    if root is None:
        return

    from collections import Counter
    from pokeprism_devtools.maplint import (
        context, rules_content, rules_geometry, rules_objects, rules_sprites,
    )

    def lint(at: Path) -> Counter:
        ctx = context.LintContext(at)
        found = []
        for mod in (rules_geometry, rules_objects, rules_sprites, rules_content):
            for rule in mod.ALL:
                found += rule(ctx)
        return Counter((d.code, d.path) for d in found)

    print("\nscaffolding into a real map, judged by the linter")
    scratch = tmp / "pokeprism"
    shutil.copytree(root, scratch, symlinks=True,
                    ignore=shutil.ignore_patterns(".git", "*.o", "*.gbc", "*.sym", "*.map"))
    before = lint(scratch)

    MAP = "CASTRO_FOREST"
    # Built and applied one at a time. An Edit carries the whole file, so five of
    # them computed against the same starting text would overwrite each other —
    # StaleEdit enforces this now, but the order still has to be right.
    for build in (
        lambda: sc.add_npc(scratch, MAP,
                           sc.Object("SPRITE_YOUNGSTER", 12, 20, palette="PAL_OW_BLUE"),
                           pages=[["Hi! I'm new", "around here."]]),
        lambda: sc.add_trainer(scratch, MAP,
                               sc.Object("SPRITE_SAGE", 14, 22, palette="PAL_OW_BLUE",
                                         behind_bg=True),
                               cls="SAGE", party=6, sight=3, seen=[["You there!"]],
                               defeated=[["I yield."]], after=[["Well fought."]]),
        lambda: sc.add_trainer(scratch, MAP, sc.Object("SPRITE_YOUNGSTER", 16, 8),
                               cls="YOUNGSTER",
                               new_party=("Testy", [tp.Mon(12, "SENTRET")], tp.NORMAL),
                               seen=[["Let's go!"]], defeated=[["Aw, man."]],
                               after=[["Good game."]]),
        lambda: pk.add_itemball(scratch, MAP, 20, 30, "ULTRA_BALL"),
        lambda: pk.add_hidden_item(scratch, MAP, 5, 6, "RARE_CANDY"),
    ):
        apply_edits(scratch, build().edits, dry_run=False)

    after = lint(scratch)
    new, gone = after - before, before - after
    check("the linter finds nothing new anywhere in the repo", not new, str(dict(new)))
    check("and nothing that was there before has been disturbed", not gone, str(dict(gone)))

    path = scratch / "maps/CastroForest.asm"
    check("the map still round-trips byte-for-byte",
          eh.parse_map(path).to_text() == path.read_text())
    check("the new trainer's party really is in the group file",
          tp.group_for(scratch, "YOUNGSTER").find("Testy") is not None)


def test_real_citations(tmp: Path) -> None:
    """The citation index has to find *every* way a party is reached, or the
    orphan rule will call a live trainer dead. There are three ways, and the
    third one is only used once in the whole repo."""
    root = _real_repo()
    if root is None:
        return

    print("\nevery way a party can be reached, in the real repo")
    cited = tc.citations(root)
    by_macro = {m: sum(1 for v in cited.values() for c in v if c.macro == m)
                for m in (tc.TRAINER, tc.LOADTRAINER, tc.SYMBOL)}
    check("the `trainer` macro reaches most of them", by_macro[tc.TRAINER] > 250)
    check("`loadtrainer` reaches the gym leaders and rivals",
          by_macro[tc.LOADTRAINER] > 40, str(by_macro))
    check("and the engine names one party by const, from outside maps/",
          by_macro[tc.SYMBOL] >= 1, str(by_macro))

    consts = tc.party_consts(root)
    check("RIVAL1_3 resolves to RIVAL1 party 3", consts.get("RIVAL1_3") == ("RIVAL1", 3))
    check("the AI-flag enum after `trainerclass CAL` is not swept up as CAL's parties",
          "NO_AI" not in consts and not any(c.startswith("TRNATTR") for c in consts))

    groups = tp.load(root)
    orphans = tc.orphans(root)
    named = {f"{label}#{p.index}" for label, p in orphans}
    check(f"{len(orphans)} of {sum(g.count for g in groups.values())} parties are orphans",
          0 < len(orphans) < 20)
    check("ArcadePC is NOT one of them — the engine loads it by const",
          not any(label == "ArcadePCGroup" for label, _ in orphans))
    check("nor is any gym leader", not any("Group#" in n and n.startswith(
        ("Bugsy", "Blue", "Lance")) for n in named))


def test_real_removal(tmp: Path) -> None:
    """Remove content a *human* wrote — the tools have never touched it, so this
    is the only test that proves removal understands the real source."""
    root = _real_repo()
    if root is None:
        return

    print("\nremoving hand-written content from a real map")
    scratch = tmp / "pokeprism-rm"
    shutil.copytree(root, scratch, symlinks=True,
                    ignore=shutil.ignore_patterns(".git", "*.o", "*.gbc", "*.sym", "*.map"))

    before = (scratch / "maps/CastroForest.asm").read_text()
    r = rm.remove(scratch, "CASTRO_FOREST", label="CastroForest_Trainer_2")
    apply_edits(scratch, r.edits, dry_run=False)
    after = (scratch / "maps/CastroForest.asm").read_text()

    check("the trainer's person_event is gone", "CastroForest_Trainer_2," not in after)
    check("its whole script block went with it, local labels and all",
          "CastroForest_Trainer_2:" not in after and 'ctxt "How droll."' not in after)
    check("the object count came down", after.count("person_event") ==
          before.count("person_event") - 1)
    check("the map still parses and round-trips",
          eh.parse_map(scratch / "maps/CastroForest.asm").to_text() == after)

    # EVENT_CASTRO_FOREST_TRAINER_2 gates two guards in JaeruGate — beating this
    # Sage is what opens that gate. Freeing it would hand a live flag back out.
    check("its flag is NOT freed, because another map still gates on it",
          r.freed_flag is None)
    check("and the caller is told which",
          any("still gates" in w for w in r.warnings), str(r.warnings))
    check("the party is left alone, with a warning",
          any("orphan" in w for w in r.warnings))

    # A hidden item whose flag is registered in event/gold_tokens.asm — a
    # reference that isn't in maps/ at all.
    r = rm.remove(scratch, "CASTRO_FOREST", at=(2, 5))
    check("a flag referenced outside maps/ is also spared",
          r.freed_flag is None, str(r.freed_flag))


def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        root = _fixture(tmp)
        test_parties(root)
        test_unbacked_classes(root)
        test_wild(root)
        test_npc(root)
        test_npc_below_a_header_first_map(root)
        test_trainer(root)
        test_items(root)
        test_the_other_two_pickups(root)
        test_a_rock_is_not_a_person(root)
        test_signpost(root)
        test_rejects_unknown_consts(root)
        test_stale_edit(root)
        test_removal(root)
        test_removal_leaves_what_it_must(root)
        test_real_parsers(tmp)
        test_real_scaffold(tmp)
        test_real_citations(tmp)
        test_real_removal(tmp)

    print()
    if _failures:
        print(f"{_failures} check(s) FAILED")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
