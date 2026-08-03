"""Where each of a map's four blobs lives, and how big it is.

A blob's size is exact when the built `.map` has a section of its own to measure;
otherwise the script falls back to the source `.asm` byte count, which is a
different number and is marked `(src)` rather than quietly reported as the truth.
A blob sharing a section with other maps is flagged, because `prism-mapfit`
cannot relocate it until it has its own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..hacks.prism import mapsource
from ..hacks.prism.blobsizes import (
    PRIMARY_HEADER_GROWTH, compressed_blk_size, secondary_size)
from ..hacks.prism.mapspec import MapSpec
from ..shared import paths
from ..shared.mapfile import MapFile


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
