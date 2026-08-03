"""How big each of a map's blobs is.

Two of the three can be known before a build — block data by compressing the
`.blk`, the secondary header by counting connections. The script's size is only
known after assembly, so it is either given on the command line or measured by a
build. A blob appended *into* an existing section has no section of its own, so
its size is how much that section grew, which needs the pre-wiring `.map` to
measure against.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..hacks.prism.blobsizes import compressed_blk_size, secondary_size
from ..hacks.prism.mapspec import INTO, MapSpec
from ..shared.mapfile import MapFile


@dataclass
class Sizes:
    blockdata: int
    secondary: int
    script: int
    script_measured: bool        # True if measured by a build, False if estimated/given



def estimate_sizes(root: Path, spec: MapSpec, script_size: int | None) -> Sizes:
    return Sizes(
        blockdata=compressed_blk_size(root, spec.blk),
        secondary=secondary_size(len(spec.connections)),
        script=script_size if script_size is not None else -1,
        script_measured=False,
    )


def sizes_from_map(mp: MapFile, spec: MapSpec, fallback: Sizes,
                   before: MapFile | None = None) -> Sizes:
    """Pull exact blob sizes out of a freshly-built .map.

    A blob with its own section is just that section's size. A blob appended
    *into* an existing section has no section of its own, so its size is how
    much that section **grew** — which needs the pre-wiring .map (`before`) to
    measure against. Without it, the estimate stands.
    """
    def size_of(section: str) -> int | None:
        hits = [s for s in mp.all_sections() if s.name == section]
        return hits[0].size if hits else None

    def one(blob: str, default: int) -> int:
        placement = spec.placement(blob)
        now = size_of(placement.section)
        if now is None:
            return default
        if placement.mode != INTO:
            return now
        if before is None:
            return default
        was = [s for s in before.all_sections() if s.name == placement.section]
        return now - was[0].size if was else default

    return Sizes(
        blockdata=one("blockdata", fallback.blockdata),
        secondary=one("secondary", fallback.secondary),
        script=one("script", fallback.script),
        script_measured=True,
    )


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

