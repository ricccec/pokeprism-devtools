#!/usr/bin/env python3
"""prism-map — inspect one map and (optionally) export its prism-mapfit spec.

The inverse of `prism-mapfit`: given a map's CamelCase label, read its
`map_header` / `map_header_2` fields, block-data and script paths straight from
the asm sources, report where each of its sections lives (bank) and how big its
blobs are, and emit the TOML `MapSpec` that `prism-mapfit` consumes.

    prism-map MtEmberSmallRoom                 # human report
    prism-map MtEmberSmallRoom --grid          # draw it, with its objects on it
    prism-map MtEmberSmallRoom --grid --zoom 3 # bigger tiles, roomier markers
    prism-map MtEmberSmallRoom --toml          # emit the spec TOML to stdout
    prism-map MtEmberSmallRoom -o mymap.toml   # ...and write it to a file

No ROM is required — not even for `--grid`, which reads the block data out of the
`.ablk` in the tree rather than out of the built game. That matters: the map you
are authoring is exactly the one that isn't in the ROM yet.

A built `.map` (next to the ROM, or via `--map`) adds the bank each section is
pinned to; without it the bank column is omitted.
"""

from .blobreport import BlobRow, gather_blobs
from .cli import main
from .grid import ZOOMS, fit_zoom, print_grid
from .mapheader import MapNotFound, build_spec

__all__ = [
    "BlobRow", "MapNotFound", "ZOOMS", "build_spec", "fit_zoom",
    "gather_blobs", "main", "print_grid",
]
