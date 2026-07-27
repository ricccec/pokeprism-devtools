"""Rebuild the map a patched save stands you on — the write-once orchestration.

`MAPSETUP_CONTINUE` loads the coordinates a save holds but not the map around
them: it never re-runs the block-data load, `wScreenSave` fill, or object-header
read that a normal warp does, trusting the saved state to already match the
current map. A save patched to a *new* position therefore renders the previous
map's tiles and NPCs at the new coordinates. :func:`rebuild_map` writes back what
that path skips — the tiles (`wScreenSave`, from the ROM block grid plus the
connected neighbours) and the objects (`wObjectStructs`/`wMapObjects`: the player
reset to the new tile, the old NPCs cleared, the destination map's own loaded and
the on-screen ones instantiated).

It is engine-general Gen-2: the position it rebuilds *for* and the `.sav` offsets
it writes *into* both arrive as declared data (:class:`SaveOffsets`), and the
formats it reads are stock pokecrystal's through the caller's own `SymFile`. It
touches only ``sav.data`` (a bytearray both trees' save objects expose), so a
prism `SaveFile` and a vanilla `Save` drive the same code. Extracted from prism's
`dev_server/apply.py`, where this logic first paid off, so a second tree does not
re-implement it. Which checksums to recompute afterwards is *not* here — that is
the one thing the trees spell differently, and it stays in each adapter.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .. import symfile
from . import blockdata, people, spritevram


@dataclass(frozen=True)
class SaveOffsets:
    """Where the fields a map rebuild writes live in *this* `.sav`.

    Resolved by the caller from its own save layout (prism from its inventory,
    vanilla from its saved-block symbols), so the neutral core never learns how a
    tree maps WRAM symbols onto save-file bytes — only the answers.
    """
    screen_save: int      # wScreenSave (30 bytes: SCREEN_META_WIDTH * HEIGHT)
    object_structs: int   # wObjectStructs (the player + NPC live structs)
    map_objects: int      # wMapObjects (the map's object headers)
    map_objects_size: int # its byte length, so the NPC slot count is known


def rebuild_map(
    sav,
    *,
    rom_path: Path,
    syms: symfile.SymFile,
    group: int,
    number: int,
    x: int,
    y: int,
    offsets: SaveOffsets,
    keep_people: bool = False,
    name: str = "",
    format: blockdata.MapFormat = blockdata.MapFormat(),
) -> list[str]:
    """Rebuild the tiles and objects around (x, y) on (group, number).

    `sav` is any object exposing a mutable `data` bytearray. `(x, y)` are the raw
    `wXCoord`/`wYCoord` tiles (no `+4`); the caller has already written the four
    position bytes — this rebuilds what the Continue path leaves stale around
    them. `keep_people` preserves the objects already in the save (only the tiles
    and the player are refreshed) instead of reloading the destination map's own.
    `format` is the tree's ROM map dialect — stock pokecrystal's by default, prism
    passes its own. Returns human-readable change lines.
    """
    changes: list[str] = []

    # Recompute wScreenSave from ROM so MAPSETUP_CONTINUE's
    # LoadNeighboringBlockData overlays consistent data (otherwise the area
    # around the player renders as stale tiles or zeros).
    bd = blockdata.load(rom_path, syms, group, number, name=name, format=format)
    # Pull in the connected neighbours so an edge position renders the real
    # border blocks instead of void. A neighbour that won't load (malformed
    # header) just falls back to zero padding — no worse than before.
    neighbors = []
    for conn in blockdata.map_connections(
        rom_path, syms, group, number, map_width=bd.width, name=name, format=format,
    ):
        try:
            nb = blockdata.load(
                rom_path, syms, conn.group, conn.map_id,
                name=f"{name or 'map'} {conn.direction} neighbour", format=format,
            )
        except ValueError:
            continue
        neighbors.append((conn, nb))
    ss_bytes = blockdata.compute_screen_save(bd, x, y, neighbors=neighbors)
    sav.data[offsets.screen_save : offsets.screen_save + len(ss_bytes)] = ss_bytes

    label = name or f"(group {group}, id {number})"
    edges = ", ".join(c.direction for c, _ in neighbors) or "none"
    changes.append(
        f"recomputed wScreenSave from {bd.width}x{bd.height} block grid "
        f"(connections filled: {edges}) for {label}"
    )

    # Reset the player struct, then (unless keep_people) clear the NPC slots and
    # load the destination map's own NPCs in their place. Without this,
    # MAPSETUP_CONTINUE leaves wObjectStructs holding the previous map's player
    # position and NPC state, so the player renders off-screen and ghost NPCs from
    # the old map show up. Clearing alone fixes the ghosts but leaves the map
    # deserted; loading is what makes teleporting in to look at an NPC you just
    # placed actually show you the NPC.
    people_changes = people.reset_player_and_clear_npcs(
        sav,
        object_structs_offset=offsets.object_structs,
        map_objects_offset=offsets.map_objects,
        map_objects_size=offsets.map_objects_size,
        x=x,
        y=y,
        keep_npcs=keep_people,
    )
    if not keep_people:
        events = blockdata.object_events(
            rom_path, syms, group, number, name=name, format=format)
        people_changes |= people.load_map_npcs(
            sav,
            map_objects_offset=offsets.map_objects,
            map_objects_size=offsets.map_objects_size,
            events=events,
        )
        # Instantiate the NPCs that fall on screen into wObjectStructs — the
        # Continue path loads their graphics (LoadGraphics rebuilds the VRAM
        # allocator) but never runs InitializeVisibleSprites, so without this they
        # exist in wMapObjects yet render as nothing. The SPRITE_TILE we write has
        # to agree with that rebuilt allocator, which is what spritevram
        # reproduces.
        player_sprite = sav.data[offsets.object_structs + people.OBJ_SPRITE]
        if blockdata.is_outdoor(bd.permission):
            pool = spritevram.outdoor_sprite_ids(
                rom_path, syms, group, name=name, count=format.outdoor_sprites)
        else:
            pool = [ev[0] for ev in events]  # indoor: the map's own NPC sprites
        npc_sprites = [ev[0] for ev in events]
        tiles = spritevram.sprite_tiles(rom_path, syms, player_sprite, pool,
                                        headers_symbol=format.sprite_headers)
        people_changes |= people.instantiate_visible_sprites(
            sav,
            object_structs_offset=offsets.object_structs,
            map_objects_offset=offsets.map_objects,
            map_objects_size=offsets.map_objects_size,
            x=x,
            y=y,
            sprite_tiles=tiles,
            sprite_palettes=spritevram.sprite_palettes(
                rom_path, syms, npc_sprites, headers_symbol=format.sprite_headers),
            movement_data=spritevram.movement_data(rom_path, syms),
            default_tile=tiles.get(player_sprite, 0),
        )
    changes.append("people: " + ", ".join(f"{k}={v}" for k, v in people_changes.items()))
    return changes
