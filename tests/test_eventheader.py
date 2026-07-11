#!/usr/bin/env python3
"""Tests for the map event-header parser and round-trip-safe writer.

Hermetic fixtures cover the shapes that actually occur in pokeprism (labelled,
label-less, inline counts, alias labels, miscounted lists). If ../pokeprism is
present, the gold test also runs the real thing: parse every maps/*.asm and
re-emit it byte-identically — the contract everything else in the studio rests
on.

    python tests/test_eventheader.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pokeprism_devtools.shared import eventheader as eh  # noqa: E402
from pokeprism_devtools.shared.eventheader import ListKind, UnparseableHeader  # noqa: E402

_failures = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global _failures
    mark = "OK  " if cond else "FAIL"
    print(f"  [{mark}] {label}{(': ' + detail) if detail else ''}")
    if not cond:
        _failures += 1


# --------------------------------------------------------------------------- #
# fixtures — each is a shape that really occurs under pokeprism/maps/          #
# --------------------------------------------------------------------------- #

LABELLED = """\
TownScript:
\tctxt "Hi."
\tdone

Town_MapEventHeader:: db 0, 0

.Warps
\tdb 2
\twarp_def 29, 35, 1, CASTRO_GATE
\twarp_def 11, 8, 2, ROUTE_62_GATE

.CoordEvents
\tdb 0

.BGEvents
\tdb 1
\tsignpost 2, 5, SIGNPOST_ITEM, Town_GoldToken

.ObjectEvents
\tdb 2
\tperson_event SPRITE_SAGE, 9, 25, SPRITEMOVEDATA_STANDING_RIGHT, 0, 0, -1, -1, 8 + PAL_OW_BLUE, PERSONTYPE_GENERICTRAINER, 2, Town_Trainer_1, -1
\tperson_event SPRITE_POKE_BALL, 28, 27, SPRITEMOVEDATA_ITEM_TREE, 0, 0, -1, -1, PAL_OW_RED, PERSONTYPE_ITEMBALL, 3, SITRUS_BERRY, EVENT_TOWN_ITEM
"""

# 146 maps look like this: no list labels at all, just comments.
LABELLESS = """\
Cave_MapEventHeader:: db 0, 0

\t;warps
\tdb 1
\twarp_def 25, 8, 2, FARAWAY_ISLAND_OUTSIDE

\t;xy triggers
\tdb 0

\t;signposts
\tdb 0

\t;people-events
\tdb 1
\tperson_event SPRITE_MEW, 10, 13, SPRITEMOVEDATA_WANDER, 0, 0, -1, -1, PAL_OW_PURPLE, PERSONTYPE_SCRIPT, 0, CaveMew, EVENT_MEW
"""

# Counts inlined on the label; alias label stacked on top (MoundB2F-style).
INLINE_AND_ALIAS = """\
Airport_MapEventHeader::
AirportDark_MapEventHeader:: db 0, 0

.Warps: db 1
\twarp_def  0, 17, 1, MYSTERY_ZONE

.CoordEvents: db 0

.BGEvents: db 0

.ObjectEvents: db 1
\tperson_event SPRITE_OFFICER,  8,  3, SPRITEMOVEDATA_STANDING_DOWN, 0, 0, -1, -1, PAL_OW_YELLOW, PERSONTYPE_SCRIPT, 0, AirportNPC, -1
"""

# Real bugs from pokeprism: over-declared count (EagulouCity), and a
# commented-out entry left behind (MtEmberRoom1).
OVERDECLARED = """\
Bad_MapEventHeader:: db 0, 0

.Warps
\tdb 0

.CoordEvents
\tdb 0

.BGEvents
\tdb 0

.ObjectEvents
\tdb 3
\t; person_event SPRITE_MINER, 5, 11, SPRITEMOVEDATA_STANDING_RIGHT, 0, 0, -1, -1, PAL_OW_RED, PERSONTYPE_TEXTFP, 0, BadNPC, -1
\tperson_event SPRITE_COOLTRAINER_M, 7, 5, SPRITEMOVEDATA_STANDING_RIGHT, 0, 0, -1, -1, PAL_OW_RED, PERSONTYPE_TEXTFP, 0, BadNPC, -1
"""

# Under-declared count (PhloxLab1F): the trailing entry never spawns.
UNDERDECLARED = OVERDECLARED.replace("\tdb 3\n\t; person_event", "\tdb 0\n\t; person_event")

NO_HEADER = "SomeScript:\n\tctxt \"just a script include\"\n\tdone\n"


def _write(tmp: Path, name: str, text: str) -> Path:
    p = tmp / name
    p.write_text(text)
    return p


# --------------------------------------------------------------------------- #
# tests                                                                       #
# --------------------------------------------------------------------------- #

def test_parse_shapes(tmp: Path) -> None:
    print("\nparsing the shapes that occur in the real repo")

    h = eh.parse_map(_write(tmp, "Town.asm", LABELLED))
    check("labelled: label", h.label == "Town", h.label)
    check("labelled: 2 warps / 0 coord / 1 bg / 2 objects",
          (len(h.warps), len(h.coord_events), len(h.bg_events), len(h.object_events)) == (2, 0, 1, 2))
    check("labelled: counts all agree with entries",
          all(h.lists[k].count_matches for k in ListKind))

    h = eh.parse_map(_write(tmp, "Cave.asm", LABELLESS))
    check("label-less (comments only): 1 warp, 1 object",
          (len(h.warps), len(h.object_events)) == (1, 1))

    h = eh.parse_map(_write(tmp, "Airport.asm", INLINE_AND_ALIAS))
    check("inline counts + alias label: 1 warp, 1 object",
          (len(h.warps), len(h.object_events)) == (1, 1))
    check("alias label: the *last* header line is the anchor",
          h.label == "AirportDark", h.label)


def test_typed_accessors(tmp: Path) -> None:
    print("\ntyped accessors over verbatim args")
    h = eh.parse_map(_write(tmp, "Town.asm", LABELLED))
    trainer, ball = h.object_events

    check("sprite / y / x", (trainer.sprite, trainer.y, trainer.x) == ("SPRITE_SAGE", 9, 25))
    check("persontype", trainer.persontype == "PERSONTYPE_GENERICTRAINER")
    check("expressions survive verbatim", trainer.args[8] == "8 + PAL_OW_BLUE", trainer.args[8])
    check("script pointer", trainer.script_pointer == "Town_Trainer_1")
    check("event flag is the last arg, whatever the tail shape",
          (trainer.event_flag, ball.event_flag) == ("-1", "EVENT_TOWN_ITEM"))
    check("itemball tail: pointer slot holds the item",
          ball.script_pointer == "SITRUS_BERRY")

    warp = h.warps[0]
    check("warp_def args", warp.args == ["29", "35", "1", "CASTRO_GATE"], str(warp.args))


def test_round_trip_identity(tmp: Path) -> None:
    print("\nround-trip identity (the contract)")
    for name, text in [("Town.asm", LABELLED), ("Cave.asm", LABELLESS),
                       ("Airport.asm", INLINE_AND_ALIAS), ("Bad.asm", OVERDECLARED)]:
        h = eh.parse_map(_write(tmp, name, text))
        check(f"{name}: unmodified re-emit is byte-identical", h.to_text() == text)


def test_miscounts_are_findings_not_failures(tmp: Path) -> None:
    print("\na wrong count byte is a lint finding, not a parse failure")

    h = eh.parse_map(_write(tmp, "Bad.asm", OVERDECLARED))
    objs = h.lists[ListKind.OBJECT_EVENTS]
    check("over-declared map still parses", len(h.object_events) == 1)
    check("commented-out entry is not counted as present", objs.declared_count == 3)
    check("count_matches is False -> lint can fire", not objs.count_matches)
    check("other lists unaffected", h.lists[ListKind.WARPS].count_matches)

    h = eh.parse_map(_write(tmp, "Under.asm", UNDERDECLARED))
    objs = h.lists[ListKind.OBJECT_EVENTS]
    check("under-declared: entry past the count is recorded as a stray",
          len(objs.strays) == 1 and objs.declared_count == 0, f"strays={objs.strays}")
    check("under-declared: count_matches is False", not objs.count_matches)

    h.fix_count(ListKind.OBJECT_EVENTS)
    check("fix_count absorbs the stray and makes the list consistent",
          h.lists[ListKind.OBJECT_EVENTS].count_matches
          and h.lists[ListKind.OBJECT_EVENTS].declared_count == 1)


def test_unparseable(tmp: Path) -> None:
    print("\nunparseable maps degrade to unmanaged, never mis-written")
    try:
        eh.parse_map(_write(tmp, "NoHeader.asm", NO_HEADER))
        check("a file with no event header raises", False)
    except UnparseableHeader:
        check("a file with no event header raises", True)

    missing_count = LABELLED.replace(".ObjectEvents\n\tdb 2\n", ".ObjectEvents\n")
    try:
        eh.parse_map(_write(tmp, "NoCount.asm", missing_count))
        check("a list with no count byte at all raises", False)
    except UnparseableHeader:
        check("a list with no count byte at all raises", True)


def test_writes(tmp: Path) -> None:
    print("\nwrites splice into the recorded spans and nothing else")
    path = _write(tmp, "Town.asm", LABELLED)

    h = eh.parse_map(path)
    h.add_entry(ListKind.WARPS, ["5", "6", "1", "NEW_MAP"])
    text = h.to_text()
    check("added warp is appended after the last warp",
          text.index("warp_def 5, 6, 1, NEW_MAP") > text.index("warp_def 11, 8, 2, ROUTE_62_GATE"))
    check("count byte bumped to 3", "\tdb 3\n\twarp_def 29" in text)
    check("re-parses with 3 warps and a consistent count",
          len(h.warps) == 3 and h.lists[ListKind.WARPS].count_matches)
    check("script code above the header is untouched", text.startswith(LABELLED[:LABELLED.index("Town_MapEventHeader")]))
    check("other lists' lines are byte-identical",
          "\tsignpost 2, 5, SIGNPOST_ITEM, Town_GoldToken" in text
          and "8 + PAL_OW_BLUE" in text)

    # add + remove is a true inverse: back to byte-identical.
    h.remove_entry(ListKind.WARPS, 2)
    check("add then remove restores the file byte-for-byte", h.to_text() == LABELLED)

    # empty list: the entry must land under the count, not float away.
    h = eh.parse_map(path)
    h.add_entry(ListKind.COORD_EVENTS, ["1", "4", "7", "SomeScript"])
    check("first entry of an empty list lands directly under its count",
          "\tdb 1\n\txy_trigger 1, 4, 7, SomeScript" in h.to_text())

    h = eh.parse_map(path)
    h.replace_entry(ListKind.WARPS, 0, ["1", "2", "3", "OTHER_MAP"])
    check("replace rewrites in place, count unchanged",
          "warp_def 1, 2, 3, OTHER_MAP" in h.to_text()
          and h.lists[ListKind.WARPS].declared_count == 2)

    h = eh.parse_map(path)
    edit = h.to_edit(tmp, "no changes")
    check("to_edit on an untouched header reports changed=False", not edit.changed)
    h.add_entry(ListKind.BG_EVENTS, ["1", "1", "SIGNPOST_READ", "Sign"])
    edit = h.to_edit(tmp, "added a signpost")
    check("to_edit after a change carries the full new text",
          edit.changed and "signpost 1, 1, SIGNPOST_READ, Sign" in edit.new_text)


def test_inline_count_write(tmp: Path) -> None:
    print("\nwriting into a map whose count is inlined on the label")
    h = eh.parse_map(_write(tmp, "Airport.asm", INLINE_AND_ALIAS))
    h.add_entry(ListKind.WARPS, ["3", "4", "2", "OTHER"])
    check("the inline label survives the count bump",
          ".Warps: db 2" in h.to_text(), _line_with(h.to_text(), ".Warps"))
    check("entry inserted under it", "\twarp_def 3, 4, 2, OTHER" in h.to_text())


def _line_with(text: str, needle: str) -> str:
    return next((ln for ln in text.split("\n") if needle in ln), "")


# --------------------------------------------------------------------------- #
# gold test — the real repo                                                   #
# --------------------------------------------------------------------------- #

def test_real_repo() -> None:
    root = Path(__file__).resolve().parent.parent.parent / "pokeprism"
    if not (root / "maps").is_dir():
        print("\n(skipping gold test — ../pokeprism not found)")
        return

    print("\ngold test: every real map parses and re-emits byte-identically")
    maps = sorted((root / "maps").glob("*.asm"))
    parsed, unmanaged, corrupted = [], [], []
    miscounts = []

    for p in maps:
        try:
            h = eh.parse_map(p)
        except UnparseableHeader:
            unmanaged.append(p.name)
            continue
        parsed.append(p.name)
        if h.to_text() != p.read_text():
            corrupted.append(p.name)
        for kind in ListKind:
            lst = h.lists[kind]
            if not lst.count_matches:
                miscounts.append(f"{p.name} {kind.value}: db {lst.declared_count} vs "
                                 f"{len(lst.entries)} entries"
                                 + (f" +{len(lst.strays)} past the count" if lst.strays else ""))

    check(f"parsed {len(parsed)}/{len(maps)} map files", len(parsed) >= 450, f"{len(parsed)}")
    check("EVERY parsed map re-emits byte-identically",
          not corrupted, f"{len(corrupted)} corrupted: {corrupted[:3]}")
    check("unmanaged files are only script-includes and index files",
          all(n.startswith("LaurelForestPokemonOnly_")
              or n in {"blockdata.asm", "map_headers.asm", "map_scripts.asm",
                       "map_triggers.asm", "second_map_headers.asm",
                       "HaywardMartElevator.asm"}
              for n in unmanaged),
          f"{len(unmanaged)}: {unmanaged}")

    # Real, pre-existing bugs in pokeprism: the count byte is what the engine
    # trusts, so each is a phantom or a never-spawning object at runtime. Held
    # as a baseline of known-bad *maps* rather than a count — fixing one of them
    # upstream must not fail this test, but a map joining the list must.
    known_bad = {
        "EagulouCity.asm",              # db 4, 3 objects
        "MtEmberRoom1.asm",             # db 2, 1 live object (one commented out)
        "MysteryZoneLeagueAirport.asm", # db 3, 1 object
        "PhloxLab1F.asm",               # db 6, 7 objects — the 7th never spawns
        "SaffronCopycatsHouse.asm",     # db 4, 5 objects — the 5th never spawns
    }
    print(f"\n  pokeprism count-byte bugs found ({len(miscounts)}):")
    for m in miscounts:
        print(f"      {m}")
    offenders = {m.split()[0] for m in miscounts}
    check("no map has newly acquired a count-byte bug",
          offenders <= known_bad, f"new: {sorted(offenders - known_bad)}")
    if fixed := known_bad - offenders:
        print(f"      ({len(fixed)} since fixed upstream: {', '.join(sorted(fixed))})")


def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        test_parse_shapes(tmp)
        test_typed_accessors(tmp)
        test_round_trip_identity(tmp)
        test_miscounts_are_findings_not_failures(tmp)
        test_unparseable(tmp)
        test_writes(tmp)
        test_inline_count_write(tmp)
    test_real_repo()

    print()
    if _failures:
        print(f"{_failures} check(s) FAILED")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
