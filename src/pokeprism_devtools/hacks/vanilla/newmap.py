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

from ...shared.constants import ConstSet
from ...studio import actions
from ...studio.actions import Field
from ...wiring.mapnew import NewMap
from ...wiring.mapresize import MapShape
from ...wiring.placement import JOIN, MINT, Placement, banks, sections
from .resize import SHAPE

#: Where each blob's entry is written, in both trees.
SCRIPTS = "data/maps/scripts.asm"
BLOCKS = "data/maps/blocks.asm"

#: The map environments, in the order `const_def 1` numbers them — and the two
#: trees differ in exactly one slot: vanilla's fifth is the unused
#: `ENVIRONMENT_5`, polished's is `ISOLATED`. Written down rather than read,
#: for the reason prism's `PERMS` is: it is a bare `const` block in a file full
#: of other bare `const` blocks, so there is no prefix to match on and a
#: `ConstSet` would offer the palettes and the fishing groups alongside.
VANILLA_ENVIRONMENTS = ("TOWN", "ROUTE", "INDOOR", "CAVE", "ENVIRONMENT_5",
                        "GATE", "DUNGEON")
POLISHED_ENVIRONMENTS = ("TOWN", "ROUTE", "INDOOR", "CAVE", "ISOLATED",
                         "GATE", "DUNGEON")

#: The `map` macro's arguments after the label, one :class:`Field` each, in the
#: order the macro takes them. Two lists, because the trees do not take the
#: same ones — polished has a location sign and no fishing group — and the
#: order is load-bearing twice over: it is what `header_line` joins, and a
#: missing argument shifts every argument after it by one and still assembles.
VANILLA_FIELDS = (
    Field("tileset", "Tileset", choices=actions.TILESETS),
    Field("environment", "Environment", options=VANILLA_ENVIRONMENTS,
          default="INDOOR",
          help="which collision and encounter rules the map lives under"),
    Field("landmark", "Landmark", choices=actions.LANDMARKS,
          help="its own, usually — or the town it sits inside"),
    Field("music", "Music", choices=actions.MUSIC),
    Field("phone", "Phone service", options=("FALSE", "TRUE"), default="FALSE",
          help="TRUE prevents phone calls here"),
    Field("palette", "Palette", choices=actions.TIMES, default="PALETTE_AUTO",
          help="PALETTE_AUTO follows the clock; PALETTE_DARK is a cave"),
    Field("fishgroup", "Fish group", choices=actions.FISHGROUPS,
          default="FISHGROUP_NONE"),
)
POLISHED_FIELDS = (
    Field("tileset", "Tileset", choices=actions.TILESETS),
    Field("environment", "Environment", options=POLISHED_ENVIRONMENTS,
          default="INDOOR"),
    Field("sign", "Location sign", choices=actions.SIGNS,
          default="SIGN_BUILDING",
          help="the plaque that slides in when you walk on — vanilla has none"),
    Field("landmark", "Landmark", choices=actions.LANDMARKS,
          help="no LANDMARK_ prefix in this tree — just OLIVINE_CITY"),
    Field("music", "Music", choices=actions.MUSIC),
    Field("phone", "Phone service", options=("0", "1"), default="0"),
    Field("palette", "Palette", choices=actions.TIMES, default="PALETTE_AUTO"),
)

#: Where the `map` macro's named arguments get their constants — merged into
#: `.write`'s CHOICES, and here because this form is what asks for them.
#:
#: The landmark prefix is a fork, and a near-silent one. Vanilla writes
#: `LANDMARK_OLIVINE_CITY`; polished writes `OLIVINE_CITY` for the same place.
#: Both files hold nothing but landmarks, so what differs is only whether the
#: names carry the prefix — and reading polished through vanilla's entry
#: returns *nothing at all* rather than failing, which a form renders as a
#: plain text box. The same shape of miss as the `PAL_NPC_` macro fork.
HEADER_SETS = {
    actions.TILESETS: ConstSet("constants/tileset_constants.asm", "TILESET_"),
    actions.MUSIC: ConstSet("constants/music_constants.asm", "MUSIC_"),
    actions.TIMES: ConstSet("constants/map_data_constants.asm", "PALETTE_"),
    actions.FISHGROUPS: ConstSet("constants/map_data_constants.asm",
                                 "FISHGROUP_"),
    actions.LANDMARKS: ConstSet("constants/landmark_constants.asm",
                                "LANDMARK_"),
}

#: Polished's two forks: unprefixed landmarks, and a location sign vanilla's
#: `map` macro does not take at all.
POLISHED_HEADER_SETS = {
    **HEADER_SETS,
    actions.LANDMARKS: ConstSet("constants/landmark_constants.asm"),
    actions.SIGNS: ConstSet("constants/map_data_constants.asm", "SIGN_"),
}

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

    def __init__(self, *, blocks_placement, blocks_kind: str,
                 header_fields: tuple[Field, ...], template: str,
                 block_suffix: str, blk_ext: str, incbin_ext: str) -> None:
        self._blocks = blocks_placement
        self._blocks_kind = blocks_kind
        self.header_fields = header_fields
        self._template = template
        self._suffix = block_suffix
        #: The extension the author's grid carries in this tree. Public
        #: because the form's file list has to offer the same one the writer
        #: will name — a list that offered `.ablk.lzp` would offer the build's
        #: output, which nobody draws in.
        self.blk_ext = blk_ext
        self._incbin = incbin_ext

    @property
    def header_args(self) -> tuple[str, ...]:
        """The `map` macro's arguments, in order — the field names *are* the
        argument list, so the form and the line it writes cannot disagree."""
        return tuple(f.name for f in self.header_fields)

    @property
    def asks(self) -> tuple[str, ...]:
        """Which blobs have a placement question. Answerable without reading
        the tree, because the *shape* of the answer is the dialect's and only
        the list of choices is the checkout's — which is what lets the form's
        fields be decided before a root is in hand."""
        return ("script", "blocks") if self._blocks_kind == JOIN else ("script",)

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
        return f"maps/{label}{self.blk_ext}"

    def blocks_entry(self, label: str, blk_rel: str) -> list[str]:
        return [f"{label}{self._suffix}:",
                f'\tINCBIN "{blk_rel}{self._incbin}"']

    def script_entry(self, label: str) -> list[str]:
        return [f'INCLUDE "maps/{label}.asm"']

    def header_line(self, spec: NewMap) -> str:
        args = ", ".join(self._arg(spec, name) for name in self.header_args)
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
                f"{', '.join(self.header_args)}")
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


VANILLA = FamilyNewMap(blocks_placement=_vanilla_blocks, blocks_kind=JOIN,
                       header_fields=VANILLA_FIELDS,
                       template=_VANILLA_TEMPLATE,
                       block_suffix="_Blocks", blk_ext=".blk", incbin_ext="")

POLISHED = FamilyNewMap(blocks_placement=_polished_blocks, blocks_kind=MINT,
                        header_fields=POLISHED_FIELDS,
                        template=_POLISHED_TEMPLATE,
                        block_suffix="_BlockData", blk_ext=".ablk",
                        incbin_ext=".lzp")


def offers(root: Path, dialect: FamilyNewMap, kind: str) -> list[str] | None:
    """The new-map form's four answers that are not constant sets.

    `None` means "not mine" — the caller falls through to its `ConstSet` map.
    Here rather than in `.write` because every one of them is a fact about
    *adding a map*: which sections exist, how many groups there are, and where
    this tree's author keeps the grids they draw.
    """
    if kind in (actions.SCRIPT_SECTIONS, actions.BLOCK_SECTIONS):
        from ...studio.mapadd import section_choices
        return section_choices(dialect.placements(root), kind)
    if kind == actions.GROUPS:
        # A number, not a name — the only reason to offer a list of numbers is
        # that nothing else on the form says how many there are.
        text = (root / "constants/map_constants.asm").read_text()
        n = sum(1 for ln in text.split("\n") if ln.strip().startswith("newgroup"))
        return [str(i) for i in range(1, n + 1)]
    if kind == actions.BLOCKS:
        from ...studio.mapadd import grids
        # `maps/`, not prism's `maps/blk/` — the family keeps its grids beside
        # the map files. The suffix is this tree's own for the same reason
        # `blk_name` uses it: polished draws `.ablk` and INCBINs the
        # `.ablk.lzp` the build makes from it, and offering the compressed file
        # would offer something no author ever edits.
        return grids((root.parent / "polished-map", root / "maps", Path.cwd()),
                     (dialect.blk_ext,))
    return None
