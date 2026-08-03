"""What prism-maps knows about one map, and how to read it out of the tree.

`used` is the contestable field: a map counts as wired only when its
`map_header_2` label also has a block-data label and a map-script-header label,
which is the same three-way agreement `mapsource.py` relies on. A label present
in only one of the three is a half-deleted map, and reporting it as used is what
this tool exists to avoid.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..hacks.prism import maps as maps_mod
from ..hacks.prism import mapsource


@dataclass
class MapInfo:
    name: str
    group: int
    map_id: int
    width: int
    height: int
    blocks: int
    blk_raw: int | None
    blk_lz: int | None
    lz_ratio: float | None   # blk_lz / blk_raw
    script_src: int | None   # bytes
    npc_count: int | None
    used: bool


_NPC_RE = re.compile(r"\s+(person_event|trainer)\b")
_AGGREGATE_SCRIPTS = frozenset({
    "blockdata.asm",
    "map_headers.asm",
    "second_map_headers.asm",
    "map_scripts.asm",
})


def _norm(name: str) -> str:
    return name.replace("_", "").lower()


def _blk_sizes(root: Path, target: str) -> tuple[int | None, int | None]:
    """(raw, lz) byte sizes for a `blockdata_labels()` INCBIN target (which
    always points at the compressed `.lz` file)."""
    lz_path = root / target
    raw_path = lz_path.with_name(lz_path.name[: -len(".lz")]) if target.endswith(".lz") else lz_path
    raw = raw_path.stat().st_size if raw_path.exists() else None
    lz = lz_path.stat().st_size if lz_path.exists() else None
    return raw, lz


def collect(root: Path) -> list[MapInfo]:
    """Build MapInfo list from source files under *root*."""
    map_defs = maps_mod.parse_maps(
        root / "constants" / "map_dimension_constants.asm"
    )

    # Ground truth for "used": a map_header_2 entry ties a Pascal-case label
    # to its ALL_CAPS const; the map is only really wired if that label also
    # has a block-data label and a map-script-header label (see mapsource.py).
    const_to_labels: dict[str, list[str]] = {}
    for label, const in mapsource.header_pairs(root):
        const_to_labels.setdefault(const, []).append(label)

    bd_labels = mapsource.blockdata_labels(root)
    script_labels = mapsource.script_header_labels(root)

    # Script file index: stem normalised → Path
    script_index: dict[str, Path] = {}
    maps_dir = root / "maps"
    if maps_dir.is_dir():
        for p in maps_dir.glob("*.asm"):
            if p.name not in _AGGREGATE_SCRIPTS:
                script_index[_norm(p.stem)] = p

    result: list[MapInfo] = []
    for md in map_defs:
        labels = const_to_labels.get(md.name, [])
        wired = [l for l in labels if l in bd_labels and l in script_labels]
        used = bool(wired)

        blk_label = wired[0] if wired else next((l for l in labels if l in bd_labels), None)
        raw = lz = None
        if blk_label is not None:
            raw, lz = _blk_sizes(root, bd_labels[blk_label])
        ratio = (lz / raw) if raw and lz else None

        key = _norm(md.name)
        script_path = script_index.get(key)
        script_src: int | None = None
        npc_count: int | None = None
        if script_path is not None:
            text = script_path.read_text(encoding="utf-8")
            script_src = len(text.encode("utf-8"))
            npc_count = sum(1 for line in text.splitlines() if _NPC_RE.match(line))

        result.append(MapInfo(
            name=md.name,
            group=md.group,
            map_id=md.map_id,
            width=md.width,
            height=md.height,
            blocks=md.width * md.height,
            blk_raw=raw,
            blk_lz=lz,
            lz_ratio=ratio,
            script_src=script_src,
            npc_count=npc_count,
            used=used,
        ))

    return result


_SORT_KEYS: dict[str, object] = {
    "name":   lambda r: r.name,
    "width":  lambda r: r.width,
    "height": lambda r: r.height,
    "blocks": lambda r: r.blocks,
    "raw":    lambda r: (r.blk_raw is None, r.blk_raw or 0),
    "lz":     lambda r: (r.blk_lz is None, r.blk_lz or 0),
    "ratio":  lambda r: (r.lz_ratio is None, r.lz_ratio or 0.0),
    "script": lambda r: (r.script_src is None, r.script_src or 0),
    "npcs":   lambda r: (r.npc_count is None, r.npc_count or 0),
}

# Sort keys that return (is_none, value) tuples — need None-at-end in both directions.
_NULLABLE_SORTS = frozenset({"raw", "lz", "ratio", "script", "npcs"})
