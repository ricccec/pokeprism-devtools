"""What the tree already contains, so the wizard can refuse a duplicate.

A new map's label and const have to be unique, and its group has to be one that
exists — creating a group is out of scope (see docs/devtools.md). All three
answers come from files `prism-newmap` never writes.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..hacks.prism import maps as maps_mod
from ..hacks.prism import mapsource


def _consts(path: Path, prefix: str) -> list[str]:
    """Every `const <prefix>...` name in *path*, in file order."""
    if not path.exists():
        return []
    rx = re.compile(rf"^\s*const\s+({re.escape(prefix)}\w*)")
    out = []
    for ln in path.read_text().splitlines():
        m = rx.match(ln)
        if m:
            out.append(m.group(1))
    return out


def _existing_groups(root: Path) -> dict[int, list[str]]:
    defs = maps_mod.parse_maps(root / "constants" / "map_dimension_constants.asm")
    groups: dict[int, list[str]] = {}
    for d in defs:
        groups.setdefault(d.group, []).append(d.name)
    return groups


def _existing_labels_consts(root: Path) -> tuple[set[str], set[str]]:
    labels = {label for label, _const in mapsource.header_pairs(root)}
    consts = {
        d.name
        for d in maps_mod.parse_maps(root / "constants" / "map_dimension_constants.asm")
    }
    return labels, consts
