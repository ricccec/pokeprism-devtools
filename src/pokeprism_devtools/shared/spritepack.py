"""A faithful replay of how the engine packs a map's sprites into VRAM.

This exists to make the "~8 walking NPCs per map" limit *computable* instead of
folklore. The number is emergent — it appears nowhere in the engine — and it
falls out of three things acting together:

1. ``RefreshSprites`` (engine/overworld.asm) builds the used-sprite list: the
   player first, then the map's sprites. Outdoor maps take them from the map
   group's ``OutdoorSprites`` set; indoor maps from the map's own objects. The
   list is deduplicated and capped at ``SPRITE_GFX_LIST_CAPACITY`` ($20).

2. ``SortUsedSprites`` bubble-sorts it ascending by sprite *type*, and
   ``WALKING_SPRITE`` (1) sorts before ``STANDING`` (2) and ``STILL`` (3). So
   walkers are deliberately packed first.

3. ``ArrangeUsedSprites`` lays them out: table 1 fills from tile $00 while the
   running total stays under $80; the first sprite that would cross $80 starts
   table 2 at tile $80; anything that would run past $FF gets **no allocation at
   all** and renders as garbage.

The catch that makes walkers scarce: walk-frame OAM is addressed at a **fixed
+$80 tile offset** from the sprite's base tile (``data/facings.asm``:
``FacingDownStanding`` reads base+$00, ``FacingDownWalking1`` reads base+$80).
A walking sprite therefore only animates correctly if its 12 standing tiles sit
entirely inside table 1, so that base+$80 lands inside table 2. A walker that
lands in table 2 fetches its walk frames from base+$80 ≥ $100 — past the sprite
tables entirely — and animates out of whatever tiles are there.

128 tiles / 12 per walker ≈ 10 slots, minus the player's ⇒ the famous ~8. But
nothing here hardcodes that: change a sprite's type or the capacity and the
answer moves.
"""

from __future__ import annotations

from dataclasses import dataclass

from .spritesets import SpriteData

#: ArrangeUsedSprites: the second tile table starts here, and VRAM ends at $100.
TABLE_2_START = 0x80
VRAM_END = 0x100


@dataclass(frozen=True)
class Allocation:
    sprite: str
    type: str
    tiles: int
    tile: int | None      # base tile, or None if the sprite got no allocation

    @property
    def dropped(self) -> bool:
        """No VRAM was left — the sprite renders as garbage."""
        return self.tile is None

    @property
    def walking(self) -> bool:
        return self.type == "WALKING_SPRITE"

    @property
    def walk_frames_ok(self) -> bool:
        """Whether this sprite's walk frames (base + $80) land inside VRAM.

        Only meaningful for walkers. True exactly when the sprite's standing
        tiles fit entirely inside table 1.
        """
        if self.tile is None:
            return False
        return self.tile + self.tiles <= TABLE_2_START


def used_sprites(sd: SpriteData, sprites: list[str]) -> list[str]:
    """Replay ``AddSpriteGFX``: dedupe in first-seen order, cap at capacity.

    A sprite pushed out by the cap is never loaded — ``AddSpriteGFX`` returns
    carry and the caller drops it on the floor.
    """
    out: list[str] = []
    for sprite in sprites:
        if sprite not in out:
            out.append(sprite)
        if len(out) >= sd.list_capacity:
            break
    return out


def arrange(sd: SpriteData, sprites: list[str]) -> list[Allocation]:
    """Replay ``SortUsedSprites`` then ``ArrangeUsedSprites``.

    `sprites` is the used-sprite list in list order (player first). Sprites with
    no header — overworld Pokémon and variable sprites — take no part in this
    allocation and are skipped.
    """
    entries = []
    for sprite in used_sprites(sd, sprites):
        header = sd.header(sprite)
        if header is None:
            continue
        entries.append((sprite, header.type, header.tiles))

    # SortUsedSprites: ascending by type value. A bubble sort is stable, and so
    # is this — sprites of equal type keep the order they were added in.
    entries.sort(key=lambda e: sd.type_rank(e[1]))

    out: list[Allocation] = []
    cursor = 0
    i = 0

    # First table: keep going while the running total stays within $80.
    while i < len(entries):
        sprite, type_name, tiles = entries[i]
        end = cursor + tiles
        if end > TABLE_2_START:
            break                       # this one starts the second table
        out.append(Allocation(sprite, type_name, tiles, cursor))
        cursor = end
        i += 1

    # Second table, starting at $80. `ret c` in the engine: a sprite that would
    # run past $FF ends the loop, and it — and everything after — gets nothing.
    cursor = TABLE_2_START
    while i < len(entries):
        sprite, type_name, tiles = entries[i]
        end = cursor + tiles
        if end > VRAM_END - 1:          # `add b` sets carry only past $FF
            break
        out.append(Allocation(sprite, type_name, tiles, cursor))
        cursor = end
        i += 1

    for sprite, type_name, tiles in entries[i:]:
        out.append(Allocation(sprite, type_name, tiles, None))
    return out


def walkable(sd: SpriteData, sprites: list[str]) -> frozenset[str]:
    """Which of this used-sprite list would actually animate a walk cycle here —
    the ones whose standing tiles land entirely inside table 1. See the module
    docstring for why that caps out near 9 once the player has taken a slot."""
    return frozenset(a.sprite for a in arrange(sd, sprites)
                      if a.walking and a.walk_frames_ok)
