"""Terminal table of per-map metadata for pokeprism.

Usage:  prism-maps [OPTIONS]
Run from anywhere inside the pokeprism checkout. No ROM required.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from ..hacks.prism import maps as maps_mod
from ..hacks.prism import mapsource
from ..shared.paths import RepoNotFound, repo_root

# ---------------------------------------------------------------------------
# ANSI helpers
# ---------------------------------------------------------------------------

_GREEN = "\033[32m"
_RED = "\033[31m"
_RESET = "\033[0m"


def _c(text: str, code: str, *, color: bool) -> str:
    return f"{code}{text}{_RESET}" if color else text


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class MapInfo:
    name: str
    group: int
    map_id: int
    width: int
    height: int
    blocks: int
    blk_raw: int | None
    blk_lz: int | None
    lz_ratio: float | None   # blk_lz / blk_raw
    script_src: int | None   # bytes
    npc_count: int | None
    used: bool


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------

_NPC_RE = re.compile(r"\s+(person_event|trainer)\b")
_AGGREGATE_SCRIPTS = frozenset({
    "blockdata.asm",
    "map_headers.asm",
    "second_map_headers.asm",
    "map_scripts.asm",
})


def _norm(name: str) -> str:
    return name.replace("_", "").lower()


def _blk_sizes(root: Path, target: str) -> tuple[int | None, int | None]:
    """(raw, lz) byte sizes for a `blockdata_labels()` INCBIN target (which
    always points at the compressed `.lz` file)."""
    lz_path = root / target
    raw_path = lz_path.with_name(lz_path.name[: -len(".lz")]) if target.endswith(".lz") else lz_path
    raw = raw_path.stat().st_size if raw_path.exists() else None
    lz = lz_path.stat().st_size if lz_path.exists() else None
    return raw, lz


def collect(root: Path) -> list[MapInfo]:
    """Build MapInfo list from source files under *root*."""
    map_defs = maps_mod.parse_maps(
        root / "constants" / "map_dimension_constants.asm"
    )

    # Ground truth for "used": a map_header_2 entry ties a Pascal-case label
    # to its ALL_CAPS const; the map is only really wired if that label also
    # has a block-data label and a map-script-header label (see mapsource.py).
    const_to_labels: dict[str, list[str]] = {}
    for label, const in mapsource.header_pairs(root):
        const_to_labels.setdefault(const, []).append(label)

    bd_labels = mapsource.blockdata_labels(root)
    script_labels = mapsource.script_header_labels(root)

    # Script file index: stem normalised → Path
    script_index: dict[str, Path] = {}
    maps_dir = root / "maps"
    if maps_dir.is_dir():
        for p in maps_dir.glob("*.asm"):
            if p.name not in _AGGREGATE_SCRIPTS:
                script_index[_norm(p.stem)] = p

    result: list[MapInfo] = []
    for md in map_defs:
        labels = const_to_labels.get(md.name, [])
        wired = [l for l in labels if l in bd_labels and l in script_labels]
        used = bool(wired)

        blk_label = wired[0] if wired else next((l for l in labels if l in bd_labels), None)
        raw = lz = None
        if blk_label is not None:
            raw, lz = _blk_sizes(root, bd_labels[blk_label])
        ratio = (lz / raw) if raw and lz else None

        key = _norm(md.name)
        script_path = script_index.get(key)
        script_src: int | None = None
        npc_count: int | None = None
        if script_path is not None:
            text = script_path.read_text(encoding="utf-8")
            script_src = len(text.encode("utf-8"))
            npc_count = sum(1 for line in text.splitlines() if _NPC_RE.match(line))

        result.append(MapInfo(
            name=md.name,
            group=md.group,
            map_id=md.map_id,
            width=md.width,
            height=md.height,
            blocks=md.width * md.height,
            blk_raw=raw,
            blk_lz=lz,
            lz_ratio=ratio,
            script_src=script_src,
            npc_count=npc_count,
            used=used,
        ))

    return result


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

_HEADERS = ("NAME", "W", "H", "BLKS", "RAW", "LZ", "RATIO", "SCRIPT", "NPCS", "USED")

_SORT_KEYS: dict[str, object] = {
    "name":   lambda r: r.name,
    "width":  lambda r: r.width,
    "height": lambda r: r.height,
    "blocks": lambda r: r.blocks,
    "raw":    lambda r: (r.blk_raw is None, r.blk_raw or 0),
    "lz":     lambda r: (r.blk_lz is None, r.blk_lz or 0),
    "ratio":  lambda r: (r.lz_ratio is None, r.lz_ratio or 0.0),
    "script": lambda r: (r.script_src is None, r.script_src or 0),
    "npcs":   lambda r: (r.npc_count is None, r.npc_count or 0),
}

# Sort keys that return (is_none, value) tuples — need None-at-end in both directions.
_NULLABLE_SORTS = frozenset({"raw", "lz", "ratio", "script", "npcs"})


def _fmt_row(r: MapInfo, *, color: bool) -> tuple[str, ...]:
    def _dash(v: int | None) -> str:
        return "—" if v is None else str(v)

    if r.lz_ratio is None:
        ratio_str = "—"
    else:
        pct = f"{r.lz_ratio * 100:.0f}%"
        ratio_str = _c(pct, _RED, color=color) if r.lz_ratio > 1.0 else pct

    used_str = (
        _c("✓", _GREEN, color=color)
        if r.used
        else _c("✗", _RED, color=color)
    )

    return (
        r.name,
        str(r.width),
        str(r.height),
        str(r.blocks),
        _dash(r.blk_raw),
        _dash(r.blk_lz),
        ratio_str,
        _dash(r.script_src),
        _dash(r.npc_count),
        used_str,
    )


def _visible_len(s: str) -> int:
    return len(re.sub(r"\033\[[0-9;]*m", "", s))


def render_table(rows: list[MapInfo], *, color: bool) -> str:
    """Return a fixed-width table string."""
    formatted = [_fmt_row(r, color=color) for r in rows]
    widths = [len(h) for h in _HEADERS]
    for row in formatted:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], _visible_len(cell))

    def _pad(cell: str, width: int) -> str:
        return cell + " " * (width - _visible_len(cell))

    sep = "  ".join("-" * w for w in widths)
    header = "  ".join(h.ljust(w) for h, w in zip(_HEADERS, widths))
    lines = [header, sep]
    for row in formatted:
        lines.append("  ".join(_pad(c, w) for c, w in zip(row, widths)))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="prism-maps",
        description="Show per-map metadata from pokeprism source files (no ROM needed).",
    )
    parser.add_argument(
        "--sort",
        default="name",
        choices=list(_SORT_KEYS),
        metavar="{" + ",".join(_SORT_KEYS) + "}",
        help="Sort column (default: name)",
    )
    parser.add_argument("--reverse", action="store_true", help="Reverse sort order")
    parser.add_argument("--search", metavar="PATTERN",
                        help="Case-insensitive substring match on map name")
    parser.add_argument("--min-blocks", type=int, metavar="N",
                        help="Only maps with BLKS >= N")
    parser.add_argument("--max-blocks", type=int, metavar="N",
                        help="Only maps with BLKS <= N")
    parser.add_argument("--json", action="store_true",
                        help="Emit a JSON array instead of a table")

    ug = parser.add_mutually_exclusive_group()
    ug.add_argument("--used", action="store_true",
                    help="Show only maps referenced in blockdata.asm")
    ug.add_argument("--unused", action="store_true",
                    help="Show only maps NOT referenced in blockdata.asm")

    args = parser.parse_args()

    try:
        root = repo_root()
    except RepoNotFound as e:
        print(f"prism-maps: {e}", file=sys.stderr)
        sys.exit(2)

    rows = collect(root)

    # Filters (AND logic)
    if args.search:
        pat = args.search.lower()
        rows = [r for r in rows if pat in r.name.lower()]
    if args.min_blocks is not None:
        rows = [r for r in rows if r.blocks >= args.min_blocks]
    if args.max_blocks is not None:
        rows = [r for r in rows if r.blocks <= args.max_blocks]
    if args.used:
        rows = [r for r in rows if r.used]
    if args.unused:
        rows = [r for r in rows if not r.used]

    if not rows:
        sys.exit(1)

    sort_fn = _SORT_KEYS[args.sort]
    rows.sort(key=sort_fn, reverse=args.reverse)  # type: ignore[arg-type]
    if args.sort in _NULLABLE_SORTS:
        # Stable re-partition so None values always land at the end.
        rows.sort(key=lambda r: sort_fn(r)[0])  # type: ignore[index]

    if args.json:
        print(json.dumps([asdict(r) for r in rows], indent=2))
    else:
        color = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
        print(render_table(rows, color=color))
