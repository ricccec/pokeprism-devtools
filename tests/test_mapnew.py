#!/usr/bin/env python3
"""Tests for `wiring/mapnew.py` — adding a map to a pokecrystal-family tree.

The check that matters is not that the written lines look right. It is that
`constants/map_constants.asm` and `data/maps/maps.asm` stay **parallel arrays**:
`map_const` assigns a map's id by counting, and `MapGroupPointers` is indexed by
that id, so an insertion in the wrong place renumbers every map below it in its
group and the game builds anyway, with doors opening onto the wrong rooms.

So :func:`agree` walks both files, every group, every map, and reports the first
position where the two disagree — and :func:`test_falsify` breaks the tree on
purpose first, because a consistency check that has never been shown to fail is
not evidence of consistency.

Run against real checkouts, copied file-by-file into a temp dir:

    python tests/test_mapnew.py
"""

from __future__ import annotations

import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pokeprism_devtools.hacks.vanilla import newmap as NM  # noqa: E402
from pokeprism_devtools.shared.edits import apply_edits  # noqa: E402
from pokeprism_devtools.wiring import mapnew as MN  # noqa: E402
from pokeprism_devtools.wiring.editvocab import EditError  # noqa: E402

VANILLA = Path.home() / "code/ricccec/pokecrystal"
POLISHED = Path.home() / "code/ricccec/polishedcrystal"

#: Enough of a tree to wire a map into. Everything else a real checkout has is
#: irrelevant to these six files.
NEEDED = ("constants/map_constants.asm", "data/maps/maps.asm",
          "data/maps/attributes.asm", "data/maps/blocks.asm",
          "data/maps/scripts.asm", "layout.link")

_failures = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global _failures
    mark = "OK  " if cond else "FAIL"
    print(f"  [{mark}] {label}{(': ' + detail) if detail else ''}")
    if not cond:
        _failures += 1


def clone(src: Path, dst: Path) -> Path:
    for rel in NEEDED:
        (dst / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src / rel, dst / rel)
    (dst / "maps").mkdir(exist_ok=True)
    return dst


# --------------------------------------------------------------------------- #
# the invariant                                                                #
# --------------------------------------------------------------------------- #
_CONST = re.compile(r"^\s*map_const\s+(\w+)\s*,")
_GROUP = re.compile(r"^\s*newgroup\b")
_PTR = re.compile(r"^\s*dw\s+(\w+)")
_MAP = re.compile(r"^\s*map\s+(\w+)\s*,")


def ids(root: Path) -> list[list[str]]:
    """Per group, the map consts in the order `map_const` numbers them."""
    out: list[list[str]] = []
    for line in (root / "constants/map_constants.asm").read_text().split("\n"):
        if _GROUP.match(line):
            out.append([])
        elif (m := _CONST.match(line)) and out:
            out[-1].append(m.group(1))
    return out


def headers(root: Path) -> list[list[str]]:
    """Per group, the map labels in the order `MapGroupPointers` indexes them.

    Read positionally on purpose — that is exactly how the engine reads it, and
    a check that looked labels up by name could not see a renumbering at all.
    """
    lines = (root / "data/maps/maps.asm").read_text().split("\n")
    start = next(i for i, ln in enumerate(lines)
                 if ln.startswith("MapGroupPointers"))
    labels: list[str] = []
    for ln in lines[start + 1:]:
        if re.match(r"^\w", ln):
            break
        if m := _PTR.match(ln):
            labels.append(m.group(1))
    out = []
    for label in labels:
        at = next(i for i, ln in enumerate(lines)
                  if ln.rstrip() == f"{label}:")
        group = []
        for ln in lines[at + 1:]:
            if re.match(r"^\w", ln):
                break
            if m := _MAP.match(ln):
                group.append(m.group(1))
        out.append(group)
    return out


def agree(root: Path) -> str:
    """"" when the two arrays line up, else the first disagreement."""
    consts, labels = ids(root), headers(root)
    if len(consts) != len(labels):
        return f"{len(consts)} groups of ids, {len(labels)} groups of headers"
    for g, (cs, ls) in enumerate(zip(consts, labels), 1):
        if len(cs) != len(ls):
            return (f"group {g}: {len(cs)} map_const lines but "
                    f"{len(ls)} map lines")
    return ""


# --------------------------------------------------------------------------- #
def spec_for(label: str, const: str, blk: Path, header: dict) -> MN.NewMap:
    blk.write_bytes(bytes(4 * 5))
    return MN.NewMap(label=label, const=const, group=1, height=4, width=5,
                     blk=blk, border_block="$5", header=header)


VANILLA_HEADER = dict(tileset="TILESET_HOUSE", environment="INDOOR",
                      landmark="LANDMARK_OLIVINE_CITY", music="MUSIC_VIOLET_CITY",
                      phone="FALSE", palette="PALETTE_DAY",
                      fishgroup="FISHGROUP_SHORE")
POLISHED_HEADER = dict(tileset="TILESET_JOHTO_HOUSE", environment="INDOOR",
                       sign="SIGN_BUILDING", landmark="OLIVINE_CITY",
                       music="MUSIC_VIOLET_CITY", phone="0",
                       palette="PALETTE_DAY")


def test_add(src: Path, dialect, header: dict, name: str, tmp: Path,
             mints: bool) -> None:
    if not src.exists():
        print(f"\n== {name}: not checked out at {src}, skipped ==")
        return
    print(f"\n== {name} ==")
    root = clone(src, tmp / name)
    check("the tree starts consistent", not agree(root), agree(root))

    before = [len(g) for g in ids(root)]
    blk = tmp / f"{name}.blk"
    spec = spec_for("MtEmberSmallRoom", "MT_EMBER_SMALL_ROOM", blk, header)
    script_section, blocks_section = dialect.placements(root)
    answers = {"script": script_section.preset(),
               "blocks": blocks_section.preset()}
    change = MN.add_map(root, spec, answers, dialect=dialect)
    apply_edits(root, change.changes, dry_run=False)

    # The whole point.
    check("the two arrays still agree, every group, every map",
          not agree(root), agree(root))
    check("and group 1 grew by exactly one",
          [len(g) for g in ids(root)][0] == before[0] + 1)
    check("the new map is last in its group — the only position where the "
          "arrays cannot fall out of step",
          ids(root)[0][-1] == spec.const and
          headers(root)[0][-1] == spec.label)

    # Written and read by the same MapShape, which is the only guarantee that
    # `map_const NAME, W, H` did not go in as H, W.
    h, w = dialect.shape.read(root, spec.const)
    check("the dimension line reads back the way it was written",
          (h, w) == (spec.height, spec.width), f"{h}x{w}")

    text = (root / "data/maps/blocks.asm").read_text()
    scripts = (root / "data/maps/scripts.asm").read_text()
    check("the blocks are indexed under a label this tree would look for",
          f"{spec.label}{dialect._suffix}:" in text)
    check("the script is INCLUDEd", f'INCLUDE "maps/{spec.label}.asm"' in scripts)
    check("the map's own asm was written",
          (root / f"maps/{spec.label}.asm").exists())
    check("and the grid landed at this tree's own extension, not the source's",
          (root / dialect.blk_name(spec.label, blk)).read_bytes()
          == blk.read_bytes())

    # A JOIN lands *inside* the section it named; a MINT adds one at the end.
    if mints:
        check("the blocks minted a section of their own",
              f'SECTION "{spec.label}_BlockData", ROMX' in text)
    else:
        check("the blocks landed inside the section that was chosen, not "
              "after the next one",
              _in_section(text, answers["blocks"], f"{spec.label}_Blocks:"))
    check("the script landed inside the section that was chosen",
          _in_section(scripts, answers["script"],
                      f'INCLUDE "maps/{spec.label}.asm"'))

    # Adding it twice is a collision, not a second copy.
    try:
        MN.add_map(root, spec, answers, dialect=dialect)
    except EditError as e:
        check("adding the same map again refuses", True, str(e)[:60])
    else:
        check("adding the same map again refuses", False)

    # The mistake that builds: a grid that is not height x width.
    bad = tmp / f"{name}-bad.blk"
    bad.write_bytes(bytes(19))
    wrong = MN.NewMap(label="MtEmberBigRoom", const="MT_EMBER_BIG_ROOM",
                      group=1, height=4, width=5, blk=bad, header=header)
    try:
        MN.add_map(root, wrong, answers, dialect=dialect)
    except EditError as e:
        check("a grid that is not height x width refuses", True, str(e)[:60])
    else:
        check("a grid that is not height x width refuses", False)

    # A group that does not exist, and a name the assembler would read as local.
    for bad_spec, why in (
        (dict(group=999), "a group the tree does not have"),
        (dict(label="mtEmber"), "a label that is not CamelCase"),
        (dict(const="MtEmber"), "a const that is not SCREAMING_SNAKE"),
    ):
        fields = dict(label="MtEmberOther", const="MT_EMBER_OTHER", group=1,
                      height=4, width=5, blk=blk, header=header) | bad_spec
        s = MN.NewMap(**fields)
        try:
            MN.add_map(root, s, answers, dialect=dialect)
        except EditError:
            check(f"{why} refuses", True)
        else:
            check(f"{why} refuses", False)


def _in_section(text: str, section: str, needle: str) -> bool:
    """Is `needle` inside `SECTION "section"` — where "inside" ends at the next
    `SECTION` **or** at an `ENDSECTION`?

    The `ENDSECTION` half is not defensive. Each of these four files closes its
    last section with one, and the last section is what a numbered tree offers
    as its default, so the first version of this check — which stopped only at
    the next `SECTION` — passed on output that had appended the map *after* the
    close, into no section at all. It agreed with the bug. Reading the
    generated file is what found it.
    """
    lines = text.split("\n")
    at = next((i for i, ln in enumerate(lines)
               if ln.startswith(f'SECTION "{section}"')), None)
    if at is None:
        return False
    end = next((i for i in range(at + 1, len(lines))
                if lines[i].startswith(("SECTION ", "ENDSECTION"))), len(lines))
    return any(ln.strip() == needle for ln in lines[at:end])


def test_falsify(tmp: Path) -> None:
    """The consistency check, shown to fail before it is believed."""
    print("\n== falsifying the invariant check ==")
    if not VANILLA.exists():
        print("  (no pokecrystal checkout, skipped)")
        return
    root = clone(VANILLA, tmp / "falsify")
    check("clean tree: no disagreement", not agree(root))

    path = root / "constants/map_constants.asm"
    lines = path.read_text().split("\n")
    at = next(i for i, ln in enumerate(lines) if _CONST.match(ln))
    lines.insert(at, "\tmap_const SMUGGLED_IN, 4, 4")
    path.write_text("\n".join(lines))
    check("one extra map_const and the check reports it",
          bool(agree(root)), agree(root))


def test_seam() -> None:
    """What the mounted tree hands the studio — the point of the whole phase.

    The two forms must differ in the ways the trees do and in no other way, and
    the crossing is the place that could quietly stop being true: a mount that
    forgot to declare polished's dialect would hand it vanilla's form, which
    renders perfectly and writes a `map` line with a fishing group where the
    macro wants a palette.
    """
    print("\n== the seam ==")
    from pokeprism_devtools.hacks import mount
    from pokeprism_devtools import contract as actions

    forms = {}
    for name, root in (("vanilla", VANILLA), ("polished", POLISHED)):
        if not root.exists():
            print(f"  ({name} not checked out, skipped)")
            return
        hack = mount.mount(root)
        form = hack.writes.form("newmap")
        check(f"{name}: newmap crosses", form is not None)
        forms[name] = (hack, form, [f.name for f in form.FIELDS])

    (vh, _, vf), (ph, _, pf) = forms["vanilla"], forms["polished"]
    check("vanilla's header asks for a fishing group and polished's does not",
          "fishgroup" in vf and "fishgroup" not in pf)
    check("polished's asks for a location sign and vanilla's does not",
          "sign" in pf and "sign" not in vf)
    check("vanilla asks where the blocks go; polished mints and so does not",
          "blocks_section" in vf and "blocks_section" not in pf)
    check("both ask where the script goes",
          "script_section" in vf and "script_section" in pf)

    # A field whose list is empty renders as free text, which for a section
    # would silently accept a name that does not exist — so every offered
    # field must have answers behind it.
    for name, (hack, _, fields) in forms.items():
        empty = [f.name for f in hack.writes.form("newmap").FIELDS
                 if f.choices and not hack.writes.choices(f.choices, ())]
        check(f"{name}: every field that promises a list has one",
              not empty, f"empty: {empty}")

    check("polished's landmarks lose the prefix, and are found anyway",
          all(not c.startswith("LANDMARK_")
              for c in ph.writes.choices(actions.LANDMARKS, ())[:5])
          and len(ph.writes.choices(actions.LANDMARKS, ())) > 100)
    check("a minted blob answers [] rather than a stub list",
          ph.writes.choices(actions.BLOCK_SECTIONS, ()) == [])


def main() -> int:
    test_seam()
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        test_falsify(tmp)
        test_add(VANILLA, NM.VANILLA, VANILLA_HEADER, "pokecrystal", tmp,
                 mints=False)
        test_add(POLISHED, NM.POLISHED, POLISHED_HEADER, "polishedcrystal",
                 tmp, mints=True)

    print()
    if _failures:
        print(f"{_failures} check(s) FAILED")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
