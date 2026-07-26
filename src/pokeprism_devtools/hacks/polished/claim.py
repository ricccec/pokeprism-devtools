"""Recognise a polished tree, and if it is one, build its adapter.

`claims()` asks polished's one question — does the first map file this checkout
lists *open* with `<Label>_MapScriptHeader:` at the head? — using the same
opinion-free read from `shared/mapindex` that vanilla uses, and knowing nothing
of vanilla's tail anchor. What polished is *made of* is `build` below, and
polished is a fork of vanilla, so most of what it is made of is vanilla's,
imported there rather than reimplemented. That dependency is declared in the
dependent hack on purpose: polished reads through vanilla's parsers and writes
through vanilla's `Writer`, and the code states the fork instead of a shared
middle pretending the two trees are peers. The fork is a build-time relation,
not a recognition one — polished recognises its own tree alone. Nothing is
imported until polished claims the tree.
"""

from __future__ import annotations

from pathlib import Path

from ...shared.mapindex import first_listed_map
from ..mount import NearMiss
from ..seam import Hack

#: Polished's own structural fact: its map files open with the event block,
#: where vanilla closes with it. It recognises a tree by this anchor, and here
#: it is also the head the writer splices against.
_ANCHOR = "_MapScriptHeader"


def claims(root: Path) -> Hack | NearMiss:
    """Polished's tree, or a near-miss naming the head anchor it looked for.
    A pokecrystal checkout whose first map opens with `_MapScriptHeader:` is
    polished's; one that lists no map, or lists one that does not, is a
    near-miss that names the anchor so the mount's refusal stays actionable."""
    src = first_listed_map(root)
    if src is not None and f"{src[0]}{_ANCHOR}:" in src[1]:
        return build(root)
    where = (f"{src[0]} does not" if src is not None
             else "data/maps/maps.asm lists none to read")
    return NearMiss("polished",
                    f"reads a map file that opens with {_ANCHOR}: at the head; "
                    f"{where}")


def build(root: Path) -> Hack:
    """The polished :class:`~..seam.Hack`: vanilla's `Writer`, six forks over."""
    from .read import Reader
    from . import lint
    from ..vanilla.actions import POLISHED_ADDERS, POLISHED_EDITORS
    from ..vanilla.newmap import POLISHED as POLISHED_NEWMAP
    from ..vanilla.resize import polished as polished_resize
    from ..vanilla.write import POLISHED_CHOICES, POLISHED_WARPS, Writer
    # The same writer vanilla mounts, holding the head anchor, the larger warp
    # grammar, its own constant-set map, its own forms and its own resize and
    # new-map answers — the fork relation is real, so the code states it,
    # exactly as the polished read adapter imports vanilla's parsers. All six
    # arguments are forks measured by survey, never sniffed: polished opens a
    # map file where vanilla closes it, counts warps with a `digmod` vanilla
    # has never heard of, writes its overworld palettes through a macro that
    # leaves their names out of the source, spells an `object_event` in twelve
    # arguments whose movement radius is the other way round, and indexes a
    # map's blocks under `_BlockData:` where vanilla writes `_Blocks:`, and
    # mints a section per map for a new map's blocks where vanilla joins one of
    # three — so its new-map form asks one question fewer than vanilla's, over
    # a different list of header arguments.
    return Hack("polished", Reader(root), ctx=lint.build(root),
                writes=Writer(root, _ANCHOR, POLISHED_WARPS,
                              POLISHED_CHOICES,
                              (POLISHED_ADDERS, POLISHED_EDITORS),
                              polished_resize(), POLISHED_NEWMAP))
