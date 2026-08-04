"""Block colors for a vanilla tileset, from palettes alone.

Prism's swatches average real pixels; this adapter never decodes a tile.
What vanilla *declares* about a tile's color is its palette class — one of
eight names per tile in `gfx/tileset_palette_maps.asm` — and `bg_tiles.pal`
says what each class looks like. A block is 4×4 tiles and a swatch quadrant
is its 2×2 corner, so a quadrant's color is the average of its four tiles'
class colors: honest degradation, exactly what the `Swatch` alias in
`studio/panels` licenses an adapter without decoded graphics to do.

The day palette is the one shown. Morn and nite exist in the file; a picker
would be a feature, a hardcoded *time* is just a choice of daylight.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from ... import contract

#: bg_tiles.pal line order within each time-of-day section.
CLASSES = ("GRAY", "RED", "GREEN", "WATER", "YELLOW", "BROWN", "ROOF", "TEXT")

#: The tile indices of each swatch quadrant in a 4×4 metatile, reading order.
QUADS = ((0, 1, 4, 5), (2, 3, 6, 7), (8, 9, 12, 13), (10, 11, 14, 15))

_RGB = re.compile(r"^\s*RGB\s+([\d, ]+)")
_TILEPAL = re.compile(r"^\s*tilepal\s+\d+\s*,\s*(.+)")


def for_tileset(root: Path, tileset_const: str) -> tuple[contract.Swatch, ...]:
    """One swatch per block of `TILESET_*`'s metatiles. Raises
    :class:`contract.Unreadable` when the metatiles file is missing — a tileset
    with no blocks has nothing for the grid to draw."""
    name = tileset_const.removeprefix("TILESET_").lower()
    meta_path = root / f"data/tilesets/{name}_metatiles.bin"
    if not meta_path.exists():
        raise contract.Unreadable(
            f"{meta_path} does not exist — {tileset_const} has no metatiles "
            "to color.")
    meta = meta_path.read_bytes()
    classes = _classes(root, name)
    colors = day_colors(root)
    gray = colors.get("GRAY", (128, 128, 128))

    out: list[contract.Swatch] = []
    for b in range(len(meta) // 16):
        tiles = meta[b * 16:(b + 1) * 16]
        quads = []
        for quad in QUADS:
            rs = gs = bs = 0
            for q in quad:
                cls = classes[tiles[q]] if tiles[q] < len(classes) else "GRAY"
                r, g, bl = colors.get(cls, gray)
                rs, gs, bs = rs + r, gs + g, bs + bl
            quads.append((rs // 4, gs // 4, bs // 4))
        out.append(tuple(quads))
    return tuple(out)


def _camel(name: str) -> str:
    return "".join(part.capitalize() for part in name.split("_"))


@lru_cache(maxsize=None)
def _classes(root: Path, name: str) -> tuple[str, ...]:
    """Flat tile → class-name list for one tileset. Each `tilepal` line
    covers eight tiles in order; the leading VRAM-bank digit adds nothing to
    a color. The per-tileset file usually matches the tileset's name; the few
    that share another's (dark cave wears cave's colors) are resolved through
    the labels file, whose stacked `Tileset*PalMap:` labels sit over one
    INCLUDE."""
    path = root / f"gfx/tilesets/{name}_palette_map.asm"
    if not path.exists():
        path = _included_map(root, _camel(name))
    if path is None or not path.exists():
        return ()
    classes: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if m := _TILEPAL.match(raw):
            classes += [c.strip().removeprefix("PRIORITY_")
                        for c in m.group(1).split(";")[0].split(",")]
    return tuple(classes)


def _included_map(root: Path, camel: str) -> Path | None:
    """The palette-map file `Tileset<Camel>PalMap:` covers, from the labels
    file: the first INCLUDE after the label, labels between skipped."""
    labels = root / "gfx/tileset_palette_maps.asm"
    if not labels.exists():
        return None
    found = False
    for raw in labels.read_text(encoding="utf-8").splitlines():
        if raw.startswith(f"Tileset{camel}PalMap:"):
            found = True
        elif found and (m := re.search(r'INCLUDE\s+"([^"]+)"', raw)):
            return root / m.group(1)
    return None


@lru_cache(maxsize=None)
def day_colors(root: Path) -> dict[str, tuple[int, int, int]]:
    """class name → its representative color: the second entry of its day
    palette, the mid-light hue a tile mostly shows. 5-bit → 8-bit."""
    path = root / "gfx/tilesets/bg_tiles.pal"
    if not path.exists():
        return {}
    day: list[tuple[int, int, int]] = []
    section = ""
    for raw in path.read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        if s.startswith(";"):
            section = s.lstrip("; ").strip()
            continue
        if section == "day" and (m := _RGB.match(raw)):
            vals = [int(v) for v in m.group(1).replace(",", " ").split()]
            if len(vals) >= 6:
                day.append(tuple(v * 255 // 31 for v in vals[3:6]))
    return dict(zip(CLASSES, day))
