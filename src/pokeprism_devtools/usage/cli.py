"""The `prism-usage` command line."""

from __future__ import annotations

import argparse
import sys

from .diffreport import cmd_diff
from .maploader import _load
from .reports import (
    cmd_bank, cmd_banks, cmd_check, cmd_free, cmd_largest, cmd_section,
    cmd_summary,
)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="prism-usage",
        description="Analyze RGBDS link-map bank usage.",
    )
    p.add_argument("--debug", action="store_true", help="use debug ROM's .map")
    p.add_argument("--map", metavar="PATH", help="override auto-located .map file")

    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("summary", help="headline stats (default)")

    pb = sub.add_parser("banks", help="ANSI bar chart of bank occupancy")
    pb.add_argument("numbers", nargs="*", metavar="N",
                    help="bank numbers/ranges to show, e.g. 5 12 $1a 10-20 (default: all banks in region)")
    pb.add_argument("--region", help="show a RAM region instead of ROM (e.g. SRAM, WRAMX)")

    pbn = sub.add_parser("bank", help="section breakdown of one or more banks")
    pbn.add_argument("n", nargs="+", metavar="N",
                    help="bank number(s)/range(s): decimal 23, hex $17 / 0x17 / 17, or range 10-20")

    pl = sub.add_parser("largest", help="top-N sections by size")
    pl.add_argument("-n", type=int, default=20, metavar="N",
                    help="how many to show, 0=all (default: 20)")

    pf = sub.add_parser("free", help="banks sorted by free space (descending)")
    pf.add_argument("--region", help="show a RAM region instead of ROM")

    ps = sub.add_parser("section", help="find section(s) by name")
    ps.add_argument("names", nargs="+", metavar="NAME",
                    help="section name(s) (exact match first, then substring); repeat to search several")

    pc = sub.add_parser("check", help="exit 1 if any ROM bank exceeds threshold")
    pc.add_argument("--max-bank-usage", type=float, default=95.0, metavar="P",
                    help="threshold %% (default: 95)")

    pd = sub.add_parser("diff", help="per-bank/section deltas between two .map files")
    pd.add_argument("old_map", help="old .map file")
    pd.add_argument("new_map", help="new .map file")
    pd.add_argument("--max-bank-usage", type=float, default=95.0, metavar="P",
                    help="threshold for ⚠ warning (default: 95)")

    args = p.parse_args(argv)

    if args.cmd == "diff":
        return cmd_diff(args)

    mp, map_path = _load(args)

    if args.cmd is None or args.cmd == "summary":
        return cmd_summary(mp, map_path, args)
    if args.cmd == "banks":
        return cmd_banks(mp, args)
    if args.cmd == "bank":
        return cmd_bank(mp, args)
    if args.cmd == "largest":
        return cmd_largest(mp, args)
    if args.cmd == "free":
        return cmd_free(mp, args)
    if args.cmd == "section":
        return cmd_section(mp, args)
    if args.cmd == "check":
        return cmd_check(mp, args)

    p.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
