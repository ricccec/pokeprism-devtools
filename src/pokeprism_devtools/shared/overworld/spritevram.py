"""The ROM tables the overworld reads when it instantiates a map's sprites.

When we hand-instantiate `wObjectStructs` for a patched save (see
`people.instantiate_visible_sprites`, because `MAPSETUP_CONTINUE` skips
`InitializeVisibleSprites`) every struct field the engine would have filled from
ROM has to be filled the same way. This module supplies those inputs:

    sprite_tiles     the VRAM tile each sprite's graphics land at (SPRITE_TILE)
    sprite_palettes  each sprite's default palette (SpriteHeaders)
    movement_data    the per-movement facing/action/flags/palette row

`sprite_tiles` is the involved one: it reproduces `GetSpriteVTile` by replaying
the whole `RefreshSprites` pipeline (`engine/overworld.asm`), because on
`MAPSETUP_CONTINUE` the game *does* rebuild `wUsedSprites` and reload sprite VRAM
(`LoadGraphics` → `RefreshSprites`); it just never runs `InitializeVisibleSprites`
to point any struct at those tiles. So a struct's `SPRITE_TILE` must name the tile
the rebuilt allocator places that sprite at, or it renders from a stale offset:

    zero wUsedSprites
    GetPlayerSprite            -> wUsedSprites[0]
    AddMapSprites              -> append the map's sprite pool, deduped
    LoadSpriteGFX              -> tag each entry with its sprite *type*
    SortUsedSprites            -> stable sort by type ascending
    ArrangeUsedSprites         -> assign cumulative tile offsets, two VRAM tables

Verified byte-for-byte against a real game-written save: the on-screen SPRITE_ROCK
on MtEmberWest lands at tile 200, exactly as the game placed it.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from .. import symfile

# Sprite types (constants/sprite_constants.asm). GetSpriteLength gives STILL_SPRITE
# 4 tiles and everything else 12; only the STILL/non-STILL split matters here.
WALKING_SPRITE = 1
STILL_SPRITE = 3
WALKING_TILES = 12
STILL_TILES = 4

# SpriteHeaders entry: 6 bytes, TYPE at +4, PALETTE at +5 (sprite_constants.asm).
_HEADER_SIZE = 6
_HEADER_TYPE_OFF = 4
_HEADER_PALETTE_OFF = 5

# PAL_OW_PLAYER (= 0): the palette GetMonSprite hands back for monster/variable
# sprite ids, which have no SpriteHeaders row.
_MON_PALETTE = 0

# SpriteMovementData (data/map_objects.asm): 6-byte rows, one per movement type,
# 0x00..0x27. Fields: function, facing, action, flags1, flags2, palette-nibble<<4.
_MOVEMENT_ENTRY_SIZE = 6
_MOVEMENT_ENTRIES = 0x28  # rows 0x00..0x27

# ArrangeUsedSprites spills into a second VRAM table once the first passes $80
# tiles; the whole sprite VRAM is $100 tiles. SPRITE_GFX_LIST_CAPACITY caps the
# list at $20 entries (constants/misc_constants.asm).
FIRST_TABLE_TILES = 0x80
VRAM_TILES = 0x100
LIST_CAPACITY = 0x20


def _rom_offset(bank: int, addr: int) -> int:
    return addr if addr < 0x4000 else bank * 0x4000 + (addr - 0x4000)


def _u16_le(data: bytes, offset: int) -> int:
    return data[offset] | (data[offset + 1] << 8)


@lru_cache(maxsize=8)
def _pokemon_sprite_id(constants_path: Path) -> int:
    """`SPRITE_POKEMON` — the first sprite id the engine treats as a monster.

    Sprite ids at or above it go through `GetMonSprite` (which reports them as
    walking sprites) instead of the sprite-header table, so it is the cut-off
    for reading a real type byte out of ROM. Recovered by replaying the assembler
    counter up to the `SPRITE_POKEMON EQU const_value` line, so a reorder of the
    sprite list can't silently shift it. Stock pokecrystal spells the definition
    `DEF SPRITE_POKEMON EQU ...` (modern rgbds); prism omits the `DEF`, so strip a
    leading `DEF ` before matching and both are read the same.
    """
    counter = 0
    for raw in constants_path.read_text().splitlines():
        line = raw.split(";", 1)[0].strip()
        if not line:
            continue
        if line.startswith("DEF "):
            line = line[4:].lstrip()
        if line == "const_def":
            counter = 0
        elif line.startswith("const_def "):
            counter = _to_int(line.split(None, 1)[1])
        elif line.startswith("const_value"):
            counter = _to_int(line.split("=", 1)[1])
        elif line.startswith("const "):
            counter += 1
        elif line.startswith("SPRITE_POKEMON") and "EQU" in line:
            return counter
    raise ValueError(f"SPRITE_POKEMON not found in {constants_path}")


def _to_int(s: str) -> int:
    s = s.strip()
    return int(s[1:], 16) if s.startswith("$") else int(s)


def outdoor_sprite_ids(
    rom_path: Path, syms: symfile.SymFile, group: int, *, name: str = "",
    count: int | None = 23,
) -> list[int]:
    """The sprite pool the overworld loads for maps in `group`.

    `AddMapSprites` (outdoor branch) reads `OutdoorSprites[group - 1]`, a pointer
    to that group's sprite list, and feeds each id to `AddSpriteGFX`. Both the
    table and the list it points at live in the table's own bank.

    How the list ends differs by tree, so `count` says which: stock pokecrystal's
    lists are a **fixed** `MAX_OUTDOOR_SPRITES` (23) entries — `AddOutdoorSprites`
    reads exactly that many, `AddSpriteGFX` no-ops on a 0 — so `count=23` reads 23
    and drops the zero padding. Prism's are **zero-terminated**, read with
    `count=None`. Reading past a fixed list as if it were terminated (the stock
    case) runs straight into the next group's list — a pool of a hundred-plus ids
    that shoulders the map's real sprites out of VRAM, so they fall back to the
    player's tile and render as the player. That is the bug this parameter fixes.
    """
    if group < 1:
        raise ValueError(f"group must be 1-based; got {group}")
    rom = rom_path.read_bytes()
    table = syms["OutdoorSprites"]
    entry = _rom_offset(table.bank, table.addr) + (group - 1) * 2
    if entry + 2 > len(rom):
        raise ValueError(f"OutdoorSprites[{group}] index past ROM end")
    list_off = _rom_offset(table.bank, _u16_le(rom, entry))
    ids: list[int] = []
    if count is None:
        while list_off < len(rom) and rom[list_off] != 0:
            ids.append(rom[list_off])
            list_off += 1
    else:
        for i in range(count):
            if list_off + i >= len(rom):
                break
            v = rom[list_off + i]
            if v != 0:      # a 0 entry is padding; AddSpriteGFX skips it
                ids.append(v)
    return ids


def sprite_tiles(
    rom_path: Path,
    syms: symfile.SymFile,
    player_sprite: int,
    candidate_ids: list[int],
    *,
    headers_symbol: str = "OverworldSprites",
) -> dict[int, int]:
    """Return `{sprite_id: vtile}` — the VRAM tile each sprite id ends up at.

    `player_sprite` is `wUsedSprites[0]` (the player always occupies slot 0);
    `candidate_ids` is the map's sprite pool in `AddMapSprites` order (the
    `OutdoorSprites` list outdoors, or the map's own NPC sprite ids indoors).
    `headers_symbol` names the sprite-header table — the stock `OverworldSprites`,
    or prism's `SpriteHeaders` (same 6-byte entry, different label).
    """
    rom = rom_path.read_bytes()
    headers = syms[headers_symbol]
    headers_off = _rom_offset(headers.bank, headers.addr)
    pokemon_id = _pokemon_sprite_id(rom_path.parent / "constants" / "sprite_constants.asm")

    def type_of(sprite_id: int) -> int:
        # GetSprite routes monster/variable ids through GetMonSprite, which
        # reports them as walking sprites; only lower ids read SpriteHeaders.
        if sprite_id == 0 or sprite_id >= pokemon_id:
            return WALKING_SPRITE
        return rom[headers_off + (sprite_id - 1) * _HEADER_SIZE + _HEADER_TYPE_OFF]

    # AddSpriteGFX: slot 0 is the player; each map sprite is appended unless it is
    # already present. The dedup scans from slot 1, so it never compares against
    # the player — a rare map sprite equal to the player's is added a second time,
    # which is the engine's behaviour too.
    used: list[int] = [player_sprite]
    for sid in candidate_ids:
        if sid == 0:
            continue
        if sid in used[1:]:
            continue
        used.append(sid)
        if len(used) >= LIST_CAPACITY:
            break

    # LoadSpriteGFX tags each entry with its type; SortUsedSprites bubble-sorts by
    # type ascending, swapping only on a strict decrease, so equal types keep their
    # order — a stable sort.
    entries = sorted(((sid, type_of(sid)) for sid in used), key=lambda e: e[1])

    # ArrangeUsedSprites: walk the sorted list assigning cumulative tile offsets,
    # spilling into the second VRAM table the moment the first would pass $80.
    tiles: dict[int, int] = {}
    base = 0
    i = 0
    n = len(entries)
    while i < n:
        sid, typ = entries[i]
        length = STILL_TILES if typ == STILL_SPRITE else WALKING_TILES
        after = base + length
        if after > FIRST_TABLE_TILES:
            break  # this sprite spills; re-place it in the second table
        tiles[sid] = base
        base = after
        i += 1
    if i < n:
        base = FIRST_TABLE_TILES
        while i < n:
            sid, typ = entries[i]
            length = STILL_TILES if typ == STILL_SPRITE else WALKING_TILES
            if base + length >= VRAM_TILES:
                break  # 8-bit add carries (ret c); the engine leaves these unplaced
            tiles[sid] = base
            base += length
            i += 1
    return tiles


def sprite_palettes(
    rom_path: Path, syms: symfile.SymFile, sprite_ids: list[int],
    *, headers_symbol: str = "OverworldSprites",
) -> dict[int, int]:
    """`{sprite_id: default palette}` from the sprite-header table (GetSpritePalette).

    A map object can override this from its own colour nibble; that override is
    applied where the struct is written, not here. Monster/variable ids have no
    header row and report PAL_OW_PLAYER, matching GetMonSprite. `headers_symbol`
    names the table (stock `OverworldSprites`, prism `SpriteHeaders`).
    """
    rom = rom_path.read_bytes()
    headers = syms[headers_symbol]
    headers_off = _rom_offset(headers.bank, headers.addr)
    pokemon_id = _pokemon_sprite_id(rom_path.parent / "constants" / "sprite_constants.asm")
    out: dict[int, int] = {}
    for sid in sprite_ids:
        if sid == 0 or sid >= pokemon_id:
            out[sid] = _MON_PALETTE
        else:
            out[sid] = rom[headers_off + (sid - 1) * _HEADER_SIZE + _HEADER_PALETTE_OFF]
    return out


def movement_data(rom_path: Path, syms: symfile.SymFile) -> list[tuple[int, int, int, int, int]]:
    """`SpriteMovementData` as `(facing, action, flags1, flags2, palette_byte)` rows.

    Indexed by a map object's movement type. The row's first byte (the movement
    *function*) is skipped — CopySpriteMovementData starts at the facing field.
    The 6th byte is already `palette_nibble << 4`, the value the engine ORs into
    OBJECT_PALETTE, so it is returned verbatim.
    """
    rom = rom_path.read_bytes()
    table = syms["SpriteMovementData"]
    base = _rom_offset(table.bank, table.addr)
    rows: list[tuple[int, int, int, int, int]] = []
    for i in range(_MOVEMENT_ENTRIES):
        at = base + i * _MOVEMENT_ENTRY_SIZE
        facing, action, flags1, flags2, palette = rom[at + 1 : at + 6]
        rows.append((facing, action, flags1, flags2, palette))
    return rows
