#!/usr/bin/env python3
"""Tests for the family map-header editor — `e` on the Attributes tab of a
vanilla or polished map (`hacks/vanilla/mapedit.py`, mounted through the seam).

The family header is **split across two files** and its `map` arguments **fork
between the two trees**, so the two failure modes this guards are (1) a splice
that touches an argument it was not asked to — the transposed-radius class of bug
one macro along — and (2) the split write landing in the wrong file. Both are
checked falsified-first, on real checkouts, through the mounted write adapter
rather than by calling the module directly: the bug worth catching is a form and
a splicer that each work and do not meet.

Everything runs against the real trees without touching them: `edit_map` computes
the full post-edit file text and never writes it, so the checks diff that text
against the file on disk. A single field moved must change **exactly one line, in
exactly one file, at exactly one argument**, and every other argument must come
back as the *source text* it was — spacing, hex and all.

    ./.venv/bin/python tests/test_family_mapedit.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pokeprism_devtools.hacks import mount as m  # noqa: E402
from pokeprism_devtools.hacks.vanilla import mapedit  # noqa: E402
from pokeprism_devtools.contract import ActionError  # noqa: E402
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


def _args_of(root: Path, rel: str, macro: str, label: str) -> list[str]:
    """The one `macro Label, …` line's arguments, as source text (verbatim)."""
    line = _line_of(root, rel, macro, label)
    body = line.split(",", 1)[1].split(";")[0]
    return [a.strip() for a in body.split(",")]


def _line_of(root: Path, rel: str, macro: str, label: str) -> str:
    for ln in (root / rel).read_text().splitlines():
        s = ln.strip()
        if s.startswith(f"{macro} {label},"):
            return ln
    raise AssertionError(f"no {macro} {label} line in {rel}")


def _diff_lines(orig: str, new: str) -> list[int]:
    a, b = orig.splitlines(), new.splitlines()
    return [i for i in range(max(len(a), len(b)))
            if (a[i] if i < len(a) else None) != (b[i] if i < len(b) else None)]


def _new_text(change, rel: str) -> str | None:
    """The post-edit text of one file, or None if this edit changed nothing."""
    for e in change.edits:
        if e.path == rel:
            return e.new_text if e.changed else None
    return None


def _another(hack, field, current: str) -> str | None:
    """A valid value for this field that is not the current one, or None to skip
    (a field with only one legal value cannot be exercised)."""
    if field.options:
        pool = [o for o in field.options if o != current]
    else:
        pool = [c for c in hack.writes.choices(field.choices, ())
                if c != current]
    return pool[0] if pool else None


def test_tree(name: str, tree: Path) -> None:
    print(f"\n{name} — the header is edited across two files")
    if not tree.exists():
        print(f"  --   no checkout at {tree} — skipping")
        return
    hack = m.mount(tree)
    if hack.writes is None:
        print("  --   this tree is read-only — skipping")
        return

    label, const = _drawable_map(hack)
    print(f"       editing {label} ({const})")

    # -- the seam: `e` on the map row opens the header form ------------------- #
    cls, values, boxes = hack.writes.editor(label, const, Ref("map"), [])
    dialect = cls.dialect
    want = ("label", "const", *dialect.header_args, "border_block")
    check("the map row now opens an editor instead of refusing",
          cls.name == "editmap" and boxes == {})
    check("  its fields are the two fixed rows, the tree's own map arguments, "
          "and the border block", tuple(f.name for f in cls.FIELDS) == want,
          str(tuple(f.name for f in cls.FIELDS)))
    check("  prefilled with every argument the writer will splice",
          all(values.get(k) for k in dialect.header_args) and values["const"] == const,
          str(values))

    base = {k: values[k] for k in (*dialect.header_args, "border_block")}

    # -- round-trip identity: same values in, nothing written ---------------- #
    change = mapedit.edit_map(tree, label, dialect, hack.writes.set_of, base)
    check("editing with the values it opened with writes nothing",
          change.changes == [], change.summary)

    # -- one field moved: exactly one line, one file, one argument ----------- #
    orig_maps = (tree / mapedit.MAPS).read_text()
    orig_attrs = (tree / mapedit.ATTRS).read_text()

    for field in dialect.header_fields:
        alt = _another(hack, field, base[field.name])
        if alt is None:
            continue
        moved = {**base, field.name: alt}
        change = mapedit.edit_map(tree, label, dialect, hack.writes.set_of, moved)

        new_maps = _new_text(change, mapedit.MAPS)
        check(f"{field.name} -> {alt}: only maps.asm changes",
              new_maps is not None and _new_text(change, mapedit.ATTRS) is None)
        if new_maps is None:
            continue
        lines = _diff_lines(orig_maps, new_maps)
        check(f"  exactly one line moves", len(lines) == 1, f"lines {lines}")

        before = _args_of(tree, mapedit.MAPS, "map", label)
        after = [a.strip() for a in
                 new_maps.splitlines()[lines[0]].split(",", 1)[1].split(";")[0].split(",")]
        idx = dialect.header_args.index(field.name)
        # Falsify a transposed / whole-line rewrite: only the target argument may
        # differ, and every other must be byte-for-byte its old source text.
        others_verbatim = all(before[i] == after[i]
                              for i in range(len(before)) if i != idx)
        check(f"  only argument {idx} differs; the rest come back verbatim",
              after[idx] == alt and others_verbatim,
              f"before={before} after={after}")

    # -- the border block is the split: it lands in the *other* file --------- #
    alt_border = "$1" if base["border_block"] != "$1" else "$2"
    change = mapedit.edit_map(tree, label, dialect, hack.writes.set_of,
                              {**base, "border_block": alt_border})
    check("border block -> the change lands in attributes.asm, not maps.asm",
          _new_text(change, mapedit.ATTRS) is not None
          and _new_text(change, mapedit.MAPS) is None)
    new_attrs = _new_text(change, mapedit.ATTRS)
    if new_attrs is not None:
        lines = _diff_lines(orig_attrs, new_attrs)
        after = _args_of_text(new_attrs, "map_attributes", label)
        check("  exactly one line moves, the const (arg 0) untouched",
              len(lines) == 1 and after[0] == const and after[mapedit.BORDER] == alt_border,
              f"lines {lines} args {after}")

    # -- validation: a changed constant must exist; an unchanged one need not - #
    _test_validation(name, hack, tree, label, dialect, base)


def _test_validation(name, hack, tree, label, dialect, base) -> None:
    # A *changed* enum field set to a bogus constant is refused, by name.
    enum = next((f for f in dialect.header_fields if f.choices and not f.options), None)
    if enum is not None:
        bogus = "TOTALLY_NOT_A_REAL_CONSTANT"
        try:
            mapedit.edit_map(tree, label, dialect, hack.writes.set_of,
                             {**base, enum.name: bogus})
            check(f"a bogus {enum.name} is refused", False, "it wrote instead")
        except mapedit.EditError as exc:
            check(f"a bogus {enum.name} is refused, by name", bogus in str(exc),
                  str(exc))

    # An *unchanged* value the repo cannot vouch for is NOT refused — you are not
    # made to fix what you did not touch (the MUSIC_NONE lesson). Forge a `was`
    # that already holds an unknown constant and edit a *different* field.
    if enum is not None:
        forged = {**base, enum.name: "SOME_LEGACY_CONSTANT_WE_CANNOT_FIND"}
        # only validates changed fields, so leaving enum untouched must pass
        problems = mapedit._unknown(tree, dialect, hack.writes.set_of,
                                    was=forged, new=forged)
        check("an unknown constant left untouched is not refused",
              problems == [], str(problems))


def _args_of_text(text: str, macro: str, label: str) -> list[str]:
    for ln in text.splitlines():
        if ln.strip().startswith(f"{macro} {label},"):
            body = ln.split(",", 1)[1].split(";")[0]
            return [a.strip() for a in body.split(",")]
    raise AssertionError(f"no {macro} {label} after edit")


def _drawable_map(hack) -> tuple[str, str]:
    """A map both files describe — most do; pick the first that `values` reads
    cleanly so the test is about the splice, not about a half-wired map."""
    from pokeprism_devtools.hacks.vanilla import newmap
    dialect = hack.writes._newmap or newmap.VANILLA
    for label, const in hack.reads.maps().items():
        try:
            mapedit.values(hack.reads.root, label, dialect)
            return label, const
        except mapedit.EditError:
            continue
    raise RuntimeError("no readable map header found")


def main() -> int:
    for name, tree in TREES.items():
        test_tree(name, tree)
    print("\nall checks passed" if not _failures else f"\n{_failures} FAILED")
    return 1 if _failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
