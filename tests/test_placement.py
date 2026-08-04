#!/usr/bin/env python3
"""Tests for `asmedit/placement.py` and the family's declared placements.

Two halves, and the first exists to earn the second. The hermetic half tries to
*break* the two readers before any measurement made with them is believed: a
link script says `ROMX $15`, and a reader that answers 15 rather than 21 is
wrong in a way that looks completely plausible in a report. So the fixtures
here are written to fail under every misreading worth having — decimal banks,
commented-out lines, names before any bank heading, a repeated SECTION.

The second half runs the readers over the real pokecrystal and polishedcrystal
trees and asserts the shape of the answer, not the day's numbers: that vanilla
joins on both blobs and polished mints its blocks, that every vanilla bucket is
pinned, and that a section's pinning comes from `layout.link` and could not
have come from the asm. Counts are printed, never asserted — the number of
`Map Scripts N` buckets is a thing an author changes.

    python tests/test_placement.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pokeprism_devtools.hacks.vanilla import newmap as NM  # noqa: E402
from pokeprism_devtools.asmedit import placement as P  # noqa: E402
from pokeprism_devtools.asmedit.editvocab import EditError  # noqa: E402

VANILLA = Path.home() / "code/ricccec/pokecrystal"
POLISHED = Path.home() / "code/ricccec/polishedcrystal"

_failures = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global _failures
    mark = "OK  " if cond else "FAIL"
    print(f"  [{mark}] {label}{(': ' + detail) if detail else ''}")
    if not cond:
        _failures += 1


def refuses(label: str, fn, *args) -> None:
    """The refusal is the feature: check it happens *and* that it says why."""
    try:
        fn(*args)
    except EditError as e:
        check(label, True, str(e)[:70])
    else:
        check(label, False, "no refusal")


# --------------------------------------------------------------------------- #
# the readers, against fixtures built to break them                            #
# --------------------------------------------------------------------------- #
_LINK = """\
ROM0
	org $0150
	"Home"

ROMX $15
	"Map Scripts 1"
	"Map Scripts 2"

ROMX $2c
	"Map Blocks 3"
;	"Commented Out"

WRAM0
	"Audio RAM"
"""

_ASM = """\
SECTION "Map Scripts 1", ROMX

INCLUDE "maps/A.asm"

SECTION "Unpinned Scripts", ROMX

INCLUDE "maps/B.asm"

SECTION "Map Scripts 1", ROMX ; rgbds continues the same section

INCLUDE "maps/C.asm"
"""


def test_readers(tmp: Path) -> None:
    print("\n== the readers, and what they must not do ==")
    (tmp / "layout.link").write_text(_LINK)
    (tmp / "data/maps").mkdir(parents=True)
    (tmp / "data/maps/scripts.asm").write_text(_ASM)
    b = P.banks(tmp)

    # $15 is 21. A reader using int(x) rather than int(x, 16) answers 15, and
    # 15 is a real bank, so nothing downstream would ever notice.
    check("a bank is read as hex", b.get("Map Scripts 1") == 0x15,
          f"got {b.get('Map Scripts 1')}")
    check("$2c too", b.get("Map Blocks 3") == 0x2C)
    check("a heading with no number is bank 0", b.get("Home") == 0)
    check("the bank carries to every name under it",
          b.get("Map Scripts 2") == 0x15)
    check("a commented-out name is not a section",
          "Commented Out" not in b, ", ".join(sorted(b)))
    check("a non-ROM region is still read, not skipped",
          b.get("Audio RAM") == 0)

    s = P.sections(tmp, "data/maps/scripts.asm", b)
    check("a repeated SECTION is one choice, not two",
          [x.name for x in s] == ["Map Scripts 1", "Unpinned Scripts"],
          str([x.name for x in s]))
    check("pinning comes from the link script", s[0].bank == 0x15)
    check("a section the link script does not name is unpinned",
          s[1].bank is None and not s[1].pinned)
    check("no link script means nothing is pinned, not an error",
          P.banks(tmp, "absent.link") == {})
    refuses("a missing asm file refuses by name",
            P.sections, tmp, "data/maps/nope.asm")


# --------------------------------------------------------------------------- #
# the three shapes                                                             #
# --------------------------------------------------------------------------- #
def test_shapes(tmp: Path) -> None:
    print("\n== resolving an answer into a section ==")
    b = P.banks(tmp)
    choices = P.sections(tmp, "data/maps/scripts.asm", b)

    join = P.Placement("script", P.JOIN, "data/maps/scripts.asm", choices)
    check("JOIN asks", join.asks)
    check("JOIN starts on the last bucket — where a numbered tree has been "
          "adding lately", join.preset() == "Unpinned Scripts", join.preset())
    check("JOIN inherits the bank of what it joined",
          join.resolve("Map Scripts 1", "NewMap") == P.Section("Map Scripts 1", 0x15))
    refuses("JOIN refuses a name that is not there", join.resolve, "Map Scripts 9", "X")
    refuses("JOIN refuses an empty answer", join.resolve, "", "X")

    mint = P.Placement("blocks", P.MINT, "data/maps/blocks.asm",
                       convention="{label}_BlockData")
    check("MINT does not ask — there is nothing to choose", not mint.asks)
    check("MINT names the section from the label",
          mint.resolve("", "MtEmberSmallRoom")
          == P.Section("MtEmberSmallRoom_BlockData", None))
    check("MINT takes an override when one is typed",
          mint.resolve("Special Map Blockdata", "X").name == "Special Map Blockdata")

    pin = P.Placement("blocks", P.PIN, "data/maps/blocks.asm",
                      convention="Map block data {label}")
    check("PIN takes a bank the way a link script spells it",
          pin.resolve("$7C", "X") == P.Section("Map block data X", 0x7C))
    check("PIN with a blank bank floats, which is an answer not an omission",
          pin.resolve("", "X") == P.Section("Map block data X", None))
    refuses("PIN refuses a bank that is not one", pin.resolve, "bank seven", "X")
    refuses("PIN refuses a bank past the end of the ROM", pin.resolve, "$1FF", "X")

    # A Placement that cannot be honoured is a construction error, not a
    # runtime one: JOIN over an empty list would render a field with no
    # options, and MINT with no convention would name a section "".
    for bad, why in (
        (dict(blob="s", kind=P.JOIN, path="p"), "JOIN with no choices"),
        (dict(blob="s", kind=P.MINT, path="p"), "MINT with no convention"),
        (dict(blob="s", kind="float", path="p"), "an unknown kind"),
    ):
        try:
            P.Placement(**bad)
        except ValueError:
            check(f"{why} is refused at construction", True)
        else:
            check(f"{why} is refused at construction", False)


# --------------------------------------------------------------------------- #
# the real trees                                                               #
# --------------------------------------------------------------------------- #
def test_real(root: Path, declare, name: str, blocks_kind: str) -> None:
    if not root.exists():
        print(f"\n== {name}: not checked out at {root}, skipped ==")
        return
    print(f"\n== {name} ==")
    script, blocks = declare(root)

    check("the script INCLUDE joins an existing section",
          script.kind == P.JOIN)
    check(f"the blocks are a {blocks_kind}", blocks.kind == blocks_kind)
    print(f"    {len(script.choices)} script sections, "
          f"{sum(s.pinned for s in script.choices)} pinned")

    if blocks_kind == P.JOIN:
        print(f"    {len(blocks.choices)} block sections, "
              f"{sum(s.pinned for s in blocks.choices)} pinned")
        check("every bucket this tree offers is pinned by layout.link — "
              "which is what makes joining one mean a known bank",
              all(s.pinned for s in script.choices + blocks.choices))
        # The point of the whole module: the asm cannot answer this.
        asm = (root / blocks.path).read_text()
        check("and no SECTION line in the asm says so",
              "BANK[" not in asm)
        chosen = blocks.resolve(blocks.preset(), "X")
        check("resolving the preset yields a pinned section",
              chosen.pinned, chosen.describe())
    else:
        check("minting names the section after the map",
              blocks.resolve("", "MtEmberSmallRoom").name
              == "MtEmberSmallRoom_BlockData")
        # Measured claim from the module docstring, re-measured here.
        labels = {ln.strip()[:-1] for ln in (root / blocks.path).read_text().split("\n")
                  if ln.endswith("_BlockData:")}
        secs = {s.name for s in P.sections(root, blocks.path)}
        share = len(secs & labels)
        check("nearly every blockdata section is spelled like its block label, "
              "so the mint follows the tree rather than inventing",
              share >= len(secs) - 5, f"{share} of {len(secs)}")

    # A form that offers a name its own resolver rejects is worse than a form
    # with no choices at all, so every offered name is put back through.
    bad = [s.name for s in script.choices if script.resolve(s.name, "X") != s]
    check("every choice the form would offer resolves to itself",
          not bad, f"{len(script.choices)} checked, {len(bad)} bad")


def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        test_readers(tmp)
        test_shapes(tmp)
    test_real(VANILLA, NM.VANILLA.placements, "pokecrystal", P.JOIN)
    test_real(POLISHED, NM.POLISHED.placements, "polishedcrystal", P.MINT)

    print()
    if _failures:
        print(f"{_failures} check(s) FAILED")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
