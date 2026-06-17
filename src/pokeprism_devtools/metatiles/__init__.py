"""prism-metatiles — analyze how a tileset's metatiles are used across maps.

Usage:
    prism-metatiles [N] [--top K] [--render] [--json]

With a tileset id N (decimal or 0x-hex) it prints a full report: the maps that
use the tileset, a 16-column UTF-8 heatmap of the metatiles coloured by how many
maps reference each one, the top-k most/least used metatiles, the unused
metatiles, the 8x8 graphics-tile coverage, and the tileset's blob sizes.

Omit N to print a one-line summary per tileset.

Works purely from the pokeprism source files (maps/map_headers.asm, the
constants, tilesets/*, maps/blk/*) — no built ROM required. Run from anywhere
inside the pokeprism checkout.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from ..shared import constants, lz, paths
from ..shared.symfile import SymFile
from ..shared.viewer import is_stale, open_images, parse_tileset_id

# ``shared.render`` pulls in Pillow; import it lazily so the pure helpers below
# (and their tests) stay usable without it. Only analyze()/--render need it.

_TILES_PER_METATILE = 16
_METATILE_CAP = 256

_MAP_HEADER_RE = re.compile(r"^\s*map_header\s+(\w+)\s*,\s*([A-Za-z_]\w*)")

# ---------------------------------------------------------------------------
# ANSI / heatmap buckets
# ---------------------------------------------------------------------------

_RESET = "\033[0m"

# (lower_bound, 256-colour code, plain-fallback char, legend label)
# Ordered high→low; first whose lower_bound <= count wins. Colour ramps from
# red (cold, 1 map) through yellow up to dark green (hot, 6+ maps); unused is a
# dim dot.
_BUCKETS: list[tuple[int, int, str, str]] = [
    (6, 22, "█", "6+"),
    (5, 46, "█", "5"),
    (4, 154, "█", "4"),
    (3, 226, "█", "3"),
    (2, 208, "█", "2"),
    (1, 196, "█", "1"),
    (0, 236, "·", "0 (unused)"),
]


def _bucket(count: int) -> tuple[int, str, str]:
    for lo, code, ch, label in _BUCKETS:
        if count >= lo:
            return code, ch, label
    return _BUCKETS[-1][1:]


def _square(count: int, *, color: bool) -> str:
    code, ch, _ = _bucket(count)
    return f"\033[38;5;{code}m{ch}{_RESET}" if color else ch


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MapUse:
    label: str
    blocks: bytes
    # Metatiles placed dynamically by the map's scripts (changeblock /
    # eventflagchangeblock), which never appear in the static block data.
    script_ids: frozenset[int] = field(default_factory=frozenset)


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


# ---------------------------------------------------------------------------
# Source-file collection (no ROM)
# ---------------------------------------------------------------------------


def _norm(name: str) -> str:
    return name.replace("_", "").lower()


def tileset_id_map(root: Path) -> dict[str, int]:
    """`TILESET_* -> numeric id` from constants/tilemap_constants.asm."""
    consts = constants.parse_constants(root / "constants" / "tilemap_constants.asm")
    return {c.name: c.value for c in consts if c.name.startswith("TILESET_")}


_BLOCKDATA_LABEL_RE = re.compile(r"^(\w+)_BlockData:\s*$")
_INCBIN_RE = re.compile(r'^\s*INCBIN\s+"([^"]+)"')


def blockdata_index(root: Path) -> dict[str, str]:
    """`_norm(map label) -> INCBIN target` from maps/blockdata.asm.

    Consecutive `<Label>_BlockData:` labels share the single INCBIN that
    follows them (many maps — pokecenters, marts, … — alias one block-data
    blob), so a per-label entry is emitted for every label in the run.
    """
    index: dict[str, str] = {}
    asm = root / "maps" / "blockdata.asm"
    if not asm.exists():
        return index
    pending: list[str] = []
    for line in asm.read_text(encoding="utf-8").splitlines():
        m = _BLOCKDATA_LABEL_RE.match(line.strip())
        if m:
            pending.append(m.group(1))
            continue
        m = _INCBIN_RE.match(line)
        if m:
            for label in pending:
                index[_norm(label)] = m.group(1)
            pending = []
            continue
        if line.strip():           # SECTION / anything else ends the run
            pending = []
    return index


# Script commands that write a metatile id into the live map. In both the
# block id is the LAST argument (changeblock x,y,BLOCK ;
# eventflagchangeblock FLAG,x,y,BLOCK).
_BLOCK_CMD_RE = re.compile(r"^\s*(?:changeblock|eventflagchangeblock)\b(.*)$")


def _parse_block_literal(tok: str) -> int | None:
    tok = tok.strip()
    try:
        if tok.startswith("$"):
            return int(tok[1:], 16)
        if tok.lower().startswith("0x"):
            return int(tok, 16)
        if tok.isdigit():
            return int(tok)
    except ValueError:
        return None
    return None  # symbolic constant — can't resolve to an id, skip


def script_block_ids(text: str) -> set[int]:
    """Metatile ids placed by changeblock/eventflagchangeblock in a map script."""
    ids: set[int] = set()
    for line in text.splitlines():
        m = _BLOCK_CMD_RE.match(line)
        if not m:
            continue
        args = m.group(1).split(";", 1)[0]          # drop trailing comment
        last = args.rsplit(",", 1)[-1]              # block id = last arg
        val = _parse_block_literal(last)
        if val is not None:
            ids.add(val)
    return ids


def _read_blocks(root: Path, target: str) -> bytes:
    """Read block bytes for an INCBIN target, decompressing `.lz` as needed.

    Falls back to the .lz/.raw counterpart if the literal target is absent.
    """
    path = root / target
    if not path.exists():
        alt = path.parent / (path.name[:-3] if path.name.endswith(".lz") else path.name + ".lz")
        path = alt if alt.exists() else path
    if path.name.endswith(".lz"):
        data, _ = lz.decompress(path.read_bytes())
        return data
    return path.read_bytes()


def collect(root: Path) -> tuple[dict[int, list[MapUse]], list[str]]:
    """Group maps by the tileset id they use.

    Returns `({tileset_id: [MapUse, ...]}, warnings)`.
    """
    ts_map = tileset_id_map(root)
    blk_index = blockdata_index(root)
    script_index = _script_index(root)
    warnings: list[str] = []

    by_tileset: dict[int, list[MapUse]] = {}
    headers = (root / "maps" / "map_headers.asm").read_text(encoding="utf-8")
    for line in headers.splitlines():
        m = _MAP_HEADER_RE.match(line)
        if not m:
            continue
        label, tileset_const = m.group(1), m.group(2)
        tid = ts_map.get(tileset_const)
        if tid is None:
            warnings.append(f"{label}: unknown tileset {tileset_const}")
            continue
        target = blk_index.get(_norm(label))
        if target is None:
            warnings.append(f"{label}: no block-data file")
            continue
        try:
            blocks = _read_blocks(root, target)
        except Exception as e:  # pragma: no cover - corrupt blob
            warnings.append(f"{label}: {e}")
            continue
        script = script_index.get(_norm(label))
        script_ids = frozenset(
            script_block_ids(script.read_text(encoding="utf-8")) if script else ()
        )
        by_tileset.setdefault(tid, []).append(MapUse(label, blocks, script_ids))

    return by_tileset, warnings


def _script_index(root: Path) -> dict[str, Path]:
    """`_norm(map label) -> maps/<Label>.asm` (the per-map script file)."""
    index: dict[str, Path] = {}
    maps_dir = root / "maps"
    if maps_dir.is_dir():
        for p in maps_dir.glob("*.asm"):
            index[_norm(p.stem)] = p
    return index


# ---------------------------------------------------------------------------
# Per-tileset analysis (pure)
# ---------------------------------------------------------------------------


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
    from ..shared.render import load_tileset_files
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


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

_HEAT_COLS = 16


def _fmt_size(n: int | None) -> str:
    return "—" if n is None else str(n)


def _compact_ranges(nums: list[int]) -> str:
    """'0,1,2,5,6' -> '0-2, 5-6'."""
    if not nums:
        return "(none)"
    parts: list[str] = []
    start = prev = nums[0]
    for n in nums[1:]:
        if n == prev + 1:
            prev = n
            continue
        parts.append(str(start) if start == prev else f"{start}-{prev}")
        start = prev = n
    parts.append(str(start) if start == prev else f"{start}-{prev}")
    return ", ".join(parts)


def render_report(a: TilesetAnalysis, *, top: int, color: bool) -> str:
    out: list[str] = []
    out.append(
        f"Tileset {a.tileset_id} (0x{a.tileset_id:02X})  {a.name}"
    )
    out.append(
        f"  metatiles defined: {a.n_defined}/{_METATILE_CAP}    "
        f"maps using it: {len(a.map_labels)}"
    )

    out.append("\nMaps using this tileset:")
    if a.map_labels:
        for chunk_start in range(0, len(a.map_labels), 3):
            out.append("  " + "  ".join(
                f"{lbl:<24}" for lbl in a.map_labels[chunk_start:chunk_start + 3]
            ).rstrip())
    else:
        out.append("  (none)")

    out.append("\nMetatile usage heatmap (maps referencing each metatile):")
    for row_start in range(0, a.n_defined, _HEAT_COLS):
        row = a.usage[row_start:row_start + _HEAT_COLS]
        out.append("  " + "".join(_square(c, color=color) for c in row))
    legend = "  ".join(
        f"{_square(lo, color=color)} {label}" for lo, _c, _ch, label in reversed(_BUCKETS)
    )
    out.append("  legend: " + legend)

    ranked = a.ranked()
    out.append(f"\nTop {top} most-used metatiles:")
    out.append("  " + (", ".join(f"#{m}×{c}" for m, c in ranked[:top]) or "(none)"))

    least = sorted(ranked, key=lambda t: (t[1], t[0]))[:top]
    out.append(f"Top {top} least-used (referenced) metatiles:")
    if least:
        idx_w = max(len(str(m)) for m, _ in least)
        cnt_w = max(len(str(c)) for _, c in least)
        for m, c in least:
            maps = ", ".join(a.users.get(m, []))
            out.append(f"  #{m:<{idx_w}} ×{c:<{cnt_w}}  {maps}")
    else:
        out.append("  (none)")

    unused = a.unused
    out.append(f"\nUnused metatiles: {len(unused)} of {a.n_defined}")
    out.append("  " + _compact_ranges(unused))

    out.append(
        f"\n8x8 tile coverage: {a.tiles_used}/{a.tiles_total} used"
        + (f"  ({a.tiles_total - a.tiles_used} unused)" if a.tiles_total else "")
    )
    if a.unused_tiles:
        out.append("  unused tiles: " + _compact_ranges(a.unused_tiles))

    out.append("\nBlob sizes (bytes):")
    out.append(f"  {'BLOB':<11} {'RAW':>7} {'LZ':>7}  {'RATIO':>5}  BANK")
    for b in a.blobs:
        ratio = "—" if b.ratio is None else f"{b.ratio * 100:.0f}%"
        bank = "—" if b.bank is None else f"0x{b.bank:02X}"
        out.append(
            f"  {b.name:<11} {_fmt_size(b.raw):>7} {_fmt_size(b.lz):>7}  "
            f"{ratio:>5}  {bank}"
        )

    return "\n".join(out)


def render_summary(rows: list[TilesetAnalysis]) -> str:
    header = f"{'ID':>3}  {'NAME':<24} {'META':>4} {'MAPS':>4} {'UNUSED':>6} {'RAW':>7} {'LZ':>7}"
    lines = [header, "-" * len(header)]
    for a in rows:
        meta = next((b for b in a.blobs if b.name == "metatiles"), None)
        raw = _fmt_size(meta.raw if meta else None)
        lz_sz = _fmt_size(meta.lz if meta else None)
        lines.append(
            f"{a.tileset_id:>3}  {a.name:<24} {a.n_defined:>4} "
            f"{len(a.map_labels):>4} {len(a.unused):>6} {raw:>7} {lz_sz:>7}"
        )
    return "\n".join(lines)


def _as_dict(a: TilesetAnalysis) -> dict:
    return {
        "tileset_id": a.tileset_id,
        "name": a.name,
        "n_defined": a.n_defined,
        "maps": a.map_labels,
        "usage": a.usage,
        "unused_metatiles": a.unused,
        "tiles_used": a.tiles_used,
        "tiles_total": a.tiles_total,
        "unused_tiles": a.unused_tiles,
        "users": {str(m): labels for m, labels in sorted(a.users.items())},
        "blobs": [
            {"name": b.name, "raw": b.raw, "lz": b.lz, "bank": b.bank}
            for b in a.blobs
        ],
    }


# ---------------------------------------------------------------------------
# --render
# ---------------------------------------------------------------------------


def _render_sheet(root: Path, tileset_id: int, force: bool) -> Path:
    cache_dir = root / ".devtools" / "gfx-renders"
    cache_dir.mkdir(parents=True, exist_ok=True)
    tid = f"{tileset_id:02d}"
    sources = [
        root / "tilesets" / f"{tid}_metatiles.bin",
        root / "tilesets" / f"{tid}_metatiles.bin.lz",
        root / "tilesets" / f"{tid}_attributes.bin",
        root / "tilesets" / f"{tid}_attributes.bin.lz",
        root / "gfx" / "tilesets" / f"{tid}.2bpp",
        root / "gfx" / "tilesets" / f"{tid}.2bpp.lz",
        root / "gfx" / "tilesets" / f"{tid}.png",
        root / "tilesets" / "bg.pal",
    ]
    cache_file = cache_dir / f"tileset_{tid}_outdoor_day.png"
    if is_stale(cache_file, sources, force):
        from ..shared.render import palettes_for_table, render_tileset_sheet
        palettes = palettes_for_table(root, "outdoor", 1)
        render_tileset_sheet(root, tileset_id, palettes).save(str(cache_file))
    return cache_file


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="prism-metatiles",
        description="Analyze how a tileset's metatiles are used across maps.",
    )
    p.add_argument("tileset_id", type=parse_tileset_id, metavar="N", nargs="?",
                   help="Tileset id (decimal or 0x-hex). Omit for a summary of all tilesets.")
    p.add_argument("--top", type=int, default=10, metavar="K",
                   help="How many most/least-used metatiles to list (default: 10).")
    p.add_argument("--render", action="store_true",
                   help="Also render the tileset sheet to a PNG and open it (single id only).")
    p.add_argument("--force", action="store_true", help="Re-render even if the cache is fresh.")
    p.add_argument("--json", action="store_true",
                   help="Emit JSON instead of a formatted report.")
    args = p.parse_args(argv)

    try:
        root = paths.repo_root()
    except paths.RepoNotFound as e:
        print(f"prism-metatiles: {e}", file=sys.stderr)
        return 2

    by_tileset, warnings = collect(root)
    for w in warnings:
        print(f"  warning: {w}", file=sys.stderr)

    syms = load_syms(root)

    # Summary mode (no id given)
    if args.tileset_id is None:
        rows = [
            analyze(root, tid, by_tileset.get(tid, []), syms)
            for tid in all_tileset_ids(root)
        ]
        if args.json:
            print(json.dumps([_as_dict(a) for a in rows], indent=2))
        else:
            print(render_summary(rows))
        return 0

    # Single-tileset report
    a = analyze(root, args.tileset_id, by_tileset.get(args.tileset_id, []), syms)
    if args.json:
        print(json.dumps(_as_dict(a), indent=2))
    else:
        color = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
        print(render_report(a, top=args.top, color=color))

    if args.render:
        try:
            out = _render_sheet(root, args.tileset_id, args.force)
            open_images([out])
        except Exception as e:
            print(f"prism-metatiles: render failed: {e}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
