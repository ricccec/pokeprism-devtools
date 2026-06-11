"""prism-gfx — visualize tilesets and BG palettes, to pick prism-mapview args.

Usage:
    prism-gfx tileset [N] [--palette {outdoor,indoor,dungeon}] [--time {morn,day,nite,dark}] [--force]
    prism-gfx palettes [--force]

`tileset` renders a tileset's 256 metatile blocks as a 16×16 grid (512×512),
colored with a chosen palette table — so you can see what each `--tileset N`
looks like before rendering a map with it. Omit N to render every tileset and
open them all at once. `palettes` renders the outdoor/indoor/dungeon ×
time-of-day swatch sheet.

Images are cached under .devtools/gfx-renders/ and only re-rendered when their
source files (tileset bins / gfx / bg.pal) are newer than the cache.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw

from ..shared import paths
from ..shared.render import PALETTE_TABLES, palettes_for_table, render_tileset_sheet
from ..shared.viewer import TOD_MAP, TOD_NAMES, is_stale, open_images, parse_tileset_id


def _all_tileset_ids(root: Path) -> list[int]:
    """Every tileset id present under tilesets/ (from *_metatiles.bin[.lz])."""
    ids: set[int] = set()
    for p in (root / "tilesets").glob("*_metatiles.bin*"):
        stem = p.name.split("_", 1)[0]
        if stem.isdigit():
            ids.add(int(stem))
    return sorted(ids)


def _tileset_sources(root: Path, tileset_id: int) -> list[Path]:
    """Files render_tileset_sheet reads — used for cache-staleness checks."""
    tid = f"{tileset_id:02d}"
    return [
        root / "tilesets" / f"{tid}_metatiles.bin",
        root / "tilesets" / f"{tid}_metatiles.bin.lz",
        root / "tilesets" / f"{tid}_attributes.bin",
        root / "tilesets" / f"{tid}_attributes.bin.lz",
        root / "gfx" / "tilesets" / f"{tid}.2bpp",
        root / "gfx" / "tilesets" / f"{tid}.2bpp.lz",
        root / "gfx" / "tilesets" / f"{tid}.png",
        root / "tilesets" / "bg.pal",
    ]


def _render_tileset(
    root: Path, cache_dir: Path, tileset_id: int, table: str, tod: int, force: bool
) -> Path:
    cache_file = cache_dir / f"tileset_{tileset_id:02d}_{table}_{TOD_NAMES[tod]}.png"
    if is_stale(cache_file, _tileset_sources(root, tileset_id), force):
        palettes = palettes_for_table(root, table, tod)
        img = render_tileset_sheet(root, tileset_id, palettes)
        img.save(str(cache_file))
    return cache_file


def _draw_palette_sheet(root: Path) -> Image.Image:
    """Swatch sheet of every BG palette table × time-of-day (8 palettes × 4 colors)."""
    sw = 20            # one color swatch
    pal_w = 4 * sw     # one palette = 4 colors in a row
    pal_gap = 10
    label_w = 140
    row_h = sw + 14
    top = 30
    n_cols = 8         # 8 palettes per set

    rows = [(table, tod) for table in PALETTE_TABLES for tod in range(4)]
    content_w = n_cols * pal_w + (n_cols - 1) * pal_gap
    width = label_w + content_w + 20
    height = top + len(rows) * row_h + 10

    img = Image.new("RGB", (width, height), (24, 24, 24))
    draw = ImageDraw.Draw(img)

    for c in range(n_cols):
        x = label_w + c * (pal_w + pal_gap)
        draw.text((x, 10), f"pal {c}", fill=(200, 200, 200))

    for r, (table, tod) in enumerate(rows):
        y = top + r * row_h
        draw.text((8, y + sw // 2 - 6), f"{table} {TOD_NAMES[tod]}", fill=(230, 230, 230))
        for c, pal in enumerate(palettes_for_table(root, table, tod)):
            x0 = label_w + c * (pal_w + pal_gap)
            for k, color in enumerate(pal):
                x = x0 + k * sw
                draw.rectangle([x, y, x + sw - 1, y + sw - 1], fill=tuple(color))
    return img


def _render_palettes(root: Path, cache_dir: Path, force: bool) -> Path:
    cache_file = cache_dir / "palettes.png"
    if is_stale(cache_file, [root / "tilesets" / "bg.pal"], force):
        _draw_palette_sheet(root).save(str(cache_file))
    return cache_file


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="prism-gfx",
        description="Visualize tilesets and BG palettes for picking prism-mapview args.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    pt = sub.add_parser("tileset", help="Render a tileset's 256 metatile blocks.")
    pt.add_argument("tileset_id", type=parse_tileset_id, metavar="N", nargs="?",
                    help="Tileset id (decimal or 0x-hex, e.g. 45 or 0x2D). "
                         "Omit to render every tileset.")
    pt.add_argument("--palette", choices=PALETTE_TABLES, default="outdoor",
                    help="BG palette table to color the sheet with (default: outdoor).")
    pt.add_argument("--time", choices=list(TOD_MAP), default="day",
                    help="Time of day for palette selection (default: day).")
    pt.add_argument("--force", action="store_true", help="Re-render even if cache is fresh.")

    pp = sub.add_parser("palettes", help="Render the outdoor/indoor/dungeon swatch sheet.")
    pp.add_argument("--force", action="store_true", help="Re-render even if cache is fresh.")

    args = parser.parse_args()

    try:
        root = paths.repo_root()
    except paths.RepoNotFound as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)

    cache_dir = root / ".devtools" / "gfx-renders"
    cache_dir.mkdir(parents=True, exist_ok=True)

    if args.cmd == "tileset":
        tod = TOD_MAP[args.time]
        if args.tileset_id is not None:
            ids = [args.tileset_id]
        else:
            ids = _all_tileset_ids(root)
            if not ids:
                print("No tilesets found under tilesets/.", file=sys.stderr)
                sys.exit(1)
        outputs = []
        errors = 0
        for tid in ids:
            try:
                outputs.append(_render_tileset(root, cache_dir, tid, args.palette, tod, args.force))
            except Exception as e:
                print(f"  Warning: tileset {tid}: {e}", file=sys.stderr)
                errors += 1
        if len(ids) > 1:
            print(f"  {len(outputs)}/{len(ids)} tilesets rendered")
        if not outputs:
            sys.exit(1)
        open_images(outputs)
        if errors:
            print(f"{errors} tileset(s) failed to render.", file=sys.stderr)
    else:  # palettes
        out = _render_palettes(root, cache_dir, args.force)
        open_images([out])
