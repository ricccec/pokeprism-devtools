"""Shared helpers for the image-rendering CLIs (prism-mapview, prism-gfx):
time-of-day name maps, tileset-id parsing, and opening images in the OS viewer.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

TOD_MAP = {"morn": 0, "day": 1, "nite": 2, "dark": 3}
TOD_NAMES = {0: "morn", 1: "day", 2: "nite", 3: "dark"}


def parse_tileset_id(value: str) -> int:
    """Parse a tileset id given as decimal or 0x-hex (e.g. '45' or '0x2D')."""
    try:
        n = int(value, 0)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"invalid tileset id {value!r} (use decimal or 0x-hex)"
        ) from exc
    if n < 0:
        raise argparse.ArgumentTypeError("tileset id must be non-negative")
    return n


def max_mtime(candidates: list[Path]) -> float:
    """Newest mtime among the candidate paths that exist (0.0 if none)."""
    times = [p.stat().st_mtime for p in candidates if p.exists()]
    return max(times) if times else 0.0


def is_stale(cache_file: Path, sources: list[Path], force: bool) -> bool:
    """True if the cache is missing, forced, or older than any source file."""
    if force or not cache_file.exists():
        return True
    return cache_file.stat().st_mtime < max_mtime(sources)


def open_images(paths_list: list[Path]) -> None:
    """Open one or more images in the platform's default viewer."""
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
