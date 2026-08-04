"""A map's header, its edges, and the roof its group loads.

The three facts about a map that are not things standing on it. Each is spread
across a different set of files in every tree, which is why each crosses as a
declared record rather than as whatever the source happened to say.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: What a header field says when the source does not say. The reading side
#: draws it as written, so this is the one placeholder both sides share — two
#: spellings of it would put a different dash in the Attributes tab from the
#: one in every other column, and nothing would ever report the difference.
UNSAID = "—"


@dataclass(frozen=True)
class Link:
    """One edge connection, in the seam's words. Prism writes all four numbers
    in its `connection` macro; the modern `def_*` dialect declares only the
    offset and computes the rest at assembly — so the computed columns are
    None there, and appear only when some row fills them."""
    direction: str
    target: str
    offset: int
    coord: int | None = None
    strip: int | None = None

    @property
    def delta(self) -> int | None:
        """The alignment between the two maps' coordinate systems. The map on
        the other side must carry exactly its negation, or the seam tears."""
        return None if self.coord is None else self.coord - self.offset


@dataclass(frozen=True)
class Attributes:
    """A map's header, as it is written down. Assembled by the session, which is
    the side that knows which five files these eight facts are spread across."""
    label: str
    const: str
    group: int
    map_id: int
    height: int
    width: int
    tileset: str = UNSAID
    permission: str = UNSAID
    landmark: str = UNSAID
    music: str = UNSAID
    palette: str = UNSAID
    fishgroup: str = UNSAID
    phone: str = "0"
    border_block: str = UNSAID
    blk: str = UNSAID
    #: section name -> the bank it is pinned to in contents/romx.link, or "" for
    #: a section that floats. Three of them: blockdata, script, secondary.
    banks: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Roof:
    """The roof a map group loads, in the seam's words — including the two ways
    a source can disagree with itself about it, which are facts about the tree
    and so cross as data, not as prose only one adapter could write."""
    group: int
    #: Index into the roof-tiles table, or None when the group has no roof.
    tiles: int | None = None
    #: The tiles file that index names, if it exists. None for an index with no
    #: file behind it — itself worth knowing: the engine will copy whatever
    #: bytes follow the last roof.
    tile_file: str | None = None
    #: morn/day ×2, then nite ×2, as `#rrggbb`.
    colors: tuple[str, str, str, str] | None = None
    #: What the source's comment *says* this byte belongs to, when that is not
    #: this group. Prism's roofs.asm disagrees with its own engine on every row.
    mislabelled: int | None = None
    #: The group is past the end of the roof table — which is not "no roof":
    #: the engine indexes the table unconditionally and reads whatever
    #: assembles next as a roof index.
    past_end: bool = False
    #: How many entries the table actually has, for saying how far past.
    entries: int = 0
