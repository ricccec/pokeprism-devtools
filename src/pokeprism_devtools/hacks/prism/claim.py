"""Build the prism adapter, for a tree the mount has already recognised.

Recognition stays in `mount.py`; what lives here is only what prism is *made
of* — the linter's context, the reader and writer that both take it, and the
two capabilities (a build-and-boot, text measured against prism's own VWF) that
no other tree in this repo declares. None of it is imported until the mount has
decided the tree is prism, so a probe that never mounts pays for no linter.
"""

from __future__ import annotations

from pathlib import Path

from ..seam import Hack


def build(root: Path) -> Hack:
    """The prism :class:`~..seam.Hack`: reader and writer over one linter."""
    from ...maplint.context import LintContext
    from .read import Reader
    from .write import Writer
    ctx = LintContext(root)
    return Hack("prism", Reader(root, ctx), ctx=ctx,
                writes=Writer(root, ctx), plays=True, measures=True)
