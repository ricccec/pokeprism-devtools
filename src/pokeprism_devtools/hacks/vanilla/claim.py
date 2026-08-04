"""Recognise a vanilla tree, and if it is one, build its adapter.

`claims()` asks vanilla's one question and no other's: does the first map file
this checkout lists end with `<Label>_MapEvents:` at the tail? The shared read
that finds *which* file to look at lives in `shared/mapindex`; what the file's
contents mean is vanilla's alone, and it knows nothing of polished's head anchor
— they are two independent questions about the same byte. What vanilla is *made
of* is `build` below: a reader and a writer over a stock pokecrystal checkout,
and its family linter. The `ctx` is what makes the session lint a vanilla tree
at all — the dialogue-overflow rules, surfacing through the same Diagnostics
channel prism uses; `plays` carries a stock-pokecrystal build-and-boot, and
`measures` is now answered by the tree rather than declared false: a checkout with
its text engine on disk can say how wide a line draws, and one without it cannot.
Nothing is imported until vanilla claims the tree.
"""

from __future__ import annotations

from pathlib import Path

from ...shared.mapindex import first_listed_map
from ...contract import Hack
from ...contract.mount import NearMiss

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
    """The vanilla :class:`~...contract.Hack`: a reader, a writer, a text linter,
    build-and-boot, and now the tile ruler under the reword box.

    `measures` is read off the tree, not written down here. The reason it was
    hardcoded false — "the dialogue font is fixed-width, so there is no VWF to
    measure against" — had the question backwards: fixed width is what makes the
    count *exact*, and `contract.Measured` was always denominated in tiles. What
    genuinely cannot be measured is a checkout with no charmap and no engine file
    to read them out of, so that is what is asked, and a tree that fails it gets a
    reader with no `measure` on it rather than one that would crash on a
    keystroke.
    """
    from . import lint, metrics, play
    from .read import MeasuringReader, Reader
    from .write import Writer
    tiles = metrics.engine_is_readable(root, metrics.ENGINE_FILES)
    return Hack("vanilla", (MeasuringReader if tiles else Reader)(root),
                ctx=lint.build(root), writes=Writer(root),
                plays=play.Player(root), measures=tiles)
