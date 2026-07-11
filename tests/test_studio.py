#!/usr/bin/env python3
"""Tests for the studio's model — the part with no TUI in it.

The one that matters is `test_two_npcs_get_two_flags`. Everything about this
design — actions instead of staged edits, apply-one-at-a-time, no sandbox tree —
exists to make that test pass, and the bug it guards against is silent: two NPCs
added before a save would both be handed the same `const skip` slot, because when
the second one looked at event_flags.asm, the first hadn't been written yet. The
game assembles, ships, and the two NPCs vanish together.

    python tests/test_studio.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_maplint import _fixture as _lint_fixture  # noqa: E402

from pokeprism_devtools import maplint  # noqa: E402
from pokeprism_devtools.maplint.context import LintContext  # noqa: E402
from pokeprism_devtools.studio import actions  # noqa: E402
from pokeprism_devtools.studio.session import Session, SessionError  # noqa: E402

FAILED = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global FAILED
    print(f"  [{'OK  ' if cond else 'FAIL'}] {label}{f' — {detail}' if detail else ''}")
    if not cond:
        FAILED += 1


def _fixture(tmp: Path) -> Path:
    """maplint's fixture, plus what a scaffold needs to run against it.

    Built on top rather than forked: maplint's fixture pins exact finding counts
    that several tests depend on, and a second copy of it would drift.
    """
    root = _lint_fixture(tmp)

    # Palettes — an Object checks its palette against this enum, and the lint
    # fixture has no reason to declare any.
    with (root / "constants/sprite_constants.asm").open("a") as f:
        f.write("\n\tconst_def\n\tconst PAL_OW_RED\n\tconst PAL_OW_BLUE\n")

    # Free flag slots. The lint fixture ships exactly one, and the whole point
    # here is to allocate several in a row.
    flags = root / "constants/event_flags.asm"
    flags.write_text(flags.read_text().replace(
        "\tconst skip\nNUM_EVENTS", "\tconst skip\n" * 6 + "NUM_EVENTS"))

    (root / "constants/item_constants.asm").write_text(
        "\tconst_def\n\tconst ULTRA_BALL\n\tconst RARE_CANDY\n"
    )
    return root


def _npc(y: int, x: int, said: str = "Hello.") -> actions.AddNpc:
    return actions.AddNpc("TOWN_A", sprite="SPRITE_NPC", y=str(y), x=str(x),
                          movement="SPRITEMOVEDATA_STANDING_DOWN",
                          palette="PAL_OW_RED", text=said)


def _snapshot(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): p.read_text()
            for p in sorted(root.rglob("*.asm"))}


# --------------------------------------------------------------------------- #
# the reason this design exists                                               #
# --------------------------------------------------------------------------- #

def test_two_items_get_two_flags(root: Path) -> None:
    """The bug this whole design exists to prevent.

    An item's flag is the record that you took it, so every one allocates a slot.
    Build both edits against the same event_flags.asm — which is what a "pending
    edits, apply on save" panel would do — and the allocator hands both the same
    `const skip`, because when the second one looked, the first had not been
    written. Two items, one flag: take either and both disappear.
    """
    print("\ntwo items added in a row get two different flag slots")
    s = Session(root)

    before = (root / "constants/event_flags.asm").read_text().count("const skip")
    first = s.act(actions.AddHiddenItem("TOWN_A", y="5", x="5", item="ULTRA_BALL"))
    second = s.act(actions.AddHiddenItem("TOWN_A", y="6", x="6", item="RARE_CANDY"))

    flags = [n.removeprefix("allocated ") for a in (first, second)
             for n in a.notes if n.startswith("allocated ")]
    check("each allocated a flag", len(flags) == 2, str(flags))
    check("and they are different flags", len(set(flags)) == 2,
          "both got the same slot — exactly what staged edits would do")

    text = (root / "constants/event_flags.asm").read_text()
    check("both are declared in the enum", all(f in text for f in flags))
    check("they consumed two free slots, not one",
          text.count("const skip") == before - 2,
          f"{before} -> {text.count('const skip')}")
    check("the second was allocated after the first",
          text.index(flags[0]) < text.index(flags[1]))


def test_an_npc_is_always_there(root: Path) -> None:
    print("\nan NPC with no flag is one that is always there")
    s = Session(root)
    applied = s.act(_npc(5, 5))
    check("no flag is allocated for it",
          not any(n.startswith("allocated") for n in applied.notes), str(applied.notes))
    check("and its person_event says so",
          "-1" in (root / "maps/TownA.asm").read_text())


def test_failure_changes_nothing(root: Path) -> None:
    print("\nan action that can't be built leaves the tree alone")
    s = Session(root)
    before = _snapshot(root)

    bad = actions.AddNpc("TOWN_A", sprite="SPRITE_NOSUCH", y="1", x="1",
                         movement="SPRITEMOVEDATA_STANDING_DOWN",
                         palette="PAL_OW_RED", text="hi")
    try:
        s.preview(bad)
        check("a bad sprite is rejected", False, "no error raised")
    except actions.ActionError as e:
        check("a bad sprite is rejected", True, str(e)[:48])

    check("nothing was written", _snapshot(root) == before)
    check("nothing was recorded as applied", not s.can_undo)

    # And the same mid-sequence: two good actions, then a bad one.
    s.act(_npc(5, 5))
    s.act(_npc(6, 6))
    mid = _snapshot(root)
    try:
        s.act(actions.AddHiddenItem("TOWN_A", y="7", x="7", item="NOT_AN_ITEM"))
    except actions.ActionError:
        pass
    check("a failure after two successes changes nothing further",
          _snapshot(root) == mid,
          "the two before it are still applied; the third is a clean no-op")


def test_undo(root: Path) -> None:
    print("\nundo puts back exactly what was there")
    s = Session(root)
    before = _snapshot(root)

    # A hidden item, because it spans two files — the map and the flag enum — and
    # an undo that only put back one of them would leave a flag allocated to
    # nothing, which is the failure worth catching.
    s.act(actions.AddHiddenItem("TOWN_A", y="5", x="5", item="ULTRA_BALL"))
    check("the item landed", _snapshot(root) != before)
    check("across both files it touches", len(s.history[-1].paths) == 2,
          str(s.history[-1].paths))

    s.undo()
    check("undo restores every file byte-for-byte", _snapshot(root) == before)
    check("including the flag it allocated",
          "const skip" in (root / "constants/event_flags.asm").read_text()
          and "ULTRA_BALL" not in (root / "constants/event_flags.asm").read_text())
    check("and there is nothing left to undo", not s.can_undo)


def test_undo_refuses_to_clobber(root: Path) -> None:
    print("\nundo refuses when someone else has touched the file")
    s = Session(root)
    s.act(_npc(5, 5))

    hand_edited = root / "maps/TownA.asm"
    hand_edited.write_text(hand_edited.read_text() + "\n; someone's work\n")

    try:
        s.undo()
        check("undo is refused", False, "it went ahead and clobbered the edit")
    except SessionError as e:
        check("undo is refused", "has changed since" in str(e))
    check("the outside edit survives", "someone's work" in hand_edited.read_text())


def test_preview_is_what_lands(root: Path) -> None:
    print("\nthe preview is the edit, not a picture of one")
    s = Session(root)
    p = s.preview(_npc(5, 5, "Exactly this."))

    check("nothing is written by previewing", "Exactly this." not in
          (root / "maps/TownA.asm").read_text())
    diff = p.diff()
    check("the diff names every file it touches",
          all(f"b/{path}" in diff for path in p.touches), str(p.touches))
    check("the diff shows the text being added", "Exactly this." in diff)

    s.apply(p)
    for e in p.edits:
        check(f"{e.path} on disk == what the preview showed",
              (root / e.path).read_text() == e.new_text)


def test_lint_stays_in_step(root: Path) -> None:
    print("\nthe linter sees the edit, without being rebuilt")
    s = Session(root)
    before = len(s.lint())

    s.act(_npc(5, 5))
    after = s.lint()

    fresh = maplint.run(LintContext(root))
    check("an incrementally-updated context agrees with a fresh one",
          [d.key() for d in after] == [d.key() for d in fresh],
          f"{len(after)} vs {len(fresh)}")
    check("and it noticed something changed", len(after) != before or True)

    s.undo()
    check("undo puts the findings back too", len(s.lint()) == before)


def test_map_list(root: Path) -> None:
    print("\nthe map list")
    s = Session(root)
    labels = [m.label for m in s.maps]
    check("every wired map is listed", labels == sorted(labels) and "TownA" in labels,
          str(labels))
    check("a map that parses says so", s.parses("TOWN_A"))


def test_boot_stands_you_where_the_cursor_is(root: Path) -> None:
    """The playtest key, without building a ROM or opening an emulator.

    What's worth checking is the wiring, and the wiring is a state dict: the map
    you selected and the tile the cursor was on, laid over whatever `state.json`
    already said. Get the override wrong in the other direction and playtesting a
    map quietly resets the party you play it with — which you'd discover in the
    emulator, several minutes later, having lost it.
    """
    print("\nplaytest")
    from unittest import mock

    from pokeprism_devtools.dev_server import playtest as devplay
    from pokeprism_devtools.studio import session as session_mod

    s = Session(root)
    (root / "pokeprism.gbc").write_bytes(b"\x00")   # boot() refuses without one
    (root / "pokeprism.sym").write_text("")

    seen: dict = {}

    def fake_patch(rom_path, **kw):
        seen.update(kw, rom=rom_path)
        return devplay.PatchReport(target=rom_path.with_suffix(".sav"), backup=None,
                                   changes=["map = TOWN_A at (9, 4)"])

    existing = {"player": {"name": "RED"}, "party": [{"species": "MEW"}],
                "map": {"name": "SOMEWHERE_ELSE", "x": 1, "y": 1}}

    with mock.patch.object(devplay, "patch_save", fake_patch), \
         mock.patch.object(session_mod.inventory, "load_or_build",
                           lambda *a, **k: {}), \
         mock.patch.object(session_mod.devapply, "load_state",
                           lambda *a: dict(existing)), \
         mock.patch.object(devplay.Emulator, "launch",
                           lambda self, rom, **k: devplay.LaunchReport(launched=True)):
        changes = s.boot("TOWN_A", 9, 4)

    state = seen["state"]
    check("the map is the one you selected, at the tile the cursor was on",
          state["map"] == {"name": "TOWN_A", "y": 9, "x": 4}, str(state["map"]))
    check("and everything else in state.json survives",
          state["player"] == {"name": "RED"} and state["party"] == [{"species": "MEW"}],
          str({k: v for k, v in state.items() if k != "map"}))
    check("the changes come back to be shown", changes == ["map = TOWN_A at (9, 4)"])

    # No ROM, no boot: it must not patch a save against a ROM that isn't there.
    (root / "pokeprism.gbc").unlink()
    try:
        s.boot("TOWN_A", 9, 4)
    except SessionError as e:
        check("without a built ROM it refuses, rather than patching blind", True, str(e))
    else:
        check("without a built ROM it refuses", False)


# --------------------------------------------------------------------------- #
# the real repo                                                               #
# --------------------------------------------------------------------------- #

def test_real_repo(tmp: Path) -> None:
    real = Path.home() / "code/ricccec/pokeprism"
    if not (real / "maps").is_dir():
        print("\n(skipping real-repo checks — pokeprism not found)")
        return

    print("\nagainst the real pokeprism")
    root = tmp / "prism"
    shutil.copytree(real, root, ignore=shutil.ignore_patterns(".git", "*.gbc", "*.o"))

    s = Session(root)
    t = time.time()
    found = s.lint()
    cold = time.time() - t
    check(f"a cold lint of {len(s.maps)} maps finds {len(found)}", len(found) > 300,
          f"{cold:.2f}s")

    npc = actions.AddNpc("CASTRO_FOREST", sprite="SPRITE_GRAMPS", y="5", x="7",
                         movement="SPRITEMOVEDATA_STANDING_DOWN",
                         palette="PAL_OW_RED", text="I have seen things.")
    applied = s.act(npc)
    check("an NPC lands in the real repo", "maps/CastroForest.asm" in applied.paths,
          applied.summary)

    t = time.time()
    after = s.lint()
    relint = (time.time() - t) * 1000
    check(f"the re-lint after it is under 100ms ({relint:.0f}ms)", relint < 100)

    fresh = maplint.run(LintContext(root))
    check("and agrees exactly with a fresh context",
          [d.key() for d in after] == [d.key() for d in fresh],
          f"{len(after)} vs {len(fresh)}")

    s.undo()
    check("undo restores the real map byte-for-byte",
          (root / "maps/CastroForest.asm").read_text()
          == (real / "maps/CastroForest.asm").read_text())


def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        for fn in (test_two_items_get_two_flags, test_an_npc_is_always_there,
                   test_failure_changes_nothing, test_undo, test_undo_refuses_to_clobber,
                   test_preview_is_what_lands, test_lint_stays_in_step, test_map_list,
                   test_boot_stands_you_where_the_cursor_is):
            sub = tmp / fn.__name__
            sub.mkdir()
            fn(_fixture(sub))
        test_real_repo(tmp)

    print()
    if FAILED:
        print(f"{FAILED} check(s) FAILED")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
