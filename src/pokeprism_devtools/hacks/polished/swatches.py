"""Block colors for a polished tileset, from its attribute bytes.

Polished dropped vanilla's `tilepal` asm in favour of a binary: each tile of
`data/tilesets/<name>_metatiles.bin` has a byte in the sibling
`<name>_attributes.bin`, and its low three bits are the palette class — the
same eight classes, in the same `bg_tiles.pal` order, so the colors
themselves are read by vanilla's parser. The quadrant averaging is
vanilla's too; only the class lookup differs.
"""

from __future__ import annotations

from pathlib import Path

from ...studio import panels
from ..vanilla.swatches import CLASSES, QUADS, day_colors


def for_tileset(root: Path, tileset_const: str) -> tuple[panels.Swatch, ...]:
    """One swatch per block. Raises :class:`panels.Unreadable` when the
    metatiles file is missing."""
    name = tileset_const.removeprefix("TILESET_").lower()
    meta_path = root / f"data/tilesets/{name}_metatiles.bin"
    if not meta_path.exists():
        raise panels.Unreadable(
            f"{meta_path} does not exist — {tileset_const} has no metatiles "
            "to color.")
    meta = meta_path.read_bytes()
    attr_path = meta_path.with_name(f"{name}_attributes.bin")
    attr = attr_path.read_bytes() if attr_path.exists() else b""
    colors = day_colors(root)
    gray = colors.get("GRAY", (128, 128, 128))

    out: list[panels.Swatch] = []
    for b in range(len(meta) // 16):
        quads = []
        for quad in QUADS:
            rs = gs = bs = 0
            for q in quad:
                i = b * 16 + q
                cls = CLASSES[attr[i] & 0b111] if i < len(attr) else "GRAY"
                r, g, bl = colors.get(cls, gray)
                rs, gs, bs = rs + r, gs + g, bs + bl
            quads.append((rs // 4, gs // 4, bs // 4))
        out.append(tuple(quads))
    return tuple(out)
