"""The seven reports that read one link map.

Each returns a process exit code, and each prints rather than returns its text —
`check` is meant to be run in a build, so "did anything overflow?" has to be
answerable without reading stdout.
"""

from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path

from ..shared.mapfile import MapFile
from .ansi import _color, _fmt, _green, _red, _yellow
from .bankselector import parse_bank_selectors

#: Percent-full at which `check` fails a build. Defined once here and read by
#: both argparse defaults and both commands that take the flag, so there is one
#: answer to "what counts as too full?" rather than a default and a fallback
#: that could drift apart.
DEFAULT_MAX_BANK_USAGE = 95.0

#: The bar in `banks` is 16 cells wide, and changes colour as it fills.
_BAR_CELLS = 16
_BAR_RED_AT = 95      # percent full
_BAR_YELLOW_AT = 80


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
    numbers = getattr(args, "numbers", None)
    if numbers:
        try:
            wanted = set(parse_bank_selectors(numbers))
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        banks = [b for b in banks if b.number in wanted]
    if not banks:
        print(f"no banks in region {(region or 'ROM').upper()}", file=sys.stderr)
        return 1
    for b in banks:
        p2 = b.utilization * 100
        bar = _render_bar(b.utilization, c)
        print(f"Bank ${b.number:02x}  {bar}  {p2:3.0f}%  {_fmt(b.free)} free")
    return 0


def _render_bar(utilization: float, c) -> str:
    """The occupancy bar, coloured by how full the bank is."""
    filled = round(utilization * _BAR_CELLS)
    bar = "█" * filled + "░" * (_BAR_CELLS - filled)
    if not c:
        return bar
    pct = utilization * 100
    if pct >= _BAR_RED_AT:
        return _red(bar, c)
    if pct >= _BAR_YELLOW_AT:
        return _yellow(bar, c)
    return _green(bar, c)


def cmd_bank(mp: MapFile, args: argparse.Namespace) -> int:
    try:
        numbers = parse_bank_selectors(args.n)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    exit_code = 0
    printed = 0
    for n in numbers:
        bank = _find_bank(mp, n)
        if bank is None:
            print(f"no bank #{n} ({n:#x}) found", file=sys.stderr)
            exit_code = 1
            continue
        if printed:
            print()
        printed += 1
        _print_bank(bank)
    return exit_code


def _find_bank(mp: MapFile, n: int):
    """The bank numbered *n*, preferring ROM before any other region.

    A number alone is ambiguous — WRAMX and SRAM have a bank 1 too — so ROMX
    and ROM0 are tried by name first, and only then does any region answer.
    """
    bank = mp.banks.get(("ROMX", n)) or mp.banks.get(("ROM0", n))
    if bank is not None:
        return bank
    return next((b for b in mp.banks.values() if b.number == n), None)


def _print_bank(bank) -> None:
    p2 = bank.utilization * 100
    print(f"Bank ${bank.number:02x} ({bank.region})")
    print(f"  Used: {_fmt(bank.used)} / {_fmt(bank.capacity)} bytes   ({p2:.1f}%)")
    free_s = f"{_fmt(bank.free)} byte{'s' if bank.free != 1 else ''}"
    print(f"  Free: {free_s}\n")
    if not bank.sections:
        print("  (no sections)")
        return
    print("Sections")
    for s in bank.sections:
        print(f"  ${s.start:04x}–${s.end:04x}  ${s.size:04x} bytes  {s.name}")


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
    results = []
    any_found = False
    for name in args.names:
        matches = mp.find_section(name)
        if not matches:
            print(f"no section matching '{name}'", file=sys.stderr)
            continue
        any_found = True
        results.extend(matches)
    if not any_found:
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
    threshold = getattr(args, "max_bank_usage", DEFAULT_MAX_BANK_USAGE)
    failures = [b for b in mp.rom_banks() if b.utilization * 100 > threshold]
    if not failures:
        return 0
    for b in sorted(failures, key=lambda b: b.utilization, reverse=True):
        p2 = b.utilization * 100
        print(_red(f"ERROR: Bank ${b.number:02x} exceeds threshold", c))
        print(f"  Usage: {p2:.2f}%   (limit: {threshold}%)")
        print(f"  Used:  {_fmt(b.used)} / {_fmt(b.capacity)} bytes\n")
    return 1
