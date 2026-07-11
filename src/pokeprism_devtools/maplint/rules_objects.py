"""Rules about what a map puts *in* itself: objects, sprites, events, flags.

These are the failures that never reach the assembler. A sprite missing from the
map group's outdoor set still builds — it just renders as garbage. A count byte
that over-declares still builds — the engine spawns a phantom NPC out of the
following bytes. An event flag that doesn't exist still builds, because the
`dw` takes any expression.
"""

from __future__ import annotations

import re

from ..shared.eventheader import ListKind
from .context import LintContext
from .diagnostics import Diagnostic, Severity

_LIST_NAMES = {
    ListKind.WARPS: "warps",
    ListKind.COORD_EVENTS: "coord events",
    ListKind.BG_EVENTS: "BG events",
    ListKind.OBJECT_EVENTS: "object events",
}

_EVENT_RE = re.compile(r"\bEVENT_[A-Z0-9_]+\b")


def obj_count(ctx: LintContext) -> list[Diagnostic]:
    """Each list's count byte must match the entries under it.

    The count is what the engine trusts. Too high and it reads the bytes after
    the list as another object — a phantom NPC you can walk into and talk to.
    Too low and the trailing entries simply never spawn.
    """
    out = []
    for const, info in sorted(ctx.map_infos.items()):
        header = ctx.header(const)
        if header is None:
            continue
        path = ctx.rel(info.path)
        for kind in ListKind:
            lst = header.lists[kind]
            if lst.count_matches:
                continue
            present = len(lst.entries) + len(lst.strays)
            if lst.declared_count > present:
                msg = (f"{_LIST_NAMES[kind]} count is {lst.declared_count} but only "
                       f"{present} entr{'y' if present == 1 else 'ies'} follow — the "
                       f"engine will read the bytes after the list as "
                       f"{lst.declared_count - present} more")
            else:
                msg = (f"{_LIST_NAMES[kind]} count is {lst.declared_count} but "
                       f"{present} entries follow — the last "
                       f"{present - lst.declared_count} will never spawn")
            out.append(Diagnostic("obj-count", Severity.ERROR, path,
                                  lst.count_lineno + 1, msg))
    return out


def sprite_outdoor(ctx: LintContext) -> list[Diagnostic]:
    """On an outdoor map, every object's sprite must be in the map group's
    `OutdoorSprites` set.

    `AddMapSprites` (engine/overworld.asm) loads graphics for an outdoor map from
    the *group's* set, not from the map's own objects. A sprite the set doesn't
    list gets no graphics loaded and renders as whatever tiles happen to be
    there — with no build error.
    """
    sd = ctx.sprites
    out = []
    for const, info in sorted(ctx.map_infos.items()):
        header = ctx.header(const)
        if header is None or not ctx.is_outdoor(const):
            continue
        mapdef = ctx.map_defs.get(const)
        if mapdef is None:
            continue

        allowed = set(sd.outdoor_set(mapdef.group))
        set_name = sd.set_names.get(mapdef.group, "?")
        path = ctx.rel(info.path)
        for obj in header.object_events:
            sprite = obj.sprite
            if not sd.needs_header(sprite):
                continue                  # Pokemon / variable sprites load elsewhere
            if sprite not in allowed:
                out.append(Diagnostic(
                    "sprite-outdoor", Severity.ERROR, path, obj.lineno + 1,
                    f"{sprite} is not in {set_name}, the outdoor sprite set for map "
                    f"group {mapdef.group} — it will render as garbage. Add it to "
                    f"{set_name} or use a sprite from that set",
                ))
    return out


def sprite_static_walker(ctx: LintContext) -> list[Diagnostic]:
    """An object that takes steps needs a `WALKING_SPRITE`.

    Walk-frame graphics are fetched at a fixed +$80 tile offset from the
    sprite's base tile (data/facings.asm). A sprite without them animates its
    walk cycle out of whatever tiles sit at that offset.
    """
    sd = ctx.sprites
    out = []
    for const, info in sorted(ctx.map_infos.items()):
        header = ctx.header(const)
        if header is None:
            continue
        path = ctx.rel(info.path)
        for obj in header.object_events:
            hdr = sd.header(obj.sprite)
            if hdr is None or hdr.walking:
                continue                  # no header (Pokemon/variable), or already fine
            if not ctx.object_walks(obj):
                continue

            why = (f"its movement {obj.movement} "
                   f"({sd.move_function(obj.movement)}) makes it walk"
                   if sd.steps(obj.movement) else
                   "this trainer's sight radius makes it walk up to the player")
            out.append(Diagnostic(
                "sprite-static-walker", Severity.ERROR, path, obj.lineno + 1,
                f"{obj.sprite} is a {hdr.type}, which has no walk frames at all, but "
                f"{why}",
            ))
    return out


ALL = (obj_count, sprite_outdoor, sprite_static_walker)
