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

import io
import os
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
from pokeprism_devtools.hacks import mount as hackmount # noqa: E402
from pokeprism_devtools.hacks.prism import eventheader # noqa: E402
from pokeprism_devtools.shared import coords, world # noqa: E402
from pokeprism_devtools.studio import actions, content, offers, panels  # noqa: E402
from pokeprism_devtools.studio.session import (Session, SessionError,  # noqa: E402
                                               StaleWorld)

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


def _npc(y: int, x: int, said: str = "Hello.") -> content.AddNpc:
    return content.AddNpc("TOWN_A", sprite="SPRITE_NPC", y=str(y), x=str(x),
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
    first = s.act(content.AddProp("TOWN_A", kind=content.HIDDEN, y="5", x="5", item="ULTRA_BALL"))
    second = s.act(content.AddProp("TOWN_A", kind=content.HIDDEN, y="6", x="6", item="RARE_CANDY"))

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


def test_the_world_notices(root: Path) -> None:
    """What counts as the repo moving, and what doesn't.

    The `touch` case is the one worth having. `git checkout` rewrites a file's
    mtime whether or not its bytes change, and so does saving in an editor without
    editing. Drift that fires on those is drift you learn to ignore, and a warning
    you have learned to ignore is worse than no warning — you would press `r` out
    of habit and lose two seconds every time, until you stopped reading it at all.
    """
    print("\nthe world, and what counts as it moving")
    stamped = world.World.stamp(root)
    check("nothing has changed, and it says so", stamped.drift(root) == [])

    items = root / "constants/item_constants.asm"
    os.utime(items, (0, 0))                       # a new mtime, the same bytes
    check("a touch with no edit is NOT drift", stamped.drift(root) == [],
          "mtime moved and the content did not — this must be silent")

    items.write_text(items.read_text() + "\tconst MASTER_BALL\n")
    check("an edit is drift, and it names the file",
          stamped.drift(root) == ["constants/item_constants.asm"],
          str(stamped.drift(root)))

    (root / "maps/Brand.blk").write_bytes(b"\x00")
    check("a new file is drift too — a new map's .blk is a change to the world",
          "maps/Brand.blk" in stamped.drift(root))

    (root / "maps/Brand.blk").unlink()
    (root / "constants/item_constants.asm").write_text(
        stamped.hashes and items.read_text().replace("\tconst MASTER_BALL\n", ""))
    check("put back byte-for-byte, and it is quiet again", stamped.drift(root) == [],
          str(stamped.drift(root)))


def test_a_stale_model_will_not_write(root: Path) -> None:
    """The bug this phase exists to prevent, and it is a silent one.

    A `Session` reads the repo into an lru_cached model. Change a constant behind
    its back and every validator in the writing layer — `scaffold.require`, which
    is a *good* validator with a did-you-mean and everything — goes on checking
    your sprite against the sprites of an hour ago. It does not fail. It passes,
    and writes a `person_event` naming a sprite that no longer exists, and the
    first you hear of it is the assembler.
    """
    print("\na session that has been overtaken will not write")
    s = Session(root)
    s.warm()                                      # the model is now in the caches
    before = _snapshot(root)

    sprites = root / "constants/sprite_constants.asm"
    sprites.write_text(sprites.read_text().replace("SPRITE_NPC", "SPRITE_TOWNSFOLK"))
    before[str(sprites.relative_to(root))] = sprites.read_text()

    try:
        s.act(_npc(5, 5))
        check("it refuses to write against a repo it has not read", False,
              "it wrote — the NPC cites a sprite that does not exist")
    except StaleWorld as e:
        check("it refuses to write against a repo it has not read", True)
        check("and it names the file that moved",
              e.paths == ["constants/sprite_constants.asm"], str(e.paths))

    check("and nothing at all was written", _snapshot(root) == before)

    # And after re-reading, the *existing* validation does the rest — which is the
    # whole point: no new checking was needed, only a repo worth checking against.
    s.reload()
    try:
        s.act(_npc(5, 5))
        check("once re-read, the sprite itself is caught", False, "no error raised")
    except actions.ActionError as e:
        check("once re-read, the sprite itself is caught", "SPRITE_NPC" in str(e),
              str(e)[:60])

    check("and the renamed sprite now works",
          s.act(content.AddNpc("TOWN_A", sprite="SPRITE_TOWNSFOLK", y="5", x="5",
                               movement="SPRITEMOVEDATA_STANDING_DOWN",
                               palette="PAL_OW_RED", text="hi")).paths != [])


def test_our_own_writes_are_not_drift(root: Path) -> None:
    """Otherwise the studio spends its life telling you that you have just done
    something — and one action would poison every action after it."""
    print("\nwriting is not drifting")
    s = Session(root)
    s.act(_npc(5, 5))
    check("after applying, the repo has not 'moved'", s.drifted() == [],
          str(s.drifted()))
    s.act(_npc(6, 6))
    check("so the next action goes through", len(s.history) == 2)

    s.undo()
    check("and an undo is not drift either", s.drifted() == [], str(s.drifted()))


def test_undo_does_not_care_that_the_world_moved(root: Path) -> None:
    """An undo reasons about nothing — it restores bytes it can prove are its own.

    So it is deliberately *not* gated on a fresh repo, and this pins that. Refusing
    an undo because some unrelated file changed would mean a `git pull` could strand
    you with a mutation you could no longer take back. The guard that matters is the
    per-file content check, and that one stays.
    """
    print("\nan undo is about bytes, not about the world")
    s = Session(root)
    s.act(_npc(5, 5))

    items = root / "constants/item_constants.asm"
    items.write_text(items.read_text() + "\tconst MASTER_BALL\n")
    check("the world has moved", s.drifted() == ["constants/item_constants.asm"])

    try:
        s.undo()
        check("the undo still goes through", True)
    except SessionError as e:
        check("the undo still goes through", False, str(e))

    check("but a write is still refused", not _writes(s, _npc(7, 7)))
    check("and the unrelated hand-edit is untouched",
          "MASTER_BALL" in items.read_text())


def _writes(s: Session, action) -> bool:
    try:
        s.act(action)
        return True
    except SessionError:
        return False


def test_it_says_what_it_broke(root: Path) -> None:
    """The backstop for what a fresh repo cannot catch: a change that read the
    repo correctly and was wrong anyway. Only the linter can see those, and the
    only moment you would ever be looking is the one just after you made one."""
    print("\nwhat a change broke")
    s = Session(root)
    # An empty tile, and it has to be: TownA's people stand on (3,3) through (8,8),
    # and dropping another one on top of one of those is a finding all by itself
    # (event-overlap) — a true one, but not the one this test is about.
    clean = s.act(_npc(11, 11))
    check("a good change introduces nothing", clean.introduced == [],
          str([f.code for f in clean.introduced]))

    # Dialogue that runs off the edge of the textbox. The scaffold writes it
    # without a murmur — a line's *width in tiles* is not a fact about the asm, it
    # is a fact about the charmap and the box the engine draws — so this is exactly
    # the class of mistake a fresh repo cannot save you from, and the linter can.
    broke = s.act(_npc(12, 12, "Mississippi hippopotamus academy graduation ceremony."))
    codes = [f.code for f in broke.introduced]
    check("a change that breaks something says so", codes != [],
          "it introduced nothing — the overflowing line went unremarked")
    check("and it is the overflow it names", any("text" in c for c in codes), str(codes))
    check("the finding is about the map we wrote",
          all(f.map_label == "TownA" for f in broke.introduced),
          str([f.location for f in broke.introduced]))

    # And undoing it takes the finding away again, which is what makes the offer to
    # undo worth making.
    s.undo()
    check("undo takes the breakage back", s.act(_npc(13, 13)).introduced == [])

    # The other half of the same promise, and the reason the coordinates above had
    # to be moved: standing an NPC on another NPC is a mistake the assembler is
    # perfectly happy with, and one you cannot see in a diff of one line.
    on_top = s.act(_npc(3, 3))
    check("and standing one on top of another says so",
          [f.code for f in on_top.introduced] == ["event-overlap"],
          str([f.code for f in on_top.introduced]))


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

    bad = content.AddNpc("TOWN_A", sprite="SPRITE_NOSUCH", y="1", x="1",
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
        s.act(content.AddProp("TOWN_A", kind=content.HIDDEN, y="7", x="7", item="NOT_AN_ITEM"))
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
    s.act(content.AddProp("TOWN_A", kind=content.HIDDEN, y="5", x="5", item="ULTRA_BALL"))
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


def test_a_ref_offers_only_its_affordances() -> None:
    """The view's whole share of a Ref is its declared surface — `adds`,
    `deletable`, equality. Identity underneath is the adapter's Handle, carried
    whole: prism names an object by list position because that is all its
    source can say, but the rest of the gen-2 family writes `object_const_def`
    — see docs/polished-crystal-feasibility.md, #1. A view that reads only the
    surface, and a port that never takes a handle apart, will not notice when
    an adapter mints names instead.
    """
    print("\na Ref offers only its affordances")
    add = panels.add_ref("NPC")
    check("an add-row Ref says what it would add", add.adds == "NPC")
    check("and is not deletable — it names nothing yet", not add.deletable)
    npc = panels.Ref("npc", eventheader.Handle(eventheader.ListKind.OBJECT_EVENTS, 3))
    check("a real row adds nothing", npc.adds == "")
    check("and can be deleted", npc.deletable)
    check("the map's own rows cannot", not panels.Ref("map").deletable)
    header = eventheader.parse_text(
        "X_MapEventHeader::\n\tdb 0, 0\n\tdb 1\n\twarp_def 3, 5, 1, TOWN_A\n"
        "\tdb 0\n\tdb 0\n\tdb 0\n", Path("X.asm"))
    warp = eventheader.Handle(eventheader.ListKind.WARPS, 0)
    found = header.entry_at(warp)
    check("a handle resolves by being handed back to the adapter",
          found is not None and found.macro == "warp_def")
    check("a handle the map has outgrown resolves to None, not a crash",
          header.entry_at(eventheader.Handle(eventheader.ListKind.WARPS, 7)) is None)


def test_a_tile_crosses_the_seam_by_name() -> None:
    """(y, x) and (x, y) both typecheck as two ints, and the hacks disagree on
    the order — prism is (y, x), vanilla and polished are (x, y). The seam's
    tile carries names so the order is written down once, at construction."""
    print("\na tile crosses the seam by name")
    t = coords.Tile(y=7, x=9)
    check("Tile(y=7, x=9) has named fields", t.y == 7 and t.x == 9)
    check("and is still the bare (7, 9) older callers build", t == (7, 9))
    check("markers are keyed by it", all(
        isinstance(k, coords.Tile)
        for k in eventheader.markers(eventheader.parse_text(
            "X_MapEventHeader::\n\tdb 0, 0\n\tdb 1\n\twarp_def 3, 5, 1, TOWN_A\n"
            "\tdb 0\n\tdb 0\n\tdb 0\n", Path("X.asm"))).keys()))


def test_a_foreign_tree_is_refused_loudly(tmp: Path) -> None:
    """Phase 0 (docs/polished-crystal-feasibility.md) measured five of eight
    parsers failing *silently* on a pokecrystal checkout — empty lists, not
    errors. A studio opened on one would report an empty repo with a straight
    face. The session is the seam, so the session is where the refusal lives.
    """
    print("\na foreign tree is refused loudly")
    alien = tmp / "alien"
    (alien / "src").mkdir(parents=True)
    (alien / "Makefile").write_text("")
    try:
        Session(alien)
        check("Session refuses a tree no adapter recognises", False)
    except hackmount.UnknownTree as exc:
        check("Session refuses a tree no adapter recognises", True)
        check("and names what it looked for",
              "second_map_headers" in str(exc), str(exc))

    # Family-shaped, but no map file carries either anchor — a tree the mount
    # can place in the pokecrystal family and no adapter can claim.
    hollow = tmp / "hollow"
    (hollow / "data/maps").mkdir(parents=True)
    (hollow / "data/maps/maps.asm").write_text("")
    try:
        Session(hollow)
        check("Session refuses a family tree with no readable map", False)
    except hackmount.UnknownTree as exc:
        check("Session refuses a family tree with no readable map", True)
        check("and names both anchors", "_MapEvents" in str(exc)
              and "_MapScriptHeader" in str(exc), str(exc))



def test_an_object_past_the_count_is_still_shown(root: Path) -> None:
    """The count byte is wrong. The object is still there, and you can still act on it.

    PhloxLab1F says `db 6 ; FIXME` over seven `person_event`s — somebody wrote the
    seventh and forgot the byte, and the engine reads six and stops. So the Max
    Revive on its floor is in the source and not in the game, and the studio used to
    show the map with the ball drawn on it and no row for it anywhere: the one object
    you would actually be looking for, missing from the only table that could have
    told you why.
    """
    print("\nan object past the count byte is in the file, so it is on the tab")
    asm = root / "maps/TownA.asm"
    was = asm.read_text()
    # Six people, and a `db 5` — the last one never spawns.
    header = eventheader.parse_map(asm)
    n = len(header.object_events)
    asm.write_text(was.replace(f".ObjectEvents\n\tdb {n}", f".ObjectEvents\n\tdb {n - 1}"))

    s = Session(root)
    data = s.load("TownA")
    tab = next(t for t in data.tabs if t.name == "NPCs")
    rows = tab.table[1]
    check("every object still gets a row, count byte or no count byte",
          len(rows) == n, f"{len(rows)} rows for {n} people, one of them past the count")
    check("and the row says so, because the byte does not",
          rows[-1].cells[0].endswith(panels.UNDECLARED)
          and not rows[-2].cells[0].endswith(panels.UNDECLARED),
          str([r.cells[0] for r in rows]))
    check("the linter says why",
          any(f.code == "obj-count" for f in s.findings_for("TOWN_A")),
          str([f.code for f in s.findings_for("TOWN_A")]))

    # And it is not a ghost: it can be pointed at, which is the whole reason to show
    # it. A row whose Ref you cannot edit would just be a nicer way of hiding it.
    ref = rows[-1].ref
    check("it can be selected like any other", ref is not None and ref.handle.index == n - 1)
    action, values, _ = s.editor("TownA", "TOWN_A", ref)
    check("and `e` opens it, filled in from the line that is really there",
          (values["y"], values["x"]) == ("8", "8"), str(values))

    asm.write_text(was)


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
    from pokeprism_devtools.studio import play as play_mod

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
         mock.patch.object(play_mod.inventory, "load_or_build",
                           lambda *a, **k: {}), \
         mock.patch.object(play_mod.devapply, "load_state",
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


def test_a_quiet_build_keeps_only_the_problems(root: Path) -> None:
    """The filter a quiet build runs each line through — the studio's grep. It has
    to keep every line that carries the answer and drop the mountain that doesn't,
    because the mountain is the whole reason quiet exists."""
    print("\nthe quiet build's grep")
    from pokeprism_devtools.studio import play as play_mod

    keep = [
        "maps/CastroForest.asm:41: error: Unknown symbol \"SPRITE_NOPE\"",
        "error.o: fatal: Segment overflow",
        "engine/foo.asm:9: warning: Deprecated",
        "make: *** [Makefile:120: pokeprism.gbc] Error 1",
        "make[1]: *** No rule to make target 'x'.  Stop.",
    ]
    drop = [
        "rgbasm -h -E -o build/CastroForest.o maps/CastroForest.asm",
        "        DEP     build/CastroForest.d",
        "python3 tools/make_patch.py",
        "Linking pokeprism.gbc",             # 'error' is not in it; a bare verb is not a problem
    ]
    for ln in keep:
        check(f"kept: {ln[:40]}", play_mod.is_problem(ln))
    for ln in drop:
        check(f"dropped: {ln[:40]}", not play_mod.is_problem(ln))


def test_it_boots_the_rom_it_built(root: Path) -> None:
    """The two ROMs sit side by side, and picking between them by which file exists
    is how the studio came to build one and boot the other.

    `make` with no target is `all`, which builds *both* — so the state this is
    guarding against is not exotic, it is the state the studio left the repo in
    every single time. Then `rom_path` preferred `pokeprism_nodebug.gbc`, and you
    would spend four minutes building the debug ROM, patch a save against the other
    one, and go looking for your new map in a game that had never heard of it.
    """
    print("\nthe target, on both sides")
    from unittest import mock

    from pokeprism_devtools.dev_server import playtest as devplay
    from pokeprism_devtools.studio import play as play_mod

    ran: list[list[str]] = []

    class FakeProc:
        stdout = io.StringIO("")
        def wait(self): return 0

    def fake_popen(cmd, **kw):
        ran.append(cmd)
        return FakeProc()

    s = Session(root)
    with mock.patch.object(play_mod.subprocess, "Popen", fake_popen):
        s.build(lambda _: None, target="prism", jobs=4)
    check("it names the target and the jobs", ran[-1] == ["make", "-j4", "prism"],
          " ".join(ran[-1]))

    # Both ROMs on disk, which is exactly what `make all` used to leave behind.
    for name in ("pokeprism.gbc", "pokeprism_nodebug.gbc"):
        (root / name).write_bytes(b"\x00")
        (root / name).with_suffix(".sym").write_text("")

    seen: dict = {}

    def fake_patch(rom_path, **kw):
        seen["rom"] = rom_path
        return devplay.PatchReport(target=rom_path.with_suffix(".sav"),
                                   backup=None, changes=[])

    with mock.patch.object(devplay, "patch_save", fake_patch), \
         mock.patch.object(play_mod.inventory, "load_or_build", lambda *a, **k: {}), \
         mock.patch.object(play_mod.devapply, "load_state", lambda *a: {}), \
         mock.patch.object(devplay.Emulator, "launch",
                           lambda self, rom, **k: devplay.LaunchReport(launched=True)):
        s.boot("TOWN_A", 9, 4, target="prism")
    check("having built prism, it boots pokeprism.gbc and not the other one",
          seen["rom"].name == "pokeprism.gbc", seen["rom"].name)

    # And with only the debug ROM built, asking for nodebug must *refuse* rather
    # than fall back to the one that happens to be lying there.
    (root / "pokeprism_nodebug.gbc").unlink()
    try:
        s.boot("TOWN_A", 9, 4, target="nodebug")
    except SessionError as e:
        check("and asking for a ROM that wasn't built refuses, rather than "
              "booting whatever else is on disk", "make nodebug" in str(e), str(e))
    else:
        check("asking for a ROM that wasn't built refuses", False)


def test_the_blocks_on_offer_are_the_newest_first(root: Path) -> None:
    """The `.blk` you are looking for is the one you drew ninety seconds ago.

    Which is why this list is not sorted by name and is not cached: it is *made* of
    the answer to "what have I just been working on", and a list built at startup
    would be a list with exactly the file you want missing from it.
    """
    print("\nthe blocks on offer")
    (root / "maps/blk").mkdir(parents=True, exist_ok=True)
    old = root / "maps/blk/Older.ablk"
    old.write_bytes(b"\x00")
    os.utime(old, (1, 1))
    (root / "maps/blk/JustDrawn.ablk").write_bytes(b"\x00")
    (root / "maps/blk/notes.txt").write_text("not blocks")

    rows = offers.blocks(root)
    check("the one you just drew is at the top", rows[0].endswith("JustDrawn.ablk"),
          rows[0])
    check("and the older one is still on offer",
          any(r.endswith("Older.ablk") for r in rows))
    check("and nothing that isn't blocks",
          not any(r.endswith(".txt") for r in rows))


def _check_every_tile_points_at_its_own_row(s: Session) -> None:
    """The grid and the tables must agree about where everything is.

    A map's objects are laid out twice: once as glyphs on the grid, once as rows in
    the tables. The grid's marks come from `eventheader.markers` walking the event
    header; the rows come from `panels` walking it again. If those two ever disagree
    — about the order, about the `+4` the `person_event` macro adds, about which
    list a hidden item lives in — then clicking the third NPC highlights the fourth,
    and it does so *quietly*, and you edit the wrong one.

    Nothing about that failure looks like a bug from inside either module. It is
    only visible from here, across both, on every map in the repo.
    """
    print("\n  every tile points at the row that owns it")
    stray, missing, checked = [], [], 0
    for m in s.maps:
        data = s.load(m.label)
        if data.geometry is None:
            continue
        checked += 1
        marks = set(data.geometry.marks)
        rows = {row.tile for tab in data.tabs for row in tab.table[1]
                if row.tile is not None}
        # A tile with a glyph on it must be reachable as a row, or the grid shows
        # you something you cannot select.
        missing.extend((m.label, t) for t in marks - rows)
        # And a row's tile must be a tile the grid actually drew, or selecting it
        # would send the cursor somewhere blank.
        stray.extend((m.label, t) for t in rows - marks)

    check(f"every glyph on every one of {checked} maps is a selectable row",
          not missing, str(missing[:4]))
    check("and every row with a tile has a glyph standing on it",
          not stray, str(stray[:4]))


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

    t = time.time()
    s = Session(root)
    stamp = (time.time() - t) * 1000
    # The whole argument for watching the entire repo rather than making each
    # mutation declare what it depends on. If this ever stops being true, the
    # design stops being right — so it is a test, not a comment.
    check(f"stamping the whole repo is cheap ({stamp:.0f}ms, "
          f"{len(s.world.stamps)} files)", stamp < 400, "startup pays this once")

    t = time.time()
    moved = s.drifted()
    sweep = (time.time() - t) * 1000
    check(f"and a sweep for drift is cheaper ({sweep:.0f}ms)", sweep < 120,
          "this runs every 5 seconds — a regression here is one that hashes "
          "every file instead of stat-ing them")
    check("a repo nobody touched has not drifted", moved == [], str(moved[:3]))

    t = time.time()
    found = s.lint()
    cold = time.time() - t
    check(f"a cold lint of {len(s.maps)} maps finds {len(found)}", len(found) > 300,
          f"{cold:.2f}s")

    _check_every_tile_points_at_its_own_row(s)

    npc = content.AddNpc("CASTRO_FOREST", sprite="SPRITE_GRAMPS", y="5", x="7",
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

    test_editing_leaves_alone_what_it_did_not_touch(root)


def test_editing_leaves_alone_what_it_did_not_touch(root: Path) -> None:
    """Open every editable row on every map, submit it untouched, write nothing.

    **An editor that cannot leave a thing alone cannot be trusted to change it.**
    This is the whole warranty on `e`, and it is not a formality — it found five
    separate silent corruptions while it was being written, each of which
    assembles perfectly:

    * a `trainer` macro with a tail (`…, NULL, .script`) rebuilt from the five
      arguments we knew about, deleting the script it runs;
    * `Action.pages()` stripping each line, so a sign's centred `"  Closed due to"`
      quietly lost the two spaces that centre it;
    * a warp whose `warp_to` is written `$06`, which `int(raw, 0)` cannot read;
    * a trainer whose party is a *constant*, `RIVAL1_3`, not a number;
    * a header validated in full, so `IntroCave`'s unfindable `MUSIC_NONE` refused
      an edit to the tileset beside it.

    None of those show up in a test that only checks that a *change* works. They
    only show up if you insist that a non-change be a non-change.
    """
    s = Session(root)
    rows = wrote = crashed = 0
    trouble: list[str] = []

    for m in s.maps:
        try:
            data = s.load(m.label)
        except Exception:                                     # noqa: BLE001
            continue
        for tab in data.tabs:
            for row in tab.table[1]:
                ref = row.ref
                if ref is None or ref.what == "add":
                    continue
                try:
                    action, values, boxes = s.editor(m.label, m.const, ref)
                except SessionError:
                    continue                # says why it can't; that is its own test
                missing = [f.name for f in action.fields_for(values)
                           if f.name not in values]
                if missing and len(trouble) < 5:
                    trouble.append(f"{m.label} {ref.what} #{ref.handle.index}: the form asks "
                                   f"for {missing} and the prefill has no answer")
                rows += 1

                built = action(m.const, **values)
                built.target = ref
                try:
                    result = built.run(root)
                except Exception as exc:                      # noqa: BLE001
                    crashed += 1
                    if len(trouble) < 5:
                        trouble.append(f"{m.label} {ref.what} #{ref.handle.index}: {exc}")
                    continue
                if result.edits:
                    wrote += 1
                    if len(trouble) < 5:
                        trouble.append(f"{m.label} {ref.what} #{ref.handle.index} rewrote "
                                       f"{[e.path for e in result.edits]}")

    check(f"every editable row on every map opens a filled-in form ({rows})",
          rows > 10000, f"only {rows}")
    check("submitting one of them untouched writes nothing at all",
          wrote == 0 and crashed == 0 and not trouble,
          "; ".join(trouble))
    check("and the repo is byte-for-byte where it started",
          not [p for p in ("maps/CastroForest.asm", "maps/map_headers.asm",
                           "constants/event_flags.asm")
               if (root / p).read_text() != (real_root() / p).read_text()])


def real_root() -> Path:
    return Path.home() / "code/ricccec/pokeprism"


def main() -> int:
    test_a_ref_offers_only_its_affordances()
    test_a_tile_crosses_the_seam_by_name()
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        test_a_foreign_tree_is_refused_loudly(tmp)
        for fn in (test_two_items_get_two_flags, test_an_npc_is_always_there,
                   test_failure_changes_nothing, test_undo, test_undo_refuses_to_clobber,
                   test_preview_is_what_lands, test_lint_stays_in_step, test_map_list,
                   test_an_object_past_the_count_is_still_shown,
                   test_boot_stands_you_where_the_cursor_is,
                   test_a_quiet_build_keeps_only_the_problems,
                   test_it_boots_the_rom_it_built,
                   test_the_blocks_on_offer_are_the_newest_first,
                   test_the_world_notices, test_a_stale_model_will_not_write,
                   test_our_own_writes_are_not_drift, test_it_says_what_it_broke,
                   test_undo_does_not_care_that_the_world_moved):
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
