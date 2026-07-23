"""Recognise a vanilla tree, and if it is one, build its adapter.

`claims()` asks vanilla's one question and no other's: does the first map file
this checkout lists end with `<Label>_MapEvents:` at the tail? The shared read
that finds *which* file to look at lives in `shared/mapindex`; what the file's
contents mean is vanilla's alone, and it knows nothing of polished's head anchor
— they are two independent questions about the same byte. What vanilla is *made
of* is `build` below: a reader and a writer over a stock pokecrystal checkout,
and none of the extra capabilities. No ctx means the session does not lint;
`plays` and `measures` left false mean the emulator and the tile ruler degrade
to absence above the seam. Nothing is imported until vanilla claims the tree.
"""

from __future__ import annotations

from pathlib import Path

from ...shared.mapindex import first_listed_map
from ..mount import NearMiss
from ..seam import Hack

#: Vanilla closes a map file with the event block: `<Label>_MapEvents:` last.
_ANCHOR = "_MapEvents"


def claims(root: Path) -> Hack | NearMiss:
    """Vanilla's tree, or a near-miss naming the tail anchor it looked for.
    A pokecrystal checkout whose first map ends with `_MapEvents:` is vanilla's;
    one that lists no map, or lists one that does not, is a near-miss that names
    the anchor so the mount's refusal stays actionable."""
    src = first_listed_map(root)
    if src is not None and f"{src[0]}{_ANCHOR}:" in src[1]:
        return build(root)
    where = (f"{src[0]} does not" if src is not None
             else "data/maps/maps.asm lists none to read")
    return NearMiss("vanilla",
                    f"reads a map file that ends with {_ANCHOR}: at the tail; "
                    f"{where}")


def build(root: Path) -> Hack:
    """The vanilla :class:`~..seam.Hack`: a reader and a writer, nothing more."""
    from .read import Reader
    from .write import Writer
    return Hack("vanilla", Reader(root), writes=Writer(root))
