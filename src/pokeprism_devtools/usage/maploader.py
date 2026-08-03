"""Find and read the `.map` every command works from.

The linker only lists banks it touched, so a `.map` alone understates a
cartridge: the trailing all-$ff padding banks rgbfix appends are invisible in
it. The sibling ROM's header supplies the real bank count. An orphan `.map` with
no ROM beside it keeps its map-only view rather than guessing one.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..shared import paths
from ..shared.mapfile import MapFile


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
        mp = MapFile.parse(p)
    except (OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(2)
    _fill_cartridge_banks(mp, p)
    return mp, p


def _fill_cartridge_banks(mp: MapFile, map_path: Path) -> None:
    """Pad the parsed map out to the physical cartridge's bank count, using the
    sibling ROM's header. The .map only lists banks the linker touched, so the
    trailing all-$ff padding banks are otherwise invisible. No-op if the ROM
    can't be found or read — orphan .map files keep their map-only view."""
    rom = map_path.with_suffix(".gbc")
    if not rom.exists():
        return
    total = paths.rom_bank_count(rom)
    if total > 0:
        mp.fill_rom_banks(total)
