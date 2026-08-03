"""What one tileset's metatiles look like: how used, how covered, how big.

Everything above `_blob_sizes` is pure — bytes in, numbers out — so the counting
rules can be tested without a checkout. `analyze` is the one function that needs
the tree, and it imports the renderer lazily because that pulls in Pillow.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..shared import paths
from ..shared.symfile import SymFile
from .mapuse import MapUse, tileset_id_map

_TILES_PER_METATILE = 16
_COLLISION_PER_METATILE = 4
_METATILE_CAP = 256


@dataclass
class BlobSize:
    name: str
    raw: int | None
    lz: int | None
    bank: int | None = None   # ROM bank from the .sym; None if no build artifact

    @property
    def ratio(self) -> float | None:
        return (self.lz / self.raw) if self.raw and self.lz else None


@dataclass
class TilesetAnalysis:
    tileset_id: int
    name: str
    n_defined: int          # metatiles defined in the .bin
    map_labels: list[str]
    usage: list[int]        # usage[m] = #maps referencing metatile m (len n_defined)
    tiles_used: int         # distinct 8x8 gfx tiles referenced by the metatiles
    tiles_total: int        # 8x8 tiles present in the .2bpp
    unused_tiles: list[int]
    users: dict[int, list[str]] = field(default_factory=dict)  # metatile -> map labels
    blobs: list[BlobSize] = field(default_factory=list)

    @property
    def unused(self) -> list[int]:
        return [m for m, c in enumerate(self.usage) if c == 0]

    def ranked(self) -> list[tuple[int, int]]:
        """(metatile, count) for referenced metatiles, most-used first."""
        ref = [(m, c) for m, c in enumerate(self.usage) if c > 0]
        ref.sort(key=lambda t: (-t[1], t[0]))
        return ref



def metatile_usage(uses: list[MapUse], n_defined: int) -> list[int]:
    """usage[m] = number of maps that reference metatile m at least once."""
    usage = [0] * n_defined
    for use in uses:
        for m in set(use.blocks) | use.script_ids:
            if 0 <= m < n_defined:
                usage[m] += 1
    return usage


def metatile_users(uses: list[MapUse], n_defined: int) -> dict[int, list[str]]:
    """metatile m -> sorted labels of maps that reference it (statically or via script)."""
    users: dict[int, set[str]] = {}
    for use in uses:
        for m in set(use.blocks) | use.script_ids:
            if 0 <= m < n_defined:
                users.setdefault(m, set()).add(use.label)
    return {m: sorted(labels) for m, labels in users.items()}


def tile_coverage(
    metatiles: bytes, attributes: bytes, n_defined: int, tiles_total: int
) -> tuple[int, list[int]]:
    """Return (distinct 8x8 tiles used, sorted unused tile ids).

    A metatile entry's attribute bit 3 selects VRAM bank 1, which maps to
    tile_id + 128 (mirrors render._composite_block).
    """
    used: set[int] = set()
    for i in range(n_defined * _TILES_PER_METATILE):
        if i >= len(metatiles):
            break
        tid = metatiles[i]
        attr = attributes[i] if i < len(attributes) else 0
        tid += ((attr >> 3) & 1) * 128
        used.add(tid)
    in_range = {t for t in used if t < tiles_total}
    unused = sorted(set(range(tiles_total)) - in_range)
    return len(in_range), unused


def blank_unused_metatiles(
    metatiles: bytes,
    attributes: bytes,
    collision: bytes,
    unused: list[int],
) -> tuple[bytes, bytes, bytes]:
    """Return new (metatiles, attributes, collision) with unused entries zeroed.

    Each unused metatile's 16 sub-tile references and their attributes are set to
    zero (pointing to 8×8 tile 0, bank 0). The 4 collision bytes per metatile are
    also zeroed. Safe to call with an empty `unused` list — returns copies unchanged.
    """
    mt = bytearray(metatiles)
    at = bytearray(attributes)
    co = bytearray(collision)
    for m in unused:
        base = m * _TILES_PER_METATILE
        mt[base : base + _TILES_PER_METATILE] = bytes(_TILES_PER_METATILE)
        at[base : base + _TILES_PER_METATILE] = bytes(_TILES_PER_METATILE)
        co_base = m * _COLLISION_PER_METATILE
        if co_base + _COLLISION_PER_METATILE <= len(co):
            co[co_base : co_base + _COLLISION_PER_METATILE] = bytes(_COLLISION_PER_METATILE)
    return bytes(mt), bytes(at), bytes(co)


def _blob_sizes(root: Path, tileset_id: int, syms: SymFile | None) -> list[BlobSize]:
    tid = f"{tileset_id:02d}"
    tdir = root / "tilesets"
    # (display name, raw-file path, .sym label for the bank lookup)
    specs = [
        ("metatiles", tdir / f"{tid}_metatiles.bin", f"Tileset{tid}Meta"),
        ("attributes", tdir / f"{tid}_attributes.bin", f"Tileset{tid}Attr"),
        ("collision", tdir / f"{tid}_collision.bin", f"Tileset{tid}Coll"),
        ("gfx", root / "gfx" / "tilesets" / f"{tid}.2bpp", f"Tileset{tid}GFX"),
    ]
    out: list[BlobSize] = []
    for name, raw_path, sym_label in specs:
        lz_path = raw_path.parent / (raw_path.name + ".lz")
        raw = raw_path.stat().st_size if raw_path.exists() else None
        lz_sz = lz_path.stat().st_size if lz_path.exists() else None
        sym = syms.get(sym_label) if syms is not None else None
        out.append(BlobSize(name, raw, lz_sz, bank=sym.bank if sym else None))
    return out


def load_syms(root: Path) -> SymFile | None:
    """The build's .sym table for bank lookups, or None if no ROM was built."""
    try:
        return SymFile.load(paths.sym_path(root))
    except (FileNotFoundError, OSError):
        return None


def analyze(
    root: Path, tileset_id: int, uses: list[MapUse], syms: SymFile | None = None
) -> TilesetAnalysis:
    from ..hacks.prism.render import load_tileset_files
    metatiles, attributes, gfx = load_tileset_files(root, tileset_id)
    n_defined = max(1, len(metatiles) // _TILES_PER_METATILE)
    usage = metatile_usage(uses, n_defined)
    users = metatile_users(uses, n_defined)
    tiles_total = len(gfx) // _TILES_PER_METATILE
    tiles_used, unused_tiles = tile_coverage(
        metatiles, attributes, n_defined, tiles_total
    )
    names = {v: k for k, v in tileset_id_map(root).items()}
    return TilesetAnalysis(
        tileset_id=tileset_id,
        name=names.get(tileset_id, "?"),
        n_defined=n_defined,
        map_labels=sorted(u.label for u in uses),
        usage=usage,
        tiles_used=tiles_used,
        tiles_total=tiles_total,
        unused_tiles=unused_tiles,
        users=users,
        blobs=_blob_sizes(root, tileset_id, syms),
    )


def all_tileset_ids(root: Path) -> list[int]:
    ids: set[int] = set()
    for p in (root / "tilesets").glob("*_metatiles.bin*"):
        stem = p.name.split("_", 1)[0]
        if stem.isdigit():
            ids.add(int(stem))
    return sorted(ids)

