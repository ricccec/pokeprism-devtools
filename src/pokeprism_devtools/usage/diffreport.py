"""What changed between two link maps.

The only command that reads two `.map` files, and so the only one that loads
them itself rather than taking the one the CLI already found.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..shared.mapfile import MapFile
from .ansi import _color, _fmt, _yellow
from .maploader import _fill_cartridge_banks
from .reports import DEFAULT_MAX_BANK_USAGE


def _load_map_file(raw: str) -> MapFile:
    """Parse one of the two .map files, reporting rather than raising.

    This command is given paths by the user instead of finding one itself, so
    a missing or malformed file is a boundary error and exits 2.
    """
    p = Path(raw)
    if not p.exists():
        print(f"error: {p}: file not found", file=sys.stderr)
        sys.exit(2)
    try:
        mp = MapFile.parse(p)
    except (OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(2)
    _fill_cartridge_banks(mp, p)
    return mp


def _print_rom_utilization(old: MapFile, new: MapFile) -> None:
    old_rom, new_rom = old.rom_banks(), new.rom_banks()
    old_cap = sum(b.capacity for b in old_rom)
    new_cap = sum(b.capacity for b in new_rom)
    if not (old_cap and new_cap):
        return
    old_used = sum(b.used for b in old_rom)
    new_used = sum(b.used for b in new_rom)
    delta = (new_used / new_cap - old_used / old_cap) * 100
    sign = "+" if delta >= 0 else ""
    print(f"ROM utilization:  {sign}{delta:.1f}%   ({_fmt(old_used)} → {_fmt(new_used)})\n")


def _print_bank_deltas(old: MapFile, new: MapFile, threshold: float) -> None:
    """Banks whose used bytes moved, biggest change first."""
    deltas = []
    for key in set(old.banks) | set(new.banks):
        ob, nb = old.banks.get(key), new.banks.get(key)
        if ob and nb and nb.used != ob.used:
            deltas.append((key, nb, nb.used - ob.used))
    if not deltas:
        return

    c = _color()
    print("Banks")
    for (_region, number), nb, d in sorted(deltas, key=lambda x: abs(x[2]), reverse=True):
        sign = "+" if d >= 0 else ""
        warn = ""
        if nb.utilization * 100 > threshold:
            warn = "  " + _yellow(f"⚠ {nb.utilization * 100:.2f}%", c)
        print(f"  Bank ${number:02x}   {sign}{_fmt(d)} bytes used{warn}")
    print()


def _print_section_deltas(old_secs: dict, new_secs: dict) -> None:
    """Sections present in both whose size moved, biggest change first."""
    changed = [
        (name, old_secs[name].size, new_secs[name].size,
         new_secs[name].size - old_secs[name].size)
        for name in old_secs
        if name in new_secs and old_secs[name].size != new_secs[name].size
    ]
    if not changed:
        return
    print("Sections")
    w = max(len(name) for name, *_ in changed)
    for name, old_sz, new_sz, d in sorted(changed, key=lambda x: abs(x[3]), reverse=True):
        sign = "+" if d >= 0 else ""
        print(f"  {name:<{w}}   {sign}{_fmt(d)}   {_fmt(old_sz)} → {_fmt(new_sz)}")
    print()


def _print_added_and_removed(old_secs: dict, new_secs: dict) -> None:
    """Both counts always print, including zero — "New sections (0)" is the
    answer to "did my edit add a section?", and a silent section is not."""
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


def cmd_diff(args: argparse.Namespace) -> int:
    threshold = getattr(args, "max_bank_usage", DEFAULT_MAX_BANK_USAGE)
    old = _load_map_file(args.old_map)
    new = _load_map_file(args.new_map)

    _print_rom_utilization(old, new)
    _print_bank_deltas(old, new, threshold)

    old_secs = {s.name: s for s in old.all_sections()}
    new_secs = {s.name: s for s in new.all_sections()}
    _print_section_deltas(old_secs, new_secs)
    _print_added_and_removed(old_secs, new_secs)
    return 0
