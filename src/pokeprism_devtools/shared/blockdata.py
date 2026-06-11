"""Read a map's blockdata from the pokeprism ROM, and compute the
`wScreenSave` window the game would have written for a given player
position.

Used by prism-dev to keep wScreenSave consistent with (wMapGroup,
wMapNumber, wXCoord, wYCoord) when patching a save. See
docs/blockdata-plan.md for the data-flow and asm cross-references.

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

from . import lz, symfile

# Sizes derived from the asm — see docs/blockdata-plan.md.
MAP_HEADER_SIZE = 9     # 1 + 1 + 1 + 2 + 1 + 1 + 1 + 1 + 1
SECOND_MAP_HEADER_SIZE = 12
SCREEN_SAVE_ROWS = 5    # outer-loop count in SaveScreen_LoadNeighbor (c)
SCREEN_SAVE_COLS = 6    # inner-loop count (b)
SCREEN_SAVE_SIZE = SCREEN_SAVE_ROWS * SCREEN_SAVE_COLS  # 30
PADDING = 3             # 3-block padding around the actual grid in wOverworldMap


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


def rom_offset(bank: int, addr: int) -> int:
    """Convert a (bank, GB-address) pair to a ROM file offset."""
    if addr < 0x4000:
        return addr  # bank 0 mapped at the start of ROM
    return bank * 0x4000 + (addr - 0x4000)


def load(
    rom_path: Path,
    syms: symfile.SymFile,
    group: int,
    map_id: int,
    *,
    name: str = "",
) -> BlockData:
    """Read and decompress the blockdata for (group, map_id) from the ROM.

    `group` and `map_id` are both 1-based (matching `wMapGroup` /
    `wMapNumber` values). `name` is optional, used only in error messages.
    """
    if group < 1:
        raise ValueError(f"group must be 1-based; got {group}")
    if map_id < 1:
        raise ValueError(f"map_id must be 1-based; got {map_id}")

    rom = rom_path.read_bytes()

    # Walk MapGroupPointers → MapGroup<N> → primary header → secondary header.
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
    second_bank = rom[primary_off]
    # primary header: bank, tileset, permission, dw second_header_addr, ...
    tileset_id = rom[primary_off + 1]
    permission = rom[primary_off + 2]
    second_addr = _u16_le(rom, primary_off + 3)

    secondary_off = rom_offset(second_bank, second_addr)
    if secondary_off + SECOND_MAP_HEADER_SIZE > len(rom):
        raise ValueError(
            f"secondary header for (group={group}, map_id={map_id}) past ROM end"
        )
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
    decompressed, _consumed = lz.decompress(rom, blockdata_off)
    expected = width * height
    if len(decompressed) < expected:
        raise ValueError(
            f"map {name or f'({group},{map_id})'} blockdata decompressed to "
            f"{len(decompressed)} bytes, need at least {expected} ({width}x{height})"
        )
    # The game's ReadMapBlocks copies exactly width*height bytes; trailing
    # data in the compressed stream is ignored. A handful of maps in
    # pokeprism encode more than they need (e.g. SEVII_ISLAND_1, the
    # BATTLE_TOWER_* rooms). Truncate so callers see only the live grid.
    blocks = decompressed[:expected]

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


def compute_screen_save(bd: BlockData, x: int, y: int) -> bytes:
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

    Padding regions stay zero (= block 0). For interior positions on
    indoor maps with no connections, this is exactly what wOverworldMap
    contains. For edge positions on maps with connections, the game's
    FillMapConnections would have filled the padding with neighbor map
    data — see docs/blockdata-plan.md "Limitations".
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
            # else: stays zero
    return bytes(out)


def _u16_le(data: bytes, offset: int) -> int:
    return data[offset] | (data[offset + 1] << 8)
