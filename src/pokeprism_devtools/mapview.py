"""prism-mapview — render and open map images.

Usage:
    prism-mapview [MAP_NAME [MAP_NAME ...]] [--time {morn,day,nite,dark}] [--force]

With no MAP_NAME, renders all maps and opens them all.
With one or more MAP_NAMEs, renders those maps and opens them all at once
(macOS Preview opens them in a sidebar; use arrow keys to navigate).
Images are cached as .devtools/map-renders/<mapname>_<tod>.bmp and only
re-rendered when the ROM is newer than the cache.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import maps, paths, symfile
from .render import PALETTE_TABLES, render_map
from .viewer import TOD_MAP, TOD_NAMES, open_images, parse_tileset_id


def _normalize(name: str) -> str:
    return name.lower().replace("_", "").replace(" ", "")


def _find_map(all_maps: list, query: str):
    norm = _normalize(query)
    for m in all_maps:
        if _normalize(m.name) == norm:
            return m
    # Fallback: substring match
    matches = [m for m in all_maps if norm in _normalize(m.name)]
    if len(matches) == 1:
        return matches[0]
    if matches:
        names = ", ".join(m.name for m in matches[:5])
        print(f"Ambiguous map name '{query}'. Matches: {names}", file=sys.stderr)
        sys.exit(1)
    print(f"Map '{query}' not found.", file=sys.stderr)
    sys.exit(1)


def _cache_path(
    cache_dir: Path,
    map_name: str,
    tod: int,
    tileset_id: int | None = None,
    palette_table: str | None = None,
) -> Path:
    # No-override renders keep the original `<name>_<tod>.bmp` form (and cache).
    # Overrides are encoded in the name and use .png so combos never collide.
    if tileset_id is None and palette_table is None:
        return cache_dir / f"{map_name.lower()}_{TOD_NAMES[tod]}.bmp"
    suffix = ""
    if tileset_id is not None:
        suffix += f"_ts{tileset_id:02d}"
    if palette_table is not None:
        suffix += f"_pal{palette_table}"
    return cache_dir / f"{map_name.lower()}_{TOD_NAMES[tod]}{suffix}.png"


def _needs_render(cache_file: Path, rom: Path, force: bool) -> bool:
    if force:
        return True
    if not cache_file.exists():
        return True
    return cache_file.stat().st_mtime < rom.stat().st_mtime


def _render_one(
    root, rom, syms, m, cache_dir, tod, force,
    tileset_id: int | None = None,
    palette_table: str | None = None,
) -> Path:
    cache_file = _cache_path(cache_dir, m.name, tod, tileset_id, palette_table)
    if _needs_render(cache_file, rom, force):
        img = render_map(
            root, rom, syms, m.group, m.map_id, name=m.name, time_of_day=tod,
            tileset_id=tileset_id, palette_table=palette_table,
        )
        img.save(str(cache_file))
    return cache_file


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="prism-mapview",
        description="Render a Pokémon Prism map to an image and open it.",
    )
    parser.add_argument("map_names", nargs="*", metavar="MAP_NAME",
                        help="Map name(s) (case-insensitive). Omit to render all.")
    parser.add_argument("--time", choices=list(TOD_MAP), default="day",
                        help="Time of day for palette selection (default: day).")
    parser.add_argument("--tileset", type=parse_tileset_id, metavar="N",
                        help="Override the graphics tileset (decimal or 0x-hex), "
                             "instead of the map's own. See `prism-gfx tileset`.")
    parser.add_argument("--palette", choices=PALETTE_TABLES,
                        help="Override the BG palette table, instead of deriving it "
                             "from the map's permission.")
    parser.add_argument("--force", action="store_true", help="Re-render even if cache is fresh.")
    args = parser.parse_args()

    try:
        root = paths.repo_root()
        rom = paths.rom_path(root)
        sym = paths.sym_path(root)
    except (paths.RepoNotFound, FileNotFoundError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)

    syms = symfile.SymFile.load(sym)
    tod = TOD_MAP[args.time]
    cache_dir = root / ".devtools" / "map-renders"
    cache_dir.mkdir(parents=True, exist_ok=True)

    all_maps = maps.parse_maps(root / "constants" / "map_dimension_constants.asm")

    if args.map_names:
        targets = [_find_map(all_maps, name) for name in args.map_names]
        outputs = []
        for m in targets:
            try:
                outputs.append(_render_one(root, rom, syms, m, cache_dir, tod, args.force,
                                           args.tileset, args.palette))
            except Exception as e:
                print(f"Error rendering {m.name}: {e}", file=sys.stderr)
                sys.exit(1)
        open_images(outputs)
    else:
        outputs = []
        errors = 0
        for i, m in enumerate(all_maps):
            try:
                outputs.append(_render_one(root, rom, syms, m, cache_dir, tod, args.force,
                                           args.tileset, args.palette))
                if (i + 1) % 50 == 0 or (i + 1) == len(all_maps):
                    print(f"  {i + 1}/{len(all_maps)} maps rendered")
            except Exception as e:
                print(f"  Warning: {m.name}: {e}", file=sys.stderr)
                errors += 1
        open_images(outputs)
        if errors:
            print(f"{errors} map(s) failed to render.", file=sys.stderr)
