"""prism-metatiles — analyze how a tileset's metatiles are used across maps.

Usage:
    prism-metatiles [N] [--top K] [--render] [--json]

With a tileset id N (decimal or 0x-hex) it prints a full report: the maps that
use the tileset, a 16-column UTF-8 heatmap of the metatiles coloured by how many
maps reference each one, the top-k most/least used metatiles, the unused
metatiles, the 8x8 graphics-tile coverage, and the tileset's blob sizes.

Omit N to print a one-line summary per tileset.

Works purely from the pokeprism source files (maps/map_headers.asm, the
constants, tilesets/*, maps/blk/*) — no built ROM required. Run from anywhere
inside the pokeprism checkout.
"""

from .cli import main
from .mapuse import MapUse, blockdata_index, group_maps_by_tileset, script_block_ids, tileset_id_map
from .report import render_report, render_summary
from .tileset import (
    BlobSize, TilesetAnalysis, all_tileset_ids, analyze_tileset, blank_unused_metatiles,
    load_syms, metatile_usage, metatile_users, tile_coverage,
)

__all__ = [
    "BlobSize", "MapUse", "TilesetAnalysis", "all_tileset_ids", "analyze_tileset",
    "blank_unused_metatiles", "blockdata_index", "group_maps_by_tileset", "load_syms",
    "main", "metatile_usage", "metatile_users", "render_report",
    "render_summary", "script_block_ids", "tile_coverage", "tileset_id_map",
]
