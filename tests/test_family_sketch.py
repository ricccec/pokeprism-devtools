#!/usr/bin/env python3
"""Tests for the family new-map form's picture — `studio/mapadd.AddMap.sketch`
and the `sketch` each family reader answers it with.

The form draws the *shape* and the adapter puts the *colour* on it, because a
grid file is bytes in any tree but a tileset constant means something only to
the tree that defines it. Both halves are checked here, on real checkouts,
through the mounted seam rather than by calling the pieces directly — the bug
worth catching is a form and a reader that each work and do not meet.

Every check is shown failing first (`falsified`), because the failure mode this
feature exists to prevent is a picture that looks fine and is wrong: a `.blk`
whose length disagrees with the height draws a map cut off at the bottom, and a
tileset that silently fell back to zero draws a forest in a cave's colours. A
check that has never been shown to fail is not evidence of either.

Run against real checkouts:

    ./.venv/bin/python tests/test_family_sketch.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pokeprism_devtools.hacks import mount as m  # noqa: E402
from pokeprism_devtools.contract import ActionError  # noqa: E402
from pokeprism_devtools.wiring import mapnew  # noqa: E402

#: The trees to try, and one real map in each to borrow a grid and a tileset
#: from. Borrowed rather than invented so the sizes are a tree's own: a grid
#: that the tree itself ships at these dimensions cannot be wrong about them.
TREES = {
    "vanilla": (Path.home() / "code/ricccec/pokecrystal", "Route36"),
    "polished": (Path.home() / "code/ricccec/polishedcrystal", None),
}

_failures = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global _failures
    mark = "OK  " if cond else "FAIL"
    print(f"  [{mark}] {label}{(': ' + detail) if detail else ''}")
    if not cond:
        _failures += 1


def refuses(label: str, call, *expect: str) -> None:
    """The falsification half: this must raise, and say which thing is wrong.

    A refusal that raises the right *type* and the wrong *words* is the failure
    mode that matters on a form you are typing into — you read the message, not
    the traceback, and a message that does not name your mistake sends you
    looking at the wrong field.
    """
    try:
        call()
    except ActionError as exc:
        missing = [w for w in expect if w not in str(exc)]
        check(label, not missing, f"said {str(exc)!r}"
              + (f", missing {missing}" if missing else ""))
    else:
        check(label, False, "it drew instead of refusing")


def a_real_map(hack, tree: Path, prefer: str | None) -> tuple[str, Path, int, int, str]:
    """A map the tree ships: its label, grid path, size and tileset.

    Read back through the adapter's own `geometry`/`attributes`, so the numbers
    are the ones this tree believes rather than ones this test asserts.

    `.lzp` is stripped for the same reason `polished/read.geometry` strips it:
    the attribute names the *built* artifact, and the uncompressed `.ablk`
    beside it is the file an author draws and the form points at.
    """
    labels = list(hack.reads.maps())
    for label in ([prefer] if prefer in labels else []) + labels:
        try:
            blocks = hack.reads.geometry(label)
        except Exception:
            continue
        attrs = hack.reads.attributes(label, hack.reads.maps()[label])
        grid = tree / attrs.blk.removesuffix(".lzp")
        if blocks.swatches and grid.is_file() and attrs.tileset.startswith("TILESET_"):
            return label, grid, blocks.height, blocks.width, attrs.tileset
    raise RuntimeError(f"no drawable map found in {tree}")


def form_for(hack, **values: str):
    """The tree's own new-map action, part-filled. The class comes from the
    write adapter, so this is the form a user would actually be typing into —
    fields and all — not a stand-in built here."""
    cls = hack.writes.form("newmap")
    return cls("", **values)


def test_tree(name: str, tree: Path, prefer: str | None) -> None:
    print(f"\n{name} — the grid is drawn before it is written")
    if not tree.exists():
        print(f"  --   no checkout at {tree} — skipping")
        return
    hack = m.mount(tree)
    if hack.writes is None or hack.writes.form("newmap") is None:
        print("  --   this tree has no new-map form — skipping")
        return

    label, grid, height, width, tileset = a_real_map(hack, tree, prefer)
    print(f"       borrowing {label}: {grid.name}, {height}x{width}, {tileset}")
    base = {"label": "TestIsland", "const": "TEST_ISLAND", "group": "1",
            "height": str(height), "width": str(width), "blk": str(grid),
            "tileset": tileset}

    def drawn(**over: str):
        return hack.reads.sketch(form_for(hack, **(base | over)))

    view = drawn()
    check("the grid is on the studio's grid before anything is written",
          view is not None)
    assert view is not None
    check("  at the size the form asked for",
          (view.height, view.width) == (height, width),
          f"{view.height}x{view.width}")
    check("  holding the bytes of the file pointed at, not a copy of something else",
          view.blocks == grid.read_bytes())
    check("  in the tileset's colours, one swatch per block id",
          len(view.swatches) > 0 and max(view.blocks) < len(view.swatches),
          f"{len(view.swatches)} swatches, highest block id {max(view.blocks)}")
    check("  carrying the name typed into the form, which no map has yet",
          view.label == "TestIsland", view.label)

    # -- falsified: each refusal, shown refusing ---------------------------- #
    need = height * width
    refuses("a height that disagrees with the grid is refused, with both numbers",
            lambda: drawn(height=str(height + 1)),
            str(len(grid.read_bytes())), str(need))
    refuses("a grid file that is not there is refused by name",
            lambda: drawn(blk=str(tree / "no-such-file.blk")), "no such file")
    refuses("a form with no grid yet asks for one rather than failing",
            lambda: drawn(blk=""), "point at the grid")
    refuses("a size that is not a size is refused",
            lambda: drawn(height="0"), "at least one block")
    refuses("a tileset that does not exist is refused, not quietly drawn in "
            "tileset 0's colours", lambda: drawn(tileset="TILESET_FORREST"),
            "TILESET_FORREST")

    # -- the tileset you have not finished typing is not a mistake ---------- #
    part = drawn(tileset="")
    check("a tileset not yet typed draws the shape uncoloured rather than "
          "refusing — you are still typing", part is not None
          and part.swatches == () and part.blocks == grid.read_bytes())

    # -- the picture and the write are one rule ----------------------------- #
    # `read_grid` is shared, so a grid the picture refuses cannot then be
    # written. Falsify by proving the writer refuses the same case, with the
    # same words, rather than trusting that they were kept in step.
    with tempfile.TemporaryDirectory() as tmp:
        bad = Path(tmp) / "short.blk"
        bad.write_bytes(grid.read_bytes()[:-1])
        drew = writes = ""
        try:
            drawn(blk=str(bad))
        except ActionError as exc:
            drew = str(exc)
        try:
            mapnew.read_grid(bad, height, width)
        except mapnew.EditError as exc:
            writes = str(exc)
        check("a grid the picture refuses is refused in the same words by the "
              "write — one rule, not two that drift", bool(drew) and drew == writes,
              f"picture={drew!r} write={writes!r}")


def main() -> int:
    for name, (tree, prefer) in TREES.items():
        test_tree(name, tree, prefer)
    print("\nall checks passed" if not _failures else f"\n{_failures} FAILED")
    return 1 if _failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
