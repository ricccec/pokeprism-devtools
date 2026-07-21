#!/usr/bin/env python3
"""Tests for `wiring/blocks.py` and vanilla's item-ball adder.

Three names have to agree for an item ball to work — the label the entry line
points at, the const that gives the object its ordinal, and the event flag that
remembers the ball was picked up — and each of the three has an irregularity a
sensible guess gets wrong. So the hermetic half here is mostly about names, and
each case is one the real tree actually contains:

  * `HP_UP` is `HPUp` and not `HpUp`, so :func:`camel` cannot title-case;
  * the const is prefixed with the map *file stem* (`ROUTE29`) and not with the
    map constant (`ROUTE_29`), which differ for every route;
  * `ELMSLAB_POKE_BALL1..3` exist with no bare `ELMSLAB_POKE_BALL`, so "the
    first free name" puts a fourth ball at the head of the series.

The last two were found by generating a real item ball and reading the diff,
not by any assertion written before it — which is why the real half of this
file generates one into all 388 vanilla maps and re-parses every result.

    python tests/test_blocks.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pokeprism_devtools.hacks.vanilla import actions as fa  # noqa: E402
from pokeprism_devtools.hacks.vanilla import eventblock as eb  # noqa: E402
from pokeprism_devtools.hacks.vanilla.read import label_of  # noqa: E402
from pokeprism_devtools.studio.actions import ActionError  # noqa: E402
from pokeprism_devtools.wiring import blocks as B  # noqa: E402

VANILLA = Path.home() / "code/ricccec/pokecrystal"

_failures = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global _failures
    ok = bool(cond)
    if not ok:
        _failures += 1
    print(f"  {'ok  ' if ok else 'FAIL'} {label}"
          f"{(': ' + detail) if detail and not ok else ''}")


def test_names() -> None:
    print("names — the three that have to agree")

    check("camel keeps the acronyms whole",
          [B.camel(n) for n in ("HYPER_POTION", "HP_UP", "TM_ENDURE",
                                "PP_UP", "HM_WATERFALL")]
          == ["HyperPotion", "HPUp", "TMEndure", "PPUp", "HMWaterfall"],
          str([B.camel(n) for n in ("HYPER_POTION", "HP_UP", "TM_ENDURE")]))

    # The const prefix. Both spellings exist for the same map and only one is
    # the one the file uses; the other is unique precisely because it is wrong,
    # so no uniqueness check catches it.
    check("the const is prefixed with the file stem, not the map constant",
          B.object_const(["ROUTE29_POKE_BALL"], "Route29", "POKE_BALL")
          == "ROUTE29_POKE_BALL2",
          B.object_const(["ROUTE29_POKE_BALL"], "Route29", "POKE_BALL"))

    # Elm's Lab: POKE_BALL1..3 and no bare one. The unnumbered name is free and
    # taking it puts the fourth ball at the head of the series.
    check("a numbered series continues rather than back-filling its bare name",
          B.object_const(["ELMSLAB_POKE_BALL1", "ELMSLAB_POKE_BALL2",
                          "ELMSLAB_POKE_BALL3"], "ElmsLab", "POKE_BALL")
          == "ELMSLAB_POKE_BALL4")
    check("but a gap inside the series is filled",
          B.object_const(["A_POKE_BALL1", "A_POKE_BALL3"], "A", "POKE_BALL")
          == "A_POKE_BALL2")
    check("and a map with no ball at all gets the unnumbered name",
          B.object_const(["ROUTE29_TUSCANY"], "Route29", "POKE_BALL")
          == "ROUTE29_POKE_BALL")

    check("the flag default is EVENT_<map>_<item>",
          B.flag_name("ROUTE_29", "POTION") == "EVENT_ROUTE_29_POTION")
    # Two balls on one flag vanish together, so the second is never
    # collectable. No vanilla map has two of the same item, so the tree offers
    # no precedent — the semantics do.
    check("a defaulted flag that collides is suffixed, not shared",
          B.flag_name("ROUTE_29", "POTION", {"EVENT_ROUTE_29_POTION"})
          == "EVENT_ROUTE_29_POTION_2")

    text = "Foo:\n\tret\nFooPotion:\n\tret\n.Local:\n"
    check("a label already in the file is suffixed, not reused",
          B.unique_label(text, "FooPotion") == "FooPotion2")
    check("a free label is left alone", B.unique_label(text, "FooEther")
          == "FooEther")
    check("a local label is not a collision",
          B.unique_label(text, "Local") == "Local")


def test_block() -> None:
    print("the block — two lines, and the quantity that is usually absent")
    check("one of something writes no count",
          B.itemball("FooPotion", "POTION") == ["FooPotion:", "\titemball POTION"])
    check("more than one does",
          B.itemball("FooPotion", "POTION", 5)[1] == "\titemball POTION, 5")
    for bad, why in ((0, "at least one"), (100, "one byte")):
        try:
            B.itemball("F", "POTION", bad)
            check(f"a quantity of {bad} is refused", False, "no refusal")
        except B.BlockError as exc:
            check(f"a quantity of {bad} is refused", why in str(exc), str(exc))


def test_dialects() -> None:
    """Polished spells an item ball as three extra `object_event` arguments,
    with no block anywhere — so the adder that writes a block must not be on
    offer there. This is the seam working: one declaration, not a branch."""
    print("dialects — the adder is vanilla's, and only vanilla's")
    check("vanilla offers the item ball", len(fa.VANILLA_ADDERS["object"]) == 1)
    check("polished does not", fa.POLISHED_ADDERS.get("object") is None)
    check("both still offer the four line-only adders",
          all(k in fa.VANILLA_ADDERS and k in fa.POLISHED_ADDERS
              for k in ("NPC", "warp", "signpost", "trigger")))
    check("and the layout is stamped per dialect, not shared",
          fa.VANILLA_ADDERS["NPC"][0].layout
          is not fa.POLISHED_ADDERS["NPC"][0].layout)


def test_real() -> None:
    """Generate an item ball into every vanilla map and re-parse the result.

    Nothing is written: an `Action` returns staged edits, so this runs against
    the real tree and touches none of it. What it checks is the thing a green
    unit test could not — that the file that comes out is one the parser reads
    back with exactly one more object, exactly one more const, and every other
    list the length it was.
    """
    print("vanilla — an item ball into all 388 maps")
    if not (VANILLA / "maps").exists():
        check("vanilla tree is present", False, str(VANILLA))
        return
    add = fa.VANILLA_ADDERS["object"][0]
    ok = refused = 0
    trouble: list[str] = []
    for const, label in sorted(label_of(VANILLA).items()):
        try:
            result = add(const, y="1", x="1", item="HP_UP").run(VANILLA)
        except ActionError as exc:
            refused += 1
            if "has no objects yet" not in str(exc):
                trouble.append(f"{label}: {exc}")
            continue
        try:
            _one_map(VANILLA, label, result)
        except AssertionError as exc:
            trouble.append(f"{label}: {exc}")
            continue
        ok += 1
    check(f"{ok} maps take an item ball and re-parse clean", not trouble,
          "; ".join(trouble[:3]))
    check("the 40 refusals are all the same, named reason", refused == 40,
          f"{refused} refused")
    print(f"       ({ok} written, {refused} refused for having no objects)")


def _one_map(root: Path, label: str, result) -> None:
    edits = {e.path: e for e in result.edits}
    rel = f"maps/{label}.asm"
    assert rel in edits, f"no edit to {rel}"
    assert "constants/event_flags.asm" in edits, "no flag was allocated"
    after = edits[rel]
    before = eb.parse_map(root / rel, "_MapEvents")
    block = eb.parse_text(after.new_text, root / rel, "_MapEvents")

    objects = block.lists["object"].entries
    assert len(objects) == len(before.lists["object"].entries) + 1, "object count"
    assert len(block.names) == len(before.names) + 1, "const count"
    # The invariant the whole named-identity contract rests on, and the one a
    # const spliced at the wrong line number would break silently.
    assert len(block.names) == len(objects), "consts no longer parallel"
    for kind in ("warp", "coord", "bg"):
        assert len(block.lists[kind].entries) \
            == len(before.lists[kind].entries), f"{kind} list moved"

    entry = objects[-1]
    script, flag = entry.args[-2], entry.args[-1]
    assert entry.args[9] == "OBJECTTYPE_ITEMBALL", entry.args[9]
    assert flag != "-1", "a ball with no flag can be picked up forever"
    # The block exists, and it is on the scripts side of the event header. The
    # other side is inside the warp list, which assembles and gives the map the
    # wrong doors.
    at = after.new_text.find(f"\n{script}:")
    assert at != -1, f"{script} is pointed at but never defined"
    assert at < after.new_text.index("def_warp_events"), \
        f"{script} landed past the event header"
    assert re.search(rf"\n{script}:\n\titemball HP_UP\n", after.new_text), \
        "the block is not the two lines it should be"


def test_second_ball() -> None:
    """Burned Tower 1F already holds an HP Up. Adding another exercises all
    three collision paths at once — the label, the const and the flag."""
    print("a second ball of the same item — every name collides at once")
    if not (VANILLA / "maps/BurnedTower1F.asm").exists():
        check("BurnedTower1F is present", False)
        return
    add = fa.VANILLA_ADDERS["object"][0]
    result = add("BURNED_TOWER_1F", y="4", x="6", item="HP_UP").run(VANILLA)
    text = next(e.new_text for e in result.edits if e.path.startswith("maps/"))
    block = eb.parse_text(text, VANILLA / "maps/BurnedTower1F.asm", "_MapEvents")
    entry = block.lists["object"].entries[-1]

    check("the label is suffixed rather than redefined",
          entry.args[-2] == "BurnedTower1FHPUp2", entry.args[-2])
    check("the flag is a new one, so the two balls do not vanish together",
          entry.args[-1] == "EVENT_BURNED_TOWER_1F_HP_UP_2", entry.args[-1])
    check("a flag file edit is staged for it",
          any(e.path.endswith("event_flags.asm") for e in result.edits))
    check("the const continues the map's series",
          block.names[-1][0].startswith("BURNEDTOWER1F_POKE_BALL"),
          block.names[-1][0])

    # A flag the caller names is a flag the caller gets, sharing and all.
    shared = add("BURNED_TOWER_1F", y="4", x="6", item="HP_UP",
                 flag="EVENT_BURNED_TOWER_1F_HP_UP").run(VANILLA)
    check("but a flag typed by hand is used as typed, and said out loud",
          all(not e.path.endswith("event_flags.asm") for e in shared.edits)
          and any("vanish together" in n for n in shared.notes),
          str(shared.notes))


def test_falsified() -> None:
    """The real sweep asserts the block lands before the event header. Prove
    that assertion can fail — hand the adder the other tree's layout and it
    should splice into the warps, which is the failure the check exists for."""
    print("falsification — is the layout doing any work?")
    if not (VANILLA / "maps").exists():
        check("vanilla tree is present", False, str(VANILLA))
        return
    from pokeprism_devtools.wiring import regions

    wrong = type("Wrong", (fa.VANILLA_ADDERS["object"][0],),
                 {"layout": regions.POLISHED})
    result = wrong("ROUTE_29", y="1", x="1", item="POTION").run(VANILLA)
    text = next(e.new_text for e in result.edits if e.path.startswith("maps/"))
    at = text.find("\nRoute29Potion2:")
    check("the wrong layout puts the block past the event header, as feared",
          at > text.index("def_warp_events"),
          "the block landed correctly even with the wrong layout — the sweep's "
          "placement check is not testing placement")


if __name__ == "__main__":
    test_names()
    test_block()
    test_dialects()
    test_real()
    test_second_ball()
    test_falsified()
    print(f"\n{'FAILURES: ' + str(_failures) if _failures else 'all ok'}")
    sys.exit(1 if _failures else 0)
