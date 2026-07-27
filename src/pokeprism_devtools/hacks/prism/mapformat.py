"""Prism's ROM map dialect — where it diverges from the stock Gen-2 base.

The shared reader (`shared.overworld.blockdata`) defaults to stock pokecrystal's
map format; prism forked several of those facts, and this is the one place it
declares them, so every prism caller of the reader passes the same object rather
than re-stating the deviations. See [[port-calibrated-to-prism-outlier]]: the port
was first written against prism, so it is prism — not the reader — that carries
the difference.

Prism's deviations, each re-checked against prism's own source:
  - block data is LZ-compressed, not raw `.blk` bytes;
  - a coord event is 7 bytes, not 8;
  - the overworld block buffer is `wOverworldMap`, not `wOverworldMapBlocks`;
  - a connection's source pointer is relative to the shared decompress scratch
    buffer (prism decompresses each neighbour into it), not the neighbour's own
    block label;
  - the sprite-header table is `SpriteHeaders`, not `OverworldSprites`;
  - a group's outdoor sprite list is zero-terminated, not a fixed 23 entries.
"""

from __future__ import annotations

from ...shared.overworld.blockdata import CONN_SRC_SCRATCH, MapFormat

#: The single source of truth for prism's map format, passed to every
#: `shared.overworld` read a prism tree drives.
PRISM_FORMAT = MapFormat(
    compressed=True,
    coord_event=7,
    overworld_map="wOverworldMap",
    connection_source=CONN_SRC_SCRATCH,
    sprite_headers="SpriteHeaders",
    outdoor_sprites=None,   # zero-terminated lists
)
