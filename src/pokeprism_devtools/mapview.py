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
import os
import subprocess
import sys
from pathlib import Path

from . import maps, paths, symfile
from .render import render_map

_TOD_MAP = {"morn": 0, "day": 1, "nite": 2, "dark": 3}


def _open_images(paths_list: list[Path]) -> None:
    if not paths_list:
        return
    if sys.platform == "darwin":
        subprocess.run(["open"] + [str(p) for p in paths_list], check=False)
    elif sys.platform.startswith("linux"):
        for p in paths_list:
            subprocess.run(["xdg-open", str(p)], check=False)
    else:
        for p in paths_list:
            os.startfile(str(p))  # type: ignore[attr-defined]


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


_TOD_NAMES = {0: "morn", 1: "day", 2: "nite", 3: "dark"}


def _cache_path(cache_dir: Path, map_name: str, tod: int) -> Path:
    return cache_dir / f"{map_name.lower()}_{_TOD_NAMES[tod]}.bmp"


def _needs_render(cache_file: Path, rom: Path, force: bool) -> bool:
    if force:
        return True
    if not cache_file.exists():
        return True
    return cache_file.stat().st_mtime < rom.stat().st_mtime


def _render_one(root, rom, syms, m, cache_dir, tod, force) -> Path:
    cache_file = _cache_path(cache_dir, m.name, tod)
    if _needs_render(cache_file, rom, force):
        img = render_map(root, rom, syms, m.group, m.map_id, name=m.name, time_of_day=tod)
        img.save(str(cache_file))
    return cache_file


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="prism-mapview",
        description="Render a Pokémon Prism map to an image and open it.",
    )
    parser.add_argument("map_names", nargs="*", metavar="MAP_NAME",
                        help="Map name(s) (case-insensitive). Omit to render all.")
    parser.add_argument("--time", choices=list(_TOD_MAP), default="day",
                        help="Time of day for palette selection (default: day).")
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
    tod = _TOD_MAP[args.time]
    cache_dir = root / ".devtools" / "map-renders"
    cache_dir.mkdir(parents=True, exist_ok=True)

    all_maps = maps.parse_maps(root / "constants" / "map_dimension_constants.asm")

    if args.map_names:
        targets = [_find_map(all_maps, name) for name in args.map_names]
        outputs = []
        for m in targets:
            try:
                outputs.append(_render_one(root, rom, syms, m, cache_dir, tod, args.force))
            except Exception as e:
                print(f"Error rendering {m.name}: {e}", file=sys.stderr)
                sys.exit(1)
        _open_images(outputs)
    else:
        outputs = []
        errors = 0
        for i, m in enumerate(all_maps):
            try:
                outputs.append(_render_one(root, rom, syms, m, cache_dir, tod, args.force))
                if (i + 1) % 50 == 0 or (i + 1) == len(all_maps):
                    print(f"  {i + 1}/{len(all_maps)} maps rendered")
            except Exception as e:
                print(f"  Warning: {m.name}: {e}", file=sys.stderr)
                errors += 1
        _open_images(outputs)
        if errors:
            print(f"{errors} map(s) failed to render.", file=sys.stderr)
