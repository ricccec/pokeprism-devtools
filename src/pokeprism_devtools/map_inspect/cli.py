"""The `prism-maps` command line."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict

from ..shared.paths import RepoNotFound, repo_root
from .mapinfo import _NULLABLE_SORTS, _SORT_KEYS, collect
from .table import render_table


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
