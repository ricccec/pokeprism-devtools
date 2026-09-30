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

import os
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

#: The prism checkout, resolved absolutely and never relative to this repo — a
#: path that walks above it answers differently depending on where the repo sits.
#: The skip below is the reason that matters: an absent tree prints `all checks
#: passed` for a file whose real half never ran.
PRISM = Path(os.environ.get("POKEPRISM_TREE",
                            Path.home() / "code/ricccec/pokeprism"))


from pokeprism_devtools import maplint  # noqa: E402
from pokeprism_devtools.maplint.context import LintContext  # noqa: E402
from pokeprism_devtools.contract import Severity  # noqa: E402

_failures = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global _failures
    mark = "OK  " if cond else "FAIL"
    print(f"  [{mark}] {label}{(': ' + detail) if detail else ''}")
    if not cond:
        _failures += 1


#: The fixture moved to a module so the integration repo can build the same
#: tree; the finding counts below are counts *of it*, so the two cannot
#: disagree without one of them failing.
from prism_fixture import _CROWD, _fixture, _text_engine  # noqa: E402,F401



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
    root = PRISM
    if not (root / "maps").is_dir():
        print(f"\n(skipping real-repo pass — no prism tree at {PRISM})")
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
