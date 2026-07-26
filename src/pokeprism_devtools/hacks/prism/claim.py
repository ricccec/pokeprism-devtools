"""Recognise a prism tree, and if it is one, build its adapter.

`claims()` is prism's whole answer to the mount: it looks only at prism's own
layout — no family concept, no shared recogniser, nothing that knows another
hack exists — and returns the built adapter, or a :class:`~..mount.NearMiss`
naming the files it needed and did not find. What prism is *made of* is `build`
below: the linter's context, the reader and writer that both take it, and the
two capabilities (a build-and-boot, text measured against prism's own VWF) that
no other tree in this repo declares. None of that is imported until prism
actually claims the tree, so a discovery pass that ends elsewhere pays for no
linter.
"""

from __future__ import annotations

from pathlib import Path

from ..mount import NearMiss
from ..seam import Hack

#: The two files every prism map parser starts from. Their *presence* is what
#: makes a tree prism-shaped; every other gen-2 hack keeps these facts elsewhere.
_LAYOUT = ("maps/second_map_headers.asm",
           "constants/map_dimension_constants.asm")


def claims(root: Path) -> Hack | NearMiss:
    """Prism's tree, or a near-miss saying which of its two files is missing.
    A tree carrying both is prism's; one carrying neither is simply not prism's
    to claim, and the near-miss says so by naming what prism reads."""
    missing = [rel for rel in _LAYOUT if not (root / rel).exists()]
    if not missing:
        return build(root)
    lacks = "neither" if len(missing) == len(_LAYOUT) else f"no {', '.join(missing)}"
    return NearMiss("prism",
                    f"reads maps from {' and '.join(_LAYOUT)}, and this tree has "
                    f"{lacks}")


def build(root: Path) -> Hack:
    """The prism :class:`~..seam.Hack`: reader and writer over one linter."""
    from ...maplint.context import LintContext
    from .play import Player
    from .read import Reader
    from .write import Writer
    ctx = LintContext(root)
    return Hack("prism", Reader(root, ctx), ctx=ctx,
                writes=Writer(root, ctx), plays=Player(root), measures=True)
