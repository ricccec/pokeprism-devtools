"""Which region a map is in — the question `RegionCheck` answers at runtime.

``constants/landmark_constants.asm`` is one flat enum with ``region_def NALJO``
markers dropped into it, each recording where a region's landmarks start.
``RegionCheck`` (engine/landmarks.asm) walks those same starts as thresholds and
returns the last region whose start is <= the landmark — so regions are
contiguous ranges of the enum, and this reproduces that exactly.

It matters because a map's *landmark*, not its name or its group, is what picks
its wild-encounter table. Filing wild data under the wrong region assembles
cleanly and leaves the map with no encounters at all.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from . import mapsource

_REL = "constants/landmark_constants.asm"

_REGION_RE = re.compile(r"^region_def\s+(\w+)$")
_CONST_RE = re.compile(r"^const\s+(\w+)$")


@lru_cache(maxsize=8)
def regions(root: Path) -> dict[str, str]:
    """landmark const -> region name (lowercase)."""
    path = root / _REL
    if not path.exists():
        return {}

    out: dict[str, str] = {}
    region: str | None = None
    for line in path.read_text().split("\n"):
        stripped = line.split(";")[0].strip()
        if m := _REGION_RE.match(stripped):
            region = m.group(1).lower()
        elif (m := _CONST_RE.match(stripped)) and region:
            out[m.group(1)] = region
    return out


def region_of_map(root: Path, const: str) -> str | None:
    """The region a *map* belongs to, resolved through its landmark. None when
    the map has no primary header, or its landmark sits before the first
    ``region_def``."""
    label = {c: l for l, c in mapsource.header_pairs(root)}.get(const)
    if label is None:
        return None
    header = mapsource.primary_header(root, label)
    if header is None:
        return None
    return regions(root).get(header.landmark)
