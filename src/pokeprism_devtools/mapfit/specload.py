"""Load a spec, apply the command line's overrides, and refuse what can't work.

Command-line placement flags beat the spec file, so one spec can be reused with
a different placement without editing it. A map whose blobs sit in sections
shared with other maps is refused outright: the tool identifies and pins blobs by
their own per-map section name, and a shared section cannot be relocated without
splitting it first.
"""

from __future__ import annotations

import sys
from pathlib import Path

from ..hacks.prism import mapsource
from ..hacks.prism.mapspec import BLOBS, MapSpec
from ..shared import paths
from ..shared.mapfile import MapFile


def _apply_placement_flags(spec: MapSpec, args) -> None:
    """Command-line placement overrides beat what the spec file says, so a spec
    can be reused with a different placement without editing it."""
    for blob in BLOBS:
        into = getattr(args, f"{blob}_into", None)
        bank = getattr(args, f"{blob}_bank", None)
        if into is not None:
            setattr(spec, f"{blob}_into", into)
            setattr(spec, f"{blob}_bank", -1)     # the flags are exclusive
        if bank is not None:
            setattr(spec, f"{blob}_bank", bank)
            setattr(spec, f"{blob}_into", "")


def _load_spec(args) -> tuple[MapSpec, Path]:
    root = paths.repo_root()
    spec = MapSpec.from_toml(Path(args.spec))
    _apply_placement_flags(spec, args)
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
