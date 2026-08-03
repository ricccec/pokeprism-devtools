"""The `prism-map` command line."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..hacks.prism import blocksrc
from ..shared import paths
from .blobreport import _load_mapfile, _print_report, gather_blobs
from .grid import ZOOMS, print_grid
from .mapheader import MapNotFound, build_spec


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="prism-map",
        description="Inspect one map and optionally export its prism-mapfit spec.")
    p.add_argument("label", help="the map's CamelCase label, e.g. MtEmberSmallRoom")
    p.add_argument("--grid", action="store_true",
                   help="draw the map's blocks and everything placed on them (no ROM needed)")
    p.add_argument("--zoom", type=int, choices=ZOOMS,
                   help="columns per coordinate tile (default: the biggest that fits)")
    p.add_argument("--time-of-day", type=int, default=1, choices=(0, 1, 2, 3),
                   help="palette for --grid: 0=morn 1=day 2=nite 3=dark (default: 1)")
    p.add_argument("--toml", action="store_true", help="emit the spec TOML")
    p.add_argument("-o", "--out", metavar="FILE", help="write the spec TOML to FILE (implies --toml)")
    p.add_argument("--map", metavar="PATH", help="override the .map used for bank info")
    args = p.parse_args(argv)

    try:
        root = paths.repo_root()
        spec = build_spec(root, args.label)
    except (paths.RepoNotFound, MapNotFound) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if args.grid:
        try:
            print_grid(root, args.label, args.time_of_day, args.zoom)
        except blocksrc.BlockSourceError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        return 0

    if args.out or args.toml:
        toml = spec.to_toml()
        if args.out:
            Path(args.out).write_text(toml)
            print(f"wrote {args.out}", file=sys.stderr)
        else:
            sys.stdout.write(toml)
        return 0

    mp = _load_mapfile(args)
    blobs = gather_blobs(root, spec, mp)
    _print_report(spec, blobs, mp)
    return 0
