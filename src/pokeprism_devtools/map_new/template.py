"""The empty map a new map starts as, and where its two files go."""

from __future__ import annotations

import shutil
from pathlib import Path

#: An empty map: no triggers, no callbacks, and an event header with four empty
#: lists. Public because the studio's `NewMap` action writes the same one, and a
#: second copy of it would be a second definition of what an empty map *is*.
#:
#: The event header comes *first*, so the top of a map is the list of what stands
#: in it — every object and its attributes, at a glance — and the scripts and
#: dialogue those objects point at fill the second half below. That is the shape
#: MtEmberWest.asm keeps, and the shape the scaffolds add content into: a person
#: joins the object list up top, and its words go under `; ***** Scripts *****`.
TEMPLATE = """{label}_MapScriptHeader:
 ;trigger count
\tdb 0
 ;callback count
\tdb 0

; ***** Event header *****
{label}_MapEventHeader:: db 0, 0

.Warps
\tdb 0

.CoordEvents
\tdb 0

.BGEvents
\tdb 0

.ObjectEvents
\tdb 0

; ***** Map callbacks *****

; ***** Scripts *****
"""


def write_template(root: Path, label: str) -> str:
    """Write the empty maps/<label>.asm stub. Returns the repo-relative path."""
    rel = f"maps/{label}.asm"
    path = root / rel
    if path.exists():
        raise FileExistsError(f"{rel} already exists")
    path.write_text(TEMPLATE.format(label=label))
    return rel


def place_blk(root: Path, src: Path, label: str) -> str:
    """Copy *src* to maps/blk/<label><ext>. Returns the repo-relative path."""
    ext = src.suffix.lower()
    if ext not in (".blk", ".ablk"):
        raise ValueError(f"blk source must be .blk or .ablk, got {src.suffix!r}")
    rel = f"maps/blk/{label}{ext}"
    dest = root / rel
    if dest.exists():
        raise FileExistsError(f"{rel} already exists")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, dest)
    return rel
