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

    return [ctx.sprites.player_sprite(), *sprites]


def sprite_vram(ctx: LintContext) -> list[Diagnostic]:
    """An object on this map that will render or animate from garbage.

    Two ways, both silent at build time:

    * the object **walks**, but its sprite landed outside VRAM table 1, so the
      walk frames it fetches at base + $80 fall past the sprite tables;
    * the sprite got no allocation at all, because the map ran out of tiles —
      broken whether it moves or not.

    Landing in table 2 is only a problem for an object that actually steps.
    Standing, spinning and bobbing objects never read base + $80, so table 2 is
    exactly where they belong, and flagging them would be crying wolf.
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
            elif alloc.walking and not alloc.walk_frames_ok and ctx.object_walks(obj):
                out.append(Diagnostic(
                    "sprite-vram", Severity.ERROR, path, obj.lineno + 1,
                    f"{obj.sprite} walks ({obj.movement}), but it is allocated at tile "
                    f"${alloc.tile:02x} — outside VRAM table 1, so its walk frames are "
                    f"read from ${alloc.tile + spritepack.TABLE_2_START:03x}, past the "
                    f"sprite tables. This map loads too many walking sprites ahead of "
                    f"it; make it stand still or free a slot",
                ))
    return out


def sprite_vram_budget(ctx: LintContext) -> list[Diagnostic]:
    """This map has run out of slots for *moving* NPCs.

    Not a defect — a constraint, and the one that's invisible until you trip it.
    VRAM table 1 is the only half with walk frames behind it, so once it's full,
    every further sprite lands in table 2 and any object using one of them must
    stay put. Whoever adds the next wandering NPC needs to know that before they
    add it, not after.
    """
    sd = ctx.sprites
    out = []
    for const, info in sorted(ctx.map_infos.items()):
        sprites = _map_sprite_list(ctx, const)
        if sprites is None:
            continue
        allocs = spritepack.arrange(sd, sprites)
        spilled = [a for a in allocs if a.walking and not a.walk_frames_ok]
        if not spilled:
            continue

        fits = sum(1 for a in allocs if a.walking and a.walk_frames_ok)
        mapdef = ctx.map_defs[const]
        source = (f"the outdoor sprite set {sd.set_names.get(mapdef.group, '?')} "
                  f"(map group {mapdef.group})" if ctx.is_outdoor(const)
                  else "this map's objects")

        out.append(Diagnostic(
            "sprite-vram-budget", Severity.INFO, ctx.rel(info.path), 0,
            f"no walking slots left: {source} fills all {fits} of VRAM table 1's "
            f"walk-frame slots, so {', '.join(sorted({a.sprite for a in spilled}))} "
            f"sit in table 2 — fine as they are, but an object using one of them "
            f"cannot be given walking movement or a trainer sight radius above 1",
        ))
    return out


ALL = (sprite_vram, sprite_vram_budget)
