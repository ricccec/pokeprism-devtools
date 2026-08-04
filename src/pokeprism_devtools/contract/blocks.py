"""A map's shape: the block bytes, and the colours a block is drawn in.

Two records rather than one, and the reason is the colour. A grid of blocks is
bytes anywhere; a *tileset* means something only to the tree that defines the
constant. So a form that draws a map before it exists answers with a
:class:`Sketch` — grid, size and the tileset name as typed — and each adapter
turns that into :class:`Blocks` with its own swatches.
"""

from __future__ import annotations

from dataclasses import dataclass

Rgb = tuple[int, int, int]

#: A block's four quadrant colors, in reading order. Not an arbitrary carve-up:
#: a block is 2×2 coordinate tiles, so one swatch quadrant is exactly one place
#: you can stand, and the grid's cursor lands on a quadrant. How an adapter
#: arrives at the four colors is its own affair — prism averages real pixels,
#: an adapter without decoded graphics may answer from palettes alone.
Swatch = tuple[Rgb, Rgb, Rgb, Rgb]


@dataclass(frozen=True)
class Blocks:
    """A map's shape as the adapter read it: the block bytes, the size in
    blocks, and one swatch per block id the bytes index into."""
    blocks: bytes
    height: int
    width: int
    swatches: tuple[Swatch, ...]
    #: A name for shapes that aren't a wired map yet — a sketch of a map being
    #: made carries the name typed into the form. "" for an existing map, whose
    #: caller already knows what it asked for.
    label: str = ""


@dataclass(frozen=True)
class Sketch:
    """A grid a form drew, before the tree has put colour on it.

    The counterpart to :class:`Blocks`, and it exists for one reason: the
    family's new-map form is *neutral studio code* while the colours are not.
    A grid file is bytes anywhere, but a tileset name means something only to
    the tree that defines the constant — so the form answers with the grid and
    the name it was given, and each family reader turns that into `Blocks` with
    its own swatches. Prism needs no such record: its action and its reader are
    the same adapter, so it hands itself its own (see `Action.sketch`).
    """
    blocks: bytes
    height: int
    width: int
    #: The tileset constant as typed — `TILESET_JOHTO`. Empty when the tree's
    #: header takes no tileset at all, which is drawn uncoloured rather than
    #: refused: the shape is the half of the picture that catches a wrong
    #: height, and it is still worth seeing without the hue.
    tileset: str = ""
    label: str = ""
