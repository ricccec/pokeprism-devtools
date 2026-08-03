"""The `prism-metatiles` command line, and the two things it can write."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from ..shared import paths
from ..shared.devtools import make_devtools_dir
from ..shared.viewer import is_stale, open_images, parse_tileset_id
from .mapuse import collect
from .report import _as_dict, _compact_ranges, render_report, render_summary
from .tileset import (
    _COLLISION_PER_METATILE, TilesetAnalysis, all_tileset_ids, analyze,
    blank_unused_metatiles, load_syms,
)

def _render_sheet(root: Path, tileset_id: int, force: bool) -> Path:
    cache_dir = make_devtools_dir(root, "gfx-renders")
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
        from ..hacks.prism.render import palettes_for_table, render_tileset_sheet
        palettes = palettes_for_table(root, "outdoor", 1)
        render_tileset_sheet(root, tileset_id, palettes).save(str(cache_file))
    return cache_file


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _do_blank(root: Path, a: TilesetAnalysis, *, write: bool) -> int:
    unused = a.unused
    print(f"\nUnused metatiles to blank: {len(unused)}", end="")
    if not unused:
        print(" — nothing to do.")
        return 0
    print(f"\n  {_compact_ranges(unused)}")

    tid = f"{a.tileset_id:02d}"
    tdir = root / "tilesets"
    mt_path = tdir / f"{tid}_metatiles.bin"
    at_path = tdir / f"{tid}_attributes.bin"
    co_path = tdir / f"{tid}_collision.bin"

    metatiles  = mt_path.read_bytes()
    attributes = at_path.read_bytes()
    collision  = co_path.read_bytes() if co_path.exists() else bytes(a.n_defined * _COLLISION_PER_METATILE)

    new_mt, new_at, new_co = blank_unused_metatiles(metatiles, attributes, collision, unused)

    if not write:
        print("(dry-run — pass --write to apply changes)")
        return 0

    mt_path.write_bytes(new_mt)
    at_path.write_bytes(new_at)
    written = [mt_path.name, at_path.name]
    if co_path.exists():
        co_path.write_bytes(new_co)
        written.append(co_path.name)
    print("Written: " + ", ".join(written))
    return 0


def _build_parser() -> argparse.ArgumentParser:
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
    p.add_argument("--blank-unused", action="store_true",
                   help="Zero out unused metatile definitions in the tileset .bin files "
                        "(requires a tileset id; dry-run unless --write is also passed).")
    p.add_argument("--write", action="store_true",
                   help="With --blank-unused: write changes to disk (default is dry-run).")
    return p


def _print_all_tilesets(root: Path, by_tileset, syms, *, as_json: bool) -> None:
    rows = [
        analyze(root, tid, by_tileset.get(tid, []), syms)
        for tid in all_tileset_ids(root)
    ]
    if as_json:
        print(json.dumps([_as_dict(a) for a in rows], indent=2))
    else:
        print(render_summary(rows))


def _print_one_tileset(a: TilesetAnalysis, *, as_json: bool, top: int) -> None:
    if as_json:
        print(json.dumps(_as_dict(a), indent=2))
    else:
        color = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
        print(render_report(a, top=top, color=color))


def _open_tileset_sheet(root: Path, tileset_id: int, force: bool) -> int:
    try:
        open_images([_render_sheet(root, tileset_id, force)])
    except Exception as e:
        print(f"prism-metatiles: render failed: {e}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    try:
        root = paths.repo_root()
    except paths.RepoNotFound as e:
        print(f"prism-metatiles: {e}", file=sys.stderr)
        return 2

    by_tileset, warnings = collect(root)
    for w in warnings:
        print(f"  warning: {w}", file=sys.stderr)

    syms = load_syms(root)

    if args.blank_unused and args.tileset_id is None:
        print("prism-metatiles: --blank-unused requires a tileset id", file=sys.stderr)
        return 2

    if args.tileset_id is None:
        _print_all_tilesets(root, by_tileset, syms, as_json=args.json)
        return 0

    a = analyze(root, args.tileset_id, by_tileset.get(args.tileset_id, []), syms)
    _print_one_tileset(a, as_json=args.json, top=args.top)

    if args.render:
        failed = _open_tileset_sheet(root, args.tileset_id, args.force)
        if failed:
            return failed

    if args.blank_unused:
        return _do_blank(root, a, write=args.write)

    return 0
