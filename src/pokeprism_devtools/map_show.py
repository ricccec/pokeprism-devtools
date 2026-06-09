#!/usr/bin/env python3
"""prism-map — inspect one map and (optionally) export its prism-mapfit spec.

The inverse of `prism-mapfit`: given a map's CamelCase label, read its
`map_header` / `map_header_2` fields, block-data and script paths straight from
the asm sources, report where each of its sections lives (bank) and how big its
blobs are, and emit the TOML `MapSpec` that `prism-mapfit` consumes.

    prism-map MtEmberSmallRoom                 # human report
    prism-map MtEmberSmallRoom --toml          # emit the spec TOML to stdout
    prism-map MtEmberSmallRoom -o mymap.toml   # ...and write it to a file

No ROM is required. A built `.map` (next to the ROM, or via `--map`) adds the
bank each section is pinned to; without it the bank column is omitted.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from . import mapsource, maps as maps_mod, paths
from .blobsizes import PRIMARY_HEADER_GROWTH, compressed_blk_size, secondary_size
from .mapfile import MapFile
from .mapspec import MapSpec


class MapNotFound(RuntimeError):
    pass


def build_spec(root: Path, label: str) -> MapSpec:
    """Assemble a MapSpec for an existing, wired map from its asm sources."""
    sec = mapsource.secondary_header(root, label)
    if sec is None:
        raise MapNotFound(
            f"no `map_header_2 {label}, ...` in maps/second_map_headers.asm — "
            "is the label spelled exactly (CamelCase) and the map wired in?"
        )
    prim = mapsource.primary_header(root, label)
    if prim is None:
        raise MapNotFound(f"no `map_header {label}, ...` in maps/map_headers.asm")

    dims = {m.name: m for m in maps_mod.parse_maps(
        root / "constants" / "map_dimension_constants.asm")}
    md = dims.get(sec.const)
    if md is None:
        raise MapNotFound(
            f"const {sec.const} not found in map_dimension_constants.asm")

    return MapSpec(
        label=label, const=sec.const, group=md.group,
        height=md.height, width=md.width,
        tileset=prim.tileset, permission=prim.permission, landmark=prim.landmark,
        music=prim.music, palette=prim.palette, fishgroup=prim.fishgroup,
        phone=prim.phone,
        border_block=sec.border_block, conn_flags=sec.conn_flags,
        connections=sec.connections,
        script_asm=mapsource.script_path(root, label) or "",
        blk=mapsource.blk_path(root, label) or "",
    )


@dataclass
class BlobRow:
    blob: str
    section: str | None
    bank: int | None
    size: int | None
    exact: bool          # False => approximate (e.g. source-file proxy)
    shared: bool


def _section_bank(mp: MapFile | None, name: str | None) -> int | None:
    if mp is None or name is None:
        return None
    hits = [s for s in mp.all_sections() if s.name == name]
    return hits[0].bank if hits else None


def _mp_section_size(mp: MapFile | None, name: str) -> int | None:
    if mp is None:
        return None
    hits = [s for s in mp.all_sections() if s.name == name]
    return hits[0].size if hits else None


def gather_blobs(root: Path, spec: MapSpec, mp: MapFile | None) -> list[BlobRow]:
    label = spec.label
    shared = {b for b, _, _ in mapsource.shared_section_conflicts(root, spec)}

    sec_script = mapsource.enclosing_section(
        root / "maps/map_scripts.asm",
        lambda ln: ln.strip() == f'INCLUDE "{spec.script_asm}"') if spec.script_asm else None
    sec_blk = mapsource.enclosing_section(
        root / "maps/blockdata.asm",
        lambda ln: ln.strip() == f"{label}_BlockData:")
    sec_secondary = mapsource.enclosing_section(
        root / "maps/second_map_headers.asm",
        lambda ln: re.match(rf"^\s*map_header_2\s+{re.escape(label)}\s*,", ln) is not None)

    # script size: exact from the .map iff it has its own section; else source proxy.
    if sec_script == spec.section_script and _mp_section_size(mp, spec.section_script) is not None:
        script_size, script_exact = _mp_section_size(mp, spec.section_script), True
    elif spec.script_asm and (root / spec.script_asm).exists():
        script_size, script_exact = (root / spec.script_asm).stat().st_size, False
    else:
        script_size, script_exact = None, False

    blk_size = None
    if spec.blk and (root / spec.blk).exists():
        try:
            blk_size = compressed_blk_size(root, spec.blk)
        except FileNotFoundError:
            blk_size = None  # utils/lzcomp not built — report size as unknown

    return [
        BlobRow("primary", "Map Headers", _section_bank(mp, "Map Headers"),
                PRIMARY_HEADER_GROWTH, True, False),
        BlobRow("secondary", sec_secondary, _section_bank(mp, sec_secondary),
                secondary_size(len(spec.connections)), True, "secondary header" in shared),
        BlobRow("blk", sec_blk, _section_bank(mp, sec_blk), blk_size, True, "block data" in shared),
        BlobRow("script", sec_script, _section_bank(mp, sec_script),
                script_size, script_exact, "script" in shared),
    ]


def _load_mapfile(args) -> MapFile | None:
    try:
        p = Path(args.map) if args.map else paths.map_path()
        return MapFile.parse(p)
    except (paths.RepoNotFound, FileNotFoundError, OSError, ValueError):
        return None


def _print_report(spec: MapSpec, blobs: list[BlobRow], mp: MapFile | None) -> None:
    print(f"Map: {spec.label}  ({spec.const})")
    print(f"  group {spec.group} · {spec.height}x{spec.width} "
          f"({spec.height * spec.width} blocks)\n")

    print("Header (map_header)")
    for k in ("tileset", "permission", "landmark", "music", "phone", "palette", "fishgroup"):
        print(f"  {k:<11} {getattr(spec, k)}")
    print("\nSecondary (map_header_2)")
    print(f"  {'border_block':<11} {spec.border_block}")
    print(f"  {'conn_flags':<11} {spec.conn_flags}")
    if spec.connections:
        for c in spec.connections:
            print(f"  {'connection':<11} {c}")
    else:
        print(f"  {'connections':<11} (none)")

    print("\nFiles")
    print(f"  {'script':<11} {spec.script_asm or '(not found)'}")
    print(f"  {'blk':<11} {spec.blk or '(not found)'}")

    print("\nSections")
    if mp is None:
        print("  (no .map found — bank column omitted; pass --map or build the ROM)")
    rows = []
    for b in blobs:
        bank = "n/a" if mp is None else (f"${b.bank:02x}" if b.bank is not None else "?")
        if b.size is None:
            size = "?"
        else:
            size = f"{b.size} B" + ("" if b.exact else " (src)")
        flag = " *shared*" if b.shared else ""
        rows.append((b.blob, b.section or "(unwired)", bank, size, flag))
    w0 = max(len(r[0]) for r in rows)
    w1 = max(len(r[1]) for r in rows)
    for blob, sec, bank, size, flag in rows:
        print(f"  {blob:<{w0}}  {sec:<{w1}}  {bank:>5}  {size:>9}{flag}")
    if any(b.shared for b in blobs):
        print("\n  * in a section shared with other maps — prism-mapfit can't relocate "
              "it independently until it's in its own section.")
    if any(b.blob == "script" and not b.exact and b.size is not None for b in blobs):
        print("  (src) script size is the source .asm byte count (no dedicated .map "
              "section to measure); the assembled size differs.")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="prism-map",
        description="Inspect one map and optionally export its prism-mapfit spec.")
    p.add_argument("label", help="the map's CamelCase label, e.g. MtEmberSmallRoom")
    p.add_argument("--toml", action="store_true", help="emit the spec TOML")
    p.add_argument("-o", "--out", metavar="FILE", help="write the spec TOML to FILE (implies --toml)")
    p.add_argument("--map", metavar="PATH", help="override the .map used for bank info")
    args = p.parse_args(argv)

    try:
        root = paths.repo_root()
        spec = build_spec(root, args.label)
    except (paths.RepoNotFound, MapNotFound) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if args.out or args.toml:
        toml = spec.to_toml()
        if args.out:
            Path(args.out).write_text(toml)
            print(f"wrote {args.out}", file=sys.stderr)
        else:
            sys.stdout.write(toml)
        return 0

    mp = _load_mapfile(args)
    blobs = gather_blobs(root, spec, mp)
    _print_report(spec, blobs, mp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
