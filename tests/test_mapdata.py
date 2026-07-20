#!/usr/bin/env python3
"""Tests for the event-flag allocator and the sprite tables.

Hermetic fixtures for the logic; if ../pokeprism is present, calibration tests
run against the real thing — the parsers are only worth anything if they agree
with the data the engine actually reads.

    python tests/test_mapdata.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pokeprism_devtools.hacks.prism import (  # noqa: E402
    eventflags, eventheader as eh, spritesets)
from pokeprism_devtools.hacks.prism.eventflags import FlagError  # noqa: E402

_failures = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global _failures
    mark = "OK  " if cond else "FAIL"
    print(f"  [{mark}] {label}{(': ' + detail) if detail else ''}")
    if not cond:
        _failures += 1


# --------------------------------------------------------------------------- #
# fixture repo                                                                #
# --------------------------------------------------------------------------- #

def _fixture(tmp: Path) -> Path:
    root = tmp / "repo"
    (root / "constants").mkdir(parents=True)
    (root / "data").mkdir(parents=True)
    (root / "engine").mkdir(parents=True)

    # constants.asm sets the counter before INCLUDEing the flags: EVENT_1 == 1.
    (root / "constants.asm").write_text(
        "\tconst_def\n"
        "\tconst EVENT_0\n"
        'INCLUDE "constants/event_flags.asm"\n'
    )
    (root / "constants" / "event_flags.asm").write_text(
        "\tconst EVENT_1\n"
        "\tconst EVENT_GOT_TM63\n"
        "\tconst skip\n"
        "\tconst skip\n"
        "\tconst EVENT_LATER_FLAG\n"
        "NUM_EVENTS EQU const_value\n"
    )
    (root / "constants" / "misc_constants.asm").write_text(
        "SPRITE_GFX_LIST_CAPACITY EQU $20\n"
    )
    (root / "constants" / "sprite_constants.asm").write_text(
        "\tconst_def\n"
        "\tconst SPRITE_NONE\n"
        "\tconst SPRITE_P0\n"
        "\tconst SPRITE_SAGE\n"
        "\tconst SPRITE_POKE_BALL\n"
        "SPRITE_POKEMON EQU const_value\n"
        "\tconst SPRITE_MEW\n"
        "const_value = $08\n"
        "SPRITE_VARS EQU const_value\n"
        "\tconst SPRITE_COPYCAT\n"
        "\n; sprite types\n"
        "const_value = 1\n"
        "\tconst WALKING_SPRITE\n"
        "\tconst STANDING_SPRITE\n"
        "\tconst STILL_SPRITE\n"
        "\n; movement data\n"
        "\tconst_def\n"
        "\tconst SPRITEMOVEDATA_STANDING_DOWN\n"
        "\tconst SPRITEMOVEDATA_WANDER\n"
        "\n; a later enum that also starts with SPRITE_ — must not leak\n"
        "\tconst_def\n"
        "\tconst SPRITE_ANIM_FRAMESET_00\n"
        "\tconst SPRITE_ANIM_FRAMESET_CUT_TREE\n"
    )
    (root / "data" / "map_objects.asm").write_text(
        "SpriteMovementData::\n"
        "\tsprite_movement_data SPRITEMOVEFN_STANDING, DOWN, PERSON_ACTION_STAND, $00, $00, %0000 ; 00\n"
        "\tsprite_movement_data SPRITEMOVEFN_RANDOM_WALK_XY, DOWN, PERSON_ACTION_STAND, $00, $00, %0000 ; 01\n"
    )
    # Positional: the nth sprite_header is sprite id n.
    (root / "data" / "sprite_headers.asm").write_text(
        "SpriteHeaders:\n"
        "Player0Sprite:\n"
        "\tsprite_header Player0SpriteGFX, 3, WALKING_SPRITE, PAL_OW_PLAYER\n"
        "SageSprite:\n"
        "\tsprite_header SageSpriteGFX, 3, WALKING_SPRITE, PAL_OW_BLUE\n"
        "PokeBallSprite:\n"
        "\tsprite_header PokeBallSpriteGFX, 1, STILL_SPRITE, PAL_OW_RED\n"
    )
    (root / "engine" / "overworld.asm").write_text(
        "OutdoorSprites:\n"
        "\tdw IntroSprites ; 1\n"
        "\tdw TownSprites ; 2\n"
        "\tdw NoOutdoorSprites ; 3\n"
        "\n"
        "IntroSprites:\n"
        "\tdb SPRITE_SAGE\n"
        "\tdb 0 ; end\n"
        "\n"
        "TownSprites:\n"
        "\tdb SPRITE_SAGE\n"
        "\tdb SPRITE_POKE_BALL\n"
        "\tdb 0 ; end\n"
        "\n"
        "NoOutdoorSprites:\n"
        "\tdb 0 ; end\n"
    )
    return root


# --------------------------------------------------------------------------- #
# event flags                                                                 #
# --------------------------------------------------------------------------- #

def test_eventflags(root: Path) -> None:
    print("\nevent flags: parse")
    ef = eventflags.load(root)
    check("start_value read from constants.asm, not hardcoded", ef.start_value == 1,
          str(ef.start_value))
    check("named flags parsed", [f.name for f in ef.flags] ==
          ["EVENT_1", "EVENT_GOT_TM63", "EVENT_LATER_FLAG"])
    check("EVENT_1 == 1 (values are save-file bit positions)", ef.by_name["EVENT_1"] == 1)
    check("skip slots found", ef.free_slots == 2)
    check("skips still consume values", [s.value for s in ef.skips] == [3, 4],
          str([s.value for s in ef.skips]))
    check("flag after the skips keeps its value", ef.by_name["EVENT_LATER_FLAG"] == 5)
    check("num_events counts skips too", ef.num_events == 6, str(ef.num_events))
    check("round-trip byte-identical",
          ef.to_text() == (root / "constants/event_flags.asm").read_text())

    print("\nevent flags: allocation reuses a skip slot (save-compatible)")
    ef = eventflags.load(root)
    before = dict(ef.by_name)
    flag = ef.allocate("EVENT_NEW_NPC")
    check("takes the earliest skip slot's value", flag.value == 3, str(flag.value))
    check("one fewer free slot", ef.free_slots == 1)
    check("NUM_EVENTS unchanged — the array did not grow", ef.num_events == 6)
    check("no other flag was renumbered",
          all(ef.by_name[n] == v for n, v in before.items()))
    text = ef.to_text()
    check("the skip line became the new const", "\tconst EVENT_NEW_NPC\n" in text)
    check("exactly one skip was consumed", text.count("const skip") == 1)

    check("allocate is idempotent", ef.allocate("EVENT_NEW_NPC").value == 3
          and ef.free_slots == 1)

    edit = ef.to_edit(root, "added EVENT_NEW_NPC")
    check("to_edit carries the change", edit.changed
          and edit.path == "constants/event_flags.asm"
          and "EVENT_NEW_NPC" in edit.new_text)

    print("\nevent flags: exhaustion is an error, not a silent append")
    ef.allocate("EVENT_ANOTHER")
    check("last slot used", ef.free_slots == 0)
    try:
        ef.allocate("EVENT_ONE_TOO_MANY")
        check("allocating past the reserve raises", False)
    except FlagError:
        check("allocating past the reserve raises", True)


# --------------------------------------------------------------------------- #
# sprites                                                                     #
# --------------------------------------------------------------------------- #

def test_spritesets(root: Path) -> None:
    print("\nsprites: id enum")
    sd = spritesets.load(root)
    check("ids parsed", sd.sprite_ids["SPRITE_SAGE"] == 2, str(sd.sprite_ids.get("SPRITE_SAGE")))
    check("SPRITE_POKEMON boundary marker read", sd.pokemon_sprite_id == 4)
    check("counter jump past the marker is followed", sd.sprite_ids["SPRITE_MEW"] == 4)
    check("SPRITE_VARS boundary", sd.vars_sprite_id == 8)
    check("SPRITE_ANIM_* from a later enum does not leak in",
          not any(s.startswith("SPRITE_ANIM") for s in sd.sprite_ids))

    print("\nsprites: headers (positional table, id-1)")
    check("SPRITE_P0 -> Player0Sprite", sd.header("SPRITE_P0").label == "Player0Sprite")
    check("SPRITE_SAGE -> SageSprite", sd.header("SPRITE_SAGE").label == "SageSprite")
    check("SPRITE_POKE_BALL -> PokeBallSprite",
          sd.header("SPRITE_POKE_BALL").label == "PokeBallSprite")
    check("walking sprite costs 12 tiles",
          sd.header("SPRITE_SAGE").walking and sd.header("SPRITE_SAGE").tiles == 12)
    check("still sprite costs 4 tiles",
          not sd.header("SPRITE_POKE_BALL").walking
          and sd.header("SPRITE_POKE_BALL").tiles == 4)
    check("capacity read from misc_constants", sd.list_capacity == 0x20)

    print("\nsprites: the three id regions")
    check("normal sprite needs a header", sd.needs_header("SPRITE_SAGE"))
    check("SPRITE_NONE (id 0) needs no header", not sd.needs_header("SPRITE_NONE"))
    check("overworld Pokemon needs no header",
          sd.is_pokemon_sprite("SPRITE_MEW") and not sd.needs_header("SPRITE_MEW"))
    check("variable sprite needs no header",
          sd.is_variable_sprite("SPRITE_COPYCAT") and not sd.needs_header("SPRITE_COPYCAT"))
    check("no sprite is missing a header it ought to have", not sd.missing_headers,
          str(sd.missing_headers))

    print("\nsprites: movement data (which movements actually walk)")
    check("sprite types ranked WALKING < STANDING < STILL — the sort order that "
          "packs walkers into VRAM table 1 first",
          sd.type_rank("WALKING_SPRITE") < sd.type_rank("STANDING_SPRITE")
          < sd.type_rank("STILL_SPRITE"))
    check("movedata resolves to its movement function",
          sd.move_function("SPRITEMOVEDATA_WANDER") == "SPRITEMOVEFN_RANDOM_WALK_XY")
    check("a raw literal resolves too (some maps write $1)",
          sd.move_function("$1") == "SPRITEMOVEFN_RANDOM_WALK_XY")
    check("wandering steps", sd.steps("SPRITEMOVEDATA_WANDER"))
    check("standing does not", not sd.steps("SPRITEMOVEDATA_STANDING_DOWN"))

    print("\nsprites: outdoor sets per map group")
    check("group -> set name", sd.set_names[2] == "TownSprites")
    check("set contents", sd.outdoor_set(2) == ["SPRITE_SAGE", "SPRITE_POKE_BALL"])
    check("db 0 terminates the list", sd.outdoor_set(1) == ["SPRITE_SAGE"])
    check("indoor-only group has an empty set", sd.outdoor_set(3) == [])
    check("a sprite outside the group's set is detectable",
          "SPRITE_POKE_BALL" not in sd.outdoor_set(1))


# --------------------------------------------------------------------------- #
# calibration against the real repo                                           #
# --------------------------------------------------------------------------- #

def test_real_repo() -> None:
    root = Path(__file__).resolve().parent.parent.parent / "pokeprism"
    if not (root / "maps").is_dir():
        print("\n(skipping calibration — ../pokeprism not found)")
        return

    print("\ncalibration: event flags vs the real constants/event_flags.asm")
    ef = eventflags.load(root)
    check("EVENT_1 == 1 (the file's own naming confirms the counter origin)",
          ef.by_name.get("EVENT_1") == 1, str(ef.by_name.get("EVENT_1")))
    check("EVENT_7 == 7", ef.by_name.get("EVENT_7") == 7)
    # Not a pinned count. `free_slots` was asserted == 823 here, which is the
    # number of unallocated `skip`s the repo happened to have the day this was
    # written — and allocating a flag is the most ordinary thing an author
    # does, so the assertion failed on the tree's own progress rather than on
    # a bug (16 skips became named Mt. Ember flags, and the check said 807).
    # What the parser is actually answerable for is the accounting: every slot
    # is either a named flag or a skip, and the counter starts at start_value,
    # so the three have to close on NUM_EVENTS. That holds however many are
    # allocated, and it fails the moment `skips` are miscounted — which is the
    # bug the pinned number was standing in for.
    check("every slot is accounted for: flags + skips + origin == NUM_EVENTS",
          len(ef.flags) + ef.free_slots + ef.start_value == ef.num_events,
          f"{len(ef.flags)} + {ef.free_slots} + {ef.start_value} "
          f"!= {ef.num_events}")
    check("NUM_EVENTS is declared in the file", eventflags.declares_num_events(ef.lines))
    check("round-trip byte-identical",
          ef.to_text() == (root / "constants/event_flags.asm").read_text())
    print(f"      {len(ef.flags)} flags allocated, {ef.free_slots} free, NUM_EVENTS={ef.num_events}")

    print("\ncalibration: every sprite used by every real map resolves")
    sd = spritesets.load(root)
    check("no sprite is missing a header it ought to have", not sd.missing_headers,
          str(sorted(sd.missing_headers)))

    unresolved, counts = [], {"normal": 0, "pokemon": 0, "variable": 0}
    for p in sorted((root / "maps").glob("*.asm")):
        try:
            header = eh.parse_map(p)
        except eh.UnparseableHeader:
            continue
        for obj in header.object_events:
            s = obj.sprite
            if s not in sd.sprite_ids:
                unresolved.append((p.name, s, "unknown constant"))
            elif sd.is_variable_sprite(s):
                counts["variable"] += 1
            elif sd.is_pokemon_sprite(s):
                counts["pokemon"] += 1
            elif sd.header(s):
                counts["normal"] += 1
            else:
                unresolved.append((p.name, s, "no sprite_header"))

    total = sum(counts.values())
    check(f"all {total} objects across every map resolve to a known sprite",
          not unresolved, str(unresolved[:5]))
    print(f"      {counts['normal']} normal, {counts['pokemon']} overworld Pokemon, "
          f"{counts['variable']} variable")

    walking = sum(1 for h in sd.headers.values() if h.walking)
    check("outdoor sprite sets cover the real map groups", len(sd.outdoor_sets) >= 90,
          str(len(sd.outdoor_sets)))
    print(f"      {len(sd.headers)} sprite headers ({walking} walking), "
          f"{len(sd.outdoor_sets)} map groups")


def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        root = _fixture(Path(d))
        test_eventflags(root)
        test_spritesets(root)
    test_real_repo()

    print()
    if _failures:
        print(f"{_failures} check(s) FAILED")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
