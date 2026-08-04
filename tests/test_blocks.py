#!/usr/bin/env python3
"""Tests for `asmedit/blocks.py` and vanilla's item-ball adder.

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
from pokeprism_devtools.contract import ActionError  # noqa: E402
from pokeprism_devtools.asmedit import blocks as B  # noqa: E402

VANILLA = Path.home() / "code/ricccec/pokecrystal"
POLISHED = Path.home() / "code/ricccec/polishedcrystal"

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
    """Polished spells an item ball, a fruit tree and a hidden item all as
    inline `object_event`/`bg_event` arguments, with no block and no table
    anywhere — so the three adders that write a *block* are vanilla's alone.
    Polished offers its own two on the same tab, line-only where vanilla's write
    a block: a ball and a hidden item, but no fruit tree (it has no
    `fruit_trees.asm` to point an id into). This is the seam working: two
    declarations, `VANILLA_ONLY` and `POLISHED_ONLY`, not a branch."""
    print("dialects — the block adders are vanilla's, the line ones fork")
    offered = {c.__name__.removeprefix("Vanilla")
               for c in fa.VANILLA_ADDERS["object"]}
    check("vanilla offers the item ball, the fruit tree and the hidden item",
          offered == {"AddItemball", "AddFruittree", "AddHiddenitem"}, str(offered))
    polished = {c.name for c in fa.POLISHED_ADDERS.get("object", ())}
    check("polished offers its own ball and hidden item, line-only, no fruit tree",
          polished == {"itemball", "hiddenitem"}, str(polished))
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
    from pokeprism_devtools.asmedit import regions

    wrong = type("Wrong", (fa.VANILLA_ADDERS["object"][0],),
                 {"layout": regions.POLISHED})
    result = wrong("ROUTE_29", y="1", x="1", item="POTION").run(VANILLA)
    text = next(e.new_text for e in result.edits if e.path.startswith("maps/"))
    at = text.find("\nRoute29Potion2:")
    check("the wrong layout puts the block past the event header, as feared",
          at > text.index("def_warp_events"),
          "the block landed correctly even with the wrong layout — the sweep's "
          "placement check is not testing placement")


def test_trainer_blocks() -> None:
    """The two trainer dialects and the dialogue body they share. Vanilla names
    three global texts and hangs a local `.AfterScript`; polished inlines all
    three as locals with the after-line falling through beneath the macro — the
    shapes measured from all 333 vanilla and 593 polished trainers."""
    print("the trainer block — two dialects over one dialogue body")
    seen, beaten, after = [["Hi!"]], [["I lost."]], [["Bye.", "See ya."]]

    v = B.trainer_block("Foo", "BUG_CATCHER", "AL", "EVENT_X",
                        seen_label="FooSeen", defeated_label="FooBeaten",
                        after_label="FooAfter", seen=seen, defeated=beaten,
                        after=after)
    check("vanilla names the two texts on the macro line, loss literal 0",
          v[1] == "\ttrainer BUG_CATCHER, AL, EVENT_X, FooSeen, FooBeaten, "
                  "0, .AfterScript", v[1])
    check("vanilla writes the three texts as global blocks",
          all(f"{lbl}:" in v for lbl in ("FooSeen", "FooBeaten", "FooAfter")))
    at = v.index(".AfterScript:")
    check("vanilla's after-battle line is the measured six-command body",
          [ln.strip() for ln in v[at + 1:at + 7]]
          == ["endifjustbattled", "opentext", "writetext FooAfter",
              "waitbutton", "closetext", "end"], str(v[at + 1:at + 7]))

    p = B.generictrainer_block("Foo", "BUG_CATCHER", "AL", "EVENT_X",
                               seen=seen, defeated=beaten, after=after)
    check("polished names two locals on the macro line, no loss/after slots",
          p[1] == "\tgenerictrainer BUG_CATCHER, AL, EVENT_X, .SeenText, "
                  ".BeatenText", p[1])
    check("polished's after-line falls through directly beneath the macro",
          p[3] == '\ttext "Bye."', p[3])
    check("polished inlines the seen and beaten texts as locals",
          ".SeenText:" in p and ".BeatenText:" in p)

    body = B.dialogue_body([["a", "b", "c", "d"], ["e"]])
    check("dialogue is text/line/cont, a blank + para for a fresh box, one done",
          body == ['\ttext "a"', '\tline "b"', '\tcont "c"', '\tcont "d"', '',
                   '\tpara "e"', '\tdone'], str(body))
    try:
        B.dialogue_body([['he said "hi"']])
        check("a double-quote in a line is refused", False, "it was accepted")
    except B.BlockError as exc:
        check("a double-quote in a line is refused", "double-quote" in str(exc))
    try:
        B.dialogue_body([])
        check("empty dialogue is refused", False, "it was accepted")
    except B.BlockError as exc:
        check("empty dialogue is refused", "needs a line" in str(exc))


def test_trainer_dialects() -> None:
    """The trainer is the first block adder real on *both* trees, so unlike the
    item ball it is registered per dialect — each writes its own macro and
    `OBJECTTYPE_*`. One declaration per tree, not a branch."""
    print("the trainer forks per dialect — one macro each, registered per tree")
    v, p = fa.VANILLA_ADDERS["trainer"], fa.POLISHED_ADDERS["trainer"]
    check("both trees offer exactly one trainer adder", len(v) == 1 and len(p) == 1)
    check("vanilla writes OBJECTTYPE_TRAINER", v[0].objtype == "OBJECTTYPE_TRAINER")
    check("polished writes OBJECTTYPE_GENERICTRAINER",
          p[0].objtype == "OBJECTTYPE_GENERICTRAINER")
    check("the layout is stamped per dialect, not shared",
          v[0].layout is not p[0].layout)
    check("and the stamped names read as the dialect",
          v[0].__name__ == "VanillaTrainer"
          and p[0].__name__ == "PolishedGenericTrainer",
          f"{v[0].__name__} / {p[0].__name__}")


def test_trainer_round_trip() -> None:
    """Generate a trainer into a real map on each tree and read it back.

    The check a formatter test cannot make: the file comes back with one more
    object that the reader carves as a trainer of the class and party asked for,
    a fresh beaten flag, and a battle block the object's pointer resolves to —
    which, since the reader walks from the object line to that block to find the
    class, is also the proof the block landed on the right side of the header.
    """
    print("a trainer into a real map, both trees, read back")
    import tempfile

    from pokeprism_devtools.hacks.polished import events as pe
    from pokeprism_devtools.hacks.vanilla import events as ve
    cases = [(VANILLA, fa.VANILLA_ADDERS["trainer"][0], ve, "_MapEvents"),
             (POLISHED, fa.POLISHED_ADDERS["trainer"][0], pe, "_MapScriptHeader")]
    for root, add, reader, anchor in cases:
        rel = "maps/AzaleaGym.asm"
        if not (root / rel).exists():
            check(f"{root.name} present", False, str(root))
            continue
        result = add("AZALEA_GYM", cls="BUG_CATCHER", party="AL",
                     sprite="SPRITE_BUG_CATCHER", y="4", x="5",
                     movement="SPRITEMOVEDATA_STANDING_DOWN", sight="3",
                     seen="Our eyes met!", defeated="I lost.",
                     after="Well fought.").run(root)
        edit = next(e for e in result.edits if e.path == rel)
        before = eb.parse_map(root / rel, anchor)
        block = eb.parse_text(edit.new_text, root / rel, anchor)
        check(f"{root.name}: one more object, other lists unmoved",
              len(block.lists["object"].entries)
              == len(before.lists["object"].entries) + 1
              and all(len(block.lists[k].entries)
                      == len(before.lists[k].entries)
                      for k in ("warp", "coord", "bg")))
        check(f"{root.name}: a beaten flag was allocated",
              any(e.path.endswith("event_flags.asm") for e in result.edits))

        d = Path(tempfile.mkdtemp())
        tmp = d / rel
        tmp.parent.mkdir(parents=True)
        tmp.write_text(edit.new_text)
        tr = reader.tables(tmp).trainers[-1]
        check(f"{root.name}: reads back as BUG_CATCHER / AL",
              tr.cls == "BUG_CATCHER" and tr.party == "AL", f"{tr.cls}/{tr.party}")
        check(f"{root.name}: with the fresh EVENT_AZALEA_GYM_TRAINER flag, sight 3",
              tr.flag == "EVENT_AZALEA_GYM_TRAINER" and tr.sight == "3",
              f"{tr.flag} / {tr.sight}")


def test_trainer_reuse_only() -> None:
    """Reuse-only, the way prism's own form is: a party the class does not have
    is refused before a byte is written, and the refusal names the roster file
    rather than silently writing a `trainer` line the assembler would reject."""
    print("reuse-only — a party that isn't the class's is refused")
    if not (VANILLA / "maps/AzaleaGym.asm").exists():
        check("vanilla present", False, str(VANILLA))
        return
    add = fa.VANILLA_ADDERS["trainer"][0]
    try:
        add("AZALEA_GYM", cls="BUG_CATCHER", party="NOT_A_PARTY",
            seen="a", defeated="b", after="c").run(VANILLA)
        check("an invented party is refused", False, "it was accepted")
    except ActionError as exc:
        check("an invented party is refused, naming the roster",
              "no party" in str(exc) and "trainer_constants" in str(exc),
              str(exc))
    result = add("AZALEA_GYM", cls="BUG_CATCHER", party="AL", y="4", x="5",
                 seen="a", defeated="b", after="c").run(VANILLA)
    check("a real party is accepted and writes a map edit",
          any(e.path.startswith("maps/") for e in result.edits))


if __name__ == "__main__":
    test_names()
    test_block()
    test_dialects()
    test_real()
    test_second_ball()
    test_falsified()
    test_trainer_blocks()
    test_trainer_dialects()
    test_trainer_round_trip()
    test_trainer_reuse_only()
    print(f"\n{'FAILURES: ' + str(_failures) if _failures else 'all ok'}")
    sys.exit(1 if _failures else 0)
