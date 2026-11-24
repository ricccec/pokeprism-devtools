#!/usr/bin/env python3
"""prism-mapfit — find ROM banks for a new map and wire it in.

The ROM is ~91% full, so picking banks for a new map's blobs by hand is
tedious. This tool sizes each blob, bin-packs them into the free space the
linker reports (preferring scattered scraps over the empty high banks
``$76``–``$7F``), wires the map into the six source files, pins the new
sections in ``contents/romx.link``, and rebuilds to verify.

    prism-mapfit plan --spec map.toml [--script-size N]   # show the placement
    prism-mapfit add  --spec map.toml [--dry-run]          # wire it in + build

See :mod:`mapspec` for the spec file format. The blobs:

* **block data** — size measured exactly by compressing the ``.blk`` (lzcomp).
* **secondary header** — ``12 + 12·connections`` bytes (its own section).
* **script/event** — only known after assembly, so it is measured by a build
  unless ``--script-size`` is given.
"""

from .blobs import parse_blobs, selected_section_names
from .cli import main
from .commands import cmd_add, cmd_consolidate, cmd_plan, run_make
from .freespace import (
    PlacementError, baseline_free_space, blob_size, map_items, plan_placement,
    resolve_manual,
)
from .sizes import Sizes, estimate_sizes, sizes_from_map, sizes_from_map_strict

__all__ = [
    "PlacementError", "Sizes", "baseline_free_space", "blob_size", "cmd_add",
    "cmd_consolidate", "cmd_plan", "estimate_sizes", "main", "map_items",
    "parse_blobs", "plan_placement", "resolve_manual", "run_make",
    "selected_section_names", "sizes_from_map", "sizes_from_map_strict",
]
