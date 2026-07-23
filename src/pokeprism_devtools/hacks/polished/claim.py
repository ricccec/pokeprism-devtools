"""Build the polished adapter, for a tree the mount has already recognised.

Recognition stays in `mount.py`; what lives here is what polished is *made of*
— and polished is a fork of vanilla, so most of what it is made of is
vanilla's, imported here rather than reimplemented. That dependency is declared
in the dependent hack on purpose: polished reads through vanilla's parsers and
writes through vanilla's `Writer`, and the code states the fork instead of a
shared middle pretending the two trees are peers. Nothing is imported until the
mount has decided the tree is polished.
"""

from __future__ import annotations

from pathlib import Path

from ..seam import Hack

#: Polished's own structural fact: its map files open with the event block,
#: where vanilla closes with it. The mount recognises a tree by this anchor;
#: here it is the head the writer splices against.
_ANCHOR = "_MapScriptHeader"


def build(root: Path) -> Hack:
    """The polished :class:`~..seam.Hack`: vanilla's `Writer`, six forks over."""
    from .read import Reader
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
    return Hack("polished", Reader(root),
                writes=Writer(root, _ANCHOR, POLISHED_WARPS,
                              POLISHED_CHOICES,
                              (POLISHED_ADDERS, POLISHED_EDITORS),
                              polished_resize(), POLISHED_NEWMAP))
