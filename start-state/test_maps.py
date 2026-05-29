#!/usr/bin/env python3
"""Sweep every map through start-state's apply pipeline.

For each map in inventory.json, runs apply_state + recompute_checksums
against a fresh in-memory copy of the template .sav. Reports which
maps raise (and how). Writes nothing to disk.

Usage:
    test_maps.py                       # all maps, summary + failures only
    test_maps.py --verbose             # also show [OK] lines
    test_maps.py --map NAME            # one specific map
    test_maps.py --limit N             # only the first N
    test_maps.py --show-traceback      # full Python tb on failures
    test_maps.py --x N --y N           # override coords (default 1, 1)
    test_maps.py --keep-people         # skip the people-reset step
    test_maps.py --debug               # use the debug ROM's .sym
"""

from __future__ import annotations

import argparse
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _lib import paths, savefile, symfile  # noqa: E402

import apply  # noqa: E402
import inventory  # noqa: E402

INVENTORY_PATH = Path(__file__).parent / "inventory.json"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="test_maps")
    p.add_argument("--map", help="test only this map name (exact)")
    p.add_argument("--limit", type=int, default=None,
                   help="only test the first N maps (after --map filter)")
    p.add_argument("--x", type=int, default=1, help="x coord (default 1)")
    p.add_argument("--y", type=int, default=1, help="y coord (default 1)")
    p.add_argument("--verbose", "-v", action="store_true",
                   help="also print [OK] lines (otherwise quiet on success)")
    p.add_argument("--show-traceback", action="store_true",
                   help="print full Python traceback on each failure")
    p.add_argument("--keep-people", action="store_true",
                   help="skip the people-reset step (matches start-state's flag)")
    p.add_argument("--debug", action="store_true",
                   help="use the debug ROM's .sym")
    p.add_argument("--rebuild-inventory", action="store_true",
                   help="force rebuild of inventory.json")
    args = p.parse_args(argv)

    root = paths.repo_root()
    sym_path = paths.sym_path(root, debug=args.debug)
    rom_path = paths.rom_path(root, debug=args.debug)
    template_sav = rom_path.with_suffix(".sav")

    if not template_sav.exists():
        print(
            f"error: no template .sav at {template_sav}.\n"
            "Run start-state.py interactively once, or save the game in-game.",
            file=sys.stderr,
        )
        return 2

    inv = inventory.load_or_build(
        root, sym_path, INVENTORY_PATH,
        force=args.rebuild_inventory,
    )
    if not apply.looks_like_real_save(savefile.SaveFile.load(template_sav), inv):
        print(
            f"error: template at {template_sav} doesn't look like a valid "
            "save (validity bytes missing).",
            file=sys.stderr,
        )
        return 2

    syms = symfile.SymFile.load(sym_path)
    template_bytes = template_sav.read_bytes()

    all_maps = inv["maps"]
    if args.map:
        maps_to_test = [m for m in all_maps if m["name"] == args.map]
        if not maps_to_test:
            print(f"error: no map named {args.map!r}", file=sys.stderr)
            return 2
    else:
        maps_to_test = all_maps
    if args.limit is not None:
        maps_to_test = maps_to_test[: args.limit]

    print(f"Testing {len(maps_to_test)} maps at ({args.x}, {args.y})...")
    print()

    ok: list[str] = []
    failed: list[tuple[str, BaseException, str]] = []
    t0 = time.monotonic()

    for i, m in enumerate(maps_to_test, 1):
        name = m["name"]
        sav = savefile.SaveFile(bytearray(template_bytes))
        state = {"map": {"name": name, "x": args.x, "y": args.y}}
        try:
            apply.apply_state(
                sav, state, inv,
                rom_path=rom_path, syms=syms, keep_people=args.keep_people,
            )
            apply.recompute_checksums(sav, inv)
        except BaseException as e:
            tb = traceback.format_exc()
            failed.append((name, e, tb))
            print(f"[FAIL] {name} — {type(e).__name__}: {e}")
            if args.show_traceback:
                for line in tb.rstrip().splitlines():
                    print(f"       {line}")
        else:
            ok.append(name)
            if args.verbose:
                print(f"[OK  ] {name}")

        # Light progress every 100 maps when running quietly.
        if not args.verbose and i % 100 == 0 and i < len(maps_to_test):
            elapsed = time.monotonic() - t0
            print(f"  ... {i}/{len(maps_to_test)}  ({elapsed:.1f}s)")

    elapsed = time.monotonic() - t0
    print()
    print(f"Results: {len(ok)} OK, {len(failed)} failed   ({elapsed:.1f}s)")

    if failed:
        print()
        print("Failures by error type:")
        by_type: dict[str, list[str]] = {}
        for name, e, _ in failed:
            by_type.setdefault(type(e).__name__, []).append(name)
        for tname, names in sorted(by_type.items()):
            print(f"  {tname} ({len(names)}):")
            for n in names:
                # Find the matching error message.
                msg = next(f"{e}" for fn, e, _ in failed if fn == n)
                print(f"    {n}  — {msg}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
