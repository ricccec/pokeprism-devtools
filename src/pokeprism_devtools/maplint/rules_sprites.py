"""The VRAM budget: which of a map's sprites actually get usable graphics.

Everything here comes out of :mod:`..shared.spritepack`, which replays the
engine's own allocator rather than encoding a rule of thumb. The well-known
"about 8 walking NPCs per map" ceiling is never written down — it is what the
allocator happens to produce today, and these rules recompute it per map.
"""

from __future__ import annotations

from ..shared import spritepack
from .context import LintContext
from .diagnostics import Diagnostic, Severity


def _map_sprite_list(ctx: LintContext, const: str) -> list[str] | None:
    """The used-sprite list the engine would build for this map, player first.

    ``RefreshSprites`` calls ``GetPlayerSprite`` before ``AddMapSprites``, so the
    player always takes the first slot — and a walking slot at that, which is
    why maps get 9 walking NPCs rather than 10.
    """
    header = ctx.header(const)
    mapdef = ctx.map_defs.get(const)
    if header is None or mapdef is None:
        return None

    if ctx.is_outdoor(const):
        # AddMapSprites .outdoor: the whole group set is loaded, whatever the
        # map's objects actually ask for.
        sprites = list(ctx.sprites.outdoor_set(mapdef.group))
    else:
        sprites = [obj.sprite for obj in header.object_events]

    return [_player_sprite(ctx), *sprites]


def _player_sprite(ctx: LintContext) -> str:
    for candidate in ("SPRITE_P0", "SPRITE_PLAYER", "SPRITE_CHRIS"):
        if candidate in ctx.sprites.sprite_ids:
            return candidate
    return "SPRITE_P0"


def sprite_vram(ctx: LintContext) -> list[Diagnostic]:
    """An object placed on this map whose sprite has no usable graphics.

    Two ways that happens, both silent at build time:

    * the sprite is a walker that didn't fit in VRAM table 1, so its walk frames
      (base + $80) fall outside the sprite tables and it animates from garbage;
    * the sprite got no allocation at all, because the map ran out of tiles.
    """
    sd = ctx.sprites
    out = []
    for const, info in sorted(ctx.map_infos.items()):
        sprites = _map_sprite_list(ctx, const)
        if sprites is None:
            continue
        allocs = {a.sprite: a for a in spritepack.arrange(sd, sprites)}
        header = ctx.header(const)
        path = ctx.rel(info.path)

        for obj in header.object_events:
            alloc = allocs.get(obj.sprite)
            if alloc is None:
                continue                  # Pokemon / variable sprite — not allocated here
            if alloc.dropped:
                out.append(Diagnostic(
                    "sprite-vram", Severity.ERROR, path, obj.lineno + 1,
                    f"{obj.sprite} gets no VRAM on this map — the sprite tables are "
                    f"full, so it renders as garbage",
                ))
            elif alloc.walking and not alloc.walk_frames_ok:
                out.append(Diagnostic(
                    "sprite-vram", Severity.ERROR, path, obj.lineno + 1,
                    f"{obj.sprite} is a walking sprite allocated at tile "
                    f"${alloc.tile:02x}, outside VRAM table 1 — its walk frames are "
                    f"read from ${alloc.tile + spritepack.TABLE_2_START:03x}, past the "
                    f"sprite tables, so it animates from garbage. This map loads too "
                    f"many walking sprites",
                ))
    return out


def sprite_vram_budget(ctx: LintContext) -> list[Diagnostic]:
    """A map that loads more walking sprites than VRAM table 1 can hold.

    Reported even when the sprites that fall off the end aren't placed on this
    map — for an outdoor map the whole group set is loaded, so the map is one
    NPC away from a broken sprite, and whoever adds that NPC has no way to know.
    """
    sd = ctx.sprites
    out = []
    for const, info in sorted(ctx.map_infos.items()):
        sprites = _map_sprite_list(ctx, const)
        if sprites is None:
            continue
        allocs = spritepack.arrange(sd, sprites)
        broken = [a for a in allocs if a.walking and not a.walk_frames_ok]
        if not broken:
            continue

        header = ctx.header(const)
        used = {obj.sprite for obj in header.object_events}
        unusable = [a.sprite for a in broken if a.sprite not in used]
        if not unusable:
            continue                      # every broken sprite is placed; sprite-vram said so

        walkers = sum(1 for a in allocs if a.walking)
        fits = sum(1 for a in allocs if a.walking and a.walk_frames_ok)
        mapdef = ctx.map_defs[const]
        source = (f"the outdoor sprite set {sd.set_names.get(mapdef.group, '?')} "
                  f"(map group {mapdef.group})" if ctx.is_outdoor(const)
                  else "this map's objects")

        out.append(Diagnostic(
            "sprite-vram-budget", Severity.WARNING, path_of(ctx, const), 0,
            f"{source} loads {walkers} walking sprites but only {fits} fit in VRAM "
            f"table 1 — {', '.join(sorted(unusable))} would animate from garbage if "
            f"placed on this map",
        ))
    return out


def path_of(ctx: LintContext, const: str) -> str:
    return ctx.rel(ctx.map_infos[const].path)


ALL = (sprite_vram, sprite_vram_budget)
