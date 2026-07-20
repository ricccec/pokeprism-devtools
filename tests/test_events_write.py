#!/usr/bin/env python3
"""Tests for the family's `def_*` event writer (`hacks/vanilla/eventblock.py`).

The contract under test is the one the module states: the file is held
verbatim and mutations splice single lines, so an unmodified block
serializes byte-identical, a removal takes exactly the entry line (plus, for
a named object, its `const` — named identity), and code outside the spliced
lines is never touched — above the tail block in vanilla, *below* the head
block in polished. If real checkouts sit next to this repo, every map in
both is round-tripped.

    python tests/test_events_write.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pokeprism_devtools.hacks.vanilla import eventblock as eb  # noqa: E402

FAILED = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global FAILED
    print(f"  [{'OK  ' if cond else 'FAIL'}] {label}{f' — {detail}' if detail else ''}")
    if not cond:
        FAILED += 1


# --------------------------------------------------------------------------- #
# fixtures — a tail-block file (vanilla) and a head-block file (polished)     #
# --------------------------------------------------------------------------- #

_TAIL = """\
\tobject_const_def
\tconst TOWNA_TEACHER
\tconst TOWNA_YOUNGSTER

TownA_MapScripts:
\tdef_scene_scripts

\tdef_callbacks

TownATeacherScript:
\tjumptextfaceplayer TownATeacherText

TownATeacherText:
\ttext "Hello."
\tdone

TownA_MapEvents:
\tdb 0, 0 ; filler

\tdef_warp_events
\twarp_event  3,  5, TOWN_B, 1

\tdef_coord_events

\tdef_bg_events
\tbg_event  4,  4, BGEVENT_READ, TownASign

\tdef_object_events
\tobject_event  5,  7, SPRITE_TEACHER, SPRITEMOVEDATA_STANDING_DOWN, 0, 0, -1, -1, 0, OBJECTTYPE_SCRIPT, 0, TownATeacherScript, -1
\tobject_event  8,  2, SPRITE_YOUNGSTER, SPRITEMOVEDATA_SPINRANDOM_SLOW, 0, 0, -1, -1, 0, OBJECTTYPE_SCRIPT, 0, TownATeacherScript, -1
"""

_HEAD = """\
TownH_MapScriptHeader:
\tdef_scene_scripts

\tdef_callbacks

\tdef_warp_events
\twarp_event  6, 23, AZALEA_TOWN, 5

\tdef_coord_events

\tdef_bg_events

\tdef_object_events
\tobject_event  2, 18, SPRITE_CART, SPRITEMOVEDATA_STANDING_DOWN, 0, 0, -1, 0, OBJECTTYPE_SCRIPT, 0, CartScript, -1
\tobject_event  7,  3, SPRITE_BUGSY, SPRITEMOVEDATA_STANDING_DOWN, 0, 0, -1, 0, OBJECTTYPE_SCRIPT, 0, BugsyScript, -1

\tobject_const_def
\tconst TOWNH_CART

CartScript:
\tjumptextfaceplayer CartText

CartText:
\ttext "Careful."
\tdone
"""


def _block(text: str, anchor: str) -> eb.EventBlock:
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "Town.asm"
        p.write_text(text, encoding="utf-8")
        return eb.parse_map(p, anchor)


# --------------------------------------------------------------------------- #
# the round-trip contract                                                     #
# --------------------------------------------------------------------------- #

def test_round_trip() -> None:
    print("an unmodified block serializes byte-identical")
    for name, text, anchor in (("tail", _TAIL, "_MapEvents"),
                               ("head", _HEAD, "_MapScriptHeader")):
        b = _block(text, anchor)
        check(f"{name} block round-trips", b.to_text() == text)


def test_parse_shape() -> None:
    print("\nthe parse sees the lists and the names")
    b = _block(_TAIL, "_MapEvents")
    check("four lists", sorted(b.lists) == sorted(eb.LIST_ORDER))
    check("one warp, one bg, two objects, no coords",
          [len(b.lists[k].entries) for k in ("warp", "coord", "bg", "object")]
          == [1, 0, 1, 2])
    check("both objects are named",
          [n for n, _ in b.names] == ["TOWNA_TEACHER", "TOWNA_YOUNGSTER"])
    check("a name resolves to its position", b.index_of("TOWNA_YOUNGSTER") == 1)
    check("the unnamed tail answers empty", b.name_of(5) == "")

    h = _block(_HEAD, "_MapScriptHeader")
    check("head: partial naming is read as written",
          [n for n, _ in h.names] == ["TOWNH_CART"]
          and len(h.lists["object"].entries) == 2)


# --------------------------------------------------------------------------- #
# removal — the entry line, and named identity                                #
# --------------------------------------------------------------------------- #

def test_remove_named_object() -> None:
    print("\nremoving a named object takes its const with it, and nothing else")
    b = _block(_TAIL, "_MapEvents")
    name = b.remove_entry("object", 0)
    check("the removed const is reported", name == "TOWNA_TEACHER")
    want = [ln for ln in _TAIL.split("\n")
            if "const TOWNA_TEACHER" not in ln
            and "object_event  5,  7" not in ln]
    check("exactly two lines are gone", b.to_text() == "\n".join(want))
    check("the survivor's name still points at it",
          b.index_of("TOWNA_YOUNGSTER") == 0
          and "SPRITE_YOUNGSTER" in b.lists["object"].entries[0].raw)


def test_remove_unnamed_tail() -> None:
    print("\nremoving from the unnamed tail touches no const")
    b = _block(_HEAD, "_MapScriptHeader")
    name = b.remove_entry("object", 1)          # BUGSY, past the one const
    check("no const reported", name == "")
    check("the const list is untouched", [n for n, _ in b.names] == ["TOWNH_CART"])
    check("the entry is gone", len(b.lists["object"].entries) == 1)


def test_head_splice_leaves_scripts_alone() -> None:
    print("\nthe head splice: everything below the block is never touched")
    b = _block(_HEAD, "_MapScriptHeader")
    b.remove_entry("warp", 0)
    got, want = b.to_text().split("\n"), _HEAD.split("\n")
    tail_at = want.index("CartScript:")
    check("the scripts below are byte-identical",
          got[-(len(want) - tail_at):] == want[tail_at:])
    check("only the warp line is gone",
          got == [ln for ln in want if not ln.strip().startswith("warp_event ")])


# --------------------------------------------------------------------------- #
# adding and replacing                                                        #
# --------------------------------------------------------------------------- #

def test_add() -> None:
    print("\nadding appends the entry — and there is no count to bump")
    b = _block(_TAIL, "_MapEvents")
    e = b.add_entry("warp", ["4", "5", "TOWN_C", "2"])
    check("the entry landed under the last warp",
          e.raw == "\twarp_event  4,  5, TOWN_C, 2"
          and len(b.lists["warp"].entries) == 2)
    check("an empty list takes its first entry after the def line",
          b.add_entry("coord", ["1", "2", "0", "SceneScript"]).lineno
          == b.lists["coord"].def_lineno + 1)

    named = b.add_entry("object", ["1", "1", "SPRITE_LASS", "SPRITEMOVEDATA_STANDING_DOWN",
                                   "0", "0", "-1", "-1", "0", "OBJECTTYPE_SCRIPT", "0",
                                   "TownATeacherScript", "-1"], name="TOWNA_LASS")
    check("a named object gets a const in step",
          named.raw.startswith("\tobject_event  1,  1, SPRITE_LASS")
          and b.index_of("TOWNA_LASS") == 2)

    h = _block(_HEAD, "_MapScriptHeader")
    try:
        h.add_entry("object", ["1", "1", "X"], name="TOWNH_NEW")
        check("a partially-named list refuses a name", False)
    except eb.UnparseableEvents as exc:
        check("a partially-named list refuses a name", "positional" in str(exc))


def test_replace() -> None:
    print("\nreplacing rewrites one line in place")
    b = _block(_TAIL, "_MapEvents")
    before = len(b.lines)
    b.replace_entry("warp", 0, ["3", "5", "TOWN_C", "9"])
    check("same line count, new args",
          len(b.lines) == before
          and b.lists["warp"].entries[0].args == ["3", "5", "TOWN_C", "9"])


# --------------------------------------------------------------------------- #
# the real trees, when they are around                                        #
# --------------------------------------------------------------------------- #

def test_real_trees() -> None:
    for rel, anchor in (("../pokecrystal", "_MapEvents"),
                        ("../polishedcrystal", "_MapScriptHeader")):
        root = Path(__file__).resolve().parent.parent.parent / rel.lstrip("./")
        root = (Path(__file__).resolve().parent.parent / rel).resolve()
        if not (root / "maps").is_dir():
            print(f"\n({root.name} is not checked out next door — skipped)")
            continue
        print(f"\nevery map in {root.name} round-trips byte-identical")
        total = skipped = broken = 0
        for p in sorted((root / "maps").glob("*.asm")):
            text = p.read_text(encoding="utf-8")
            try:
                b = eb.parse_text(text, p, anchor)
            except eb.UnparseableEvents:
                skipped += 1
                continue
            total += 1
            if b.to_text() != text:
                broken += 1
        check(f"{total} maps round-trip, {skipped} without the anchor skipped",
              total > 100 and broken == 0, f"{broken} broke")


def main() -> int:
    test_round_trip()
    test_parse_shape()
    test_remove_named_object()
    test_remove_unnamed_tail()
    test_head_splice_leaves_scripts_alone()
    test_add()
    test_replace()
    test_real_trees()
    print(f"\n{'all checks passed' if not FAILED else f'{FAILED} check(s) FAILED'}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
