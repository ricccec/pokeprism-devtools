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
def _sprite_cutoffs(constants_path: Path) -> tuple[int, int]:
    """`(SPRITE_POKEMON, SPRITE_VARS)` — the two id thresholds `GetSprite` splits on.

    Below `SPRITE_POKEMON` a sprite reads its type from the header table. In
    `[SPRITE_POKEMON, SPRITE_VARS)` it is a monster icon (`GetMonSprite` reports it
    as a walking sprite). At or above `SPRITE_VARS` it is a *variable* sprite,
    resolved at runtime through `wVariableSprites[id - SPRITE_VARS]` — so its real
    type (and VRAM length) is only knowable from the save, and getting it wrong
    mis-sizes every sprite the VRAM allocator places after it.

    Recovered by replaying the assembler counter. Both constants sit behind a
    `const_next $XX` that *jumps* the counter (`SPRITE_POKEMON` at `$80`,
    `SPRITE_VARS` at `$f0`), so honouring `const_next` is load-bearing — counting
    `const` lines alone reads them far too low. `DEF ` prefixes (modern rgbds) are
    stripped so prism, which omits them, reads the same. A tree with no
    `SPRITE_VARS` has no variable sprites, so its cut-off is past every id (`$100`).
    """
    pokemon = vars_id = None
    counter = 0
    for raw in constants_path.read_text().splitlines():
        line = raw.split(";", 1)[0].strip()
        if not line:
            continue
        if line.startswith("DEF "):
            line = line[4:].lstrip()
        if line == "const_def":
            counter = 0
        elif line.startswith("const_def ") or line.startswith("const_next"):
            counter = _to_int(line.split(None, 1)[1])
        elif line.startswith("const_value"):
            counter = _to_int(line.split("=", 1)[1])
        elif line.startswith("const "):
            counter += 1
        elif line.startswith("SPRITE_POKEMON") and "EQU" in line:
            pokemon = counter
        elif line.startswith("SPRITE_VARS") and "EQU" in line:
            vars_id = counter
    if pokemon is None:
        raise ValueError(f"SPRITE_POKEMON not found in {constants_path}")
    return pokemon, (vars_id if vars_id is not None else 0x100)


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
    variable_sprites: bytes = b"",
) -> dict[int, int]:
    """Return `{sprite_id: vtile}` — the VRAM tile each sprite id ends up at.

    `player_sprite` is `wUsedSprites[0]` (the player always occupies slot 0);
    `candidate_ids` is the map's sprite pool in `AddMapSprites` order (the
    `OutdoorSprites` list outdoors, or the map's own NPC sprite ids indoors).
    `headers_symbol` names the sprite-header table — the stock `OverworldSprites`,
    or prism's `SpriteHeaders` (same 6-byte entry, different label).

    `variable_sprites` is the save's `wVariableSprites` array (empty if the caller
    hasn't got it). A *variable* sprite id (>= `SPRITE_VARS`) has no fixed type: it
    stands for whatever `wVariableSprites[id - SPRITE_VARS]` names at runtime, which
    can be a still sprite (a Sudowoodo, a boulder) as easily as a walking one. Since
    the allocator sorts by type and a still sprite is 4 tiles where a walking one is
    12, guessing walking for a variable sprite mis-sizes it and shifts the VRAM tile
    of every sprite the sort places after it — the class of bug that renders an NPC
    with the wrong graphics. So resolve it through the array; only an unset entry
    (or no array) falls back to walking, as the engine's `NoBreedmon` does.
    """
    rom = rom_path.read_bytes()
    headers = syms[headers_symbol]
    headers_off = _rom_offset(headers.bank, headers.addr)
    pokemon_id, vars_id = _sprite_cutoffs(
        rom_path.parent / "constants" / "sprite_constants.asm")

    def type_of(sprite_id: int, depth: int = 0) -> int:
        # GetSprite: below SPRITE_POKEMON the type is the header byte; a monster
        # icon (< SPRITE_VARS) is a walking sprite; a variable sprite resolves
        # through wVariableSprites to a real id whose type we then read.
        if sprite_id == 0:
            return WALKING_SPRITE
        if sprite_id < pokemon_id:
            return rom[headers_off + (sprite_id - 1) * _HEADER_SIZE + _HEADER_TYPE_OFF]
        if sprite_id < vars_id:
            return WALKING_SPRITE
        i = sprite_id - vars_id
        if depth < 4 and 0 <= i < len(variable_sprites) and variable_sprites[i]:
            return type_of(variable_sprites[i], depth + 1)
        return WALKING_SPRITE

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

    # LoadSpriteGFX tags each entry with its type; SortUsedSprites orders by type
    # ascending. It is NOT a stable sort: it selects each position's minimum by
    # scanning from the *end* of the list toward the front and swapping on a strict
    # decrease, so a run of equal types comes out reversed relative to input order.
    # That reversal moves which sprites land where — and, near a table boundary,
    # which overflow — so reproducing it (not a convenient stable sort) is what
    # makes a walking NPC land on the tile the game gave it.
    entries: list[tuple[int, int]] = [(sid, type_of(sid)) for sid in used]
    n = len(entries)
    for pivot in range(n - 1):
        j = n - 1
        while j > pivot:
            if entries[j][1] < entries[pivot][1]:
                entries[pivot], entries[j] = entries[j], entries[pivot]
            j -= 1

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
    pokemon_id, _vars = _sprite_cutoffs(
        rom_path.parent / "constants" / "sprite_constants.asm")
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
