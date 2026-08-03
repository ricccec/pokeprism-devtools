"""Which banks have room, and which blob is allowed to take it.

A hand-placed blob skips the packer, so nothing else checks it: name a bank
that is nearly full and the build fails much later inside rgblink. Each one is
therefore resolved to a real bank here, measured against that bank's free space,
and the space it takes reserved so the packer cannot hand the same bytes out
twice.
"""

from __future__ import annotations

from ..hacks.prism.blobsizes import PRIMARY_HEADER_GROWTH
from ..hacks.prism.mapspec import INTO, MapSpec
from ..shared.mapfile import MapFile
from .packing import FreeSpace, Item, Placement, pack_into_banks
from .sizes import Sizes


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
    counted). If it's new, the 'Map Headers' bank is debited the +9 bytes the
    new positional primary header adds.
    """
    own = set()
    if spec is not None:
        own = {spec.section_script, spec.section_blockdata, spec.section_secondary}
    already_placed = {s.name for s in mp.all_sections()} & own
    growth = 0 if (spec is None or already_placed) else PRIMARY_HEADER_GROWTH
    return _lift_free_space(mp, already_placed, header_growth=growth)


def blob_size(sizes: Sizes, blob: str) -> int:
    return {"blockdata": sizes.blockdata, "script": sizes.script,
            "secondary": sizes.secondary}[blob]


def map_items(spec: MapSpec, sizes: Sizes) -> list[Item]:
    """The blobs the packer is allowed to place — the ones left on `auto`."""
    return [Item(p.section, blob_size(sizes, p.blob))
            for p in spec.placements if p.needs_packing]


class PlacementError(RuntimeError):
    """A hand-placed blob won't fit, or names a section that doesn't exist."""


def resolve_manual(
    mp: MapFile, spec: MapSpec, sizes: Sizes, fs: FreeSpace, margin: int
) -> list[Placement]:
    """Work out where the hand-placed blobs land, and check they'll fit.

    These skip the packer entirely, so nothing else is checking them: if the
    author names a bank that's nearly full, or a section whose bank is, the
    build only fails much later inside rgblink. So each one is resolved to a
    real bank here and measured against that bank's free space, and the space it
    takes is reserved so the packer doesn't hand the same bytes to an auto blob.

    Raises :class:`PlacementError` naming the section and bank when it won't fit.
    """
    placements: list[Placement] = []
    for p in spec.placements:
        if p.needs_packing:
            continue
        size = blob_size(sizes, p.blob)

        if p.mode == INTO:
            hits = mp.find_section(p.section)
            if not hits:
                raise PlacementError(
                    f"{p.blob}: no section named '{p.section}' in the .map — check "
                    f"the name, or leave {p.blob} on auto to let the packer choose"
                )
            bank = hits[0].bank
        else:
            bank = p.bank

        free = fs.free.get(bank, 0)
        if size > free - margin:
            raise PlacementError(
                f"{p.blob}: '{p.section}' needs {size} bytes in bank ${bank:02x}, "
                f"which has {free} free"
                + (f" ({margin} reserved as margin)" if margin else "")
                + ". Pick another bank, or leave this blob on auto."
            )
        fs.reserve(bank, size)          # the packer must not reuse these bytes
        placements.append(Placement(Item(p.section, size), bank,
                                    "shared" if p.mode == INTO else "pinned"))
    return placements


def plan_placement(
    spec: MapSpec, sizes: Sizes, fs: FreeSpace, margin: int, strategy: str = "tight",
    mp: MapFile | None = None,
) -> list[Placement]:
    """Where every blob goes: the hand-placed ones first (they're fixed, and
    they consume space the packer would otherwise offer), then the rest packed
    into what's left."""
    manual = resolve_manual(mp, spec, sizes, fs, margin) if mp is not None else []
    auto = pack_into_banks(map_items(spec, sizes), fs, margin=margin, strategy=strategy)
    return manual + auto

