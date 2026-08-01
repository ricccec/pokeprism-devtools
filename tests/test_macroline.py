#!/usr/bin/env python3
"""Tests for `wiring/macroline.splice_macro_args` — the dialect-free rule for
rewriting one `macro Label, …` line, argument by argument.

The rule this guards is the one the whole header-edit path rests on: *an argument
you did not change comes back exactly as it was written*, comments and spacing
intact, and a label that is a prefix of another (`Route30` vs `Route30Gate`) is
not matched by its neighbour's line. Each is shown failing first where a wrong
answer would otherwise look fine.

The middle section pins a **finding, not a rule**: the same "read one macro line's
arguments" mechanic is hand-rolled a dozen times across the repo with three
different answers about a trailing comment, and prism's reader disagrees with
prism's own writer. It is latent today only because no prism header carries a
comment — which the census there checks, so the day it stops being true a test
says so instead of a map header quietly gaining a fishgroup called
`FISHGROUP_SHORE ; a note`. Recorded in `docs/refactor-STATE.md`, scheduled in
`docs/refactor-plan.md` under "Before anything".

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

from pokeprism_devtools.wiring.editvocab import EditError  # noqa: E402
from pokeprism_devtools.wiring.macroline import splice_macro_args  # noqa: E402

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


def test_readers_disagree_about_comments() -> None:
    """The three implementations of *read one macro line's arguments*, side by side.

    There is one writer (`splice_macro_args`) and two hand-rolled readers, and they
    do not agree about a trailing `; comment`: the family drops it, prism folds it
    into the last argument, the writer preserves it. So prism's read path and
    prism's *own* write path disagree about what the arguments of one line are.

    This test does not assert that the divergence is right. It **pins it in place
    so it cannot be rediscovered a third time**, and it fails the day the premise
    that keeps it harmless stops holding — see the census below. When the reader is
    lifted (`refactor-plan.md`, "Before anything"), the first check flips to *all
    three agree* and the second one stops being needed. That is what done looks
    like.
    """
    print("\nthe three macro-line readers (see refactor-STATE.md)")

    import re

    from pokeprism_devtools.hacks.prism.mapsource import _split_fields
    from pokeprism_devtools.hacks.vanilla.mapedit import _find_args  # noqa: F401

    line = ("\tmap_header MtEmberSmallRoom, TILESET_CAVE, CAVE, LM_MT_EMBER, "
            "MUSIC_CAVE, 0, PALETTE_NITE, FISHGROUP_SHORE ; a note")

    prism = _split_fields(
        re.match(r"^\s*map_header\s+MtEmberSmallRoom\s*,(.*)$", line).group(1))
    family = [a.strip() for a in
              re.match(r"^\s*map_header\s+(\w+)\s*,\s*(.+)", line)
              .group(2).split(";")[0].split(",")]
    w = re.match(r"^(?P<head>\s*map_header\s+MtEmberSmallRoom\s*,)"
                 r"(?P<args>.*?)(?P<comment>\s*;.*)?$", line)
    writer = [a.strip() for a in w.group("args").split(",")]

    check("the family reader agrees with the writer about the arguments",
          family == writer, f"{family[-1]!r} vs {writer[-1]!r}")
    check("prism's reader does NOT — the comment lands in the last argument",
          prism != writer and prism[-1].endswith("; a note"), repr(prism[-1]))
    check("the writer keeps the comment it found",
          w.group("comment") == " ; a note", repr(w.group("comment")))

    # The premise that keeps prism's version harmless: no prism header carries a
    # comment today. This is the check that announces the day that stops being
    # true — at which point prism reads a fishgroup called "FISHGROUP_SHORE ; a
    # note" and validates it against the constants file.
    if not PRISM.exists():
        print(f"  --   no pokeprism checkout at {PRISM} — census skipped")
        return
    from pokeprism_devtools.hacks.prism import mapedit
    commented = {}
    for rel, macro in ((mapedit.PRIMARY, "map_header"),
                       (mapedit.SECONDARY, "map_header_2")):
        rx = re.compile(rf"^\s*{macro}\s+\w+\s*,.*;")
        commented[rel] = sum(bool(rx.match(ln))
                             for ln in (PRISM / rel).read_text().splitlines())
    check("no prism map header carries a trailing comment, so the gap is latent",
          not any(commented.values()),
          f"{commented} — the reader must be lifted before this ships")


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
    test_readers_disagree_about_comments()
    test_prism_byte_identical()
    print("\nall checks passed" if not _failures else f"\n{_failures} FAILED")
    return 1 if _failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
