#!/usr/bin/env python3
"""Tests for `asmedit/macroline` — the dialect-free rule for reading and
rewriting one `macro Label, …` line, argument by argument.

The rule this guards is the one the whole header-edit path rests on: *an argument
you did not change comes back exactly as it was written*, comments and spacing
intact, and a label that is a prefix of another (`Route30` vs `Route30Gate`) is
not matched by its neighbour's line. Each is shown failing first where a wrong
answer would otherwise look fine.

The middle section guards the **reader and the writer agreeing**. They did not
until the reader was lifted here: it was hand-rolled once per site, and prism's
copy folded a trailing comment into the last argument while prism's own writer
kept it separate, so the same line had two different argument lists depending on
which half of the edit cycle asked. It was latent only because no map header in
any tree carries a comment — so the line under test carries one. Recorded in
`docs/refactor-STATE.md`, with the measurement in `refactor-phase--1-STATE.md`.

The last section is a **byte-identical guard on prism**: the splicer was lifted
out of `hacks/prism/mapedit.py` and prism repointed at it, so this proves the
extraction did not change what prism writes — a real prism header, edited with
its own values, must come back unchanged, and one field moved must move exactly
that line.

    ./.venv/bin/python tests/test_macroline.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pokeprism_devtools.asmedit.editvocab import EditError  # noqa: E402
from pokeprism_devtools.asmedit.macroline import splice_macro_args  # noqa: E402

PRISM = Path.home() / "code/ricccec/pokeprism"

_failures = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global _failures
    mark = "OK  " if cond else "FAIL"
    print(f"  [{mark}] {label}{(': ' + detail) if detail else ''}")
    if not cond:
        _failures += 1


def _tree(text: str) -> Path:
    d = Path(tempfile.mkdtemp())
    (d / "f.asm").write_text(text)
    return d


def test_splicer() -> None:
    print("\nthe splice rule, on synthetic lines")

    # A line with a comment and deliberately uneven spacing around the commas.
    text = ("\tmap Route1, TILESET_A, TOWN, LM_A, MUSIC_A, FALSE, "
            "PALETTE_AUTO, FISHGROUP_NONE ; a comment\n")
    root = _tree(text)

    e = splice_macro_args(root, "f.asm", "map", "Route1",
                          {0: "TILESET_B"}, "d")
    check("one argument moves, the rest and the comment survive",
          e.changed and e.new_text.strip() ==
          "map Route1, TILESET_B, TOWN, LM_A, MUSIC_A, FALSE, "
          "PALETTE_AUTO, FISHGROUP_NONE ; a comment",
          e.new_text.strip())

    # Restating a value that did not move writes nothing, even spelled the same.
    e = splice_macro_args(root, "f.asm", "map", "Route1",
                          {1: "TOWN"}, "d")
    check("an argument restated but unchanged leaves the file alone",
          not e.changed and e.new_text == "", f"changed={e.changed}")

    # A hex value the form hands back as decimal is the same number, not a change.
    root2 = _tree("\tmap_attributes Route1, ROUTE_1, $05\n")
    e = splice_macro_args(root2, "f.asm", "map_attributes", "Route1",
                          {1: "5"}, "d")
    check("hex restated as its own decimal is not a change (same, not ==)",
          not e.changed, f"changed={e.changed}")

    # Prefix-name safety: editing Route30 must not touch Route30Gate's line.
    root3 = _tree("\tmap Route30Gate, TS_G, INDOOR\n"
                  "\tmap Route30, TS_R, ROUTE\n")
    e = splice_macro_args(root3, "f.asm", "map", "Route30", {0: "TS_X"}, "d")
    lines = e.new_text.splitlines()
    check("a prefix-name neighbour (Route30 vs Route30Gate) is not matched",
          "map Route30Gate, TS_G, INDOOR" in lines[0]
          and "TS_X" in lines[1], e.new_text)

    # Out-of-range index is a refusal, not a silent miss.
    try:
        splice_macro_args(root3, "f.asm", "map", "Route30", {9: "x"}, "d")
        check("an out-of-range argument index raises", False, "did not raise")
    except EditError as exc:
        check("an out-of-range argument index raises EditError",
              "nothing at 9" in str(exc), str(exc))

    # A label the file does not have is a refusal too.
    try:
        splice_macro_args(root3, "f.asm", "map", "NoSuchMap", {0: "x"}, "d")
        check("a missing label raises", False, "did not raise")
    except EditError as exc:
        check("a missing label raises EditError", "no map line" in str(exc),
              str(exc))


def test_prism_byte_identical() -> None:
    print("\nprism byte-identical guard (the extraction changed nothing)")
    if not PRISM.exists():
        print(f"  --   no pokeprism checkout at {PRISM} — skipping")
        return

    from pokeprism_devtools.hacks.prism import mapedit

    label = _some_prism_label()
    if label is None:
        print("  --   no readable prism map header — skipping")
        return

    before_primary = (PRISM / mapedit.PRIMARY).read_text()
    before_secondary = (PRISM / mapedit.SECONDARY).read_text()

    was = mapedit.values(PRISM, label)
    same_again = {f: was[f] for f in (*mapedit.FIELDS, "border_block")}
    change = mapedit.edit_map(PRISM, label, same_again)
    check(f"{label}: editing prism with its own values writes nothing",
          change.changes == [], change.summary)

    # And exactly one line moves when one field does — the other file untouched.
    moved = dict(same_again)
    moved["border_block"] = "$1f" if was["border_block"] != "$1f" else "$1e"
    change = mapedit.edit_map(PRISM, label, moved)
    touched = [e.path for e in change.changes]
    check(f"{label}: moving the border block touches only {mapedit.SECONDARY}",
          touched == [mapedit.SECONDARY], f"touched {touched}")

    # None of this was allowed to write to disk (edit_map computes, never applies).
    check("the prism tree on disk is untouched by the round-trip",
          (PRISM / mapedit.PRIMARY).read_text() == before_primary
          and (PRISM / mapedit.SECONDARY).read_text() == before_secondary)


def test_readers_agree_about_comments() -> None:
    """*Read one macro line's arguments* — one implementation, three callers.

    This used to pin a divergence: prism's reader folded a trailing `; comment`
    into the last argument, the family's dropped it, the writer preserved it, so
    prism's read path and prism's *own* write path disagreed about what the
    arguments of one line were. The reader was lifted to `asmedit/macroline`
    beside the writer (`docs/refactor-STATE.md`, Phase −1), so the assertion
    is now that **all three agree**, and it is made through the two adapters'
    real read paths rather than against a copy of their regexes — a site that
    quietly re-rolled its own would fail here.

    The line carries a comment on purpose. No header in any tree does today, but
    that was the only reason the old divergence was harmless, and this is what
    the fix is for.
    """
    print("\nthe one macro-line reader, from both adapters' read paths")

    from pokeprism_devtools.hacks.prism import mapsource
    from pokeprism_devtools.hacks.vanilla import mapedit as family_mapedit
    from pokeprism_devtools.asmedit.macroline import read_macro_line

    args = ("TILESET_CAVE, CAVE, LM_MT_EMBER, MUSIC_CAVE, 0, PALETTE_NITE, "
            "FISHGROUP_SHORE")
    label = "MtEmberSmallRoom"
    line = f"\tmap_header {label}, {args} ; a note"
    expected = [a.strip() for a in args.split(",")]

    # Prism's read path, through the file layout it actually reads.
    root = _tree("")
    (root / "maps").mkdir()
    (root / "maps/map_headers.asm").write_text(line + "\n")
    prism = mapsource.primary_header(root, label)
    check("prism's reader drops the comment from the last argument",
          prism.fishgroup == "FISHGROUP_SHORE", repr(prism.fishgroup))

    # The family's read path, on its own two-file layout.
    family_root = _tree("")
    (family_root / "data/maps").mkdir(parents=True)
    (family_root / family_mapedit.MAPS).write_text(
        f"\tmap {label}, {args} ; a note\n")
    family = family_mapedit._args_of(family_root, family_mapedit.MAPS,
                                     "map", label)
    check("the family's reader agrees, argument for argument",
          family == expected, f"{family}")

    # And the writer, which is what those indices are handed back to.
    e = splice_macro_args(root, "maps/map_headers.asm", "map_header", label,
                          {6: "FISHGROUP_LAKE"}, "d")
    check("the writer indexes the same arguments and keeps the comment",
          e.new_text.strip().endswith("FISHGROUP_LAKE ; a note"),
          e.new_text.strip())

    # The general reader, whose first argument is the label — the shape prism's
    # event header wants, and the one that must not be confused with the above.
    read = read_macro_line(line)
    check("read_macro_line splits macro / args / comment",
          read.macro == "map_header" and read.args == [label, *expected]
          and read.comment == "; a note", f"{read}")


def _some_prism_label() -> str | None:
    from pokeprism_devtools.hacks.prism import mapedit, mapsource
    for label, _ in mapsource.header_pairs(PRISM):
        try:
            mapedit.values(PRISM, label)
            return label
        except EditError:
            continue
    return None


def main() -> int:
    test_splicer()
    test_readers_agree_about_comments()
    test_prism_byte_identical()
    print("\nall checks passed" if not _failures else f"\n{_failures} FAILED")
    return 1 if _failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
