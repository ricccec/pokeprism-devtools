"""How the pokecrystal family adds a map: where it goes, and how it is spelled.

The mirror of `hacks/{prism,vanilla}/resize.py` — no mechanism, only this
family's answers to what `wiring/mapnew.py` and `wiring/placement.py` ask. And
here, unusually, the two trees in the family disagree with *each other*: the
fork is not vanilla against prism but **blocks against scripts**, drawn
differently in each tree.

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
polished already has 436 sections for 436 maps, so joining one would be the odd
thing. Each tree is asked to do what it already does.

`scripts.asm` is a ``JOIN`` in both, and in polished that is worth saying out
loud: 110 of its 119 script sections are unpinned, so most of the choices on
that list inherit "the linker decides" rather than a bank. The choice still
matters — it decides which *neighbours* the map's script shares a bank with —
it just does not decide the bank.

The four spellings
------------------
Everything else the trees differ on is a line of text, carried here as data
rather than as a branch:

* the **`map` macro arguments** are not the same list. Vanilla ends in a
  fishing group; polished has no fishing group and carries a location sign in
  the middle. So the argument *order* is a declared tuple and the header line
  is a join, not a format string with a tree's name near it.
* the **block label** is `<Label>_Blocks` against `<Label>_BlockData` — the
  fork `hacks/vanilla/resize.py` already had to know about.
* the **grid file** is `maps/<Label>.blk`, INCBIN'd directly, against
  `maps/<Label>.ablk` INCBIN'd as the `.ablk.lzp` the build compresses from it.
  The author's file and the assembler's file are the same file in one tree and
  not in the other.
* the **script header** is two labels in vanilla (`_MapScripts` and a separate
  `_MapEvents`, with the `db 0, 0` filler between them) and one in polished
  (`_MapScriptHeader`). This is the anchor fork every module in this package
  already forks on, appearing once more.
"""

from __future__ import annotations

from pathlib import Path

from ...wiring.mapnew import NewMap
from ...wiring.mapresize import MapShape
from ...wiring.placement import JOIN, MINT, Placement, banks, sections
from .resize import SHAPE

#: Where each blob's entry is written, in both trees.
SCRIPTS = "data/maps/scripts.asm"
BLOCKS = "data/maps/blocks.asm"

#: The `map` macro's arguments after the label, in order. Two lists, because
#: the trees do not take the same ones — see the docstring.
VANILLA_HEADER = ("tileset", "environment", "landmark", "music", "phone",
                  "palette", "fishgroup")
POLISHED_HEADER = ("tileset", "environment", "sign", "landmark", "music",
                   "phone", "palette")

_VANILLA_TEMPLATE = """\
{label}_MapScripts:
\tdef_scene_scripts

\tdef_callbacks

{label}_MapEvents:
\tdb 0, 0 ; filler

\tdef_warp_events

\tdef_coord_events

\tdef_bg_events

\tdef_object_events
"""

_POLISHED_TEMPLATE = """\
{label}_MapScriptHeader:
\tdef_scene_scripts

\tdef_callbacks

\tdef_warp_events

\tdef_coord_events

\tdef_bg_events

\tdef_object_events
"""


class FamilyNewMap:
    """One dialect, holding the differences its tree declares."""

    shape: MapShape = SHAPE

    def __init__(self, *, blocks_placement, header_args: tuple[str, ...],
                 template: str, block_suffix: str, blk_ext: str,
                 incbin_ext: str) -> None:
        self._blocks = blocks_placement
        self._args = header_args
        self._template = template
        self._suffix = block_suffix
        self._ext = blk_ext
        self._incbin = incbin_ext

    # -- placement ------------------------------------------------------------ #
    def placements(self, root: Path) -> tuple[Placement, ...]:
        pins = banks(root)
        return (Placement(blob="script", kind=JOIN, path=SCRIPTS,
                          choices=sections(root, SCRIPTS, pins)),
                self._blocks(root, pins))

    # -- spelling ------------------------------------------------------------- #
    def template(self, label: str) -> str:
        return self._template.format(label=label)

    def blk_name(self, label: str, src: Path) -> str:
        """Always this tree's own extension, never the source file's. A `.blk`
        dragged into a polished tree is still bytes the build must compress."""
        return f"maps/{label}{self._ext}"

    def blocks_entry(self, label: str, blk_rel: str) -> list[str]:
        return [f"{label}{self._suffix}:",
                f'\tINCBIN "{blk_rel}{self._incbin}"']

    def script_entry(self, label: str) -> list[str]:
        return [f'INCLUDE "maps/{label}.asm"']

    def header_line(self, spec: NewMap) -> str:
        args = ", ".join(self._arg(spec, name) for name in self._args)
        return f"\tmap {spec.label}, {args}"

    def attributes_line(self, spec: NewMap) -> str:
        return (f"\tmap_attributes {spec.label}, {spec.const}, "
                f"{spec.border_block}")

    def _arg(self, spec: NewMap, name: str) -> str:
        """Every argument the macro takes, present. A missing one would shift
        every argument after it by one and still assemble — the same failure
        the swapped movement radius was, one macro along."""
        value = spec.header.get(name, "")
        if not value:
            raise KeyError(
                f"the `map` macro needs {name} — this tree takes "
                f"{', '.join(self._args)}")
        return value


def _vanilla_blocks(root: Path, pins: dict[str, int]) -> Placement:
    return Placement(blob="blocks", kind=JOIN, path=BLOCKS,
                     choices=sections(root, BLOCKS, pins))


def _polished_blocks(root: Path, pins: dict[str, int]) -> Placement:
    """`<Label>_BlockData` is not a convention invented here but the label the
    read adapter already looks the blocks up by, so the section and the label
    are one name, written once. Measured: 432 of the tree's 436 blockdata
    sections are spelled exactly like a block label. The four that are not are
    shared grids named for a *kind* of room rather than a map
    (`KantoHouse1_BlockData`, `Special Map Blockdata`) — which a new map is
    not, and which is why minting is safe to do by rule."""
    return Placement(blob="blocks", kind=MINT, path=BLOCKS,
                     convention="{label}_BlockData")


VANILLA = FamilyNewMap(blocks_placement=_vanilla_blocks,
                       header_args=VANILLA_HEADER,
                       template=_VANILLA_TEMPLATE,
                       block_suffix="_Blocks", blk_ext=".blk", incbin_ext="")

POLISHED = FamilyNewMap(blocks_placement=_polished_blocks,
                        header_args=POLISHED_HEADER,
                        template=_POLISHED_TEMPLATE,
                        block_suffix="_BlockData", blk_ext=".ablk",
                        incbin_ext=".lzp")
