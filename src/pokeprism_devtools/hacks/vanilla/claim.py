"""Build the vanilla adapter, for a tree the mount has already recognised.

Recognition stays in `mount.py`; what lives here is only what vanilla is *made
of* — a reader and a writer over a stock pokecrystal checkout, and none of the
extra capabilities. No ctx means the session does not lint; `plays` and
`measures` left false mean the emulator and the tile ruler degrade to absence
above the seam. Nothing is imported until the mount has decided the tree is
vanilla.
"""

from __future__ import annotations

from pathlib import Path

from ..seam import Hack


def build(root: Path) -> Hack:
    """The vanilla :class:`~..seam.Hack`: a reader and a writer, nothing more."""
    from .read import Reader
    from .write import Writer
    return Hack("vanilla", Reader(root), writes=Writer(root))
