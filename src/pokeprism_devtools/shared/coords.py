"""The three units a map is measured in, and the one that lies.

A map is a grid of **blocks**. Everything you place on it — a warp, a signpost,
an NPC — is placed on a **coordinate tile**, and there are exactly 2×2 of those
per block. Under both sits the 8-pixel **graphics tile**, which nothing outside
the renderer ever names.

    graphics tile     8 px    4×4 per block   the renderer's unit
    coordinate tile  16 px    2×2 per block   what you type into a macro
    block            32 px    ---             what a .blk file stores

So a 18×20 map (`mapgroup CASTRO_FOREST, 18, 20`) is 36 tiles tall and 40 wide,
and `warp_def 29, 35, …` sits at tile (29, 35) — inside it, but only just.

**And then `person_event` lies.** `macros/map.asm:22`::

    db \\2 + 4 ; y
    db \\3 + 4 ; x

It adds four to *both*, at assembly time. So the bytes in the ROM are not the
numbers in the source, and a tool that reads objects out of a save file and a
tool that reads them out of the asm are looking at two different origins. Confuse
them and every NPC lands four tiles up and to the left of where you put it — it
still assembles, it still boots, and you find out by walking into a wall that
isn't there.

Nothing here compensates for that when *writing*: source coordinates are what you
type, and `warp_def` / `signpost` / `person_event` all take the same origin in
source. The +4 exists in exactly one place — the assembled bytes — so it lives in
exactly one pair of functions here, named for what they convert between.
"""

from __future__ import annotations

#: Pixels per graphics tile / coordinate tile / block.
TILE_PX = 8
COORD_PX = 16
BLOCK_PX = 32

#: Coordinate tiles per block, per axis. The whole reason a block's swatch is 2×2.
TILES_PER_BLOCK = 2

#: What `person_event` adds to y and x at assembly (macros/map.asm:22-23). The
#: engine's object structs are offset so an NPC can stand off-screen without its
#: coordinates going negative.
PERSON_OFFSET = 4


def block_of(y: int, x: int) -> tuple[int, int]:
    """The block a coordinate tile falls in, as (row, col)."""
    return y // TILES_PER_BLOCK, x // TILES_PER_BLOCK


def tile_of(row: int, col: int) -> tuple[int, int]:
    """The top-left coordinate tile of a block, as (y, x)."""
    return row * TILES_PER_BLOCK, col * TILES_PER_BLOCK


def quadrant_of(y: int, x: int) -> tuple[int, int]:
    """Which of a block's four coordinate tiles this is, as (row, col) in 0..1.

    The same 2×2 the swatches are cut into — so a cursor on a coordinate tile is
    a cursor on exactly one swatch quadrant, and the grid can highlight it.
    """
    return y % TILES_PER_BLOCK, x % TILES_PER_BLOCK


def tile_size(height: int, width: int) -> tuple[int, int]:
    """A map's size in coordinate tiles, given its size in blocks."""
    return height * TILES_PER_BLOCK, width * TILES_PER_BLOCK


def in_bounds(y: int, x: int, height: int, width: int) -> bool:
    """Is this coordinate tile on the map? `height`/`width` are in **blocks**."""
    rows, cols = tile_size(height, width)
    return 0 <= y < rows and 0 <= x < cols


def person_to_source(y: int, x: int) -> tuple[int, int]:
    """Assembled `person_event` bytes -> the coordinates written in the source."""
    return y - PERSON_OFFSET, x - PERSON_OFFSET


def source_to_person(y: int, x: int) -> tuple[int, int]:
    """The coordinates written in the source -> the assembled `person_event` bytes."""
    return y + PERSON_OFFSET, x + PERSON_OFFSET


#: What each kind of thing is drawn as on the grid. Deliberately one character:
#: a coordinate tile is half a terminal cell, and there is no room to be clever.
WARP, SIGN, PERSON, TRAINER, ITEM = "W", "S", "N", "T", "I"

_ITEM_TYPES = ("PERSONTYPE_ITEMBALL", "PERSONTYPE_TMHMBALL", "PERSONTYPE_FRUITTREE")
_TRAINER_TYPES = ("PERSONTYPE_TRAINER", "PERSONTYPE_GENERICTRAINER")


def markers(header) -> dict[tuple[int, int], str]:
    """Everything placed on a map, by the coordinate tile it stands on.

    Takes an :class:`..eventheader.EventHeader`. **No offset is applied, and that
    is the point**: `Entry.y()` reads the number written in the *source*, and in
    source `warp_def`, `signpost` and `person_event` all share one origin. The +4
    above is added by the assembler, so it belongs to the bytes, not to these.
    Add it here and every NPC on the grid drifts four tiles from where the file
    says it is.

    Later entries win, because that is what the engine does with two objects on
    one tile — and seeing only one of them is a fair picture of the result.
    """
    from .eventheader import ListKind

    out: dict[tuple[int, int], str] = {}
    for kind, glyph in ((ListKind.WARPS, WARP), (ListKind.BG_EVENTS, SIGN)):
        for entry in header.list_of(kind).entries:
            y, x = entry.coords
            if y is not None and x is not None:
                out[(y, x)] = glyph

    for entry in header.object_events:
        y, x = entry.coords
        if y is None or x is None:
            continue
        kind = entry.persontype
        out[(y, x)] = (ITEM if kind in _ITEM_TYPES else
                       TRAINER if kind in _TRAINER_TYPES else PERSON)
    return out
