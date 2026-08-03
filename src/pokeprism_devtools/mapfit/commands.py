"""The three things prism-mapfit does: plan, add, consolidate.

`add` is the only one that builds. It builds twice when the script size is
unknown — once with the map's sections floating, purely to measure, and once at
the end to verify the pins. Unpinning first matters: a re-alloc of a map that
outgrew its bank would otherwise overflow the measurement build on a stale pin.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from ..hacks.prism.blobsizes import PRIMARY_HEADER_GROWTH
from ..hacks.prism.mapspec import MapSpec
from ..shared import paths
from ..shared.mapfile import MapFile
from . import mapwire
from .blobs import parse_blobs, selected_section_names
from .freespace import (
    PlacementError, _lift_free_space, baseline_free_space, map_items,
    plan_placement,
)
from .packing import FreeSpace, NoFitError, pack
from .sizes import estimate_sizes, sizes_from_map, sizes_from_map_strict
from .specload import _check_dedicated_sections, _load_baseline, _load_spec


def run_make(root: Path, target: str = "nodebug") -> tuple[bool, str]:
    env = dict(os.environ)
    cmd = ["make", target]
    if env.get("RGBDS"):
        cmd.append(f'RGBDS={env["RGBDS"]}')
    proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
    return proc.returncode == 0, proc.stdout + proc.stderr


def _print_plan(spec, sizes, placements, hdr_bank, fs):
    print(f"Map: {spec.label}  ({spec.const})  group {spec.group}  {spec.height}x{spec.width}\n")
    smark = "measured" if sizes.script_measured else (
        "given" if sizes.script >= 0 else "UNKNOWN (need a build or --script-size)")
    print("Blob sizes")
    print(f"  block data   {sizes.blockdata:>6} bytes  (compressed, exact)")
    print(f"  secondary    {sizes.secondary:>6} bytes  ({len(spec.connections)} connections)")
    print(f"  script/event {sizes.script:>6} bytes  ({smark})")
    print(f"  primary hdr  {PRIMARY_HEADER_GROWTH:>6} bytes  (in place, bank ${hdr_bank:02x})\n"
          if hdr_bank is not None else "")
    print("Placement")
    for p in placements:
        note = {"shared": " (appended into an existing section — not pinned)",
                "pinned": " (bank chosen by hand)"}.get(p.tier, "")
        print(f"  ${p.bank:02x}  [{p.tier:<6}]  {p.item.key}  ({p.item.size} bytes){note}")


def _strategy(args) -> str:
    return "loose" if getattr(args, "park", False) else "tight"

def cmd_plan(args) -> int:
    spec, root = _load_spec(args)
    mp = _load_baseline(root, args)
    fs, hdr_bank = baseline_free_space(mp, spec)
    sizes = estimate_sizes(root, spec, args.script_size)
    if sizes.script < 0:
        print("error: script size unknown — pass --script-size N or run `add` to "
              "measure it with a build.", file=sys.stderr)
        return 2
    strategy = _strategy(args)
    print(f"Strategy: {'park (worst-fit, biggest chunk)' if strategy == 'loose' else 'tight (best-fit)'}")
    try:
        placements = plan_placement(spec, sizes, fs, args.margin, strategy, mp)
    except (NoFitError, PlacementError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    _print_plan(spec, sizes, placements, hdr_bank, fs)
    _warn_header_overflow(fs, hdr_bank, args.margin)
    return 0


def cmd_add(args) -> int:
    spec, root = _load_spec(args)
    if not _check_dedicated_sections(root, spec):
        return 2
    mp = _load_baseline(root, args)
    fs, hdr_bank = baseline_free_space(mp, spec)
    _warn_header_overflow(fs, hdr_bank, args.margin)

    # 1. Wire the asm sources (sections float for now — not yet in romx.link).
    asm_edits = [editor(root, spec) for editor in mapwire.ALL_ASM_EDITORS]
    for e in asm_edits:
        print(f"  [{'edit' if e.changed else 'skip'}] {e.path}: {e.detail}")
    mapwire.apply_edits(root, asm_edits, dry_run=args.dry_run)

    # 2. Determine sizes. Measure the script via a build unless given one.
    sizes = estimate_sizes(root, spec, args.script_size)
    if sizes.script < 0 and not args.no_build and not args.dry_run:
        # Unpin this map's sections first: if it's a re-alloc of a map that grew
        # past its current bank, the stale pin would overflow the measurement
        # build. Floating lets rgblink place them anywhere just to measure.
        unpin = mapwire.unpin_sections(root, [
            spec.section_script, spec.section_blockdata, spec.section_secondary,
        ])
        if unpin.changed:
            print(f"  [edit] {unpin.path}: {unpin.detail}")
            mapwire.apply_edits(root, [unpin], dry_run=False)
        print("\nMeasuring script size (build with floating sections)…")
        ok, log = run_make(root)
        if not ok:
            print(log[-2000:], file=sys.stderr)
            print("error: measurement build failed — see log above.", file=sys.stderr)
            return 1
        sizes = sizes_from_map(MapFile.parse(paths.map_path()), spec, sizes, before=mp)
    if sizes.script < 0:
        print("error: script size unknown — pass --script-size N (no build was run).",
              file=sys.stderr)
        return 2

    # 3. Pack and pin.
    strategy = _strategy(args)
    try:
        placements = plan_placement(spec, sizes, fs, args.margin, strategy, mp)
    except (NoFitError, PlacementError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"\nStrategy: {'park (worst-fit, biggest chunk)' if strategy == 'loose' else 'tight (best-fit)'}")
    _print_plan(spec, sizes, placements, hdr_bank, fs)

    # Blobs appended into an existing section inherit its bank — there is no new
    # section for the linker to place, so they are deliberately left unpinned.
    shared = {p.section for p in spec.placements if not p.needs_pin}
    to_pin = {p.item.key: p.bank for p in placements if p.item.key not in shared}
    if to_pin:
        pin = mapwire.pin_sections(root, to_pin)
        print(f"\n  [{'edit' if pin.changed else 'skip'}] {pin.path}: {pin.detail}")
        mapwire.apply_edits(root, [pin], dry_run=args.dry_run)
    else:
        print("\n  [skip] contents/romx.link: every blob joined an existing section")

    if args.dry_run:
        print("\n(dry run — no files written)")
        return 0

    # 4. Verify.
    if args.no_build:
        print("\nWired in. Skipping verify build (--no-build); run `make nodebug`.")
        return 0
    print("\nVerifying (make nodebug)…")
    ok, log = run_make(root)
    if not ok:
        print(log[-2000:], file=sys.stderr)
        print("error: verify build failed. If a section overflowed its bank, "
              "re-run with a larger --margin or free a bank.", file=sys.stderr)
        return 1
    print("Build OK. Map wired and placed.")
    return 0


def _warn_header_overflow(fs: FreeSpace, hdr_bank: int | None, margin: int) -> None:
    if hdr_bank is None:
        return
    if fs.free.get(hdr_bank, 0) < margin:
        print(f"warning: bank ${hdr_bank:02x} (holds 'Map Headers') has little room "
              f"for the +{PRIMARY_HEADER_GROWTH}-byte primary header; you may need to "
              "relocate the 'Map Headers' section to a roomier bank in romx.link.",
              file=sys.stderr)

def cmd_consolidate(args) -> int:
    """Re-pack several already-built maps tightly into existing scraps in one
    pass, freeing the roomy banks they were parked in. Sizes come from the
    current .map (the maps are stable and already built), so no per-map
    measurement build is needed — just one verify build at the end."""
    root = paths.repo_root()
    specs = [MapSpec.from_toml(Path(s)) for s in args.spec]
    for spec in specs:
        problems = spec.validate(root)
        if problems:
            for p in problems:
                print(f"error: {spec.label}: {p}", file=sys.stderr)
            return 2
        if not _check_dedicated_sections(root, spec):
            return 2

    kinds = parse_blobs(args.blobs)
    mp = _load_baseline(root, args)

    # Exact sizes from the current build; lift the selected blobs of every map
    # out of the free space (non-selected blobs stay put and stay counted).
    all_names: set[str] = set()
    items = []
    for spec in specs:
        sizes = sizes_from_map_strict(mp, spec)   # raises if not built yet
        selected = selected_section_names(spec, kinds)
        for it in map_items(spec, sizes):
            if it.key in selected:
                items.append(it)
                all_names.add(it.key)

    fs, _ = _lift_free_space(mp, all_names, header_growth=0)
    try:
        placements = pack(items, fs, margin=args.margin, strategy="tight")
    except NoFitError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    # Report, grouped per map, flagging which sections actually move banks.
    current = {s.name: s.bank for s in mp.all_sections()}
    print(f"Consolidating {len(specs)} map(s), blobs: {', '.join(kinds)} "
          "-> tightest existing space\n")
    moves = 0
    for spec in specs:
        print(f"{spec.label}")
        for p in [pl for pl in placements if pl.item.key.endswith(spec.label)]:
            was = current.get(p.item.key)
            arrow = f"${was:02x} -> ${p.bank:02x}" if was is not None else f"-> ${p.bank:02x}"
            moved = "" if was == p.bank else "  *moved*"
            if was != p.bank:
                moves += 1
            print(f"  [{p.tier:<5}] {p.item.key}  ({p.item.size} B)  {arrow}{moved}")
    freed = sorted({current[n] for n in all_names if n in current}
                   - {p.bank for p in placements})
    print(f"\n{moves} section(s) relocated; banks possibly freed: "
          f"{', '.join(f'${b:02x}' for b in freed) or 'none'}")

    pin = mapwire.pin_sections(root, {p.item.key: p.bank for p in placements})
    print(f"\n  [{'edit' if pin.changed else 'skip'}] {pin.path}: {pin.detail}")
    if args.dry_run:
        print("\n(dry run — no files written)")
        return 0
    mapwire.apply_edits(root, [pin], dry_run=False)

    if args.no_build:
        print("\nRe-pinned. Skipping verify build (--no-build); run `make nodebug`.")
        return 0
    print("\nVerifying (make nodebug)…")
    ok, log = run_make(root)
    if not ok:
        print(log[-2000:], file=sys.stderr)
        print("error: verify build failed — try a larger --margin.", file=sys.stderr)
        return 1
    print("Build OK. Maps consolidated.")
    return 0

