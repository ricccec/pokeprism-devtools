"""Read a polished map's block grid from the ROM and compute its `wScreenSave`.

Polished's map headers are not stock-family (a 7-byte primary with packed
nibbles and a bankless attributes pointer, a 10-byte secondary with `dba`
pointers), so `shared.overworld.blockdata`'s header walk cannot reach a map here.
It does not need to: the labels the build exports — `<Label>_BlockData` for the
grid, `<Label>_MapAttributes` for the header — are in the `.sym`, so both are
resolved by name the same way the save patcher resolves every field. The grid is
decompressed with polished's own `lzp` codec and handed to the *neutral*
`compute_screen_save`, which is pure grid arithmetic and learns no tree's layout.

The connected-neighbour overlay works the same way: polished's `<Label>_MapAttributes`
holds the stock 12-byte connection structs behind a fixed-offset flags byte (its
`connection` macro bakes the same scratch-relative source and overworld-relative
dest pointers prism does), so the neutral `connection_geometry` recovers each
strip's placement, and the neighbour's own grid is loaded by label just like the
current map's. A spawn at a map edge then renders the real adjacent map instead of
the border void Stage 1 left there.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Optional

from ...shared.overworld import blockdata
from ...shared.symfile import SymFile
from . import lzp

#: `<Label>_MapAttributes` layout (`data/maps/attributes.asm`): `db border, height,
#: width; dba BlockData, MapScriptHeader; db connection_flags`, then the 12-byte
#: connection structs. So the flags sit at offset 9 and the structs start at 10.
_ATTR_CONN_FLAGS = 9
_ATTR_CONNECTIONS = _ATTR_CONN_FLAGS + 1

#: The two WRAM bases polished's `connection` macro counts its pointers from —
#: `wDecompressScratch + blk` for the strip source, `wOverworldMapBlocks + map` for
#: the destination. Named here because they are what polished's macro emits; the
#: neutral geometry only wants the resolved addresses.
_SCRATCH_SYM = "wDecompressScratch"
_OVERWORLD_SYM = "wOverworldMapBlocks"

#: Resolve a neighbour's (group, map_id) to its `(label, width, height)`, or None
#: when the connection points at a map the caller's catalog doesn't know. Supplied
#: by the caller (which owns the `map_constants.asm` parse) — polished loads maps by
#: label, so a connection's numeric ids alone cannot find the neighbour's blocks.
NeighbourResolver = Callable[[int, int], Optional[tuple[str, int, int]]]


def block_data(rom: bytes, syms: SymFile, label: str,
               width: int, height: int) -> blockdata.BlockData:
    """The decompressed `width x height` block grid for `label`.

    `<label>_BlockData` names the compressed stream in the `.sym`; polished's `lzp`
    codec decompresses it, and the grid is truncated to `width * height` exactly as
    `ReadMapBlocks` copies (the stream can encode more — shared blocks, padding).
    """
    sym = syms.get(f"{label}_BlockData")
    if sym is None:
        raise ValueError(
            f"the build's .sym has no {label}_BlockData — is this a polished "
            "checkout, built with symbols?")
    off = blockdata.rom_offset(sym.bank, sym.addr)
    grid, _consumed = lzp.decompress(rom, off)
    need = width * height
    if len(grid) < need:
        raise ValueError(
            f"{label} blockdata is {len(grid)} bytes, need {need} "
            f"({width}x{height}) — wrong map dimensions or a bad stream.")
    return blockdata.BlockData(
        name=label, group=0, map_id=0, width=width, height=height,
        border_block=0, blocks=grid[:need])


def map_connections(rom: bytes, syms: SymFile, label: str,
                    map_width: int) -> list[blockdata.Connection]:
    """The map's N/S/W/E connections, as neutral neighbour→overworld geometry.

    Reads the connection-flags byte and the 12-byte structs off `<label>_MapAttributes`
    (polished's header the stock walk can't reach), then hands each struct to the
    neutral `connection_geometry` with polished's own base addresses — the strip
    source relative to `wDecompressScratch`, the destination to `wOverworldMapBlocks`.
    Each returned `Connection` carries the neighbour's (group, map_id); loading its
    blocks is `neighbours`, which needs the caller's label catalog.
    """
    attr = syms.get(f"{label}_MapAttributes")
    if attr is None:
        raise ValueError(
            f"the build's .sym has no {label}_MapAttributes — is this a polished "
            "checkout, built with symbols?")
    base = blockdata.rom_offset(attr.bank, attr.addr)
    flags = rom[base + _ATTR_CONN_FLAGS]
    src_base = syms[_SCRATCH_SYM].addr
    dest_base = syms[_OVERWORLD_SYM].addr
    dest_stride = map_width + blockdata.OVERWORLD_BORDER

    at = base + _ATTR_CONNECTIONS
    out: list[blockdata.Connection] = []
    for direction, bit in blockdata.CONNECTION_DIRS:
        if not flags & bit:
            continue
        struct = rom[at: at + blockdata.CONNECTION_STRUCT_SIZE]
        at += blockdata.CONNECTION_STRUCT_SIZE
        if len(struct) < blockdata.CONNECTION_STRUCT_SIZE:
            raise ValueError(f"{label} {direction} connection struct runs past ROM end")
        out.append(blockdata.connection_geometry(
            struct, direction, src_base=src_base, dest_base=dest_base,
            dest_stride=dest_stride, who=label))
    return out


def neighbours(rom: bytes, syms: SymFile, label: str, map_width: int,
               resolve: NeighbourResolver
               ) -> list[tuple[blockdata.Connection, blockdata.BlockData]]:
    """The `(Connection, BlockData)` pairs `compute_screen_save` overlays at edges.

    For each connection the map declares, `resolve` turns the neighbour's numeric
    (group, map_id) into its `(label, width, height)`; the neighbour's grid is then
    loaded by label. A connection to a map the catalog doesn't know, or whose grid
    won't decompress, is skipped — the edge falls back to border void, no worse than
    Stage 1.
    """
    pairs: list[tuple[blockdata.Connection, blockdata.BlockData]] = []
    for conn in map_connections(rom, syms, label, map_width):
        resolved = resolve(conn.group, conn.map_id)
        if resolved is None:
            continue
        nlabel, nwidth, nheight = resolved
        try:
            nb = block_data(rom, syms, nlabel, nwidth, nheight)
        except ValueError:
            continue
        pairs.append((conn, nb))
    return pairs


def screen_save_bytes(rom: bytes, syms: SymFile, label: str,
                      width: int, height: int, x: int, y: int, *,
                      neighbors: "list[tuple[blockdata.Connection, blockdata.BlockData]]" = ()) -> bytes:
    """The 30 `wScreenSave` bytes for standing at tile `(x, y)` on `label`.

    `rom` is the built ROM's bytes; `label` is the map's file label. `width`/`height`
    are the map's block dimensions from the caller's `map_constants.asm` parse. Pass
    `neighbors` — from `neighbours` — to overlay the connected maps' edge blocks so an
    edge position reads the real border instead of void; without it only the interior
    window is filled.
    """
    bd = block_data(rom, syms, label, width, height)
    return blockdata.compute_screen_save(bd, x, y, neighbors=neighbors)
