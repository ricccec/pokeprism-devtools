#!/usr/bin/env python3
"""CLI for RGBDS link-map analysis.

Usage:
    prism-usage                              # summary (default)
    prism-usage banks [--region R]           # ANSI bar chart
    prism-usage bank N                       # section breakdown of one bank
    prism-usage largest [-n N]               # top-N sections by size
    prism-usage free [--region R]            # banks sorted by free space
    prism-usage section NAME                 # find a section by name
    prism-usage check [--max-bank-usage P]   # exit 1 if any bank exceeds P%
    prism-usage diff OLD.map NEW.map         # per-bank/section deltas
"""

from __future__ import annotations

import argparse
import datetime
import os
import sys
from pathlib import Path

from pokeprism_devtools import paths
from pokeprism_devtools.mapfile import MapFile


def _color() -> bool:
    return sys.stdout.isatty() and "NO_COLOR" not in os.environ


def _red(s: str, c: bool) -> str:
    return f"\033[31m{s}\033[0m" if c else s


def _yellow(s: str, c: bool) -> str:
    return f"\033[33m{s}\033[0m" if c else s


def _green(s: str, c: bool) -> str:
    return f"\033[32m{s}\033[0m" if c else s


def _fmt(n: int) -> str:
    return f"{n:,}"


def _load(args: argparse.Namespace) -> tuple[MapFile, Path]:
    try:
        if getattr(args, "map", None):
            p = Path(args.map)
            if not p.exists():
                print(f"error: {p}: file not found", file=sys.stderr)
                sys.exit(2)
        else:
            p = paths.map_path(debug=getattr(args, "debug", False))
    except (paths.RepoNotFound, FileNotFoundError) as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(2)
    try:
        return MapFile.parse(p), p
    except (OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(2)


def _parse_bank_number(raw: str) -> int:
    if raw.startswith("$"):
        return int(raw[1:], 16)
    if raw.lower().startswith("0x"):
        return int(raw, 16)
    if any(c in "abcdefABCDEF" for c in raw):
        return int(raw, 16)
    return int(raw, 10)


# ---------------------------------------------------------------------------

def cmd_summary(mp: MapFile, map_path: Path, args: argparse.Namespace) -> int:
    c = _color()
    mtime = datetime.datetime.fromtimestamp(map_path.stat().st_mtime)
    print(f"{map_path.name}   (built: {mtime:%Y-%m-%d %H:%M:%S})\n")

    rom = mp.rom_banks()
    rom_cap = sum(b.capacity for b in rom)
    rom_used = sum(b.used for b in rom)
    rom_free = sum(b.free for b in rom)
    pct = rom_used / rom_cap * 100 if rom_cap else 0.0
    print(f"ROM     {_fmt(rom_used)} / {_fmt(rom_cap)} bytes used   ({pct:.1f}%)")
    print(f"        {_fmt(rom_free)} free across {len(rom)} banks\n")

    for region in ("WRAMX", "WRAM0", "SRAM", "HRAM", "VRAM"):
        rbanks = mp.banks_by_region(region)
        if not rbanks:
            continue
        cap = sum(b.capacity for b in rbanks)
        used = sum(b.used for b in rbanks)
        p2 = used / cap * 100 if cap else 0.0
        print(f"{region:<7} {_fmt(used)} / {_fmt(cap)} bytes used   ({p2:.1f}%)")
    print()

    n = 5
    most_full = sorted(rom, key=lambda b: b.free)[:n]
    print(f"Most-full ROM banks (top {n})")
    for b in most_full:
        p2 = b.utilization * 100
        free_s = f"{b.free:,} byte{'s' if b.free != 1 else ''} free"
        line = f"  Bank ${b.number:02x}   {free_s}   {p2:.2f}%"
        if p2 >= 99:
            line = _red(line, c)
        elif p2 >= 95:
            line = _yellow(line, c)
        print(line)
    print()

    most_free = sorted(rom, key=lambda b: b.free, reverse=True)[:n]
    print(f"Most-free ROM banks (top {n})")
    for b in most_free:
        p2 = b.utilization * 100
        print(f"  Bank ${b.number:02x}   {_fmt(b.free)} bytes free   {p2:.1f}% used")
    return 0


def cmd_banks(mp: MapFile, args: argparse.Namespace) -> int:
    c = _color()
    region = getattr(args, "region", None)
    banks = mp.banks_by_region(region) if region else mp.rom_banks()
    if not banks:
        print(f"no banks in region {(region or 'ROM').upper()}", file=sys.stderr)
        return 1
    for b in banks:
        filled = round(b.utilization * 16)
        bar = "█" * filled + "░" * (16 - filled)
        p2 = b.utilization * 100
        if c:
            if p2 >= 95:
                bar = _red(bar, c)
            elif p2 >= 80:
                bar = _yellow(bar, c)
            else:
                bar = _green(bar, c)
        print(f"Bank ${b.number:02x}  {bar}  {p2:3.0f}%  {_fmt(b.free)} free")
    return 0


def cmd_bank(mp: MapFile, args: argparse.Namespace) -> int:
    try:
        n = _parse_bank_number(args.n)
    except ValueError:
        print(f"error: invalid bank number '{args.n}'", file=sys.stderr)
        return 2

    bank = mp.banks.get(("ROMX", n)) or mp.banks.get(("ROM0", n))
    if bank is None:
        for b in mp.banks.values():
            if b.number == n:
                bank = b
                break
    if bank is None:
        print(f"no bank #{n} ({n:#x}) found", file=sys.stderr)
        return 1

    p2 = bank.utilization * 100
    print(f"Bank ${bank.number:02x} ({bank.region})")
    print(f"  Used: {_fmt(bank.used)} / {_fmt(bank.capacity)} bytes   ({p2:.1f}%)")
    free_s = f"{_fmt(bank.free)} byte{'s' if bank.free != 1 else ''}"
    print(f"  Free: {free_s}\n")
    if bank.sections:
        print("Sections")
        for s in bank.sections:
            print(f"  ${s.start:04x}–${s.end:04x}  ${s.size:04x} bytes  {s.name}")
    else:
        print("  (no sections)")
    return 0


def cmd_largest(mp: MapFile, args: argparse.Namespace) -> int:
    n = getattr(args, "n", 20)
    sections = sorted(mp.all_sections(), key=lambda s: s.size, reverse=True)
    if n > 0:
        sections = sections[:n]
    if not sections:
        print("no sections found", file=sys.stderr)
        return 1
    w = max(len(s.name) for s in sections)
    print(f"{'Section':<{w}}   {'Size':>7}   Bank")
    for s in sections:
        print(f"{s.name:<{w}}   {_fmt(s.size):>7}   ${s.bank:02x}")
    return 0


def cmd_free(mp: MapFile, args: argparse.Namespace) -> int:
    region = getattr(args, "region", None)
    banks = mp.banks_by_region(region) if region else mp.rom_banks()
    banks = sorted(banks, key=lambda b: b.free, reverse=True)
    if not banks:
        print("no banks found", file=sys.stderr)
        return 1
    for b in banks:
        print(f"Bank ${b.number:02x}   {_fmt(b.free):>7} bytes free   {b.region}")
    return 0


def cmd_section(mp: MapFile, args: argparse.Namespace) -> int:
    results = mp.find_section(args.name)
    if not results:
        print(f"no section matching '{args.name}'", file=sys.stderr)
        return 1
    w = max(len(s.name) for s in results)
    for s in results:
        print(f"{s.name:<{w}}   ${s.bank:02x}   {_fmt(s.size):>7} bytes")
    total = sum(s.size for s in results)
    nbanks = len({s.bank for s in results})
    print(
        f"\nTotal: {len(results)} occurrence{'s' if len(results) != 1 else ''}, "
        f"{_fmt(total)} bytes across {nbanks} bank{'s' if nbanks != 1 else ''}"
    )
    return 0


def cmd_check(mp: MapFile, args: argparse.Namespace) -> int:
    c = _color()
    threshold = getattr(args, "max_bank_usage", 95.0)
    failures = [b for b in mp.rom_banks() if b.utilization * 100 > threshold]
    if not failures:
        return 0
    for b in sorted(failures, key=lambda b: b.utilization, reverse=True):
        p2 = b.utilization * 100
        print(_red(f"ERROR: Bank ${b.number:02x} exceeds threshold", c))
        print(f"  Usage: {p2:.2f}%   (limit: {threshold}%)")
        print(f"  Used:  {_fmt(b.used)} / {_fmt(b.capacity)} bytes\n")
    return 1


def cmd_diff(args: argparse.Namespace) -> int:
    c = _color()
    threshold = getattr(args, "max_bank_usage", 95.0)

    def load_path(raw: str) -> MapFile:
        p = Path(raw)
        if not p.exists():
            print(f"error: {p}: file not found", file=sys.stderr)
            sys.exit(2)
        try:
            return MapFile.parse(p)
        except (OSError, ValueError) as e:
            print(f"error: {e}", file=sys.stderr)
            sys.exit(2)

    old = load_path(args.old_map)
    new = load_path(args.new_map)

    old_rom = old.rom_banks()
    new_rom = new.rom_banks()
    old_cap = sum(b.capacity for b in old_rom)
    new_cap = sum(b.capacity for b in new_rom)
    if old_cap and new_cap:
        old_used = sum(b.used for b in old_rom)
        new_used = sum(b.used for b in new_rom)
        delta = (new_used / new_cap - old_used / old_cap) * 100
        sign = "+" if delta >= 0 else ""
        print(f"ROM utilization:  {sign}{delta:.1f}%   ({_fmt(old_used)} → {_fmt(new_used)})\n")

    all_keys = set(old.banks) | set(new.banks)
    bank_deltas = []
    for key in all_keys:
        ob = old.banks.get(key)
        nb = new.banks.get(key)
        if ob and nb:
            d = nb.used - ob.used
            if d != 0:
                bank_deltas.append((key, ob, nb, d))

    if bank_deltas:
        print("Banks")
        for (region, number), ob, nb, d in sorted(bank_deltas, key=lambda x: abs(x[3]), reverse=True):
            sign = "+" if d >= 0 else ""
            warn = ""
            if nb.utilization * 100 > threshold:
                warn = "  " + _yellow(f"⚠ {nb.utilization * 100:.2f}%", c)
            print(f"  Bank ${number:02x}   {sign}{_fmt(d)} bytes used{warn}")
        print()

    old_secs = {s.name: s for s in old.all_sections()}
    new_secs = {s.name: s for s in new.all_sections()}
    changed = [
        (name, old_secs[name].size, new_secs[name].size, new_secs[name].size - old_secs[name].size)
        for name in old_secs
        if name in new_secs and old_secs[name].size != new_secs[name].size
    ]
    if changed:
        print("Sections")
        w = max(len(name) for name, *_ in changed)
        for name, old_sz, new_sz, d in sorted(changed, key=lambda x: abs(x[3]), reverse=True):
            sign = "+" if d >= 0 else ""
            print(f"  {name:<{w}}   {sign}{_fmt(d)}   {_fmt(old_sz)} → {_fmt(new_sz)}")
        print()

    added = [s for name, s in new_secs.items() if name not in old_secs]
    removed = [s for name, s in old_secs.items() if name not in new_secs]
    print(f"New sections   ({len(added)})")
    for s in sorted(added, key=lambda x: x.size, reverse=True):
        print(f"  {s.name}  ${s.bank:02x}  +{_fmt(s.size)}")
    if added:
        print()
    print(f"Removed sections   ({len(removed)})")
    for s in removed:
        print(f"  {s.name}  ${s.bank:02x}  -{_fmt(s.size)}")
    return 0


# ---------------------------------------------------------------------------

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
    pb.add_argument("--region", help="show a RAM region instead of ROM (e.g. SRAM, WRAMX)")

    pbn = sub.add_parser("bank", help="section breakdown of one bank")
    pbn.add_argument("n", help="bank number: decimal 23, hex $17 / 0x17 / 17")

    pl = sub.add_parser("largest", help="top-N sections by size")
    pl.add_argument("-n", type=int, default=20, metavar="N",
                    help="how many to show, 0=all (default: 20)")

    pf = sub.add_parser("free", help="banks sorted by free space (descending)")
    pf.add_argument("--region", help="show a RAM region instead of ROM")

    ps = sub.add_parser("section", help="find a section by name")
    ps.add_argument("name", help="section name (exact match first, then substring)")

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
