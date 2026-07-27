"""Read a map's blockdata from a Gen-2 ROM, and compute the `wScreenSave`
window the game would have written for a given player position.

The reconstruction that keeps wScreenSave consistent with (wMapGroup,
wMapNumber, wXCoord, wYCoord) when a save is patched — the tiles half of a map
rebuild. The map-header and block-data formats are stock pokecrystal's, read
through whichever tree's `SymFile` the caller passes, so the module names no
hack and belongs to none. See docs/blockdata-plan.md for the data-flow and asm
cross-references.

Glossary:
    - Bank 0 is mapped at $0000-$3FFF; banks 1+ swap in at $4000-$7FFF.
    - In the .sym, a label like `25:40be` means bank $25, GB address $40be.
    - "Block" is the 2x2-tile map unit. wXCoord/wYCoord are in *tiles*,
      so the block grid is indexed by (X>>1, Y>>1) roughly. The exact
      anchor math comes from GetCoordOfUpperLeftCorner.
    - The decompressed grid is `height * width` bytes, row-major.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .. import lz, symfile

# Sizes derived from the asm — see docs/blockdata-plan.md.
MAP_HEADER_SIZE = 9     # 1 + 1 + 1 + 2 + 1 + 1 + 1 + 1 + 1
SECOND_MAP_HEADER_SIZE = 12
SCREEN_SAVE_ROWS = 5    # outer-loop count in SaveScreen_LoadNeighbor (c)
SCREEN_SAVE_COLS = 6    # inner-loop count (b)
SCREEN_SAVE_SIZE = SCREEN_SAVE_ROWS * SCREEN_SAVE_COLS  # 30
PADDING = 3             # 3-block padding around the actual grid in wOverworldMap

# The event header, per ReadMapEventHeader (home/map.asm:231). Two filler bytes,
# then four count-prefixed arrays back to back. Nothing records where each array
# ends except the count in front of it, so the object events — the last of the
# four — can only be found by walking the three before them.
EVENT_HEADER_FILLER = 2


#: How the map header stores a connection's strip *source* pointer. Stock
#: pokecrystal bakes `<neighbour>_Blocks + offset` — a pointer into the
#: neighbour's own (raw) block data — so the offset is recovered against that
#: neighbour's block address. Prism decompresses each neighbour into a shared
#: scratch buffer first, so its pointer is `wDecompressScratch + offset`.
CONN_SRC_NEIGHBOUR = "neighbour_blocks"
CONN_SRC_SCRATCH = "decompress_scratch"


@dataclass(frozen=True)
class MapFormat:
    """How a Gen-2 tree lays its map data out in ROM — the facts that differ
    between the trees, so the reader itself names none of them.

    Defaults are stock pokecrystal's, re-derived from its own source (not assumed
    from prism, which the port was first written against — see the branch memory):
    block data is raw `.blk` bytes (`data/maps/blocks.asm` INCBINs, one byte per
    block); the event-header records are `warp_event` 5, `coord_event` 8
    (`db scene,y,x` + filler + `dw script` + `dw 0`), `bg_event` 5; the overworld
    block buffer is `wOverworldMapBlocks`; and a connection's source pointer is
    relative to the neighbour's own blocks. Prism diverges on every one of these
    (LZ-compressed blocks, a 7-byte coord event, `wOverworldMap`, scratch-relative
    connections) and passes its own `MapFormat`; the difference crosses the seam
    as declared data rather than living in the reader.
    """
    compressed: bool = False             # blockdata: raw .blk (stock) vs LZ (prism)
    warp: int = 5                        # warp_event: y, x, warp_to, group, map
    coord_event: int = 8                 # scene, y, x, filler, script, filler
    signpost: int = 5                    # bg_event: y, x, function, script
    overworld_map: str = "wOverworldMapBlocks"
    connection_source: str = CONN_SRC_NEIGHBOUR
    sprite_headers: str = "OverworldSprites"  # prism: "SpriteHeaders"
    #: A map group's outdoor sprite list: a fixed count (stock's
    #: MAX_OUTDOOR_SPRITES), or None for a zero-terminated list (prism).
    outdoor_sprites: int | None = 23


#: What `CopyMapObjectHeaders` copies into a `wMapObjects` slot: exactly
#: `MAPOBJECT_E - MAPOBJECT_SPRITE` bytes. The `person_event` macro has three
#: branches (script pointer, jumpstd, mart) and all three assemble to this same
#: length, which is why the array can be indexed at all.
PERSON_EVENT_SIZE = 13

#: A connection struct, as GetMapConnection copies it out of the ROM: group,
#: number, strip pointer, strip location, strip length, connected-map width, y
#: offset, x offset, window (wram.asm `wNorthMapConnection`). 12 bytes.
CONNECTION_STRUCT_SIZE = 12

#: Connections in the order GetMapConnections reads them — N, S, W, E — with the
#: bit each occupies in the second header's connection-flags byte. The flags are
#: `shift_const EAST, WEST, SOUTH, NORTH` (constants/map_constants.asm), so EAST
#: is bit 0 and NORTH is bit 3.
_CONNECTION_DIRS = (("north", 0x08), ("south", 0x04), ("west", 0x02), ("east", 0x01))

#: FillNorth/SouthConnectionStrip copy 3 rows deep; FillWest/East copy 3 cols
#: wide. The other dimension is the connection's own strip length.
CONNECTION_STRIP_DEPTH = 3

#: The overworld-map row is the current map's width plus a 3-block border on each
#: side — the stride `\7_WIDTH + 6` the connection macro bakes into its pointers.
OVERWORLD_BORDER = 2 * PADDING

#: Map permissions (constants/map_constants.asm). CheckOutdoorMap treats TOWN and
#: ROUTE as outdoor; on those the overworld draws sprites from the map *group*'s
#: OutdoorSprites pool rather than the map's own NPC list.
TOWN, ROUTE = 1, 2


def is_outdoor(permission: int) -> bool:
    """Whether `AddMapSprites` uses the group's OutdoorSprites pool for this map."""
    return permission in (TOWN, ROUTE)


@dataclass(frozen=True)
class BlockData:
    name: str
    group: int
    map_id: int
    width: int           # in blocks
    height: int          # in blocks
    border_block: int
    blocks: bytes        # height * width bytes, row-major
    tileset_id: int = 0  # primary header byte 1
    permission: int = 0  # primary header byte 2


@dataclass(frozen=True)
class Connection:
    """One resolved map connection, as FillMapConnections would apply it.

    The neighbour block at (source_row + k, source_col + j) lands in the current
    map's wOverworldMap at (dest_row + k, dest_col + j), for k in range(rows) and
    j in range(cols). The geometry is recovered from the baked wOverworldMap and
    wDecompressScratch pointers the connection macro stores, so the strip's y/x
    offsets and window — which the engine uses only for scrolling, not for the
    initial fill — never enter into it.
    """
    direction: str
    group: int
    map_id: int
    source_row: int
    source_col: int
    dest_row: int
    dest_col: int
    rows: int
    cols: int


def rom_offset(bank: int, addr: int) -> int:
    """Convert a (bank, GB-address) pair to a ROM file offset."""
    if addr < 0x4000:
        return addr  # bank 0 mapped at the start of ROM
    return bank * 0x4000 + (addr - 0x4000)


@dataclass(frozen=True)
class _Headers:
    """Where a map's two headers landed, and the bank they live in."""
    bank: int            # the secondary header's bank — and the event header's
    secondary_off: int
    tileset_id: int
    permission: int


def _headers(
    rom: bytes, syms: symfile.SymFile, group: int, map_id: int, name: str = ""
) -> _Headers:
    """Walk MapGroupPointers → MapGroup<N> → primary header → secondary header.

    Both the blockdata and the event header hang off the secondary header, so
    they reach it the same way. `group` and `map_id` are 1-based, matching
    wMapGroup / wMapNumber.
    """
    if group < 1:
        raise ValueError(f"group must be 1-based; got {group}")
    if map_id < 1:
        raise ValueError(f"map_id must be 1-based; got {map_id}")

    mgp = syms["MapGroupPointers"]
    mgp_off = rom_offset(mgp.bank, mgp.addr)
    mgp_entry = mgp_off + (group - 1) * 2
    if mgp_entry + 2 > len(rom):
        raise ValueError(f"group {group} index past ROM end")
    map_group_addr = _u16_le(rom, mgp_entry)
    # MapGroup<N> lives in the same bank as MapGroupPointers (per the
    # codebase; the table only stores 16-bit addresses).
    map_group_off = rom_offset(mgp.bank, map_group_addr)

    primary_off = map_group_off + (map_id - 1) * MAP_HEADER_SIZE
    if primary_off + MAP_HEADER_SIZE > len(rom):
        raise ValueError(f"(group={group}, map_id={map_id}) past ROM end")
    # primary header: bank, tileset, permission, dw second_header_addr, ...
    bank = rom[primary_off]
    second_addr = _u16_le(rom, primary_off + 3)

    secondary_off = rom_offset(bank, second_addr)
    if secondary_off + SECOND_MAP_HEADER_SIZE > len(rom):
        raise ValueError(
            f"secondary header for {name or f'(group={group}, map_id={map_id})'} "
            f"past ROM end"
        )
    return _Headers(
        bank=bank,
        secondary_off=secondary_off,
        tileset_id=rom[primary_off + 1],
        permission=rom[primary_off + 2],
    )


def object_events(
    rom_path: Path,
    syms: symfile.SymFile,
    group: int,
    map_id: int,
    *,
    name: str = "",
    format: MapFormat = MapFormat(),
) -> list[bytes]:
    """The map's NPCs, as the 13-byte `person_event` blobs the ROM stores.

    Returned uninterpreted, because the engine does not interpret them either:
    `CopyMapObjectHeaders` memcpys these bytes straight into a `wMapObjects`
    slot behind an `$ff` struct id. Decoding them into fields here would mean
    re-encoding them there, and every field we mis-modelled on the way through
    would be a silently different NPC. See `people.load_map_npcs`.

    The y and x in them already have the `+4` the `person_event` macro adds at
    assembly time, i.e. they are in the same map-coordinate space `wMapObjects`
    wants. Nothing to convert.
    """
    rom = rom_path.read_bytes()
    hdr = _headers(rom, syms, group, map_id, name)

    # The secondary header stores the event header as a bare `dw` — no bank. The
    # bank is whichever one is paged in when the engine dereferences it, and
    # LoadMapAttributes calls SwitchToMapScriptHeaderBank first: it is the *map
    # script header's* bank (secondary +6), not the secondary header's own. The
    # two are usually the same, which is why getting this wrong still reads a
    # plausible-looking count off the wrong map.
    script_bank = rom[hdr.secondary_off + 6]
    event_addr = _u16_le(rom, hdr.secondary_off + 9)
    at = rom_offset(script_bank, event_addr) + EVENT_HEADER_FILLER
    who = name or f"(group={group}, map_id={map_id})"

    # Warps, coord events and signposts, only to step over them: the object
    # events are last, and each array's length is knowable only from the count
    # byte in front of it. The record sizes are the caller's `format` — the one
    # place a fork's event header differs from the stock base.
    for size in (format.warp, format.coord_event, format.signpost):
        if at >= len(rom):
            raise ValueError(f"event header for {who} runs past ROM end")
        at += 1 + rom[at] * size

    if at >= len(rom):
        raise ValueError(f"event header for {who} runs past ROM end")
    count = rom[at]
    at += 1
    end = at + count * PERSON_EVENT_SIZE
    if end > len(rom):
        raise ValueError(f"{who} declares {count} object events, past ROM end")

    return [
        rom[i : i + PERSON_EVENT_SIZE]
        for i in range(at, end, PERSON_EVENT_SIZE)
    ]


def load(
    rom_path: Path,
    syms: symfile.SymFile,
    group: int,
    map_id: int,
    *,
    name: str = "",
    format: MapFormat = MapFormat(),
) -> BlockData:
    """Read the blockdata for (group, map_id) from the ROM.

    `group` and `map_id` are both 1-based (matching `wMapGroup` /
    `wMapNumber` values). `name` is optional, used only in error messages.
    `format` decides whether the block grid is read raw (stock `.blk` bytes) or
    LZ-decompressed (prism) — the one place the two trees store blocks differently.
    """
    rom = rom_path.read_bytes()
    hdr = _headers(rom, syms, group, map_id, name)
    secondary_off = hdr.secondary_off
    tileset_id = hdr.tileset_id
    permission = hdr.permission

    border_block = rom[secondary_off + 0]
    height = rom[secondary_off + 1]
    width = rom[secondary_off + 2]
    blockdata_bank = rom[secondary_off + 3]
    blockdata_addr = _u16_le(rom, secondary_off + 4)

    if width == 0 or height == 0:
        raise ValueError(
            f"map {name or f'({group},{map_id})'} has zero width or height "
            f"({width}x{height}) — likely a malformed header"
        )

    blockdata_off = rom_offset(blockdata_bank, blockdata_addr)
    expected = width * height
    if format.compressed:
        raw, _consumed = lz.decompress(rom, blockdata_off)
    else:
        # Stock stores the grid raw — `width*height` bytes straight from the ROM,
        # exactly what the `.blk` file INCBINs.
        raw = rom[blockdata_off : blockdata_off + expected]
    if len(raw) < expected:
        raise ValueError(
            f"map {name or f'({group},{map_id})'} blockdata is "
            f"{len(raw)} bytes, need at least {expected} ({width}x{height})"
        )
    # The game's ReadMapBlocks copies exactly width*height bytes; any trailing
    # data (a compressed stream that encodes more than it needs — SEVII_ISLAND_1,
    # the BATTLE_TOWER_* rooms) is ignored. Truncate to the live grid.
    blocks = raw[:expected]

    return BlockData(
        name=name,
        group=group,
        map_id=map_id,
        width=width,
        height=height,
        border_block=border_block,
        blocks=blocks,
        tileset_id=tileset_id,
        permission=permission,
    )


def map_connections(
    rom_path: Path,
    syms: symfile.SymFile,
    group: int,
    map_id: int,
    *,
    map_width: int,
    name: str = "",
    format: MapFormat = MapFormat(),
) -> list[Connection]:
    """The map's N/S/W/E connections, resolved to neighbour→overworld geometry.

    Reads the connection-flags byte at the tail of the second map header and the
    connection structs that follow it, then recovers each strip's placement by
    subtracting the base addresses the macro baked into the pointers. The *dest*
    is always the overworld grid: `strip location - wOverworldMap[Blocks]` (stride
    = this map's width + 6). The *source* base differs by tree
    (`format.connection_source`): the neighbour's own block data (stock, so it is
    read from the neighbour's header) or a shared decompress buffer (prism). See
    docs/blockdata-plan.md.
    """
    rom = rom_path.read_bytes()
    hdr = _headers(rom, syms, group, map_id, name)
    flags = rom[hdr.secondary_off + SECOND_MAP_HEADER_SIZE - 1]

    overworld_base = syms[format.overworld_map].addr
    dest_stride = map_width + OVERWORLD_BORDER
    who = name or f"(group={group}, map_id={map_id})"

    at = hdr.secondary_off + SECOND_MAP_HEADER_SIZE
    out: list[Connection] = []
    for direction, bit in _CONNECTION_DIRS:
        if not flags & bit:
            continue
        c = rom[at : at + CONNECTION_STRUCT_SIZE]
        at += CONNECTION_STRUCT_SIZE
        if len(c) < CONNECTION_STRUCT_SIZE:
            raise ValueError(f"{who} {direction} connection struct runs past ROM end")

        ngroup, nmap = c[0], c[1]
        strip_ptr = _u16_le(c, 2)
        strip_loc = _u16_le(c, 4)
        strip_len = c[6]
        connected_width = c[7]
        if connected_width == 0:
            raise ValueError(f"{who} {direction} connection has zero-width neighbour")

        # Where the strip pointer counts from. Stock: the neighbour's own blocks,
        # so resolve that neighbour's header for its block address; a neighbour we
        # cannot resolve simply gets no overlay (the same as one that won't load).
        if format.connection_source == CONN_SRC_SCRATCH:
            src_base = syms["wDecompressScratch"].addr
        else:
            try:
                nb_hdr = _headers(rom, syms, ngroup, nmap,
                                  f"{who} {direction} neighbour")
            except ValueError:
                continue
            src_base = _u16_le(rom, nb_hdr.secondary_off + 4)

        src_off = strip_ptr - src_base
        dst_off = strip_loc - overworld_base
        if src_off < 0 or dst_off < 0:
            raise ValueError(
                f"{who} {direction} connection pointer below its source/dest base "
                f"(strip={strip_ptr:#06x}, loc={strip_loc:#06x})"
            )
        src_row, src_col = divmod(src_off, connected_width)
        dst_row, dst_col = divmod(dst_off, dest_stride)
        if direction in ("north", "south"):
            rows, cols = CONNECTION_STRIP_DEPTH, strip_len
        else:
            rows, cols = strip_len, CONNECTION_STRIP_DEPTH

        out.append(Connection(
            direction=direction,
            group=ngroup,
            map_id=nmap,
            source_row=src_row,
            source_col=src_col,
            dest_row=dst_row,
            dest_col=dst_col,
            rows=rows,
            cols=cols,
        ))
    return out


def compute_screen_save(
    bd: BlockData,
    x: int,
    y: int,
    *,
    neighbors: "tuple[tuple[Connection, BlockData], ...] | list[tuple[Connection, BlockData]]" = (),
) -> bytes:
    """Return the 30 bytes the game would have written to wScreenSave if the
    player had been standing at (x, y) on this map when they saved.

    Mirrors the data flow:
        1. LoadBlockData: zero-fill wOverworldMap, write the height*width
           block grid centered at offset (PADDING, PADDING).
        2. GetCoordOfUpperLeftCorner: anchor = (Y/2+1)*(width+6) + (X/2+1)
        3. SaveScreen_LoadNeighbor writes a 5-row x 6-col window from the
           anchor INTO wOverworldMap from wScreenSave; since we want the
           game to read the same map back, we just emit what wOverworldMap
           contains at that window.

    Padding regions the current map doesn't cover stay zero (= block 0) unless
    a connection fills them. Pass `neighbors` — the `(Connection, BlockData)`
    pairs from `map_connections`, with each neighbour's blockdata loaded — to
    overlay the neighbouring maps' edge blocks exactly as FillMapConnections
    would have, so an edge position on a connected map reads the real border
    instead of void. See docs/blockdata-plan.md.
    """
    if not (0 <= x < 256 and 0 <= y < 256):
        raise ValueError(f"(x, y) = ({x}, {y}) out of byte range")

    anchor_col = (x >> 1) + 1
    anchor_row = (y >> 1) + 1

    out = bytearray(SCREEN_SAVE_SIZE)
    for row in range(SCREEN_SAVE_ROWS):
        for col in range(SCREEN_SAVE_COLS):
            wr = anchor_row + row   # row index inside wOverworldMap
            wc = anchor_col + col   # col index inside wOverworldMap
            # The actual blocks occupy rows PADDING..PADDING+height-1 and
            # cols PADDING..PADDING+width-1. Everything outside is padding
            # (zero in wOverworldMap unless connections fill it).
            if (
                PADDING <= wr < PADDING + bd.height
                and PADDING <= wc < PADDING + bd.width
            ):
                grid_row = wr - PADDING
                grid_col = wc - PADDING
                out[row * SCREEN_SAVE_COLS + col] = bd.blocks[
                    grid_row * bd.width + grid_col
                ]
            # else: stays zero, or a connection fills it below

    # Overlay each connection's strip into the padding cells that fall inside the
    # window. Processed in the N/S/W/E order the engine fills them, so a corner
    # claimed by two strips ends up with the same one that wins in-game.
    for conn, nb in neighbors:
        for k in range(conn.rows):
            for j in range(conn.cols):
                row = conn.dest_row + k - anchor_row
                col = conn.dest_col + j - anchor_col
                if not (0 <= row < SCREEN_SAVE_ROWS and 0 <= col < SCREEN_SAVE_COLS):
                    continue
                nr = conn.source_row + k
                ncol = conn.source_col + j
                if not (0 <= nr < nb.height and 0 <= ncol < nb.width):
                    continue
                out[row * SCREEN_SAVE_COLS + col] = nb.blocks[nr * nb.width + ncol]
    return bytes(out)


def _u16_le(data: bytes, offset: int) -> int:
    return data[offset] | (data[offset + 1] << 8)
