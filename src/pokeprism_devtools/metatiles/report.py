"""The report prism-metatiles prints, and the JSON behind `--json`.

The heatmap ramps red (a metatile one map uses) through yellow to dark green
(six or more), so the eye lands on the *rare* ones — those are what a tileset
edit is likely to break, and the crowded ones look after themselves.
"""

from __future__ import annotations

from .tileset import _METATILE_CAP, BlobSize, TilesetAnalysis

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

