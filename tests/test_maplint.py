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


def _fixture(tmp: Path) -> Path:
    root = tmp / "repo"
    for d in ("constants", "data", "engine", "maps"):
        (root / d).mkdir(parents=True)
    (root / "Makefile").write_text("")
    (root / "main.asm").write_text("")

    (root / "constants.asm").write_text(
        "\tconst_def\n\tconst EVENT_0\n"
        'INCLUDE "constants/event_flags.asm"\n'
    )
    (root / "constants" / "event_flags.asm").write_text(
        "\tconst EVENT_REAL\n\tconst EVENT_SHARED\n\tconst skip\n"
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
    )

    sprites = ["SPRITE_NONE", "SPRITE_P0", "SPRITE_NPC", "SPRITE_BALL",
               "SPRITE_STATUE", "SPRITE_STRANGER", *_CROWD]
    (root / "constants" / "sprite_constants.asm").write_text(
        "\tconst_def\n" + "".join(f"\tconst {s}\n" for s in sprites)
        + "SPRITE_POKEMON EQU const_value\n"
        + "const_value = $f0\nSPRITE_VARS EQU const_value\n"
        + "\n; sprite types\nconst_value = 1\n"
        + "\tconst WALKING_SPRITE\n\tconst STANDING_SPRITE\n\tconst STILL_SPRITE\n"
        + "\n; movement data\n\tconst_def\n"
        + "\tconst SPRITEMOVEDATA_STANDING_DOWN\n\tconst SPRITEMOVEDATA_WANDER\n"
    )
    # Positional: the nth sprite_header is sprite id n (SPRITE_NONE has none).
    types = {"SPRITE_P0": "WALKING_SPRITE", "SPRITE_NPC": "WALKING_SPRITE",
             "SPRITE_BALL": "STILL_SPRITE", "SPRITE_STATUE": "STANDING_SPRITE",
             "SPRITE_STRANGER": "WALKING_SPRITE",
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
        "\tmap_header TownA, TILESET_A, TOWN, LANDMARK_A, MUSIC_A, 0, PALETTE_A, FISH_0\n"
        "\tmap_header TownB, TILESET_A, TOWN, LANDMARK_B, MUSIC_A, 0, PALETTE_A, FISH_0\n"
        "\tmap_header CaveC, TILESET_C, CAVE, LANDMARK_C, MUSIC_A, 0, PALETTE_A, FISH_0\n"
        "\tmap_header TownD, TILESET_A, TOWN, LANDMARK_D, MUSIC_A, 0, PALETTE_A, FISH_0\n"
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
                ptype: str = "PERSONTYPE_TEXTFP") -> str:
        return (f"person_event {sprite}, {y}, {x}, {move}, 0, 0, -1, -1, "
                f"PAL_OW_RED, {ptype}, 0, SomeScript, {flag}")

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
          _person("SPRITE_NPC", 6, 6, "SPRITEMOVEDATA_STANDING_DOWN", "EVENT_SHARED")])

    _map("TownB", ["warp_def 1, 1, 1, CAVE_C"],
         [_person("SPRITE_NPC", 1, 1, "SPRITEMOVEDATA_STANDING_DOWN", "EVENT_SHARED")])

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

    # TownD (outdoor, group 3): the group set has 10 walkers, and the player
    # makes 11 — one past what table 1 holds. The map places the one that falls
    # off the end (sprite-vram) and leaves nothing else unplaced, so
    # sprite-vram-budget must NOT also fire here.
    _map("TownD", [], [_person(s, 1, i + 1, "SPRITEMOVEDATA_STANDING_DOWN")
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
    "sprite-outdoor": 1,
    "sprite-static-walker": 1,
    "flag-unknown": 1,
    "flag-shared": 1,
    "sprite-vram": 1,
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


def test_messages(root: Path) -> None:
    print("\nfindings say what is wrong and where")
    by_code = {d.code: d for d in maplint.run(LintContext(root))}

    d = by_code["warp-target"]
    check("warp-target names the valid range", "valid: 1-1" in d.message, d.message)
    check("warp-target points at the warp line", d.path == "maps/TownA.asm" and d.line == 6,
          f"{d.path}:{d.line}")

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

    # A new bug on top of the baseline must still fail.
    path = root / "maps" / "TownB.asm"
    path.write_text(path.read_text().replace(
        "\tdb 1\n\tperson_event", "\tdb 3\n\tperson_event"))
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
        "warp-target": 15,          # warps into a slot the destination doesn't have
        "warp-oneway": 72,          # mostly the shared POKECENTER_BACKROOM — by design
        "obj-count": 4,             # count byte vs entries (see test_eventheader)
        "sprite-vram": 4,           # walkers whose walk frames fall outside VRAM
        "sprite-vram-budget": 4,    # over-full outdoor sprite sets
        "conn-missing": 2,          # one-way connections
        "conn-self": 1,             # ROUTE_69_NORTH's typo'd self-id
        "flag-shared": 10,          # deliberate: one flag gating objects in two maps
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
        test_messages(root)
        test_suppression(root)
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
