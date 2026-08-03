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


def cmd_diff(args: argparse.Namespace) -> int:
    c = _color()
    threshold = getattr(args, "max_bank_usage", 95.0)

    def load_path(raw: str) -> MapFile:
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
