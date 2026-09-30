#!/usr/bin/env python3
"""A prism-shaped tree on disk, with one seeded bug per lint rule.

**Two repos build this fixture and neither may fork it.** `test_maplint` pins
exact finding counts per rule, and `test_studio` drives the IDE against a tree
those counts describe — so a second copy drifts, and the day it does one side is
asserting numbers the other no longer produces.

It could not stay inside `test_maplint`: a test module is not importable across a
repo boundary, and the integration repo needs the fixture while carrying no
linter. Hence a module, present in both repos, changed in both or in neither.

Nothing here imports a product. It writes `.asm` text, which is the only reason
one fixture can serve a linter and an editor at once.
"""

from __future__ import annotations

from pathlib import Path


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
