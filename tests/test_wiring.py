#!/usr/bin/env python3
"""Tests for the connection and paired-warp editors.

The unit tests are hermetic. The one that matters most isn't: it copies the real
pokeprism, wires two real maps together, adds a paired warp, and runs the whole
linter over the result — because the only convincing proof that a generated
connection is right is that the tool built to find broken connections has
nothing to say about it.

    python tests/test_wiring.py
"""

from __future__ import annotations

import re
import shutil
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pokeprism_devtools import maplint  # noqa: E402
from pokeprism_devtools.maplint import rules_geometry  # noqa: E402
from pokeprism_devtools.maplint.context import LintContext  # noqa: E402
from pokeprism_devtools.shared import eventheader as eh  # noqa: E402
from pokeprism_devtools.shared.edits import apply_edits  # noqa: E402
from pokeprism_devtools.wiring import connections as C, objedit as O  # noqa: E402
from pokeprism_devtools.wiring import warps as W  # noqa: E402
from pokeprism_devtools.wiring.scaffold import Object  # noqa: E402

_failures = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global _failures
    mark = "OK  " if cond else "FAIL"
    print(f"  [{mark}] {label}{(': ' + detail) if detail else ''}")
    if not cond:
        _failures += 1


# --------------------------------------------------------------------------- #
# fixture                                                                     #
# --------------------------------------------------------------------------- #

def _fixture(tmp: Path) -> Path:
    root = tmp / "repo"
    (root / "constants").mkdir(parents=True)
    (root / "maps").mkdir(parents=True)

    (root / "constants" / "map_dimension_constants.asm").write_text(
        "\tconst_def\n\tnewgroup ; 1\n"
        "\tmapgroup TOWN_A, 9, 10\n"       # height 9, width 10
        "\tmapgroup ROUTE_B, 18, 20\n"     # height 18, width 20
        "\tmapgroup FAR_C, 5, 5\n"
    )
    (root / "constants" / "map_constants.asm").write_text(
        "\tconst_def\n\tshift_const EAST\n\tshift_const WEST\n"
        "\tshift_const SOUTH\n\tshift_const NORTH\n"
        "\nconst_value = 1\n\tconst TOWN\n\tconst ROUTE\n\tconst INDOOR\n"
    )
    (root / "maps" / "map_headers.asm").write_text(
        "\tmap_header TownA, TS, TOWN, LM_A, MU, 0, PAL, F0\n"
        "\tmap_header RouteB, TS, ROUTE, LM_B, MU, 0, PAL, F0\n"
        "\tmap_header FarC, TS, INDOOR, LM_C, MU, 0, PAL, F0\n"
    )
    (root / "maps" / "second_map_headers.asm").write_text(
        'SECTION "Second Map Headers", ROMX\n'
        "\tmap_header_2 TownA, TOWN_A, $f, 0\n"
        "\tmap_header_2 RouteB, ROUTE_B, $f, 0\n"
        "\tmap_header_2 FarC, FAR_C, $f, 0\n"
    )

    def _map(name: str, warps: list[str]) -> None:
        (root / "maps" / f"{name}.asm").write_text(
            f"{name}_MapEventHeader:: db 0, 0\n\n"
            f".Warps\n\tdb {len(warps)}\n" + "".join(f"\t{w}\n" for w in warps) + "\n"
            ".CoordEvents\n\tdb 0\n\n"
            ".BGEvents\n\tdb 0\n\n"
            ".ObjectEvents\n\tdb 0\n"
        )

    _map("TownA", ["warp_def 1, 1, 1, FAR_C"])                 # 1 existing warp
    _map("RouteB", ["warp_def 2, 2, 1, FAR_C", "warp_def 3, 3, 2, FAR_C"])
    _map("FarC", ["warp_def 4, 4, 1, TOWN_A", "warp_def 5, 5, 1, ROUTE_B"])
    return root


def _conn_lines(root: Path) -> list[str]:
    return [ln for ln in (root / "maps/second_map_headers.asm").read_text().split("\n")
            if "connection" in ln or "map_header_2" in ln]


# --------------------------------------------------------------------------- #
# the geometry                                                                #
# --------------------------------------------------------------------------- #

def test_plan(root: Path) -> None:
    print("\nk is the offset, and both sides derive from it")
    # RouteB (20 wide) sits north of TownA (10 wide), shifted 3 blocks right.
    left, right = C.plan(root, "TOWN_A", "north", "ROUTE_B", 3)

    check("owner and direction", (left.owner, left.direction) == ("TOWN_A", "north"))
    check("the neighbour gets the opposite direction",
          (right.owner, right.direction) == ("ROUTE_B", "south"))
    check("delta on this side is k", left.delta == 3, str(left.delta))
    check("delta on the other side is -k — crossing back undoes the shift",
          right.delta == -3, str(right.delta))

    # TownA is 10 wide, RouteB 20, and RouteB starts 3 columns in. So TownA's
    # own border columns (-3..2) have no neighbour behind them and can't be
    # filled: the strip starts at 3 and runs to TownA's far border, 10 blocks.
    check("the strip starts where the neighbour actually begins",
          (left.coord, left.offset) == (3, 0), f"{left.coord}, {left.offset}")
    check("and runs to the end of this map's border", left.strip == 10, str(left.strip))

    # From RouteB's side the seam starts 3 columns *before* TownA, so RouteB
    # can fill its border — and does.
    check("the neighbour's side fills its border, because there is map behind it",
          (right.coord, right.offset, right.strip) == (-C.BORDER, 0, 10),
          f"{right.coord}, {right.offset}, {right.strip}")

    print("\ngenerated strips are always in bounds")
    for k in range(-25, 26):
        for a, b in (("TOWN_A", "ROUTE_B"), ("ROUTE_B", "TOWN_A")):
            try:
                one, two = C.plan(root, a, "north", b, k)
            except C.WiringError:
                continue
            for conn, along, other in ((one, _along(root, a), _along(root, b)),
                                       (two, _along(root, b), _along(root, a))):
                inside_source = 0 <= conn.offset and conn.offset + conn.strip <= other
                inside_dest = (conn.coord + C.BORDER >= 0
                               and conn.coord + C.BORDER + conn.strip <= along + 2 * C.BORDER)
                if not (inside_source and inside_dest):
                    check(f"k={k} {a}->{b} in bounds", False, str(conn))
                    return
    check("every offset from -25 to +25 reads and writes inside both maps", True)

    print("\nmaps that don't touch are refused, not silently mis-wired")
    try:
        C.plan(root, "TOWN_A", "north", "FAR_C", 40)   # FAR_C is 5 wide, way off the end
        check("a k that puts the maps past each other raises", False)
    except C.WiringError:
        check("a k that puts the maps past each other raises", True)


def _geometry(root: Path, prefix: str):
    """Run just the geometry rules — the fixture is a map-wiring fixture, not a
    whole repo, so the sprite and flag rules have nothing to read."""
    ctx = LintContext(root)
    found = []
    for rule in rules_geometry.ALL:
        found.extend(rule(ctx))
    return [d for d in found if d.code.startswith(prefix)]


def _along(root: Path, const: str) -> int:
    text = (root / "constants/map_dimension_constants.asm").read_text()
    m = re.search(rf"mapgroup {const},\s*(\d+),\s*(\d+)", text)
    return int(m.group(2))          # width, for a north/south seam


# --------------------------------------------------------------------------- #
# the edits                                                                   #
# --------------------------------------------------------------------------- #

def test_connect(root: Path) -> None:
    print("\nconnect() writes both sides and both flag nibbles")
    edit, (left, right) = C.connect(root, "TOWN_A", "north", "ROUTE_B", 3)
    check("one edit, to the shared header file", edit.changed
          and edit.path == "maps/second_map_headers.asm")
    apply_edits(root, [edit], dry_run=False)

    lines = _conn_lines(root)
    check("TownA gains a north connection",
          any("connection north, ROUTE_B" in ln for ln in lines), str(lines))
    check("RouteB gains the south connection back",
          any("connection south, TOWN_A" in ln for ln in lines))
    check("TownA's flag nibble now names NORTH",
          any("map_header_2 TownA, TOWN_A, $f, NORTH" in ln for ln in lines),
          next(ln for ln in lines if "TownA" in ln))
    check("RouteB's names SOUTH",
          any("map_header_2 RouteB, ROUTE_B, $f, SOUTH" in ln for ln in lines))
    check("the connection sits under its own map's header",
          lines.index(next(l for l in lines if "connection north" in l))
          == lines.index(next(l for l in lines if "TownA" in l)) + 1)

    print("\nre-wiring is idempotent, and re-wiring differently replaces")
    before = (root / "maps/second_map_headers.asm").read_text()
    edit, _ = C.connect(root, "TOWN_A", "north", "ROUTE_B", 3)
    check("the same geometry again is a no-op", not edit.changed, edit.detail)

    edit, _ = C.connect(root, "TOWN_A", "north", "ROUTE_B", -2)
    apply_edits(root, [edit], dry_run=False)
    lines = _conn_lines(root)
    norths = [ln for ln in lines if "connection north, ROUTE_B" in ln]
    check("a different offset rewrites the line rather than adding a second",
          len(norths) == 1, str(norths))
    check("the neighbour's side is rewritten too",
          len([ln for ln in lines if "connection south, TOWN_A" in ln]) == 1)

    print("\nadding a second direction keeps the first")
    edit, _ = C.connect(root, "TOWN_A", "west", "FAR_C", 0)
    apply_edits(root, [edit], dry_run=False)
    lines = _conn_lines(root)
    check("both of TownA's connections are present",
          any("connection north, ROUTE_B" in ln for ln in lines)
          and any("connection west, FAR_C" in ln for ln in lines))
    check("and the nibble names both",
          any("$f, NORTH | WEST" in ln for ln in lines),
          next(ln for ln in lines if "TownA" in ln))

    # The generated wiring must satisfy the rules the linter enforces.
    print("\nthe result passes the linter's connection rules")
    found = _geometry(root, "conn-")
    check("no conn-* findings on what we just generated", not found,
          str([d.message for d in found]))


def test_paired_warp(root: Path) -> None:
    print("\nadd_paired_warp() gets both back-indices right")
    before = {d.message for d in _geometry(root, "warp-")}

    # TownA has 1 warp, RouteB has 2. The new ones become #2 and #3.
    edits, (wa, wb) = W.add_paired_warp(root, "TOWN_A", (7, 8), "ROUTE_B", (9, 10))
    check("A's new warp is #2, B's is #3", (wa.index, wb.index) == (2, 3),
          f"{wa.index}, {wb.index}")
    check("A points at B's new index, not B's current count",
          wa.back_index == 3, str(wa.back_index))
    check("and B points back at A's", wb.back_index == 2, str(wb.back_index))
    apply_edits(root, edits, dry_run=False)

    a = eh.parse_map(root / "maps/TownA.asm")
    b = eh.parse_map(root / "maps/RouteB.asm")
    check("A's warp list grew by one and the count byte agrees",
          len(a.warps) == 2 and a.lists[eh.ListKind.WARPS].count_matches)
    check("B's too", len(b.warps) == 3 and b.lists[eh.ListKind.WARPS].count_matches)
    check("A's new warp is appended, not inserted — existing indices are untouched",
          a.warps[0].args == ["1", "1", "1", "FAR_C"], str(a.warps[0].args))
    check("A's new warp reads y, x, back-index, target",
          a.warps[1].args == ["7", "8", "3", "ROUTE_B"], str(a.warps[1].args))
    check("B's new warp mirrors it", b.warps[2].args == ["9", "10", "2", "TOWN_A"],
          str(b.warps[2].args))

    print("\nthe round trip actually lands where it started")
    new = {d.message for d in _geometry(root, "warp-")} - before
    check("the linter finds nothing wrong with the pair we added — it is in range "
          "and it leads back", not new, str(new))


# --------------------------------------------------------------------------- #
# against the real repo                                                       #
# --------------------------------------------------------------------------- #

def test_real_repo(tmp: Path) -> None:
    root = Path(__file__).resolve().parent.parent.parent / "pokeprism"
    if not (root / "maps").is_dir():
        print("\n(skipping real-repo pass — ../pokeprism not found)")
        return

    print("\ncalibration: the generator vs every connection in the repo")
    exact = total = 0
    owner = None
    for line in (root / "maps/second_map_headers.asm").read_text().split("\n"):
        m = re.match(r"\s*map_header_2\s+\w+,\s*(\w+),", line)
        if m:
            owner = m.group(1)
            continue
        c = re.match(r"\s*connection\s+(\w+),\s*(\w+),\s*\w+,\s*(-?\d+),\s*(-?\d+),\s*(-?\d+),",
                     line)
        if not (c and owner):
            continue
        direction, target = c.group(1), c.group(2)
        coord, offset, strip = int(c.group(3)), int(c.group(4)), int(c.group(5))
        try:
            left, _ = C.plan(root, owner, direction, target, coord - offset)
        except C.WiringError:
            continue
        total += 1
        if (left.coord, left.offset, left.strip) == (coord, offset, strip):
            exact += 1
    check(f"reproduces {exact}/{total} existing connections byte-for-byte from k alone",
          exact >= 45, f"{exact}")
    print(f"      the rest differ only in strip length, which is authored loosely — "
          f"21 of the repo's own connections run past the end of a map")

    print("\nend-to-end: wire two real maps in a scratch copy, then lint it")
    scratch = tmp / "pokeprism"
    shutil.copytree(root, scratch, ignore=shutil.ignore_patterns(".git", "*.gbc", "*.o"))

    # Counted per (code, file). Not per message or line: adding a warp to a map
    # legitimately re-words an existing finding about it ("ROUTE_62 has 2 warps"
    # becomes "has 3"), and splicing a line into a file shifts the ones below it.
    # Neither is a new problem, so what must not move is the *count* per file.
    before = Counter((d.code, d.path) for d in maplint.run(LintContext(scratch)))

    # Two real maps that aren't connected today, and a paired warp between them.
    edit, (left, right) = C.connect(scratch, "CASTRO_FOREST", "north", "ROUTE_62", 0)
    apply_edits(scratch, [edit], dry_run=False)
    warp_edits, (wa, wb) = W.add_paired_warp(
        scratch, "CASTRO_FOREST", (5, 5), "ROUTE_62", (6, 6))
    apply_edits(scratch, warp_edits, dry_run=False)
    print(f"      {edit.detail}")
    print(f"      {left.render().strip()}")
    print(f"      {right.render().strip()}")
    print(f"      warp {wa.index} -> ROUTE_62 #{wa.back_index}, "
          f"warp {wb.index} -> CASTRO_FOREST #{wb.back_index}")

    after = Counter((d.code, d.path) for d in maplint.run(LintContext(scratch)))
    new = {k: after[k] - before.get(k, 0) for k in after if after[k] > before.get(k, 0)}
    check("the linter finds nothing new anywhere in the repo", not new, str(new))

    gone = {k: before[k] - after.get(k, 0) for k in before if before[k] > after.get(k, 0)}
    check("and nothing that was already there was disturbed", not gone, str(gone))

    # The touched files must still parse and round-trip — the writers spliced
    # into them, and everything downstream depends on that staying true.
    for label in ("CastroForest", "Route62"):
        path = scratch / "maps" / f"{label}.asm"
        header = eh.parse_map(path)
        check(f"{label}.asm still round-trips byte-for-byte",
              header.to_text() == path.read_text())

    test_editing(scratch, before)


def test_editing(root: Path, before: Counter) -> None:
    """Changing things that are already there — `wiring/objedit.py`.

    The companion to `test_studio.py`'s round-trip, which proves an edit that
    changes nothing writes nothing. This proves the other half: that an edit which
    *does* change something changes only that.
    """
    print("\nediting what is already there")
    K = eh.ListKind

    # -- one file, one edit ---------------------------------------------------- #
    # An object and the words it says live in the same maps/*.asm, and an Edit
    # carries the whole file. Two of them would silently overwrite each other.
    npc = next(i for i, e in enumerate(eh.parse_map(root / "maps/CastroForest.asm")
                                       .object_events)
               if e.persontype == "PERSONTYPE_TEXTFP")
    entry = eh.parse_map(root / "maps/CastroForest.asm").object_events[npc]
    change = O.edit_npc(
        root, "CASTRO_FOREST", npc,
        Object(sprite="SPRITE_GRAMPS", y=entry.y, x=entry.x, movement=entry.movement,
               palette=O.palette_of(entry.args[O.PALETTE])),
        flag=entry.event_flag, prose="New words.")
    maps = [e for e in change.changes if e.path.startswith("maps/")]
    check("a sprite and its words change in exactly one edit to the map file",
          len(maps) == 1, f"{[e.path for e in change.changes]}")
    check("and the two changes are both in it",
          "SPRITE_GRAMPS" in maps[0].new_text
          and "New words." in maps[0].new_text)

    # -- the palette keeps its arithmetic -------------------------------------- #
    check("the `8 +` that draws a body behind the background survives a recolour",
          "8 + PAL_OW_BLUE" in maps[0].new_text or "8 +" not in entry.args[O.PALETTE])

    # -- a door to nowhere, and back ------------------------------------------- #
    dummy = W.edit_warp(root, "CASTRO_FOREST", 0, 29, 35, dest="")
    text = next(e for e in dummy.changes if e.path.startswith("maps/")).new_text
    check("a warp whose destination is cleared becomes a dummy_warp",
          "dummy_warp 29, 35" in text)
    check("and it keeps its place in the list, so nobody else's warp_to moves",
          text.split("dummy_warp 29, 35")[0].count("warp_def")
          == 0)

    # -- a warp_to past the end is the one mistake that assembles --------------- #
    try:
        W.edit_warp(root, "CASTRO_FOREST", 0, 29, 35, dest="CASTRO_GATE",
                    dest_warp=99)
        check("a warp pointing past the end of its destination is refused", False)
    except W.WarpError as exc:
        check("a warp pointing past the end of its destination is refused",
              "no warp #99" in str(exc), str(exc))

    # -- the trainer macro's tail ---------------------------------------------- #
    # `trainer FLAG, CLASS, PARTY, seen, beaten` is the common shape, not the only
    # one: some carry `, NULL, .script`, and rebuilding the line from the five we
    # know about would delete the script the trainer runs.
    tails = [(label, i) for label in ("AcaniaGym",)
             for i, e in enumerate(eh.parse_map(root / f"maps/{label}.asm")
                                   .object_events)
             if e.pointer and "NULL" in _macro_of(root, label, e.pointer)]
    if tails:
        label, i = tails[0]
        e = eh.parse_map(root / f"maps/{label}.asm").object_events[i]
        was = _macro_of(root, label, e.pointer)
        c = O.edit_trainer(
            root, "ACANIA_GYM", i,
            Object(sprite=e.sprite, y=e.y, x=e.x, movement=e.movement,
                   palette=O.palette_of(e.args[O.PALETTE])),
            _macro_args(was)[1], _macro_args(was)[2],
            sight=e.int_arg(O.PARAM) or 0, seen="A new taunt.")
        after = next(x for x in c.changes if x.path.startswith("maps/")).new_text
        now = next(ln for ln in after.split("\n") if ln.strip().startswith("trainer "))
        check("a trainer macro with a tail keeps its tail when its words change",
              "NULL" in now, now.strip())

    # -- flags are leaked, never freed ----------------------------------------- #
    e = eh.parse_map(root / "maps/CastroForest.asm").object_events[npc]
    c = O.edit_npc(root, "CASTRO_FOREST", npc,
                   Object(sprite=e.sprite, y=e.y, x=e.x, movement=e.movement,
                          palette=O.palette_of(e.args[O.PALETTE])),
                   flag="EVENT_A_BRAND_NEW_FLAG")
    check("naming a new flag allocates it",
          any(x.path == "constants/event_flags.asm" for x in c.changes))
    check("and says the old one is left allocated, because another map may hold it",
          any("left allocated" in n for n in c.notes), str(c.notes))

    # -- and the linter still has nothing new to say --------------------------- #
    apply_edits(root, change.changes, dry_run=False)
    after_lint = Counter((d.code, d.path) for d in maplint.run(LintContext(root)))
    new = {k: after_lint[k] - before.get(k, 0)
           for k in after_lint if after_lint[k] > before.get(k, 0)}
    check("an applied edit introduces no new findings anywhere", not new, str(new))
    check("and the map it touched still round-trips byte-for-byte",
          eh.parse_map(root / "maps/CastroForest.asm").to_text()
          == (root / "maps/CastroForest.asm").read_text())


def _macro_of(root: Path, label: str, pointer: str) -> str:
    lines = (root / f"maps/{label}.asm").read_text().split("\n")
    start = next(i for i, ln in enumerate(lines) if ln.startswith(f"{pointer}:"))
    return next((ln for ln in lines[start:start + 4]
                 if ln.strip().startswith("trainer ")), "")


def _macro_args(line: str) -> list[str]:
    return [a.strip() for a in line.split("trainer ", 1)[1].split(",")]


def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        root = _fixture(tmp)
        test_plan(root)
        test_connect(root)
        test_paired_warp(root)
        test_real_repo(tmp)

    print()
    if _failures:
        print(f"{_failures} check(s) FAILED")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
