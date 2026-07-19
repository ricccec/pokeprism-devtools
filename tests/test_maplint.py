#!/usr/bin/env python3
"""Tests for prism-maplint.

The core is a hermetic fixture repo with exactly one seeded bug per rule: every
rule must fire on its own bug and stay silent on the clean maps around it. That
catches both halves of a linter going wrong — a rule that stops working, and a
rule that starts crying wolf.

If ../pokeprism is present, a real-repo pass also runs: the findings there must
stay within the triaged baseline.

    python tests/test_maplint.py
"""

from __future__ import annotations

import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pokeprism_devtools import maplint  # noqa: E402
from pokeprism_devtools.maplint.context import LintContext  # noqa: E402
from pokeprism_devtools.maplint.diagnostics import Severity  # noqa: E402

_failures = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global _failures
    mark = "OK  " if cond else "FAIL"
    print(f"  [{mark}] {label}{(': ' + detail) if detail else ''}")
    if not cond:
        _failures += 1


# --------------------------------------------------------------------------- #
# a fixture repo with one seeded bug per rule                                 #
# --------------------------------------------------------------------------- #

# 10 walking sprites + the player is one too many for VRAM table 1 (128 tiles /
# 12 tiles per walker = 10 slots), which is what sprite-vram exists to catch.
_CROWD = [f"SPRITE_W{i}" for i in range(1, 11)]

#: The glyphs the fixture's text needs, plus one digraph — `'d` is a single tile,
#: and a tokenizer that missed that would over-count every contraction.
_GLYPHS = [chr(c) for c in range(ord("A"), ord("Z") + 1)]
_GLYPHS += [chr(c) for c in range(ord("a"), ord("z") + 1)]
_GLYPHS += [" ", ".", ",", "!", "?", "-", "é", "<PK>", "<MN>", "<PO>", "<KE>", "'d"]


def _text_engine(root: Path) -> None:
    """The parts of the text engine the width rules read.

    Nothing here is invented: it is the same shape as pokeprism's, so the widths
    the rules derive (`#` -> 4 tiles, `<PLAYER>` -> up to 7) are *derived* in the
    test too, not asserted against numbers this file hardcodes.
    """
    charmap = ["LEAST_CONTROL_CHAR EQU $44"]
    for i, tok in enumerate(_GLYPHS):
        charmap.append(f'\tctxtmap "{tok}", ${0x80 + i:02x}, 0')
    for tok, byte in [("<STRBF1>", "$45"), ("<PKMN>", "$4b"), ("<POKE>", "$4d"),
                      ("<NEXT>", "$4e"), ("<LINE>", "$4f"), ("@", "$50"),
                      ("<PARA>", "$51"), ("<PLAYER>", "$52"), ("#", "$54"),
                      ("<CONT>", "$55"), ("<SDONE>", "$56"), ("<DONE>", "$57"),
                      ("<PROMPT>", "$58"), ("<TRNER>", "$5d"), ("<LNBRK>", "$5f")]:
        charmap.append(f'\tctxtmap "{tok}", {byte}, 0')
    (root / "macros" / "charmap.asm").write_text("\n".join(charmap) + "\n")

    (root / "macros" / "text.asm").write_text(
        'next   EQUS "dtxt \\"<NEXT>\\","\n'
        'line   EQUS "dtxt \\"<LINE>\\","\n'
        'para   EQUS "dtxt \\"<PARA>\\","\n'
        'cont   EQUS "dtxt \\"<CONT>\\","\n'
        'nl     EQUS "dtxt \\"<LNBRK>\\","\n'
        'sdone  EQUS "dtxt \\"<SDONE>\\""\n'
        'done   EQUS "dtxt \\"<DONE>\\""\n'
        'prompt EQUS "dtxt \\"<PROMPT>\\""\n'
    )

    (root / "home" / "text.asm").write_text(
        "BORDER_WIDTH   EQU 2\n"
        "TEXTBOX_WIDTH  EQU SCREEN_WIDTH\n"
        "TEXTBOX_INNERW EQU TEXTBOX_WIDTH - BORDER_WIDTH\n"
        "TEXTBOX_HEIGHT EQU 6\n"
        "TEXTBOX_Y      EQU SCREEN_HEIGHT - TEXTBOX_HEIGHT\n"
        "TEXTBOX_INNERY EQU TEXTBOX_Y + 2\n"
        "\n"
        "TextControlCodeJumptable::\n"
        '\tdw PlaceStringBuffer1       ; "<STRBF1>"\n'
        '\tdw PlacePKMN                ; "<PKMN>"\n'
        '\tdw PlacePOKE                ; "<POKE>"\n'
        '\tdw NextLineChar             ; "<NEXT>"\n'
        '\tdw LineChar                 ; "<LINE>"\n'
        '\tdw PlaceNextChar            ; "@"\n'
        '\tdw Paragraph                ; "<PARA>"\n'
        '\tdw PrintPlayerName          ; "<PLAYER>"\n'
        '\tdw PlacePOKe                ; "#"\n'
        '\tdw ContText                 ; "<CONT>"\n'
        '\tdw SDoneText                ; "<SDONE>"\n'
        '\tdw DoneText                 ; "<DONE>"\n'
        '\tdw PromptText               ; "<PROMPT>"\n'
        '\tdw TrainerChar              ; "<TRNER>"\n'
        '\tdw LinebreakText            ; "<LNBRK>"\n'
        "\n"
        "PrintPlayerName: print_name wPlayerName\n"
        "PlaceStringBuffer1: print_name wStringBuffer1\n"
        "TrainerChar:  print_name TrainerCharText\n"
        "PlacePOKe:    print_name PlacePOKeText\n"
        "PlacePKMN:    print_name PlacePKMNText\n"
        "PlacePOKE:    print_name PlacePOKEText\n"
        "\n"
        'TrainerCharText:: db "Trainer@"\n'
        'PlacePOKeText:: db "Poké@"\n'
        'PlacePKMNText:: db "<PK><MN>@"\n'
        'PlacePOKEText:: db "<PO><KE>@"\n'
    )

    # A signpost is a full-screen window; all the geometry that has to be read is
    # where its *body* starts, which is the hlcoord before the FarPlaceText.
    (root / "engine" / "signpost.asm").write_text(
        "SignpostFront:\n"
        "\thlcoord 2, 4\n"
        "\tcall PlaceText\n"
        "\thlcoord 2, 7\n"
        "\tcall FarPlaceText\n"
    )


def _fixture(tmp: Path) -> Path:
    root = tmp / "repo"
    for d in ("constants", "data", "engine", "home", "macros", "maps"):
        (root / d).mkdir(parents=True)
    (root / "Makefile").write_text("")
    (root / "main.asm").write_text("")
    _text_engine(root)

    (root / "constants.asm").write_text(
        "\tconst_def\n\tconst EVENT_0\n"
        'INCLUDE "constants/event_flags.asm"\n'
    )
    # EVENT_ORPHANED is declared and named by nothing (flag-unused). EVENT_TWICE
    # is the save-state record for two item balls at once (flag-multi-owner).
    # EVENT_DEAD gates an object that can never appear; EVENT_INERT gates one
    # that never goes away (flag-never-set, warning and info respectively).
    (root / "constants" / "event_flags.asm").write_text(
        "\tconst EVENT_REAL\n\tconst EVENT_SHARED\n"
        "\tconst EVENT_ORPHANED\n\tconst EVENT_TWICE\n"
        "\tconst EVENT_DEAD\n\tconst EVENT_INERT\n\tconst skip\n"
        "NUM_EVENTS EQU const_value\n"
    )
    (root / "constants" / "map_constants.asm").write_text(
        "; connection directions\n\tconst_def\n"
        "\tconst EAST_F\n\tconst WEST_F\n\tconst SOUTH_F\n\tconst NORTH_F\n\n"
        "\tconst_def\n"
        "\tshift_const EAST\n\tshift_const WEST\n\tshift_const SOUTH\n\tshift_const NORTH\n\n"
        "; permissions\nconst_value = 1\n"
        "\tconst TOWN\n\tconst ROUTE\n\tconst INDOOR\n\tconst CAVE\n"
    )
    (root / "constants" / "map_dimension_constants.asm").write_text(
        "\tconst_def\n"
        "\tnewgroup ; 1\n"
        "\tmapgroup TOWN_A, 10, 10\n"
        "\tmapgroup TOWN_B, 10, 10\n"
        "\tnewgroup ; 2\n"
        "\tmapgroup CAVE_C, 8, 8\n"
        "\tnewgroup ; 3\n"
        "\tmapgroup TOWN_D, 10, 10\n"
    )
    (root / "constants" / "misc_constants.asm").write_text(
        "SPRITE_GFX_LIST_CAPACITY EQU $20\n"
        "SCREEN_WIDTH     EQU 20\n"
        "SCREEN_HEIGHT    EQU 18\n"
        "PLAYER_NAME_LENGTH EQU 8\n"     # 7 letters and a terminator
        "PKMN_NAME_LENGTH EQU 11\n"
        "ITEM_NAME_LENGTH EQU 13\n"
    )

    # SPRITE_ROCK and SPRITE_BOULDER are here for the studio's sake rather than the
    # linter's: they are what a `person_event` that is not a person looks like (see
    # `hacks/prism/eventmodel.Prop`), and no map in this fixture places one. Last in the
    # list, so no existing sprite's id moves — `sprite_headers.asm` is positional.
    sprites = ["SPRITE_NONE", "SPRITE_P0", "SPRITE_NPC", "SPRITE_BALL",
               "SPRITE_STATUE", "SPRITE_STRANGER", *_CROWD,
               "SPRITE_ROCK", "SPRITE_BOULDER"]
    (root / "constants" / "sprite_constants.asm").write_text(
        "\tconst_def\n" + "".join(f"\tconst {s}\n" for s in sprites)
        + "SPRITE_POKEMON EQU const_value\n"
        + "const_value = $f0\nSPRITE_VARS EQU const_value\n"
        + "\n; sprite types\nconst_value = 1\n"
        + "\tconst WALKING_SPRITE\n\tconst STANDING_SPRITE\n\tconst STILL_SPRITE\n"
        + "\n; movement data\n\tconst_def\n"
        + "\tconst SPRITEMOVEDATA_STANDING_DOWN\n\tconst SPRITEMOVEDATA_WANDER\n"
        + "\tconst SPRITEMOVEDATA_SMASHABLE_ROCK\n"
        + "\tconst SPRITEMOVEDATA_STRENGTH_BOULDER\n"
    )
    # Positional: the nth sprite_header is sprite id n (SPRITE_NONE has none).
    types = {"SPRITE_P0": "WALKING_SPRITE", "SPRITE_NPC": "WALKING_SPRITE",
             "SPRITE_BALL": "STILL_SPRITE", "SPRITE_STATUE": "STANDING_SPRITE",
             "SPRITE_STRANGER": "WALKING_SPRITE",
             "SPRITE_ROCK": "STILL_SPRITE", "SPRITE_BOULDER": "STILL_SPRITE",
             **{s: "WALKING_SPRITE" for s in _CROWD}}
    (root / "data" / "sprite_headers.asm").write_text(
        "SpriteHeaders:\n" + "".join(
            f"{s.title().replace('_', '')}Sprite:\n"
            f"\tsprite_header {s}GFX, 3, {types[s]}, PAL_OW_RED\n"
            for s in sprites[1:]
        )
    )
    (root / "data" / "map_objects.asm").write_text(
        "SpriteMovementData::\n"
        "\tsprite_movement_data SPRITEMOVEFN_STANDING, DOWN, PERSON_ACTION_STAND, $00, $00, %0000 ; 00\n"
        "\tsprite_movement_data SPRITEMOVEFN_RANDOM_WALK_XY, DOWN, PERSON_ACTION_STAND, $00, $00, %0000 ; 01\n"
        "\tsprite_movement_data SPRITEMOVEFN_STANDING, DOWN, PERSON_ACTION_STAND, $00, $00, %0000 ; 02\n"
        "\tsprite_movement_data SPRITEMOVEFN_STANDING, DOWN, PERSON_ACTION_STAND, $00, $00, %0000 ; 03\n"
    )
    # Group 1's set omits SPRITE_STRANGER (-> sprite-outdoor).
    # Group 3's set is over-full with walkers (-> sprite-vram / -budget).
    (root / "engine" / "overworld.asm").write_text(
        "OutdoorSprites:\n"
        "\tdw Group1Sprites ; 1\n"
        "\tdw NoOutdoorSprites ; 2\n"
        "\tdw Group3Sprites ; 3\n"
        "\n"
        "Group1Sprites:\n\tdb SPRITE_NPC\n\tdb SPRITE_BALL\n\tdb SPRITE_STATUE\n\tdb 0 ; end\n"
        "\nGroup3Sprites:\n" + "".join(f"\tdb {s}\n" for s in _CROWD) + "\tdb 0 ; end\n"
        "\nNoOutdoorSprites:\n\tdb 0 ; end\n"
    )
    (root / "maps" / "map_headers.asm").write_text(
        "\tmap_header TownA, TILESET_A, TOWN, LM_TOWN_A, MUSIC_A, 0, PALETTE_A, FISH_0\n"
        "\tmap_header TownB, TILESET_A, TOWN, LM_TOWN_B, MUSIC_A, 0, PALETTE_A, FISH_0\n"
        "\tmap_header CaveC, TILESET_C, CAVE, LM_CAVE_C, MUSIC_A, 0, PALETTE_A, FISH_0\n"
        "\tmap_header TownD, TILESET_A, TOWN, LM_TOWN_D, MUSIC_A, 0, PALETTE_A, FISH_0\n"
    )

    # Landmarks are one flat enum with region_def markers cutting it into
    # contiguous regions — TownA/TownB are naljo, CaveC/TownD are rijon.
    (root / "constants" / "landmark_constants.asm").write_text(
        "MACRO region_def\n\tenum REGION_\\1\n\\1_LANDMARK EQU const_value\n\tENDM\n\n"
        "\tconst_def\n\tconst SPECIAL_MAP\n"
        "\tregion_def NALJO\n\tconst LM_TOWN_A\n\tconst LM_TOWN_B\n"
        "\tregion_def RIJON\n\tconst LM_CAVE_C\n\tconst LM_TOWN_D\n"
    )
    # TownB's grass block is filed under rijon, but its landmark says naljo.
    (root / "data" / "wild").mkdir()
    (root / "data" / "wild" / "naljo_grass.asm").write_text(
        "\twildmap TOWN_A\n\tdb 2 percent\n\tendwildmap\n"
    )
    (root / "data" / "wild" / "rijon_grass.asm").write_text(
        "\twildmap TOWN_D\n\tdb 2 percent\n\tendwildmap\n"
        "\twildmap TOWN_B\n\tdb 2 percent\n\tendwildmap\n"
    )

    # Block data: TownA's .blk is a byte short of its 10x10 declaration.
    (root / "maps" / "blk").mkdir()
    (root / "maps" / "blockdata.asm").write_text(
        "TownA_BlockData:\n\tINCBIN \"maps/blk/TownA.blk\"\n"
        "TownB_BlockData:\n\tINCBIN \"maps/blk/TownB.blk\"\n"
    )
    (root / "maps" / "blk" / "TownA.blk").write_bytes(b"\0" * 99)      # 10x10 = 100
    (root / "maps" / "blk" / "TownB.blk").write_bytes(b"\0" * 100)     # correct

    # Trainer parties are positional: SageGroup has two, so #3 doesn't exist.
    # A class reaches its group through TrainerGroups, indexed by class id — so
    # the enum and the pointer table have to line up for the class to resolve.
    (root / "trainers" / "groups").mkdir(parents=True)
    (root / "trainers" / "groups" / "sage.asm").write_text(
        'SageGroup:\n\t; 1\n\tdb "Genjo@"\n\tdb TRAINERTYPE_NORMAL\n'
        "\tdb 21, GASTLY\n\tdb -1\n\n"
        '\t; 2\n\tdb "Nico@"\n\tdb TRAINERTYPE_NORMAL\n\tdb 22, HAUNTER\n\tdb -1\n'
    )
    (root / "constants" / "trainer_constants.asm").write_text(
        "\tconst_def\n\ttrainerclass TRAINER_NONE\n\ttrainerclass SAGE\n"
    )
    (root / "trainers" / "trainer_pointers.asm").write_text(
        "TrainerGroups:\n\tdw SageGroup\n"
    )

    # Seeded connection bugs, one per rule:
    #   TOWN_A north  -> TOWN_B   reciprocal and aligned .......... clean
    #   TOWN_A east   -> GHOST                                      conn-target
    #   TOWN_A west   -> CAVE_C   no way back ..................... conn-missing
    #   TOWN_A flags omit EAST/WEST ............................... conn-flags
    #   TOWN_B south  -> TOWN_A   delta disagrees ................. conn-align
    #   TOWN_B 7th arg says TOWN_A ................................ conn-self
    (root / "maps" / "second_map_headers.asm").write_text(
        "\tmap_header_2 TownA, TOWN_A, $f, NORTH\n"
        "\tconnection north, TOWN_B, TownB, 3, 1, 8, TOWN_A\n"
        "\tconnection east, GHOST, Ghost, 0, 0, 8, TOWN_A\n"
        "\tconnection west, CAVE_C, CaveC, 0, 0, 8, TOWN_A\n"
        "\n"
        "\tmap_header_2 TownB, TOWN_B, $f, SOUTH\n"
        "\tconnection south, TOWN_A, TownA, 5, 1, 8, TOWN_A\n"
        "\n"
        "\tmap_header_2 CaveC, CAVE_C, $f, 0\n"
        "\tmap_header_2 TownD, TOWN_D, $f, 0\n"
    )

    def _map(name: str, warps: list[str], objects: list[str]) -> None:
        (root / "maps" / f"{name}.asm").write_text(
            f"{name}_MapEventHeader:: db 0, 0\n\n"
            f".Warps\n\tdb {len(warps)}\n" + "".join(f"\t{w}\n" for w in warps) + "\n"
            ".CoordEvents\n\tdb 0\n\n"
            ".BGEvents\n\tdb 0\n\n"
            f".ObjectEvents\n\tdb {len(objects)}\n" + "".join(f"\t{o}\n" for o in objects)
        )

    def _person(sprite: str, y: int, x: int, move: str, flag: str = "-1",
                ptype: str = "PERSONTYPE_TEXTFP", script: str = "SomeScript") -> str:
        return (f"person_event {sprite}, {y}, {x}, {move}, 0, 0, -1, -1, "
                f"PAL_OW_RED, {ptype}, 0, {script}, {flag}")

    # Warps are a chain, so they're laid out so exactly one rule fires:
    #   TownA #1 <-> CaveC #1 ..................................... clean, reciprocal
    #   TownA #2 -> CaveC #9, which doesn't exist ................. warp-target
    #   TownB #1 -> CaveC #1, which leads back to TownA ........... warp-oneway
    #
    # TownA also seeds: SPRITE_STRANGER isn't in Group1Sprites (sprite-outdoor),
    # EVENT_NOPE doesn't exist (flag-unknown), EVENT_SHARED is used in TownB too
    # (flag-shared).
    _map("TownA",
         ["warp_def 1, 1, 1, CAVE_C", "warp_def 2, 2, 9, CAVE_C"],
         [_person("SPRITE_NPC", 3, 3, "SPRITEMOVEDATA_STANDING_DOWN"),
          _person("SPRITE_STRANGER", 4, 4, "SPRITEMOVEDATA_STANDING_DOWN"),
          _person("SPRITE_NPC", 5, 5, "SPRITEMOVEDATA_STANDING_DOWN", "EVENT_NOPE"),
          _person("SPRITE_NPC", 6, 6, "SPRITEMOVEDATA_STANDING_DOWN", "EVENT_SHARED"),
          _person("SPRITE_NPC", 7, 7, "SPRITEMOVEDATA_STANDING_DOWN", "EVENT_INERT"),
          _person("SPRITE_NPC", 8, 8, "SPRITEMOVEDATA_STANDING_DOWN",
                  "EVENT_DEAD | $8000")])
    # Something has to set EVENT_SHARED, or it would itself be never-set. Put it
    # outside maps/, so no map's line numbers move.
    (root / "engine" / "std_scripts.asm").write_text(
        "StdScript:\n\tsetevent EVENT_SHARED\n")

    # TownA's dialogue, one seeded bug per text rule. Text goes *above* the event
    # header, as it does in a real map. The clean lines around each bug matter as
    # much as the bug: the whole failure mode of a width rule is crying wolf.
    a = root / "maps" / "TownA.asm"
    a.write_text(
        # 16 characters, and 19 tiles: `#` prints "Poké". This is the Route77
        # Pokecenter bug, and it is invisible without expanding the control code.
        "TownAWidth:\n"
        '\tctxt "#mon Center near"\n'
        '\tline "That fits fine."\n'
        "\tdone\n\n"
        # Fits a short name, overflows a seven-letter one (text-width-name).
        "TownAName:\n"
        '\tctxt "Nice to meet you <PLAYER>"\n'
        "\tdone\n\n"
        # A scratch buffer with four tiles of room (text-buffer).
        "TownABuffer:\n"
        '\tctxt "You just won a <STRBF1>"\n'
        "\tdone\n\n"
        # <LINE> is absolute, so the second `line` redraws row 16 (text-clobber).
        "TownAClobber:\n"
        '\tctxt "One"\n'
        '\tline "Two"\n'
        '\tline "Three"\n'
        "\tdone\n\n"
        # <NEXT> is relative: 14 -> 16 -> 18, off the bottom of the box (text-rows).
        "TownARows:\n"
        '\tctxt "One"\n'
        '\tnext "Two"\n'
        '\tnext "Three"\n'
        "\tdone\n\n"
        # Clean, and every line of it is a way the rule could cry wolf: one that is
        # exactly the full 18 wide, one that is *also* exactly 18 but only if the
        # digraph `'d` counts as one tile and `#` as four, and a block closed by an
        # inline `@` instead of a `done`. None of these may fire.
        "TownAClean:\n"
        '\tctxt "Just eighteen wide"\n'
        '\tline "I\'d like # Balls"\n'
        '\tpara "Bye then!@"\n'
        + a.read_text()
    )

    # TownB also carries a trainer pointing at SageGroup party #3, which
    # doesn't exist (trainer-party), and its wild data is filed under the wrong
    # region (wild-region). A `loadtrainer` reaches party #1 — the second way a
    # party can be cited, and the reason #1 is not an orphan while #2 is.
    # Two item balls whose flag is the same bit of save state: pick up one and
    # the other disappears (flag-multi-owner).
    # Its NPC stands on its warp — one tile, two lists, and both of them work: the
    # guard is what stops you using the door until he moves (event-stack, info).
    # Its second NPC stands on an *item ball*, which is one tile and one list, and
    # only the first of the two can be reached (event-overlap, warning).
    # Three trainers battle as SAGE — two in SPRITE_NPC, one in SPRITE_STATUE. The
    # odd one out is the same class wearing a second overworld sprite, which is
    # trainer-sprite. All three point at the one SAGE block, so nothing new is
    # cited: the class stays as backed and party #2 as orphaned as before. Both
    # sprites are in Group1Sprites, so sprite-outdoor stays silent, and all three
    # stand at their own tile, clear of the warp and item balls.
    _map("TownB", ["warp_def 1, 1, 1, CAVE_C"],
         [_person("SPRITE_NPC", 1, 1, "SPRITEMOVEDATA_STANDING_DOWN", "EVENT_SHARED"),
          _person("SPRITE_BALL", 2, 2, "SPRITEMOVEDATA_ITEM_TREE", "EVENT_TWICE",
                  ptype="PERSONTYPE_ITEMBALL"),
          _person("SPRITE_BALL", 3, 3, "SPRITEMOVEDATA_ITEM_TREE", "EVENT_TWICE",
                  ptype="PERSONTYPE_ITEMBALL"),
          _person("SPRITE_NPC", 2, 2, "SPRITEMOVEDATA_STANDING_DOWN"),
          _person("SPRITE_NPC", 5, 5, "SPRITEMOVEDATA_STANDING_DOWN",
                  ptype="PERSONTYPE_TRAINER", script="TownB_Trainer_1"),
          _person("SPRITE_NPC", 6, 6, "SPRITEMOVEDATA_STANDING_DOWN",
                  ptype="PERSONTYPE_TRAINER", script="TownB_Trainer_1"),
          _person("SPRITE_STATUE", 7, 7, "SPRITEMOVEDATA_STANDING_DOWN",
                  ptype="PERSONTYPE_TRAINER", script="TownB_Trainer_1")])
    b = root / "maps" / "TownB.asm"
    b.write_text("TownB_Trainer_1:\n"
                 "\ttrainer EVENT_REAL, SAGE, 3, .seen, .beaten\n\n"
                 "TownB_Script:\n"
                 "\tloadtrainer SAGE, 1\n\n" + b.read_text())

    # CaveC is indoor, so the outdoor-set rule doesn't apply to it. A STILL
    # sprite is told to wander (sprite-static-walker), and the object count
    # over-declares by one (obj-count).
    (root / "maps" / "CaveC.asm").write_text(
        "CaveC_MapEventHeader:: db 0, 0\n\n"
        ".Warps\n\tdb 1\n\twarp_def 1, 1, 1, TOWN_A\n\n"
        ".CoordEvents\n\tdb 0\n\n"
        ".BGEvents\n\tdb 0\n\n"
        ".ObjectEvents\n\tdb 2\n"
        f"\t{_person('SPRITE_BALL', 2, 2, 'SPRITEMOVEDATA_WANDER')}\n"
    )

    # TownD (outdoor, group 3): the group set has 10 walking-capable sprites and
    # the player makes 11 — one past what table 1 holds, so SPRITE_W10 spills
    # into table 2. Standing there would be harmless, so the seeded bug is that
    # W10's object is told to *wander*: it steps, fetches walk frames at
    # base + $80, and reads past the sprite tables (sprite-vram). Every other
    # object stands, and must not be flagged.
    _map("TownD", [],
         [_person(s, 1, i + 1,
                  "SPRITEMOVEDATA_WANDER" if s == _CROWD[-1]
                  else "SPRITEMOVEDATA_STANDING_DOWN")
          for i, s in enumerate(_CROWD)])
    return root


_EXPECTED = {
    "conn-target": 1,
    "conn-missing": 1,
    "conn-align": 1,
    "conn-self": 1,
    "conn-flags": 1,
    "warp-target": 1,
    "warp-oneway": 1,
    "obj-count": 1,
    "event-overlap": 1,      # TownB: an NPC standing on an item ball, in one list
    "event-stack": 1,        # TownB: an NPC standing on a warp, across two
    "sprite-outdoor": 1,
    "sprite-static-walker": 1,
    "flag-unknown": 1,
    "flag-shared": 1,
    "flag-unused": 1,        # EVENT_ORPHANED: declared, named by nothing
    "flag-multi-owner": 1,   # EVENT_TWICE: two item balls, one bit of save state
    "flag-never-set": 2,     # EVENT_DEAD (never appears) + EVENT_INERT (never goes)
    "sprite-vram": 1,
    "sprite-vram-budget": 1,
    "blk-size": 1,
    "trainer-sprite": 1,     # TownB: one SAGE in SPRITE_STATUE, the rest SPRITE_NPC
    "trainer-party": 1,
    "trainer-orphan": 1,        # Sage #2: #1 is reached by loadtrainer, #2 by nothing
    "wild-region": 1,
    "text-width": 1,            # "#mon Center near" -> 19 tiles, `#` prints Poké
    "text-width-name": 1,       # fits a short <PLAYER>, not a seven-letter one
    "text-buffer": 1,           # 4 tiles left for <STRBF1>
    "text-clobber": 1,          # a second `line` redraws row 16
    "text-rows": 1,             # `next` twice: row 18, off the bottom
}


def test_seeded(root: Path) -> None:
    print("\nevery rule fires exactly once on its seeded bug")
    found = maplint.run(LintContext(root))
    counts = Counter(d.code for d in found)

    for code, n in sorted(_EXPECTED.items()):
        got = counts.get(code, 0)
        detail = "" if got == n else f"expected {n}, got {got}"
        check(f"{code}", got == n, detail)

    unexpected = {c: n for c, n in counts.items() if c not in _EXPECTED}
    check("no rule cried wolf on the clean maps", not unexpected, str(unexpected))


def test_table2_is_not_a_bug(root: Path) -> None:
    """A sprite typed WALKING_SPRITE only *has* walk frames in ROM — it doesn't
    follow that its object ever fetches them. Objects that stand, spin or bob
    never read base + $80, so sitting in VRAM table 2 is where they belong.
    Flagging them was a real false positive (MtEmberWest, SaxifrageIsland); this
    pins the distinction.
    """
    print("\na non-walking object in VRAM table 2 is fine, not a finding")
    found = [d for d in maplint.run(LintContext(root)) if d.code == "sprite-vram"]
    check("only the object that actually walks is flagged", len(found) == 1, str(found))
    check("and it's the wandering one", "SPRITE_W10" in found[0].message, found[0].message)

    # Make it stand still: same VRAM layout, no finding.
    path = root / "maps" / "TownD.asm"
    original = path.read_text()
    path.write_text(original.replace("SPRITEMOVEDATA_WANDER",
                                     "SPRITEMOVEDATA_STANDING_DOWN"))
    still = [d for d in maplint.run(LintContext(root)) if d.code == "sprite-vram"]
    check("the same sprite standing in table 2 is not flagged", not still, str(still))
    path.write_text(original)


def test_map_too_big(root: Path) -> None:
    """A map whose (h+6)×(w+6) exceeds the engine's 1300-block buffer is flagged;
    30×30 (1296) is the largest that fits and stays clean."""
    print("\na map bigger than the map buffer is an error")
    path = root / "constants" / "map_dimension_constants.asm"
    original = path.read_text()

    def sized(h: int, w: int) -> list:
        path.write_text(original.replace("\tmapgroup TOWN_A, 10, 10",
                                         f"\tmapgroup TOWN_A, {h}, {w}"))
        return [d for d in maplint.run(LintContext(root)) if d.code == "map-too-big"]

    over = sized(40, 40)                       # (46)×(46) = 2116
    check("an over-buffer map is flagged", len(over) == 1, str(over))
    check("the finding names the map and the arithmetic",
          over and "TOWN_A" in over[0].message and "2116" in over[0].message,
          over[0].message if over else "")
    check("it points at the mapgroup line, not line 1",
          over and over[0].line > 1 and "map_dimension" in over[0].path,
          str(over[0]) if over else "")

    check("30×30 (1296) is under the limit and clean", not sized(30, 30))
    check("31×30 (1332) is over it", len(sized(31, 30)) == 1)
    path.write_text(original)


def test_object_overflow(root: Path) -> None:
    """A map may declare at most 15 object events: the engine copies them into a
    16-slot WRAM array whose slot 0 is the player. 16 overflows; 15 is the ceiling
    and stays clean. The count byte is what the engine reads, so a well-formed map
    of 16 fires this and not obj-count."""
    print("\na map with more than 15 object events overflows the map-object array")
    path = root / "maps" / "CaveC.asm"
    original = path.read_text()

    def with_objects(n: int) -> list:
        objs = "".join(
            f"\tperson_event SPRITE_NPC, {2 + i}, 2, SPRITEMOVEDATA_STANDING_DOWN, "
            f"0, 0, -1, -1, PAL_OW_RED, PERSONTYPE_TEXTFP, 0, SomeScript, -1\n"
            for i in range(n))
        path.write_text(
            "CaveC_MapEventHeader:: db 0, 0\n\n"
            ".Warps\n\tdb 1\n\twarp_def 1, 1, 1, TOWN_A\n\n"
            ".CoordEvents\n\tdb 0\n\n"
            ".BGEvents\n\tdb 0\n\n"
            f".ObjectEvents\n\tdb {n}\n" + objs)
        return [d for d in maplint.run(LintContext(root)) if d.code == "object-overflow"]

    over = with_objects(16)
    check("16 object events is flagged", len(over) == 1, str(over))
    check("the finding names the count and the limit",
          bool(over) and "16" in over[0].message and "15" in over[0].message,
          over[0].message if over else "")
    check("it points at the ObjectEvents count line in the map file",
          bool(over) and over[0].path == "maps/CaveC.asm" and over[0].line > 1,
          str(over[0]) if over else "")
    # A clean map of 16 has its count byte right, so obj-count stays quiet — the
    # two rules must not both fire on the same map.
    also = [d for d in maplint.run(LintContext(root))
            if d.code == "obj-count" and d.path == "maps/CaveC.asm"]
    check("obj-count does not double-report the same map", not also, str(also))

    check("15 object events is the ceiling and clean", not with_objects(15))
    check("17 is over it", len(with_objects(17)) == 1)
    path.write_text(original)


def test_messages(root: Path) -> None:
    print("\nfindings say what is wrong and where")
    by_code = {d.code: d for d in maplint.run(LintContext(root))}

    d = by_code["warp-target"]
    check("warp-target names the valid range", "valid: 1-1" in d.message, d.message)
    # Located by content, not by a line number: the fixture's maps grow as rules
    # are added, and a hardcoded line here just breaks the next time they do.
    src = (root / "maps" / "TownA.asm").read_text().split("\n")
    want = 1 + next(i for i, l in enumerate(src) if "warp_def 2, 2, 9, CAVE_C" in l)
    check("warp-target points at the warp line",
          d.path == "maps/TownA.asm" and d.line == want, f"{d.path}:{d.line} (want :{want})")

    d = by_code["conn-align"]
    check("conn-align reports both deltas", "+2" in d.message and "+4" in d.message, d.message)

    d = by_code["sprite-vram"]
    check("sprite-vram explains the +$80 walk-frame overrun",
          "walk frames" in d.message and "table 1" in d.message, d.message)

    d = by_code["obj-count"]
    check("obj-count warns about the phantom object",
          "read the bytes after the list" in d.message, d.message)

    check("severities: runtime breakage is an error, convention is info",
          by_code["sprite-vram"].severity is Severity.ERROR
          and by_code["warp-oneway"].severity is Severity.INFO
          and by_code["flag-shared"].severity is Severity.INFO)


def test_suppression(root: Path) -> None:
    print("\n; maplint: ignore[code] suppresses a finding")
    path = root / "maps" / "TownA.asm"
    original = path.read_text()

    path.write_text(original.replace(
        "\twarp_def 2, 2, 9, CAVE_C",
        "\twarp_def 2, 2, 9, CAVE_C ; maplint: ignore[warp-target]"))
    codes = Counter(d.code for d in maplint.run(LintContext(root)))
    check("an inline ignore drops the finding", codes.get("warp-target", 0) == 0)
    check("it doesn't drop anything else", codes.get("sprite-outdoor", 0) == 1)

    path.write_text(original.replace(
        "\twarp_def 2, 2, 9, CAVE_C",
        "\t; maplint: ignore[warp-target]\n\twarp_def 2, 2, 9, CAVE_C"))
    codes = Counter(d.code for d in maplint.run(LintContext(root)))
    check("an ignore on the line above works too", codes.get("warp-target", 0) == 0)

    path.write_text(original.replace(
        "\twarp_def 2, 2, 9, CAVE_C",
        "\twarp_def 2, 2, 9, CAVE_C ; maplint: ignore[conn-self]"))
    codes = Counter(d.code for d in maplint.run(LintContext(root)))
    check("ignoring a different code leaves the finding", codes.get("warp-target", 0) == 1)

    path.write_text(original)


def test_file_suppression(root: Path) -> None:
    """For a file that is the exception outright — pokeprism's PhanceroRoom is
    eleven lines of deliberately-corrupt text that is *supposed* to overflow the
    box. Eleven inline comments would say the same thing eleven times and still
    miss the twelfth line somebody adds later.
    """
    print("\n; maplint: ignore-file[code] suppresses a whole file")
    path = root / "maps" / "TownA.asm"
    original = path.read_text()

    path.write_text("; maplint: ignore-file[text-width,text-rows]\n" + original)
    codes = Counter(d.code for d in maplint.run(LintContext(root)))
    check("every text-width finding in the file goes", codes.get("text-width", 0) == 0)
    check("...and so does the other code named", codes.get("text-rows", 0) == 0)
    check("codes it didn't name stay", codes.get("text-clobber", 0) == 1)
    check("and other files are untouched", codes.get("obj-count", 0) == 1)

    # The comment is a comment: it works wherever it sits, not only at the top.
    path.write_text(original + "\n; maplint: ignore-file[text-width]\n")
    codes = Counter(d.code for d in maplint.run(LintContext(root)))
    check("it works from the bottom of the file too", codes.get("text-width", 0) == 0)
    check("...without dropping the codes it didn't name", codes.get("text-rows", 0) == 1)

    path.write_text(original)


def test_suppress_outside_maps(root: Path) -> None:
    """Findings don't all land in maps/. `flag-unused` points at the event-flag
    table and `trainer-orphan` at a trainer group, and a suppression comment has
    to work where the finding actually is — which it didn't, when the lookup only
    ever loaded maps/.
    """
    print("\nsuppression works wherever the finding lands, not just in maps/")
    path = root / "constants" / "event_flags.asm"
    original = path.read_text()

    check("the flag is reported before we touch it",
          Counter(d.code for d in maplint.run(LintContext(root)))["flag-unused"] == 1)

    path.write_text(original.replace(
        "\tconst EVENT_ORPHANED",
        "\tconst EVENT_ORPHANED ; maplint: ignore[flag-unused]"))
    codes = Counter(d.code for d in maplint.run(LintContext(root)))
    check("an ignore in constants/event_flags.asm is honoured",
          codes.get("flag-unused", 0) == 0)

    path.write_text(original)


def test_filter_and_exit(root: Path) -> None:
    print("\nCLI: filtering by map, and the exit code")
    ctx = LintContext(root)
    only = maplint.run(ctx, only="TownA")
    check("filtering by label keeps that map's findings",
          {d.code for d in only} >= {"warp-target", "sprite-outdoor", "flag-unknown"})
    check("and its connections, which live in the shared file",
          any(d.path.endswith("second_map_headers.asm") for d in only))
    check("but not another map's", not any(d.path.endswith("CaveC.asm") for d in only))

    check("errors present -> exit 1", maplint.main(["--root", str(root)]) == 1)
    check("info-only threshold still exits 1 here",
          maplint.main(["--root", str(root), "--severity", "info"]) == 1)


def test_baseline(root: Path, tmp: Path) -> None:
    print("\nbaseline: known findings stop failing the build, new ones don't")
    check("write-baseline exits 0", maplint.main(["--root", str(root), "--write-baseline"]) == 0)
    check("baseline file written", (root / maplint.BASELINE).exists())
    check("with every finding baselined, the run passes",
          maplint.main(["--root", str(root), "--baseline"]) == 0)

    # A new bug on top of the baseline must still fail: over-declare TownB's
    # object count, so the engine reads a phantom object past the end.
    path = root / "maps" / "TownB.asm"
    before = path.read_text()
    after = before.replace(".ObjectEvents\n\tdb 7\n", ".ObjectEvents\n\tdb 9\n")
    check("the seeded bug really was seeded", after != before)
    path.write_text(after)
    check("a new finding still fails despite the baseline",
          maplint.main(["--root", str(root), "--baseline"]) == 1)


# --------------------------------------------------------------------------- #
# the real repo                                                               #
# --------------------------------------------------------------------------- #

def test_real_repo() -> None:
    root = Path(__file__).resolve().parent.parent.parent / "pokeprism"
    if not (root / "maps").is_dir():
        print("\n(skipping real-repo pass — ../pokeprism not found)")
        return

    print("\nreal repo: findings stay within the triaged baseline")
    found = maplint.run(LintContext(root))
    counts = Counter(d.code for d in found)

    # Triaged 2026-07-11. Every error here is a real pre-existing bug in
    # pokeprism; the info-level codes are conventions, not defects.
    triaged = {
        "warp-target": 13,          # warps into a slot the destination doesn't have
        "warp-oneway": 72,          # mostly the shared POKECENTER_BACKROOM — by design
        "obj-count": 4,             # count byte vs entries (see test_eventheader)
        # MoundB2F's three warps on (40, 8), two of which are dead exits. Somebody
        # already knew: the source says `; FIXME` on the two.
        "event-overlap": 2,
        # info: 26 tiles holding entries of two different lists. Nothing here is
        # shadowed — an NPC standing on a warp is how you keep a door shut — and
        # the rule says so rather than staying quiet, because a typo looks the same.
        "event-stack": 26,
        "sprite-vram": 0,           # none: standing NPCs in table 2 are fine
        "sprite-vram-budget": 5,    # info: maps with no walking slots left
        "blk-size": 6,              # .blk and the declared dimensions disagree
        "conn-missing": 2,          # one-way connections
        "conn-self": 0,             # ROUTE_69_NORTH's typo, since fixed upstream
        "wild-region": 1,           # CAPER_RIDGE's grass is filed under mystery
        "wild-rate": 1,             # LAUREL_FOREST's `db 3` is 1.2%, not 3%
        "trainer-class": 0,         # none: the 7 unbacked classes are all uncited
        "trainer-orphan": 7,        # info: parties nothing references — dead weight
        # info: 11 classes drawn with a second overworld sprite somewhere —
        # HIKER as SPRITE_FISHER, LASS as SPRITE_COOLTRAINER_F, and so on. Real
        # inconsistencies, most of them old; a few (BEAUTY's rocket variant) are
        # deliberate. This is the drift the rule exists to stop growing.
        "trainer-sprite": 28,
        "flag-shared": 9,           # deliberate: one flag gating objects in two maps
        "flag-multi-owner": 2,      # info: EmberBrook's twins, and Provincial Park's PP Ups
        "flag-unused": 200,         # info: declared flags nothing references
        "flag-unknown": 0,          # none: every EVENT_* named in the repo exists
        "flag-never-set": 17,       # 1 warning (SilphWarehouse's guard never appears)
        # 3 real overflows, and 13 lines of deliberately-corrupt "Glitch City"
        # text in PhanceroRoom, which is *supposed* to spill out of the box.
        #
        # Was 14 until `dialogue.decomment` landed: the parser used to cut every
        # line at the first `;`, so a string *containing* one measured as zero
        # tiles and could not overflow. Two of the glitch lines have one. The
        # linter was blind to them, not innocent of them.
        "text-width": 16,
        "text-width-name": 0,       # none: no line breaks on a seven-letter name
        "text-rows": 0,             # none: `next` is never used in a speech box
        "text-clobber": 1,          # PhanceroRoom again, same easter egg
        "text-buffer": 12,          # info: lines whose <STRBF*> headroom is tight
        "text-unknown": 0,          # none: every character in maps/ is in the charmap
    }
    for code in sorted(set(counts) | set(triaged)):
        got, want = counts.get(code, 0), triaged.get(code, 0)
        check(f"{code}: {got}", got <= want,
              f"{got - want} NEW finding(s) beyond the triaged {want}")

    errors = sum(1 for d in found if d.severity is Severity.ERROR)
    print(f"      {len(found)} findings, {errors} of them real bugs")


def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        root = _fixture(tmp)
        test_seeded(root)
        test_table2_is_not_a_bug(root)
        test_map_too_big(root)
        test_object_overflow(root)
        test_messages(root)
        test_suppression(root)
        test_file_suppression(root)
        test_suppress_outside_maps(root)
        test_filter_and_exit(root)
        test_baseline(root, tmp)
    test_real_repo()

    print()
    if _failures:
        print(f"{_failures} check(s) FAILED")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
