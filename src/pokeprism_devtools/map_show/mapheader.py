"""Read one wired map's headers back into a `MapSpec`.

The inverse of what `prism-mapfit` consumes: `map_header` and `map_header_2`
give most fields, but the dimensions live behind the const in
`map_dimension_constants.asm`, so a spec needs all three files to reassemble.
"""

from __future__ import annotations

from pathlib import Path

from ..hacks.prism import maps as maps_mod, mapsource
from ..hacks.prism.mapspec import MapSpec


class MapNotFound(RuntimeError):
    pass


def build_spec(root: Path, label: str) -> MapSpec:
    """Assemble a MapSpec for an existing, wired map from its asm sources."""
    sec = mapsource.secondary_header(root, label)
    if sec is None:
        raise MapNotFound(
            f"no `map_header_2 {label}, ...` in maps/second_map_headers.asm — "
            "is the label spelled exactly (CamelCase) and the map wired in?"
        )
    prim = mapsource.primary_header(root, label)
    if prim is None:
        raise MapNotFound(f"no `map_header {label}, ...` in maps/map_headers.asm")

    dims = {m.name: m for m in maps_mod.parse_maps(
        root / "constants" / "map_dimension_constants.asm")}
    md = dims.get(sec.const)
    if md is None:
        raise MapNotFound(
            f"const {sec.const} not found in map_dimension_constants.asm")

    return MapSpec(
        label=label, const=sec.const, group=md.group,
        height=md.height, width=md.width,
        tileset=prim.tileset, permission=prim.permission, landmark=prim.landmark,
        music=prim.music, palette=prim.palette, fishgroup=prim.fishgroup,
        phone=prim.phone,
        border_block=sec.border_block, conn_flags=sec.conn_flags,
        connections=sec.connections,
        script_asm=mapsource.script_path(root, label) or "",
        blk=mapsource.blk_path(root, label) or "",
    )
