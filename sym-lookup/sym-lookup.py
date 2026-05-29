#!/usr/bin/env python3
"""Query the pokeprism .sym file.

Usage:
    sym-lookup LABEL                 # exact match → prints address
    sym-lookup --addr BB:AAAA        # reverse: address → label(s) at or before
    sym-lookup --prefix STR          # all labels starting with STR
    sym-lookup --search STR          # case-insensitive substring search
    sym-lookup --region SRAM STR     # filter prefix/search results by region
                                     # (regions: ROM0, ROMX, VRAM, SRAM, WRAM0,
                                     #  WRAMX, OAM, IO, HRAM, ECHO, UNUSED)

If LABEL is given but no exact match exists, falls back to substring search.

The .sym file is auto-located via the build artifacts. Use --debug to query
the debug ROM's .sym instead of the release ROM's.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _lib import paths, symfile  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="sym-lookup",
        description="Query the pokeprism .sym file by label or address.",
    )
    p.add_argument("query", nargs="?", help="label to look up (exact, then substring)")
    p.add_argument("-a", "--addr", help="reverse lookup: BB:AAAA")
    p.add_argument("-p", "--prefix", help="list labels starting with this string")
    p.add_argument("-s", "--search", help="case-insensitive substring search")
    p.add_argument(
        "-r",
        "--region",
        help="filter results to a region (ROM0, ROMX, VRAM, SRAM, "
        "WRAM0, WRAMX, OAM, IO, HRAM, ECHO, UNUSED)",
    )
    p.add_argument(
        "--debug",
        action="store_true",
        help="use the debug ROM's .sym instead of the release one",
    )
    p.add_argument(
        "-n",
        "--limit",
        type=int,
        default=50,
        help="cap on result count for prefix/search (default: 50)",
    )
    args = p.parse_args(argv)

    try:
        sym_path = paths.sym_path(debug=args.debug)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    syms = symfile.SymFile.load(sym_path)

    if args.addr is not None:
        return _reverse_lookup(syms, args.addr)

    if args.prefix is not None:
        results = syms.find_prefix(args.prefix)
        return _print_results(results, args.region, args.limit)

    if args.search is not None:
        results = syms.find_substring(args.search)
        return _print_results(results, args.region, args.limit)

    if args.query is not None:
        # Exact-match first.
        hit = syms.get(args.query)
        if hit is not None:
            print(hit)
            return 0
        # Fall back to substring search.
        results = syms.find_substring(args.query)
        if not results:
            print(f"no match for '{args.query}'", file=sys.stderr)
            return 1
        return _print_results(results, args.region, args.limit)

    p.print_help()
    return 2


def _reverse_lookup(syms: symfile.SymFile, raw: str) -> int:
    try:
        bank, addr = _parse_address(raw)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    hits = syms.at_or_before(bank, addr)
    if not hits:
        print(f"no symbol at or before {bank:02x}:{addr:04x}", file=sys.stderr)
        return 1
    for s in hits:
        delta = addr - s.addr
        suffix = f"  (+{delta:#x})" if delta else ""
        print(f"{s}{suffix}  [{s.region}]")
    return 0


def _print_results(
    results: list[symfile.Symbol],
    region: str | None,
    limit: int,
) -> int:
    if region:
        wanted = region.upper()
        results = [s for s in results if s.region == wanted]
    if not results:
        print("no matches", file=sys.stderr)
        return 1
    truncated = False
    if limit and len(results) > limit:
        results = results[:limit]
        truncated = True
    for s in results:
        print(f"{s}  [{s.region}]")
    if truncated:
        print(f"... (truncated to {limit}; pass --limit 0 for all)")
    return 0


def _parse_address(raw: str) -> tuple[int, int]:
    if ":" not in raw:
        raise ValueError(
            f"address must be BB:AAAA (bank:address in hex), got '{raw}'"
        )
    bank_s, _, addr_s = raw.partition(":")
    try:
        bank = int(bank_s, 16)
        addr = int(addr_s, 16)
    except ValueError as e:
        raise ValueError(f"invalid hex in '{raw}': {e}") from e
    return bank, addr


if __name__ == "__main__":
    sys.exit(main())
