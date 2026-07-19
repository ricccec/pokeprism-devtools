"""A map group's roof: which tiles it uses, and what colour they are.

Two tables, both **indexed by the map group directly**, both read from source::

    tilesets/roofs.asm   MapGroupRoofs — one byte per group: an index into
                         `Roofs` (the 2bpp tile sets), or -1 for no roof
    tilesets/roof.pal    RoofPals — four RGB per group: morn/day, then nite

The indexing is the whole subtlety here, and it is worth writing down because
**the source comments disagree with the engine.** `LoadMapGroupRoof`
(`tilesets/roofs.asm`) is::

    ld a, [wMapGroup]
    ld e, a
    ld d, 0
    ld hl, MapGroupRoofs
    add hl, de          ; <- no `dec a`
    ld a, [hl]

so group N reads byte N, and `wMapGroup` is 1-based (`newgroup` starts the
counter at 1). But `MapGroupRoofs`' first byte is commented ``; group 1``. Both
cannot be true. `tilesets/roof.pal` settles it: `RoofPals` is indexed the same
way (`wMapGroup * 8`), it opens with four black RGB that nothing can reach, and
its one comment — ``; Group 95`` — sits at exactly slot 95. So slot *is* group,
slot 0 is a dummy for the group that doesn't exist, and the engine is right.

Therefore: **the comments in roofs.asm are off by one from what the game reads.**
This module follows the engine, because the engine is what you see when you play.
It reports the disagreement rather than hiding it — see :attr:`Roof.mislabelled`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_ROOFS = "tilesets/roofs.asm"
_PAL = "tilesets/roof.pal"

#: Four colours per group: two for morn/day, two for nite. `engine/color.asm`
#: copies them into colours 1 and 2 of BG palette 6.
COLORS_PER_GROUP = 4

_DB_RE = re.compile(r"^\s*db\s+(-?\d+)\s*(?:;\s*group\s*(\d+))?", re.I)
_RGB_RE = re.compile(r"^\s*RGB\s+(\d+)\s*,\s*(\d+)\s*,\s*(\d+)")
_LABEL_RE = re.compile(r"^MapGroupRoofs:")
_INCBIN_RE = re.compile(r'^\s*INCBIN\s+"([^"]+)"')

#: Game Boy Color channels are 5 bits. 8-bit ×255/31 is the conversion the rest
#: of the toolchain uses (see `hacks/prism/render.py`), so the colours here match the
#: ones the grid is drawn with rather than being a second, slightly different
#: idea of the same red.
def _rgb555(r: int, g: int, b: int) -> str:
    return "#" + "".join(f"{v * 255 // 31:02x}" for v in (r, g, b))


@dataclass(frozen=True)
class Roof:
    group: int
    #: Index into `Roofs`, or None when the group has no roof (-1 / $ff) — or
    #: when nothing can be said, which :attr:`past_end` distinguishes.
    tiles: int | None
    #: The 2bpp file that index names, if it exists. None for an index with no
    #: file behind it, which is itself worth knowing: `CopyNthStruct` will copy
    #: whatever bytes follow the last roof.
    tile_file: str | None
    #: morn/day ×2, then nite ×2, as `#rrggbb`. None past the end of roof.pal.
    colors: tuple[str, str, str, str] | None
    #: What `roofs.asm`'s comment *says* this byte belongs to, when that is not
    #: this group. See the module docstring: in this repo it always disagrees.
    mislabelled: int | None = None
    #: The group is past the end of `MapGroupRoofs` — which is not "no roof".
    #: `LoadMapGroupRoof` indexes the table unconditionally, so it reads whatever
    #: assembles next and treats it as a roof index. This repo's table has 28
    #: entries and the game has 96 map groups, so this is true of most of them.
    past_end: bool = False
    #: How many entries the table actually has, for the caller that wants to say
    #: how far past the end it is.
    entries: int = 0


def for_group(root: Path, group: int) -> Roof:
    """The roof the engine will actually load for `group` — not the one the
    source comments claim. See the module docstring for why those differ."""
    entries = _table(root)
    files = _roof_files(root)

    if not 0 <= group < len(entries):
        return Roof(group=group, tiles=None, tile_file=None,
                    colors=_colors(root, group),
                    past_end=True, entries=len(entries))

    value, labelled = entries[group]
    # -1 is written `db -1` and assembles to $ff. Either spelling means no roof:
    # `LoadMapGroupRoof` compares to $ff and returns without touching VRAM.
    tiles = None if value < 0 or value == 0xFF else value
    return Roof(
        group=group,
        tiles=tiles,
        tile_file=files[tiles] if tiles is not None and tiles < len(files) else None,
        colors=_colors(root, group),
        mislabelled=labelled if labelled is not None and labelled != group else None,
        entries=len(entries),
    )


def _table(root: Path) -> list[tuple[int, int | None]]:
    """`MapGroupRoofs`, as `(value, the group its comment claims)` per byte."""
    path = root / _ROOFS
    if not path.exists():
        return []

    entries: list[tuple[int, int | None]] = []
    seen_label = False
    for line in path.read_text().split("\n"):
        if _LABEL_RE.match(line):
            seen_label = True
            continue
        if not seen_label:
            continue
        m = _DB_RE.match(line)
        if not m:
            if line.strip() and not line.lstrip().startswith(";"):
                break                      # `Roofs:` — the table is over
            continue
        entries.append((int(m.group(1)), int(m.group(2)) if m.group(2) else None))
    return entries


def _roof_files(root: Path) -> list[str]:
    """The INCBINs under `Roofs:`, in order — index N is roof N."""
    path = root / _ROOFS
    if not path.exists():
        return []
    out, seen = [], False
    for line in path.read_text().split("\n"):
        if line.startswith("Roofs:"):
            seen = True
            continue
        if not seen:
            continue
        if m := _INCBIN_RE.match(line):
            out.append(m.group(1))
    return out


def _colors(root: Path, group: int) -> tuple[str, str, str, str] | None:
    path = root / _PAL
    if not path.exists():
        return None
    rgb = [_rgb555(int(m.group(1)), int(m.group(2)), int(m.group(3)))
           for line in path.read_text().split("\n")
           if (m := _RGB_RE.match(line))]

    at = group * COLORS_PER_GROUP
    if at + COLORS_PER_GROUP > len(rgb):
        return None
    return tuple(rgb[at:at + COLORS_PER_GROUP])       # type: ignore[return-value]
