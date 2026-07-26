"""Recognise a vanilla tree, and if it is one, build its adapter.

`claims()` asks vanilla's one question and no other's: does the first map file
this checkout lists end with `<Label>_MapEvents:` at the tail? The shared read
that finds *which* file to look at lives in `shared/mapindex`; what the file's
contents mean is vanilla's alone, and it knows nothing of polished's head anchor
— they are two independent questions about the same byte. What vanilla is *made
of* is `build` below: a reader and a writer over a stock pokecrystal checkout,
and its family linter. The `ctx` is what makes the session lint a vanilla tree
at all — the dialogue-overflow rules, surfacing through the same Diagnostics
channel prism uses; `plays` now carries a stock-pokecrystal build-and-boot, while
`measures` left false means the tile ruler still degrades to absence (the dialogue
font is fixed-width, so there is no VWF to measure against). Nothing is imported
until vanilla claims the tree.
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
    """The vanilla :class:`~..seam.Hack`: a reader, a writer, a text linter, and
    now build-and-boot — a stock pokecrystal builds and the studio can stand you
    on a map in it. `measures` stays false: the dialogue font is fixed-width, so
    there is still no VWF to measure tiles against (see `docs/STATE.md`)."""
    from . import lint, play
    from .read import Reader
    from .write import Writer
    return Hack("vanilla", Reader(root), ctx=lint.build(root),
                writes=Writer(root), plays=play.Player(root))
