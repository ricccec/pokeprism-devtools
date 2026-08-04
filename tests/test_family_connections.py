#!/usr/bin/env python3
"""Tests for the family connection editor — the "Add new…" connection on the
Connections tab and `d` on a connection row (`hacks/vanilla/connections.py`,
mounted through the seam for both vanilla and polished).

A connection is the one family edit that is **two-sided and cross-map**: a pair
of `connection` lines in the shared `data/maps/attributes.asm`, one under each
map, and the neighbour's offset is the *negative* of this side's. So the two
failure modes this guards are (1) a one-sided writer — A gets its line, B never
gets the mirror, and you have a wall you can walk through one way — and (2) the
reciprocal written with the wrong sign, which is the same wall a block further
along. Both are checked falsified-first: the reciprocal must be present *and*
carry `-k`, and every line the edit did not mean to touch must come back verbatim.

The macro also refuses to assemble unless a map's connections are in north,
south, west, east order, so a fresh insert is checked to land in its slot rather
than at the end.

Nothing here writes to the real trees: the real `attributes.asm` is the source,
and every mutation runs against a throwaway copy of just that one file, so
`connect`/`disconnect` compute against a tree that is real enough for them (they
read only that file) without the checkout ever changing.

    ./.venv/bin/python tests/test_family_connections.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pokeprism_devtools.hacks import mount as m  # noqa: E402
from pokeprism_devtools.hacks.vanilla import connections as c  # noqa: E402
from pokeprism_devtools.contract import Ref  # noqa: E402

TREES = {
    "vanilla": Path.home() / "code/ricccec/pokecrystal",
    "polished": Path.home() / "code/ricccec/polishedcrystal",
}

_failures = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global _failures
    mark = "OK  " if cond else "FAIL"
    print(f"  [{mark}] {label}{(': ' + detail) if detail else ''}")
    if not cond:
        _failures += 1


def _mktree(text: str) -> Path:
    """A throwaway tree holding only `data/maps/attributes.asm` — all the
    connection editor reads."""
    d = Path(tempfile.mkdtemp())
    (d / "data/maps").mkdir(parents=True)
    (d / c.REL).write_text(text)
    return d


def _block(text: str, const: str) -> list[str]:
    lines = text.split("\n")
    start = c._header_line(lines, const)
    return lines[start:c._block_end(lines, start)]


def _dirs(block: list[str]) -> list[str]:
    return [mo.group("dir") for ln in block if (mo := c._CONN_RE.match(ln))]


def _first_pair(text: str) -> tuple[str, str, str, int] | None:
    """A real (A, direction, B, k) whose reciprocal B/opposite/A also exists —
    so identity and disconnect have a genuine two-sided pair to work on."""
    lines = text.split("\n")
    for i, ln in enumerate(lines):
        cm = c._CONN_RE.match(ln)
        if not cm:
            continue
        # which map's block are we in?
        for j in range(i, -1, -1):
            am = c._ATTRS_RE.match(lines[j])
            if am:
                a = am.group("const")
                break
        else:
            continue
        d, b, k = cm.group("dir").lower(), cm.group("const"), int(cm.group("offset"))
        if c._find(lines, c._header_line(lines, b), c.OPPOSITE[d], target=a) is not None:
            return a, d, b, k
    return None


def _free_direction(text: str, const: str) -> str | None:
    """A direction `const` has no connection in yet — room for a fresh insert."""
    have = set(_dirs(_block(text, const)))
    return next((d for d in c.ORDER if d not in have), None)


def test_tree(name: str, tree: Path) -> None:
    print(f"\n{name} — connections are two-sided, in one shared file")
    if not tree.exists():
        print(f"  --   no checkout at {tree} — skipping")
        return
    hack = m.mount(tree)
    if hack.writes is None:
        print("  --   this tree is read-only — skipping")
        return

    orig = (tree / c.REL).read_text()

    # -- the seam: the tab offers an adder, a row offers a delete -------------- #
    adders = hack.writes.adders("connection")
    check("the Connections tab now offers an adder instead of nothing",
          len(adders) == 1 and adders[0].name == "connect",
          str([a.__name__ for a in adders]))

    pair = _first_pair(orig)
    if pair is None:
        print("  --   no reciprocal connection pair found — skipping the rest")
        return
    a, d, b, k = pair
    print(f"       working from {a} {d} {b} (offset {k})")

    dele = hack.writes.deletion(a, a, Ref("connection", key=d))
    check("`d` on a connection row opens the disconnect action",
          dele.name == "disconnect")

    # -- identity: connecting an existing pair with its own geometry is a no-op  #
    e = c.connect(tree, a, d, b, k)
    check("connecting an already-connected pair writes nothing",
          not e.changed, e.detail)

    # -- disconnect removes BOTH sides; reconnect restores byte-for-byte ------- #
    edit, notes = c.disconnect(tree, a, d)
    check(f"disconnect drops {a}'s {d} line", d not in _dirs(_block(edit.new_text, a)))
    check(f"  and the neighbour {b}'s {c.OPPOSITE[d]} line back to it",
          c._find(edit.new_text.split("\n"),
                  c._header_line(edit.new_text.split("\n"), b),
                  c.OPPOSITE[d], target=a) is None)

    t = _mktree(edit.new_text)
    back = c.connect(t, a, d, b, k)
    check("disconnect then reconnect is byte-for-byte the original",
          back.new_text == orig)

    # -- a FRESH insert lands in north/south/west/east order, both sides ------- #
    free = _free_direction(orig, a)
    if free is not None:
        # pick a neighbour that isn't already wired to `a` in this direction
        nb = next((x for x in hack.reads.maps().values()
                   if x != a and x != b), b)
        e2 = c.connect(tree, a, free, nb, 2)
        after = _dirs(_block(e2.new_text, a))
        ordered = after == sorted(after, key=c.ORDER.index)
        check(f"a fresh {free} connection lands in order (not appended)",
              free in after and ordered, str(after))
        # the reciprocal must exist AND carry -k — falsify a one-sided / wrong-sign write
        recip = _block(e2.new_text, nb)
        line = next((ln for ln in recip if c.OPPOSITE[free] in ln and a in ln), "")
        km = c._CONN_RE.match(line)
        check("  the neighbour gets the mirror, at the negated offset",
              km is not None and int(km.group("offset")) == -2,
              line.strip() or "no reciprocal line")

    # -- everything the edit did not touch comes back verbatim ---------------- #
    #    A whole-file rewrite would pass the block checks and fail this: the only
    #    difference between the two files must be *deletions*, of exactly 2 lines.
    #    (Index-wise diffing is wrong here — deleting two lines shifts every line
    #    after them, so it would flag the whole tail.)
    removed, other_ops = _delete_only(orig, edit.new_text)
    check("disconnect only deletes lines — it rewrites nothing else",
          not other_ops, f"non-delete ops: {other_ops}")
    check("  and it deletes exactly the two connection lines",
          removed == 2, f"deleted {removed} lines")

    # -- validation at the boundary ------------------------------------------- #
    try:
        c.connect(tree, "TOTALLY_NOT_A_MAP", "north", b, 0)
        check("an unknown map is refused", False, "it wrote instead")
    except c.WiringError as exc:
        check("an unknown map is refused, by name", "TOTALLY_NOT_A_MAP" in str(exc),
              str(exc))


def _delete_only(orig: str, new: str) -> tuple[int, list[str]]:
    """(lines deleted, any non-delete edit tags). A clean removal shows only
    `equal` and `delete` opcodes; a `replace` or `insert` means a line the edit
    had no business touching moved."""
    import difflib
    sm = difflib.SequenceMatcher(a=orig.split("\n"), b=new.split("\n"))
    removed = 0
    others: list[str] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "delete":
            removed += i2 - i1
        elif tag != "equal":
            others.append(tag)
    return removed, others


def test_oneway_note() -> None:
    """Disconnecting a one-way connection removes the near side and *says* the far
    side was already absent, rather than silently fixing or failing."""
    print("\na one-way connection disconnects with a note, not a repair")
    text = ("\tmap_attributes AA, AA_MAP, $05\n"
            "\tconnection east, Bb, BB_MAP, 0\n"
            "\n"
            "\tmap_attributes Bb, BB_MAP, $05\n")  # no reciprocal
    t = _mktree(text)
    edit, notes = c.disconnect(t, "AA_MAP", "east")
    check("the near side is removed", "east" not in _dirs(_block(edit.new_text, "AA_MAP")))
    check("and the missing far side is reported, not invented",
          any("one-way" in n for n in notes), str(notes))


def main() -> int:
    for name, tree in TREES.items():
        test_tree(name, tree)
    test_oneway_note()
    print("\nall checks passed" if not _failures else f"\n{_failures} FAILED")
    return 1 if _failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
