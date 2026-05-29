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

# Map object layout (from `constants/map_constants.asm:93-110`). 16 bytes.
MAPOBJ_OBJECT_STRUCT_ID = 0
MAPOBJ_SPRITE           = 1
MAPOBJ_Y_COORD          = 2
MAPOBJ_X_COORD          = 3
MAP_OBJECT_LEN          = 16

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
) -> dict:
    """Reset the player ObjectStruct for new (x, y) and (unless keep_npcs)
    zero non-player slots in both wObjectStructs and wMapObjects.

    `*_offset` are file offsets inside the .sav. Caller resolves them via
    inventory or .sym + savefile.sram_to_file_offset.

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
    npc_struct_bytes = (NUM_OBJECT_STRUCTS - 1) * OBJECT_STRUCT_LEN
    sav.data[
        object_structs_offset + OBJECT_STRUCT_LEN
        : object_structs_offset + OBJECT_STRUCT_LEN + npc_struct_bytes
    ] = bytes(npc_struct_bytes)
    changes["npc_structs"] = f"zeroed slots 1..{NUM_OBJECT_STRUCTS - 1}"

    # ── Zero non-player MapObjects (slots 1..N-1) ────────────────
    npc_mapobj_bytes = map_objects_size - MAP_OBJECT_LEN
    sav.data[
        map_objects_offset + MAP_OBJECT_LEN
        : map_objects_offset + map_objects_size
    ] = bytes(npc_mapobj_bytes)
    changes["map_object_slots"] = f"zeroed {npc_mapobj_bytes // MAP_OBJECT_LEN} NPC entries"

    return changes
