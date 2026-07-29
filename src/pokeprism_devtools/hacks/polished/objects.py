"""Read polished's map objects from the ROM — the Stage-2 half of the boot.

Stage 1 stands the player on a clean, empty map. Stage 2 puts the map's own NPCs
back: their records for `wMapObjects`, and — for the ones on screen — the VRAM
tile, palette and movement each instantiated `wObjectStructs` slot needs. These are
the reads polished spells differently from the stock family, so they live here on
polished's side; the neutral `people` helper does the writing, driven by the sizes
and two strategies this module hands it.

Three polished facts drive it:

  * **Events by symbol, no header walk.** No per-map object-events label exists, but
    `<Label>_MapScriptHeader` is exported, and polished lays scene-scripts →
    callbacks → warps → coords → bg-events → object-events out contiguously under it,
    each section `db count`-prefixed. So the objects are reached by resolving that one
    symbol (as Stage 1 resolves `<Label>_BlockData`) and skipping the five leading
    count-prefixed sections — a bounded walk, not the 7-byte-primary map header.
  * **VRAM is positional.** `GetSpriteVTile` (home/map_objects.asm) derives the tile
    straight from the object-struct slot index — `12 * (slot % 8)`, `| $80` for the
    VRAM0 bank — with three oversized sprites forced to the last struct. There is no
    used-sprites pool to reproduce, so `shared.overworld.spritevram` is not used here.
  * **Palette lives in two fields.** `CopyMapObjectToObjectStruct` writes the movement
    row's palette flags to `OBJECT_PALETTE` ($06) and the sprite's palette *index*
    (its `SpriteHeaders` default, or the map object's own `MAPOBJECT_PALETTE - 1` when
    set) to `OBJECT_PAL_INDEX` ($21) — not stock's single colour-nibble byte.
"""

from __future__ import annotations

from ...shared.overworld import blockdata
from ...shared.symfile import SymFile

#: The object-event record: `sprite, y+4, x+4, movement, packed-radius, palette,
#: time-of-day, type, sight/command, pointer+flag` (`macros/scripts/maps.asm`). 13
#: bytes — the same length stock copies — dropped verbatim into `wMapObjects[1..14]`.
OBJECT_EVENT_LEN = 13

#: The five sections that precede the object events under `<Label>_MapScriptHeader`,
#: each `db count` then `count` fixed-size entries. Polished's own sizes (its coord
#: and bg events are 5 bytes, not stock's 8) — read from the section macros.
_LEADING_SECTIONS = (
    ("scene scripts", 2),   # dw script
    ("callbacks",     3),   # db type; dw script
    ("warp events",   5),   # db y, x, warp_to; map_id (group, map)
    ("coord events",  5),   # db scene, y, x; dw script
    ("bg events",     5),   # db y, x, function; dw pointer
)

#: SpriteHeaders (`constants/sprite_data_constants.asm`): 4-byte rows, one per sprite
#: id from 1, the palette in the low 6 bits of the type/palette byte at offset 3.
_HEADER_SIZE = 4
_HEADER_TYPE_PAL = 3
_PALETTE_MASK = 0x3F
#: The first Pokémon-icon id: at and past it a sprite has no header row (GetMonSprite
#: takes over), so its palette falls back rather than reading off the end of the table.
_SPRITE_MON_ICON = 0xEF

#: SpriteMovementData: 6-byte rows, movement id → (fn, facing, action, flags1, flags2,
#: palflags). Polished has 52 rows (stock 40); indexing past the end would raise.
_MOVEMENT_ENTRY_SIZE = 6
_MOVEMENT_ENTRIES = 52

#: GetSpriteVTile: each object-struct slot owns a fixed 12-tile VRAM window; slots
#: below FIRST_VRAM1 sit in VRAM0 (the `$80` bank flag), the rest in VRAM1.
_TILES_PER_STRUCT = 12
_FIRST_VRAM1_STRUCT = 8
_NUM_OBJECT_STRUCTS = 13
_VRAM0_FLAG = 0x80
#: The three sprites GetSpriteVTile forces into the last struct (too many tiles, or
#: needing VRAM1 so text won't overwrite them).
_LAST_STRUCT_SPRITES = frozenset({0xAF, 0xBF, 0xC5})  # BIG_GYARADOS, SAILBOAT, ALOLAN_EXEGGUTOR

#: Object-struct / map-object palette field offsets (`map_object_constants.asm`).
_OBJECT_PALETTE = 0x06
_OBJECT_PAL_INDEX = 0x21
_MAPOBJECT_PALETTE = 0x06


def object_events(rom: bytes, syms: SymFile, label: str) -> list[bytes]:
    """The map's object-event records, in ROM order — one 13-byte record per NPC.

    Resolves `<label>_MapScriptHeader` and walks past the five count-prefixed
    sections to the object events. Each returned record drops straight into a
    `wMapObjects` slot (`$ff`, then these bytes) via `people.load_map_npcs`.
    """
    sym = syms.get(f"{label}_MapScriptHeader")
    if sym is None:
        raise ValueError(
            f"the build's .sym has no {label}_MapScriptHeader — is this a polished "
            "checkout, built with symbols?")
    pos = blockdata.rom_offset(sym.bank, sym.addr)
    for name, entry in _LEADING_SECTIONS:
        if pos >= len(rom):
            raise ValueError(f"{label}: walked off the ROM before the {name} count")
        pos += 1 + rom[pos] * entry
    count = rom[pos]
    pos += 1
    end = pos + count * OBJECT_EVENT_LEN
    if end > len(rom):
        raise ValueError(f"{label}: {count} object events run past the ROM end")
    return [bytes(rom[pos + i * OBJECT_EVENT_LEN: pos + (i + 1) * OBJECT_EVENT_LEN])
            for i in range(count)]


def movement_data(rom: bytes, syms: SymFile) -> list[tuple[int, int, int, int, int]]:
    """`SpriteMovementData` as `(facing, action, flags1, flags2, palflags)` rows.

    The row's first byte (the movement *function*) is skipped, exactly as
    `CopySpriteMovementData` starts at the facing field. Same 6-byte format as stock,
    but polished's table is longer, so it is read here with polished's own count.
    """
    table = syms["SpriteMovementData"]
    base = blockdata.rom_offset(table.bank, table.addr)
    rows: list[tuple[int, int, int, int, int]] = []
    for i in range(_MOVEMENT_ENTRIES):
        at = base + i * _MOVEMENT_ENTRY_SIZE
        facing, action, flags1, flags2, palflags = rom[at + 1: at + 6]
        rows.append((facing, action, flags1, flags2, palflags))
    return rows


def sprite_palettes(rom: bytes, syms: SymFile, sprite_ids: list[int]) -> dict[int, int]:
    """`{sprite_id: default palette index}` from `SpriteHeaders` (GetSpritePalette).

    The palette is the low 6 bits of the sprite's header type/palette byte. A map
    object may override this from its own `MAPOBJECT_PALETTE`; that override is applied
    where the struct is written (see `palette_strategy`), not here. Pokémon-icon ids
    have no header row and fall back to palette 0.
    """
    headers = syms["SpriteHeaders"]
    base = blockdata.rom_offset(headers.bank, headers.addr)
    out: dict[int, int] = {}
    for sid in sprite_ids:
        if 1 <= sid < _SPRITE_MON_ICON:
            out[sid] = rom[base + (sid - 1) * _HEADER_SIZE + _HEADER_TYPE_PAL] & _PALETTE_MASK
        else:
            out[sid] = 0
    return out


def sprite_vtile(struct_index: int, sprite: int) -> int:
    """The VRAM tile for a sprite instantiated into object-struct slot `struct_index`.

    `GetSpriteVTile`: the tile is `12 * (slot % 8)`, in VRAM0 (`| $80`) for the first
    eight slots and VRAM1 after, except three oversized sprites which are forced to
    the last struct. Positional, so slot 0 → `$80` and slot 1 → `$8c`.
    """
    idx = _NUM_OBJECT_STRUCTS - 1 if sprite in _LAST_STRUCT_SPRITES else struct_index
    if idx >= _FIRST_VRAM1_STRUCT:
        return (idx - _FIRST_VRAM1_STRUCT) * _TILES_PER_STRUCT
    return idx * _TILES_PER_STRUCT | _VRAM0_FLAG


def tile_strategy():
    """The `tile_of(sprite, struct_index)` the neutral instantiate loop calls."""
    return lambda sprite, struct_index: sprite_vtile(struct_index, sprite)


def palette_strategy(defaults: dict[int, int]):
    """The `set_palette` the neutral instantiate loop calls, closing over the sprite
    palette `defaults`. Writes the movement flags to `OBJECT_PALETTE` and the palette
    index (sprite default, or the map object's `MAPOBJECT_PALETTE - 1` override) to
    `OBJECT_PAL_INDEX`, as `CopyMapObjectToObjectStruct` does."""
    def set_palette(sav, struct_offset, sprite, mapobject_offset, move_palflags):
        sav.data[struct_offset + _OBJECT_PALETTE] = move_palflags
        index = defaults.get(sprite, 0)
        override = sav.data[mapobject_offset + _MAPOBJECT_PALETTE]
        if override != 0:
            index = override - 1
        sav.data[struct_offset + _OBJECT_PAL_INDEX] = index
    return set_palette
