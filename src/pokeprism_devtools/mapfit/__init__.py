#!/usr/bin/env python3
"""prism-mapfit — find ROM banks for a new map and wire it in.

The ROM is ~91% full, so picking banks for a new map's blobs by hand is
tedious. This tool sizes each blob, bin-packs them into the free space the
linker reports (preferring scattered scraps over the empty high banks
``$76``–``$7F``), wires the map into the six source files, pins the new
sections in ``contents/romx.link``, and rebuilds to verify.

    prism-mapfit plan --spec map.toml [--script-size N]   # show the placement
    prism-mapfit add  --spec map.toml [--dry-run]          # wire it in + build

See :mod:`mapspec` for the spec file format. The blobs:

* **block data** — size measured exactly by compressing the ``.blk`` (lzcomp).
* **secondary header** — ``12 + 12·connections`` bytes (its own section).
* **script/event** — only known after assembly, so it is measured by a build
  unless ``--script-size`` is given.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from ..shared import mapsource, paths
from . import mapwire
from ..shared.blobsizes import (
    PRIMARY_HEADER_GROWTH, compressed_blk_size, secondary_size,
)
from ..shared.mapfile import MapFile
from ..shared.mapspec import MapSpec
from .packing import FreeSpace, Item, NoFitError, Placement, pack


@dataclass
class Sizes:
    blockdata: int
    secondary: int
    script: int
    script_measured: bool        # True if measured by a build, False if estimated/given


# --------------------------------------------------------------------------- #
# sizing                                                                       #
# --------------------------------------------------------------------------- #

def estimate_sizes(root: Path, spec: MapSpec, script_size: int | None) -> Sizes:
    return Sizes(
        blockdata=compressed_blk_size(root, spec.blk),
        secondary=secondary_size(len(spec.connections)),
        script=script_size if script_size is not None else -1,
        script_measured=False,
    )


def sizes_from_map(mp: MapFile, spec: MapSpec, fallback: Sizes) -> Sizes:
    """Pull exact section sizes out of a freshly-built .map, keeping fallbacks
    for any section the build didn't place (shouldn't happen on success)."""
    def one(name: str, default: int) -> int:
        hits = [s for s in mp.all_sections() if s.name == name]
        return hits[0].size if hits else default

    return Sizes(
        blockdata=one(spec.section_blockdata, fallback.blockdata),
        secondary=one(spec.section_secondary, fallback.secondary),
        script=one(spec.section_script, fallback.script),
        script_measured=True,
    )


# --------------------------------------------------------------------------- #
# free space + packing                                                         #
# --------------------------------------------------------------------------- #

def _lift_free_space(
    mp: MapFile, lift_names: set[str], *, header_growth: int
) -> tuple[FreeSpace, int | None]:
    """Raw .map free space, with `lift_names` sections credited back to their
    current banks (so they can be re-placed from a clean slate) and the
    'Map Headers' bank optionally debited by `header_growth`."""
    fs = FreeSpace.from_mapfile(mp)
    for s in mp.all_sections():
        if s.name in lift_names:
            fs.reserve(s.bank, -s.size)  # credit back what physically sits there
    hdr = [s for s in mp.all_sections() if s.name == "Map Headers"]
    hdr_bank = hdr[0].bank if hdr else None
    if hdr_bank is not None and header_growth:
        fs.reserve(hdr_bank, header_growth)
    return fs, hdr_bank


def baseline_free_space(
    mp: MapFile, spec: MapSpec | None = None
) -> tuple[FreeSpace, int | None]:
    """Free space for packing one map's blobs.

    If the map is already in the .map (a re-alloc), its sections are credited
    back and no header growth is charged (its primary header is already
    counted). If it's new, the 'Map Headers' bank is debited the +8 bytes the
    new positional primary header adds.
    """
    own = set()
    if spec is not None:
        own = {spec.section_script, spec.section_blockdata, spec.section_secondary}
    already_placed = {s.name for s in mp.all_sections()} & own
    growth = 0 if (spec is None or already_placed) else PRIMARY_HEADER_GROWTH
    return _lift_free_space(mp, already_placed, header_growth=growth)


def map_items(spec: MapSpec, sizes: Sizes) -> list[Item]:
    return [
        Item(spec.section_script, sizes.script),
        Item(spec.section_blockdata, sizes.blockdata),
        Item(spec.section_secondary, sizes.secondary),
    ]


def plan_placement(
    spec: MapSpec, sizes: Sizes, fs: FreeSpace, margin: int, strategy: str = "tight"
) -> list[Placement]:
    return pack(map_items(spec, sizes), fs, margin=margin, strategy=strategy)


def sizes_from_map_strict(mp: MapFile, spec: MapSpec) -> Sizes:
    """Exact sizes for an already-built map, read from the .map. Raises if any
    of the map's sections aren't present (i.e. it hasn't been built yet)."""
    secs = {s.name: s.size for s in mp.all_sections()}
    missing = [n for n in (spec.section_script, spec.section_blockdata,
                           spec.section_secondary) if n not in secs]
    if missing:
        raise ValueError(
            f"{spec.label}: not in the .map yet ({', '.join(missing)}). "
            "Allocate and build it with `add` before consolidating."
        )
    return Sizes(
        blockdata=secs[spec.section_blockdata],
        secondary=secs[spec.section_secondary],
        script=secs[spec.section_script],
        script_measured=True,
    )


# Blob kind -> the spec attribute giving its section name. Aliases collapse to
# the same section, so the selection is robust to spelling.
_BLOB_KINDS = {
    "script": lambda s: s.section_script,
    "blk": lambda s: s.section_blockdata,
    "blockdata": lambda s: s.section_blockdata,
    "secondary": lambda s: s.section_secondary,
    "header": lambda s: s.section_secondary,
}
_DEFAULT_BLOBS = "script,blk,secondary"


def parse_blobs(raw: str | None) -> list[str]:
    """Comma list of blob kinds to act on (default: all three)."""
    kinds = []
    for tok in (raw or _DEFAULT_BLOBS).split(","):
        t = tok.strip().lower()
        if not t:
            continue
        if t not in _BLOB_KINDS:
            raise ValueError(f"unknown blob kind {tok!r} (use script, blk, secondary)")
        kinds.append(t)
    if not kinds:
        raise ValueError("--blobs selected nothing")
    return kinds


def selected_section_names(spec: MapSpec, kinds: list[str]) -> set[str]:
    return {_BLOB_KINDS[k](spec) for k in kinds}


# --------------------------------------------------------------------------- #
# build                                                                        #
# --------------------------------------------------------------------------- #

def run_make(root: Path, target: str = "nodebug") -> tuple[bool, str]:
    env = dict(os.environ)
    cmd = ["make", target]
    if env.get("RGBDS"):
        cmd.append(f'RGBDS={env["RGBDS"]}')
    proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
    return proc.returncode == 0, proc.stdout + proc.stderr


# --------------------------------------------------------------------------- #
# commands                                                                     #
# --------------------------------------------------------------------------- #

def _load_spec(args) -> tuple[MapSpec, Path]:
    root = paths.repo_root()
    spec = MapSpec.from_toml(Path(args.spec))
    problems = spec.validate(root)
    if problems:
        for p in problems:
            print(f"error: spec: {p}", file=sys.stderr)
        sys.exit(2)
    return spec, root


def _load_baseline(root: Path, args) -> MapFile:
    map_path = Path(args.map) if getattr(args, "map", None) else paths.map_path()
    return MapFile.parse(map_path)


def _check_dedicated_sections(root: Path, spec: MapSpec) -> bool:
    """Refuse to manage a map whose blobs live in shared sections (e.g. an
    INCLUDE hand-added into 'Map Scripts 7'). The tool identifies and pins blobs
    by their own per-map section name, so a shared section can't be relocated
    without splitting it. Returns True if OK to proceed."""
    conflicts = mapsource.shared_section_conflicts(root, spec)
    if not conflicts:
        return True
    print(f"error: {spec.label}'s blobs are in shared sections this tool can't "
          f"relocate independently:", file=sys.stderr)
    for blob, actual, expected in conflicts:
        print(f"  - {blob}: in section \"{actual}\" (expected its own \"{expected}\")",
              file=sys.stderr)
    print("  Move each blob into its own `SECTION \"<expected>\", ROMX` (one per "
          "map) and rebuild, then re-run. The tool only manages maps that live "
          "in dedicated per-map sections.", file=sys.stderr)
    return False


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
        print(f"  ${p.bank:02x}  [{p.tier:<5}]  {p.item.key}  ({p.item.size} bytes)")


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
        placements = plan_placement(spec, sizes, fs, args.margin, strategy)
    except NoFitError as e:
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
        sizes = sizes_from_map(MapFile.parse(paths.map_path()), spec, sizes)
    if sizes.script < 0:
        print("error: script size unknown — pass --script-size N (no build was run).",
              file=sys.stderr)
        return 2

    # 3. Pack and pin.
    strategy = _strategy(args)
    try:
        placements = plan_placement(spec, sizes, fs, args.margin, strategy)
    except NoFitError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"\nStrategy: {'park (worst-fit, biggest chunk)' if strategy == 'loose' else 'tight (best-fit)'}")
    _print_plan(spec, sizes, placements, hdr_bank, fs)

    pin = mapwire.pin_sections(root, {p.item.key: p.bank for p in placements})
    print(f"\n  [{'edit' if pin.changed else 'skip'}] {pin.path}: {pin.detail}")
    mapwire.apply_edits(root, [pin], dry_run=args.dry_run)

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


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="prism-mapfit",
        description="Find ROM banks for a new map and wire it in.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--spec", required=True, metavar="FILE", help="map spec .toml")
    common.add_argument("--script-size", type=int, metavar="N",
                        help="script/event section size in bytes (skip the measurement build)")
    common.add_argument("--margin", type=int, default=16, metavar="N",
                        help="bytes of slack to reserve per bank (default: 16)")
    common.add_argument("--map", metavar="PATH", help="override the baseline .map file")

    pp = sub.add_parser("plan", parents=[common], help="show the bank placement, write nothing")
    pp.add_argument("--park", action="store_true",
                    help="worst-fit into the biggest chunk (for a still-growing map)")
    pp.set_defaults(func=cmd_plan)

    pa = sub.add_parser("add", parents=[common], help="wire the map in and build")
    pa.add_argument("--park", action="store_true",
                    help="worst-fit into the biggest free chunk (empty high bank) so a "
                         "still-growing map has maximum headroom; off = tight best-fit")
    pa.add_argument("--dry-run", action="store_true", help="print edits without writing")
    pa.add_argument("--no-build", action="store_true", help="wire + pin but skip builds")
    pa.set_defaults(func=cmd_add)

    pc = sub.add_parser("consolidate",
                        help="tightly re-pack several already-built maps, freeing parked banks")
    pc.add_argument("--spec", required=True, action="append", metavar="FILE",
                    help="map spec .toml (repeat for each map to consolidate)")
    pc.add_argument("--blobs", metavar="KINDS", default=None,
                    help="comma list of blob kinds to move: script,blk,secondary "
                         "(default: all). e.g. --blobs blk to relocate only block data")
    pc.add_argument("--margin", type=int, default=16, metavar="N",
                    help="bytes of slack to reserve per bank (default: 16)")
    pc.add_argument("--map", metavar="PATH", help="override the baseline .map file")
    pc.add_argument("--dry-run", action="store_true", help="print the plan without writing")
    pc.add_argument("--no-build", action="store_true", help="re-pin but skip the verify build")
    pc.set_defaults(func=cmd_consolidate)

    args = p.parse_args(argv)
    try:
        return args.func(args)
    except (paths.RepoNotFound, FileNotFoundError, ValueError, mapwire.WiringError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
