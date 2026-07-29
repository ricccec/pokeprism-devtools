"""Reset the on-map object engine state (player + NPCs) for a custom (x, y).

The game's MAPSETUP_CONTINUE path doesn't re-initialize wObjectStructs or
wMapObjects on boot — it assumes the saved state is consistent with the
current map. When we teleport via save-patching, the player's struct
still holds the previous map's position (= player invisible, off-screen)
and NPC slots hold the previous map's NPCs (= ghost NPCs / glitches).

This module replicates just enough of SpawnPlayer + RefreshPlayerCoords
to make the player render at the new (x, y), and optionally zeros the
NPC slots so stale objects from the previous map don't show up.

Coordinate convention (verified from real saves and `engine/spawn_player.asm`):
    OBJECT_MAP_X / wPlayerStandingMapX = wXCoord + 4
    OBJECT_MAP_Y / wPlayerStandingMapY = wYCoord + 4

Clearing the NPC slots is only half the job: it stops the *old* map's NPCs from
haunting the new one, but it leaves the new map empty, which is the wrong answer
when the whole reason you teleported there was to look at an NPC you just placed.
So `load_map_npcs` puts them back, by doing what the engine's ReadObjectEvents
would have done on a normal warp — see `blockdata.object_events` for where the
bytes come from.
"""

from __future__ import annotations

# Object struct layout (from wram.asm `MACRO object_struct`). 40 bytes total.
OBJ_STEP_TYPE       = 9
OBJ_STEP_DURATION   = 10
OBJ_STEP_FRAME      = 12
OBJ_STANDING_TILE   = 14   # collision under player; engine recomputes
OBJ_LAST_TILE       = 15
OBJ_STANDING_MAP_X  = 16   # wPlayerStandingMapX alias for player slot
OBJ_STANDING_MAP_Y  = 17
OBJ_LAST_MAP_X      = 18
OBJ_LAST_MAP_Y      = 19
OBJ_INIT_X          = 20
OBJ_INIT_Y          = 21
OBJECT_STRUCT_LEN   = 40

# Object struct fields we populate at instantiation (canonical names, from the
# `object struct` const block in `constants/map_constants.asm`). The player-slot
# reset above uses its own STANDING_/LAST_ aliases for some of these offsets.
OBJ_SPRITE           = 0
OBJ_MAP_OBJECT_INDEX = 1
OBJ_SPRITE_TILE      = 2
OBJ_MOVEMENTTYPE     = 3
OBJ_FLAGS1           = 4
OBJ_FLAGS2           = 5
OBJ_PALETTE          = 6
OBJ_FACING           = 8
OBJ_ACTION           = 11
OBJ_FACING_STEP      = 13
OBJ_NEXT_MAP_X       = 16
OBJ_NEXT_MAP_Y       = 17
OBJ_MAP_X            = 18
OBJ_MAP_Y            = 19
OBJ_RADIUS           = 22
OBJ_SPRITE_X         = 23
OBJ_SPRITE_Y         = 24
OBJ_RANGE            = 32

#: Values CopyTempObjectToObjectStruct writes verbatim: the struct starts settled
#: at STEP_TYPE_00 with a standing facing-step, and the engine evolves both on the
#: first frame (as it would after any warp).
STEP_TYPE_00 = 0
STANDING = 0xFF

# Map object layout (from `constants/map_constants.asm:93-110`). 16 bytes.
MAPOBJ_OBJECT_STRUCT_ID = 0
MAPOBJ_SPRITE           = 1
MAPOBJ_Y_COORD          = 2
MAPOBJ_X_COORD          = 3
MAPOBJ_MOVEMENT         = 4
MAPOBJ_RADIUS           = 5
MAPOBJ_COLOR            = 8
MAPOBJ_PARAMETER        = 9
MAPOBJ_E                = 14   # first of the two unused trailing bytes
MAP_OBJECT_LEN          = 16

# wMapObjects holds NUM_OBJECTS = 16 slots (slot 0 the player, 1..15 the NPCs).
NUM_OBJECTS = 16

# InitializeVisibleSprites' screen window (constants/map_constants.asm):
# an NPC shows when (mapobj_coord + 1 - player_coord) is in [0, SCREEN).
MAPOBJECT_SCREEN_HEIGHT = 11
MAPOBJECT_SCREEN_WIDTH  = 12

#: The span CopyMapObjectHeaders copies out of a `person_event`: everything from
#: the sprite up to the unused bytes, which is exactly what the macro emits.
PERSON_EVENT_LEN = MAPOBJ_E - MAPOBJ_SPRITE   # 13

#: The struct id of an NPC that is not on screen. The engine binds a real slot
#: when the NPC comes into view; every entry ReadObjectEvents writes starts here,
#: including the ones for NPCs standing right next to you.
OBJECT_STRUCT_ID_NONE = 0xFF

#: An unoccupied slot is *not* zeroed — ReadObjectEvents leaves sprite 0 and sets
#: y to -1. Zero is a legal y, so a zeroed slot is an NPC standing in a corner.
EMPTY_SLOT_Y = 0xFF

# Counts (from the object_struct macro list: wPlayer + wObject1..wObject12 = 13).
NUM_OBJECT_STRUCTS = 13
# wMapObjects size / MAP_OBJECT_LEN = 256 / 16 = 16 entries (verified at runtime).


def reset_player_and_clear_npcs(
    sav,
    *,
    object_structs_offset: int,
    map_objects_offset: int,
    map_objects_size: int,
    x: int,
    y: int,
    keep_npcs: bool = False,
    object_struct_len: int = OBJECT_STRUCT_LEN,
    map_object_len: int = MAP_OBJECT_LEN,
) -> dict:
    """Reset the player ObjectStruct for new (x, y) and (unless keep_npcs)
    zero non-player slots in both wObjectStructs and wMapObjects.

    `*_offset` are file offsets inside the .sav. Caller resolves them via
    inventory or .sym + savefile.sram_to_file_offset.

    The player-slot field offsets (`OBJ_STANDING_MAP_X` … `OBJECT_STRUCT_ID`) are
    shared across the stock-family trees *and polished* — polished only resized
    the struct tail and slot count, not these leading fields. Those two sizes are
    the whole difference, so they cross as data: `object_struct_len` /
    `map_object_len` default to stock's 40 / 16 (vanilla and prism unchanged) and
    polished passes its own 34 / 14. Nothing here learns which tree it is.

    Returns a dict of human-readable changes for the launcher's diff log.
    """
    coord_x = (x + 4) & 0xFF
    coord_y = (y + 4) & 0xFF
    changes: dict[str, str] = {}

    # ── wObjectStructs[0] = player ───────────────────────────────
    p = object_structs_offset
    # Position fields (the engine reads these for sprite placement +
    # collision lookup).
    sav.data[p + OBJ_STANDING_MAP_X] = coord_x
    sav.data[p + OBJ_STANDING_MAP_Y] = coord_y
    sav.data[p + OBJ_LAST_MAP_X]     = coord_x
    sav.data[p + OBJ_LAST_MAP_Y]     = coord_y
    sav.data[p + OBJ_INIT_X]         = coord_x
    sav.data[p + OBJ_INIT_Y]         = coord_y
    # Clear in-flight movement state (the engine will re-derive on the
    # first frame via GetMovementPermissions / RefreshMapSprites).
    sav.data[p + OBJ_STEP_TYPE]      = 0
    sav.data[p + OBJ_STEP_DURATION]  = 0
    sav.data[p + OBJ_STEP_FRAME]     = 0
    sav.data[p + OBJ_STANDING_TILE]  = 0
    sav.data[p + OBJ_LAST_TILE]      = 0
    changes["player_struct"] = f"coords → ({coord_x}, {coord_y}); tile state reset"

    # ── wMapObjects[0] = player MapObject ────────────────────────
    m = map_objects_offset
    sav.data[m + MAPOBJ_Y_COORD] = coord_y
    sav.data[m + MAPOBJ_X_COORD] = coord_x
    changes["player_map_object"] = f"coords → ({coord_x}, {coord_y})"

    if keep_npcs:
        return changes

    # ── Zero non-player ObjectStructs (slots 1..N-1) ─────────────
    npc_struct_bytes = (NUM_OBJECT_STRUCTS - 1) * object_struct_len
    sav.data[
        object_structs_offset + object_struct_len
        : object_structs_offset + object_struct_len + npc_struct_bytes
    ] = bytes(npc_struct_bytes)
    changes["npc_structs"] = f"zeroed slots 1..{NUM_OBJECT_STRUCTS - 1}"

    # ── Zero non-player MapObjects (slots 1..N-1) ────────────────
    npc_mapobj_bytes = map_objects_size - map_object_len
    sav.data[
        map_objects_offset + map_object_len
        : map_objects_offset + map_objects_size
    ] = bytes(npc_mapobj_bytes)
    changes["map_object_slots"] = f"zeroed {npc_mapobj_bytes // map_object_len} NPC entries"

    return changes


def load_map_npcs(
    sav,
    *,
    map_objects_offset: int,
    map_objects_size: int,
    events: list[bytes],
    map_object_len: int = MAP_OBJECT_LEN,
    person_event_len: int = PERSON_EVENT_LEN,
) -> dict:
    """Put the destination map's NPCs into wMapObjects[1..], from ROM.

    This is `ReadObjectEvents` (home/map.asm:375) done in Python, and it is a
    copy rather than a translation on purpose: each entry is `$ff` followed by
    the map's `person_event` bytes verbatim, because that is precisely what
    `CopyMapObjectHeaders` does. The y and x in those bytes already carry the
    `+4` the macro added at assembly time, so they need no adjusting — the same
    convention the player's coords use, four lines up.

    `map_object_len`/`person_event_len` default to stock's 16 / 13; polished's
    map object is 14 bytes and its `object_event` still 13, so its record fills
    the slot with no trailing pad. As in `reset_player_and_clear_npcs`, only the
    sizes cross — the copy itself learns no tree.

    Call *after* `reset_player_and_clear_npcs`: the engine clears the object
    structs before it reads the headers, and so must we, or an NPC inherits the
    walk state of whoever stood in that slot on the last map.

    Slots past the last NPC get sprite 0 and y = -1, not zeros. Zero is a legal
    coordinate.
    """
    slots = map_objects_size // map_object_len
    if slots < 1:
        raise ValueError(f"wMapObjects holds {map_objects_size} bytes — no room for the player")
    for i, event in enumerate(events):
        if len(event) != person_event_len:
            raise ValueError(
                f"object event {i} is {len(event)} bytes, expected {person_event_len}"
            )

    # Slot 0 is the player; the NPCs start at wMap1Object. A map with more
    # object events than there are slots is a map the engine would also fail to
    # load fully, so drop the tail rather than write past wMapObjects.
    room = slots - 1
    loaded = events[:room]

    for i, event in enumerate(loaded):
        at = map_objects_offset + (i + 1) * map_object_len
        sav.data[at + MAPOBJ_OBJECT_STRUCT_ID] = OBJECT_STRUCT_ID_NONE
        sav.data[at + MAPOBJ_SPRITE : at + MAPOBJ_SPRITE + person_event_len] = event
        # Zero any bytes between the copied record and the slot's end (stock
        # leaves two unused trailing bytes; polished's record fills the slot).
        sav.data[at + MAPOBJ_SPRITE + person_event_len : at + map_object_len] = bytes(
            map_object_len - MAPOBJ_SPRITE - person_event_len)

    for i in range(len(loaded), room):
        at = map_objects_offset + (i + 1) * map_object_len
        sav.data[at + MAPOBJ_SPRITE] = 0
        sav.data[at + MAPOBJ_Y_COORD] = EMPTY_SLOT_Y

    changes = {"map_npcs": f"loaded {len(loaded)} NPC(s) from the map's event header"}
    if len(events) > room:
        changes["map_npcs_dropped"] = (
            f"{len(events) - room} object event(s) past the {room} available slots"
        )
    return changes


def _incremented_radius(radius: int) -> int:
    """`InitRadius` — increment the low and high nibble of `radius` separately.

    The engine does `inc a`, then adds `$10` unless that inc already carried into
    the high nibble (i.e. unless the low nibble wrapped to 0). So `$00 -> $11`.
    """
    a = (radius + 1) & 0xFF
    return a if (a & 0x0F) == 0 else (a + 0x10) & 0xFF


def instantiate_visible_sprites(
    sav,
    *,
    object_structs_offset: int,
    map_objects_offset: int,
    map_objects_size: int,
    x: int,
    y: int,
    sprite_tiles: dict[int, int],
    sprite_palettes: dict[int, int],
    movement_data: list[tuple[int, int, int, int, int]],
    default_tile: int = 0,
    global_offset_x: int = 0,
    global_offset_y: int = 0,
    object_struct_len: int = OBJECT_STRUCT_LEN,
    map_object_len: int = MAP_OBJECT_LEN,
    num_objects: int = NUM_OBJECTS,
    num_object_structs: int = NUM_OBJECT_STRUCTS,
    tile_of=None,
    set_palette=None,
) -> dict:
    """Populate `wObjectStructs` for the NPCs on screen, as the engine would.

    `MAPSETUP_CONTINUE` never runs `InitializeVisibleSprites`, so a patched save's
    on-screen NPCs are defined in `wMapObjects` (via `load_map_npcs`) but never
    instantiated — invisible. This walks `wMapObjects[1..]`, and for each NPC whose
    map coords fall in the player's screen window, fills the next free object
    struct exactly as `CopyMapObjectToObjectStruct` + `CopySpriteMovementData` do,
    then binds the map object to that struct (its `OBJECT_STRUCT_ID`).

    Only the fields those two routines set are written; the engine re-derives the
    animated remainder (step type, walking direction) on the first frame, the same
    as it does right after a normal warp. Call *after* `reset_player_and_clear_npcs`
    (which zeroes the slots) and `load_map_npcs` (which fills `wMapObjects`).

    The three lookups come from `spritevram` (`sprite_tiles`, `sprite_palettes`,
    `movement_data`); `default_tile` is the player's tile, the value `GetSpriteVTile`
    falls back to for a sprite absent from the VRAM list. `x`/`y` are the raw
    player coords (`wXCoord`/`wYCoord`); the map coords in `wMapObjects` already
    carry the `+4` the `person_event` macro added, and the window check mixes the
    two exactly as the engine does.

    The `*_len`/`num_*` sizes default to stock's (vanilla and prism unchanged);
    polished passes its own 34 / 14 / 21 / 13. The two behavioural forks cross as
    adapter-supplied strategies, so the neutral loop names no tree: `tile_of(sprite,
    struct_index)` yields the sprite's VRAM tile (stock looks it up in the pool
    `sprite_tiles`; polished's tile is positional, `12*slot`), and `set_palette(sav,
    struct_offset, sprite, mapobject_offset, move_palette)` writes the tree's palette
    field(s) (stock combines a colour nibble into one byte; polished writes an index
    and flags to two). Left `None`, both reproduce stock exactly.
    """
    n_slots = map_objects_size // map_object_len
    struct_index = 1  # object struct 0 is the player
    instantiated: list[tuple[int, int, int]] = []

    for mi in range(1, min(n_slots, num_objects)):
        mo = map_objects_offset + mi * map_object_len
        sprite = sav.data[mo + MAPOBJ_SPRITE]
        if sprite == 0:
            continue
        if sav.data[mo + MAPOBJ_OBJECT_STRUCT_ID] != OBJECT_STRUCT_ID_NONE:
            continue  # already bound to a struct

        mx = sav.data[mo + MAPOBJ_X_COORD]
        my = sav.data[mo + MAPOBJ_Y_COORD]
        # An 8-bit underflow (NPC behind the player) wraps to a large value, so the
        # single upper-bound test rejects it too — exactly the engine's `jr c` + `cp`.
        if (mx + 1 - x) & 0xFF >= MAPOBJECT_SCREEN_WIDTH:
            continue
        if (my + 1 - y) & 0xFF >= MAPOBJECT_SCREEN_HEIGHT:
            continue
        if struct_index >= num_object_structs:
            break  # no free struct — CopyObjectStruct returns carry and gives up

        sav.data[mo + MAPOBJ_OBJECT_STRUCT_ID] = struct_index
        _write_object_struct(
            sav,
            object_structs_offset + struct_index * object_struct_len,
            struct_index=struct_index,
            mapobject_offset=mo,
            map_object_index=mi,
            sprite=sprite,
            movement=sav.data[mo + MAPOBJ_MOVEMENT],
            radius=sav.data[mo + MAPOBJ_RADIUS],
            param=sav.data[mo + MAPOBJ_PARAMETER],
            mx=mx,
            my=my,
            px=x,
            py=y,
            sprite_tiles=sprite_tiles,
            sprite_palettes=sprite_palettes,
            movement_data=movement_data,
            default_tile=default_tile,
            global_offset_x=global_offset_x,
            global_offset_y=global_offset_y,
            object_struct_len=object_struct_len,
            tile_of=tile_of,
            set_palette=set_palette,
        )
        instantiated.append((struct_index, mi, sprite))
        struct_index += 1

    if instantiated:
        desc = ", ".join(f"slot {s}=sprite {sp} (map obj {mi})" for s, mi, sp in instantiated)
    else:
        desc = "(none on screen)"
    return {"visible_sprites": f"instantiated {len(instantiated)}: {desc}"}


def _write_object_struct(
    sav,
    p: int,
    *,
    struct_index: int,
    mapobject_offset: int,
    map_object_index: int,
    sprite: int,
    movement: int,
    radius: int,
    param: int,
    mx: int,
    my: int,
    px: int,
    py: int,
    sprite_tiles: dict[int, int],
    sprite_palettes: dict[int, int],
    movement_data: list[tuple[int, int, int, int, int]],
    default_tile: int,
    global_offset_x: int,
    global_offset_y: int,
    object_struct_len: int = OBJECT_STRUCT_LEN,
    tile_of=None,
    set_palette=None,
) -> None:
    """Write one instantiated NPC into the object struct at file offset `p`.

    Mirrors `CopyTempObjectToObjectStruct` + `CopySpriteMovementData`. The slot is
    zeroed first so only the settled fields are set (the engine finds an empty slot
    for the same reason). The struct's leading fields are shared across the
    stock-family and polished; only the VRAM-tile source and the palette field
    layout fork, and both cross as adapter strategies (`tile_of` / `set_palette`).
    """
    sav.data[p : p + object_struct_len] = bytes(object_struct_len)

    sav.data[p + OBJ_MAP_OBJECT_INDEX] = map_object_index

    # CopySpriteMovementData: movement type, then the table row's facing/action/
    # flags. GetSpriteMovementFunction clamps an out-of-range movement to 0.
    mv = movement if 0 <= movement < len(movement_data) else 0
    facing_raw, action, flags1, flags2, move_palette = movement_data[mv]
    sav.data[p + OBJ_MOVEMENTTYPE] = movement
    sav.data[p + OBJ_FACING] = (facing_raw << 2) & 0x0C
    sav.data[p + OBJ_ACTION] = action
    sav.data[p + OBJ_FLAGS1] = flags1
    sav.data[p + OBJ_FLAGS2] = flags2

    # Palette. Stock (default) folds the sprite's default palette, the map object's
    # colour nibble and the movement row's flags into the single OBJECT_PALETTE
    # byte; a tree whose palette lives in different fields supplies `set_palette`.
    if set_palette is not None:
        set_palette(sav, p, sprite, mapobject_offset, move_palette)
    else:
        color = sav.data[mapobject_offset + MAPOBJ_COLOR]
        palette = sprite_palettes.get(sprite, 0)
        if color & 0xF0:
            palette = (color >> 4) & 0x07
        sav.data[p + OBJ_PALETTE] = palette | move_palette

    # Coords: the map object's own X/Y seed INIT / NEXT_MAP / MAP; SPRITE_X/Y are
    # the pixel offset from the player, (Δtile & $f) << 4 minus the global offset.
    sav.data[p + OBJ_NEXT_MAP_X] = mx
    sav.data[p + OBJ_MAP_X] = mx
    sav.data[p + OBJ_INIT_X] = mx
    sav.data[p + OBJ_NEXT_MAP_Y] = my
    sav.data[p + OBJ_MAP_Y] = my
    sav.data[p + OBJ_INIT_Y] = my
    sav.data[p + OBJ_SPRITE_X] = ((((mx - px) & 0x0F) << 4) - global_offset_x) & 0xFF
    sav.data[p + OBJ_SPRITE_Y] = ((((my - py) & 0x0F) << 4) - global_offset_y) & 0xFF

    sav.data[p + OBJ_SPRITE] = sprite
    sav.data[p + OBJ_SPRITE_TILE] = (
        tile_of(sprite, struct_index) if tile_of is not None
        else sprite_tiles.get(sprite, default_tile))
    sav.data[p + OBJ_STEP_TYPE] = STEP_TYPE_00
    sav.data[p + OBJ_FACING_STEP] = STANDING
    sav.data[p + OBJ_RADIUS] = _incremented_radius(radius)
    sav.data[p + OBJ_RANGE] = param
