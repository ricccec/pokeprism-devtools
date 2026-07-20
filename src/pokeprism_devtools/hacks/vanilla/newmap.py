"""How the pokecrystal family answers "where does the new map go?".

The mirror of `hacks/{prism,vanilla}/resize.py`: no mechanism, only this
family's answers to what `wiring/placement.py` asks. And here, unusually, the
two trees in the family disagree with each other — the fork is not vanilla
against prism but **blocks against scripts**, drawn differently in each tree:

              scripts                          blocks
    vanilla   JOIN, 25 buckets, all pinned     JOIN, 3 buckets, all pinned
    polished  JOIN, 119 sections, 9 pinned     MINT, one per map, unpinned

Measured on the real trees rather than read off a convention, and the
measurement corrected the survey twice. The survey said polished pins 11 of its
script sections; 11 is how many section names in `layout.link` contain the word
"Scripts", and two of those (`Phone Scripts`, `Phone Scripts 2`) are not map
script sections at all. Intersecting the link script with `data/maps/scripts.asm`
gives 9. And it said the family pins nothing, which is what the asm looks like:
every `SECTION` line in both trees is a bare ``ROMX``, and all the pinning is in
`layout.link`.

Why vanilla's blocks are a ``JOIN`` and polished's are a ``MINT`` — the same
question, two answers — is a fact about the trees and not a preference. Vanilla
keeps 302 `INCBIN`s in 3 pinned sections, so a fourth would be a section
`layout.link` does not name, floating where its three neighbours are fixed;
polished already has 436 sections for 436 maps, so joining one would be the
odd thing. Each tree is asked to do what it already does.

`scripts.asm` is a ``JOIN`` in both, and in polished that is worth saying out
loud: 110 of its 119 script sections are unpinned, so most of the choices on
that list inherit "the linker decides" rather than a bank. The choice still
matters — it decides which *neighbours* the map's script shares a bank with —
it just does not decide the bank.
"""

from __future__ import annotations

from pathlib import Path

from ...wiring.placement import JOIN, MINT, Placement, banks, sections

#: Where each blob's entry is written, in both trees.
SCRIPTS = "data/maps/scripts.asm"
BLOCKS = "data/maps/blocks.asm"


def _script(root: Path, pins: dict[str, int]) -> Placement:
    """The script `INCLUDE` joins a section that already exists — the same
    answer in both trees, over very different lists."""
    return Placement(blob="script", kind=JOIN, path=SCRIPTS,
                     choices=sections(root, SCRIPTS, pins))


def vanilla(root: Path) -> tuple[Placement, ...]:
    """Two joins. The blocks pick one of `Map Blocks 1..3`."""
    pins = banks(root)
    return (_script(root, pins),
            Placement(blob="blocks", kind=JOIN, path=BLOCKS,
                      choices=sections(root, BLOCKS, pins)))


def polished(root: Path) -> tuple[Placement, ...]:
    """A join and a mint. The blocks get `<Label>_BlockData` — which is not a
    convention invented here but the label the read adapter already looks the
    blocks up by, so the section and the label are one name, written once.
    Measured: 432 of the tree's 436 blockdata sections are spelled exactly like
    a block label. The four that are not are shared grids named for a *kind* of
    room rather than a map (`KantoHouse1_BlockData`, `Special Map Blockdata`) —
    which a new map is not, and which is why minting is safe to do by rule."""
    return (_script(root, banks(root)),
            Placement(blob="blocks", kind=MINT, path=BLOCKS,
                      convention="{label}_BlockData"))
