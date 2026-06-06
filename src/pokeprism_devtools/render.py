"""Shared map rendering library for pokeprism devtools.

Renders a map to a PIL RGB Image by compositing:
  - block grid (from ROM blockdata)
  - metatile → tile-ID lookup (tilesets/<id>_metatiles.bin)
  - per-tile palette slot (tilesets/<id>_attributes.bin)
  - 2bpp tile graphics (gfx/tilesets/<id>.2bpp[.lz])
  - BG palette colors (tilesets/bg.pal and per-tileset overrides)

See docs/map-rendering.md for the full pipeline explanation.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from . import blockdata, lz, symfile

TILE_PX = 8
BLOCK_PX = 32   # 4×4 graphics tiles per block (wDecompressedMetatiles: ds 256 * 16)
_TILES_PER_BLOCK = 16
_BLOCK_COLS = 4

# From constants/tilemap_constants.asm (const_value = 1, sequential consts)
_TILESET_TRAINER_HOUSE = 0x1E
_TILESET_TUNOD = 0x2D
_TILESET_ESPO_FOREST = 0x36
_TILESET_OLCAN_ISLE = 0x37

# Special tileset → .pal file name (relative to tilesets/); None = no time-of-day offset
_SPECIAL_TILESET_PALS: dict[int, tuple[str, bool]] = {
    _TILESET_TRAINER_HOUSE: ("battle_tower.pal", False),
    _TILESET_TUNOD: ("tunod.pal", True),
    _TILESET_ESPO_FOREST: ("espo_forest.pal", True),
    _TILESET_OLCAN_ISLE: ("tunod.pal", True),
}

# Hardcoded from engine/color.asm (.TilesetColorsPointers + per-table rows)
_PERM_TO_TABLE = {0: "outdoor", 1: "outdoor", 2: "outdoor", 3: "indoor",
                  4: "dungeon", 5: "dungeon", 6: "indoor", 7: "dungeon"}

_COLOR_TABLES: dict[str, list[list[int]]] = {
    "outdoor": [
        [0x00, 0x01, 0x02, 0x28, 0x04, 0x05, 0x06, 0x07],
        [0x08, 0x09, 0x0a, 0x28, 0x0c, 0x0d, 0x0e, 0x0f],
        [0x10, 0x11, 0x12, 0x29, 0x14, 0x15, 0x16, 0x17],
        [0x18, 0x19, 0x1a, 0x1b, 0x1c, 0x1d, 0x1e, 0x1f],
    ],
    "indoor": [
        [0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x07],
        [0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x07],
        [0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x07],
        [0x18, 0x19, 0x1a, 0x1b, 0x1c, 0x1d, 0x1e, 0x07],
    ],
    "dungeon": [
        [0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07],
        [0x08, 0x09, 0x0a, 0x0b, 0x0c, 0x0d, 0x0e, 0x0f],
        [0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17],
        [0x18, 0x19, 0x1a, 0x1b, 0x1c, 0x1d, 0x1e, 0x1f],
    ],
}

_GRAY_PALETTE: list[tuple[int, int, int]] = [(0, 0, 0), (85, 85, 85), (170, 170, 170), (255, 255, 255)]

# The freely-combinable BG palette tables (engine/color.asm .TilesetColorsPointers).
# Each resolves against bg.pal via _COLOR_TABLES; special per-tileset .pal files
# are deliberately not exposed as override choices.
PALETTE_TABLES = ("outdoor", "indoor", "dungeon")


def _read_or_lz(path: Path) -> bytes:
    if path.exists():
        return path.read_bytes()
    lz_path = path.parent / (path.name + ".lz")
    if lz_path.exists():
        data, _ = lz.decompress(lz_path.read_bytes())
        return data
    return b""


def _png_to_2bpp(path: Path) -> bytes:
    """Convert a 4-shade grayscale PNG tileset to 2bpp bytes.

    rgbgfx convention: 255→index 0, 170→1, 85→2, 0→3.
    Tiles are laid out in a grid, left-to-right then top-to-bottom.
    """
    img = Image.open(path).convert("L")
    w, h = img.size
    px = img.load()
    out = bytearray()
    for tr in range(h // 8):
        for tc in range(w // 8):
            for row in range(8):
                lo = hi = 0
                for col in range(8):
                    lum = px[tc * 8 + col, tr * 8 + row]
                    idx = (255 - lum) // 85   # 255→0, 170→1, 85→2, 0→3
                    bit = 7 - col
                    lo |= (idx & 1) << bit
                    hi |= ((idx >> 1) & 1) << bit
                out.append(lo)
                out.append(hi)
    return bytes(out)


def parse_pal_file(path: Path) -> list[list[tuple[int, int, int]]]:
    """Parse an RGBDS .pal text file into a list of palettes (each 4 RGB tuples).

    5-bit channel values (0-31) are expanded to 8-bit.
    """
    colors: list[tuple[int, int, int]] = []
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(";"):
            continue
        if stripped.upper().startswith("RGB"):
            parts = stripped[3:].strip().split(",")
            if len(parts) == 3:
                vs = [int(p.strip()) for p in parts]
                colors.append(tuple((v << 3) | (v >> 2) for v in vs))  # type: ignore[misc]
    return [colors[i:i + 4] for i in range(0, len(colors) - 3, 4)]


def get_map_palettes(
    root: Path,
    tileset_id: int,
    permission: int,
    time_of_day: int,
) -> list[list[tuple[int, int, int]]]:
    """Return 8 BG palettes (each 4 RGB tuples) for the given map.

    Replicates the LoadMapPals / LoadSpecialMapPalette logic from engine/color.asm.
    time_of_day: 0=morn 1=day 2=nite 3=dark
    """
    tod = max(0, min(3, time_of_day))
    tilesets_dir = root / "tilesets"

    if tileset_id in _SPECIAL_TILESET_PALS:
        pal_name, use_tod = _SPECIAL_TILESET_PALS[tileset_id]
        pal_path = tilesets_dir / pal_name
        if pal_path.exists():
            pals = parse_pal_file(pal_path)
            offset = tod * 8 if use_tod else 0
            section = pals[offset:offset + 8]
            if len(section) == 8:
                return section

    table_name = _PERM_TO_TABLE.get(permission & 7, "outdoor")
    return palettes_for_table(root, table_name, tod)


def table_for_permission(permission: int) -> str:
    """Return the BG palette table ('outdoor'/'indoor'/'dungeon') a map's
    permission byte resolves to (engine/color.asm .TilesetColorsPointers)."""
    return _PERM_TO_TABLE.get(permission & 7, "outdoor")


def palettes_for_table(
    root: Path,
    table_name: str,
    time_of_day: int,
) -> list[list[tuple[int, int, int]]]:
    """Return 8 BG palettes from bg.pal for an explicit color table.

    table_name: one of PALETTE_TABLES ('outdoor', 'indoor', 'dungeon').
    time_of_day: 0=morn 1=day 2=nite 3=dark

    This is the non-special branch of get_map_palettes, exposed so callers can
    pick a palette table directly (ignoring per-tileset special .pal files).
    """
    tod = max(0, min(3, time_of_day))
    bg_path = root / "tilesets" / "bg.pal"
    if not bg_path.exists():
        return [_GRAY_PALETTE] * 8

    bg_pals = parse_pal_file(bg_path)
    indices = _COLOR_TABLES[table_name][tod]
    return [bg_pals[idx] if idx < len(bg_pals) else _GRAY_PALETTE for idx in indices]


def load_tileset_files(root: Path, tileset_id: int) -> tuple[bytes, bytes, bytes]:
    """Return (metatiles, attributes, gfx) raw bytes for a tileset.

    GFX loading order: .2bpp → .2bpp.lz → .png (converted on the fly) → zeros.
    """
    tid = f"{tileset_id:02d}"
    metatiles = _read_or_lz(root / "tilesets" / f"{tid}_metatiles.bin") or bytes(4096)
    attributes = _read_or_lz(root / "tilesets" / f"{tid}_attributes.bin") or bytes(4096)
    gfx = _read_or_lz(root / "gfx" / "tilesets" / f"{tid}.2bpp")
    if not gfx:
        png_path = root / "gfx" / "tilesets" / f"{tid}.png"
        if png_path.exists():
            gfx = _png_to_2bpp(png_path)
    gfx = gfx or bytes(4096)
    return metatiles, attributes, gfx


def decode_2bpp_tile(gfx: bytes, tile_id: int) -> list[list[int]]:
    """Decode tile_id from 2bpp data. Returns 8×8 list of palette indices 0-3."""
    base = tile_id * 16
    if base + 16 > len(gfx):
        return [[0] * 8 for _ in range(8)]
    rows = []
    for row in range(8):
        lo = gfx[base + row * 2]
        hi = gfx[base + row * 2 + 1]
        rows.append([
            ((lo >> bit) & 1) | (((hi >> bit) & 1) << 1)
            for bit in range(7, -1, -1)
        ])
    return rows


def _composite_block(
    buf: bytearray,
    buf_w_px: int,
    block_col: int,
    block_row: int,
    tile_ids: bytes,
    attrs: bytes,
    gfx: bytes,
    palettes: list[list[tuple[int, int, int]]],
    tile_cache: dict[tuple[int, bool, bool], list[list[int]]],
) -> None:
    """Composite one 4×4-tile block into `buf` at (block_col, block_row).

    tile_ids / attrs are the 16 metatile entries for the block. `tile_cache`
    is shared across calls to avoid re-decoding identical (tile, flip) tiles.
    """
    for i in range(_TILES_PER_BLOCK):
        attr = attrs[i]
        pidx = attr & 7
        vram_bank = (attr >> 3) & 1   # bit 3: VRAM bank (bank 1 → tile_id + 128)
        h_flip = bool(attr & 0x20)    # bit 5: horizontal mirror
        v_flip = bool(attr & 0x40)    # bit 6: vertical mirror
        palette = palettes[pidx]

        effective_tid = tile_ids[i] + vram_bank * 128
        cache_key = (effective_tid, h_flip, v_flip)
        if cache_key not in tile_cache:
            pixels = decode_2bpp_tile(gfx, effective_tid)
            if h_flip:
                pixels = [row_px[::-1] for row_px in pixels]
            if v_flip:
                pixels = pixels[::-1]
            tile_cache[cache_key] = pixels
        tile_pixels = tile_cache[cache_key]

        tx = block_col * _BLOCK_COLS + (i % _BLOCK_COLS)
        ty = block_row * _BLOCK_COLS + (i // _BLOCK_COLS)

        for py in range(8):
            dst_y = ty * 8 + py
            dst_x_base = tx * 8
            row_off = (dst_y * buf_w_px + dst_x_base) * 3
            for px in range(8):
                r, g, b = palette[tile_pixels[py][px]]
                off = row_off + px * 3
                buf[off] = r
                buf[off + 1] = g
                buf[off + 2] = b


def render_map(
    root: Path,
    rom_path: Path,
    syms: symfile.SymFile,
    group: int,
    map_id: int,
    *,
    name: str = "",
    time_of_day: int = 1,
    tileset_id: int | None = None,
    palette_table: str | None = None,
) -> Image.Image:
    """Render a map to a PIL RGB Image.

    time_of_day: 0=morn 1=day 2=nite 3=dark
    tileset_id: override the graphics tileset (default: the map's own).
    palette_table: override the BG palette table (one of PALETTE_TABLES);
        default derives it from the map's permission via get_map_palettes.
    """
    bd = blockdata.load(rom_path, syms, group, map_id, name=name)
    gfx_tileset = tileset_id if tileset_id is not None else bd.tileset_id
    metatiles, attributes, gfx = load_tileset_files(root, gfx_tileset)
    if palette_table is not None:
        palettes = palettes_for_table(root, palette_table, time_of_day)
    else:
        palettes = get_map_palettes(root, bd.tileset_id, bd.permission, time_of_day)

    w_px = bd.width * BLOCK_PX    # BLOCK_PX = 32 (4×4 tiles × 8px)
    h_px = bd.height * BLOCK_PX
    buf = bytearray(w_px * h_px * 3)

    # Cache decoded tiles to avoid redundant work
    tile_cache: dict[tuple[int, bool, bool], list[list[int]]] = {}

    for row in range(bd.height):
        for col in range(bd.width):
            block_id = bd.blocks[row * bd.width + col]
            base = block_id * _TILES_PER_BLOCK
            end = base + _TILES_PER_BLOCK
            tile_ids = metatiles[base:end] if end <= len(metatiles) else bytes(_TILES_PER_BLOCK)
            attrs = attributes[base:end] if end <= len(attributes) else bytes(_TILES_PER_BLOCK)
            _composite_block(buf, w_px, col, row, tile_ids, attrs, gfx, palettes, tile_cache)

    return Image.frombytes("RGB", (w_px, h_px), bytes(buf))


def render_tileset_sheet(
    root: Path,
    tileset_id: int,
    palettes: list[list[tuple[int, int, int]]],
) -> Image.Image:
    """Render a tileset's 256 metatile blocks as a 16×16 grid (512×512 px).

    Each block is composited with its own attribute bytes (palette slot + flips)
    against the supplied 8 `palettes`, so it reads like an in-game screen.
    """
    metatiles, attributes, gfx = load_tileset_files(root, tileset_id)
    cols = rows = 16
    w_px = cols * BLOCK_PX
    h_px = rows * BLOCK_PX
    buf = bytearray(w_px * h_px * 3)
    tile_cache: dict[tuple[int, bool, bool], list[list[int]]] = {}

    for m in range(cols * rows):
        base = m * _TILES_PER_BLOCK
        end = base + _TILES_PER_BLOCK
        tile_ids = metatiles[base:end] if end <= len(metatiles) else bytes(_TILES_PER_BLOCK)
        attrs = attributes[base:end] if end <= len(attributes) else bytes(_TILES_PER_BLOCK)
        _composite_block(buf, w_px, m % cols, m // cols, tile_ids, attrs, gfx, palettes, tile_cache)

    return Image.frombytes("RGB", (w_px, h_px), bytes(buf))
