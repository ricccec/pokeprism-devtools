"""Rules about what a map puts *in* itself: objects, sprites, events, flags.

These are the failures that never reach the assembler. A sprite missing from the
map group's outdoor set still builds — it just renders as garbage. A count byte
that over-declares still builds — the engine spawns a phantom NPC out of the
following bytes. An event flag that doesn't exist still builds, because the
`dw` takes any expression.
"""

from __future__ import annotations

import re

from ..hacks.prism.eventheader import LIST_ORDER, ListKind
from .context import LintContext
from ..contract import Diagnostic, Severity

_LIST_NAMES = {
    ListKind.WARPS: "warps",
    ListKind.COORD_EVENTS: "coord events",
    ListKind.BG_EVENTS: "BG events",
    ListKind.OBJECT_EVENTS: "object events",
}

_EVENT_RE = re.compile(r"\bEVENT_[A-Z0-9_]+\b")

#: A map may declare at most this many object events. `ReadObjectEvents`
#: (home/map.asm) copies the list into `wMapObjects`, a fixed `NUM_OBJECTS` = 16
#: array (constants/wram_constants.asm) whose slot 0 is always the player — so 15
#: are left for the map. The copy (`CopyMapObjectHeaders`) is *unclamped*: a 16th
#: entry is written straight past `wMap15Object` into the WRAM that follows. And
#: it is one shared pool — NPCs, trainers and boulders are all `person_event`s,
#: counted together, not 15 of each. Fitted against the repo: four maps sit
#: exactly on 15 and none is over, so >15 is safe to report as an error.
_MAX_OBJECT_EVENTS = 15


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
            present = len(lst.entries)
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


def object_overflow(ctx: LintContext) -> list[Diagnostic]:
    """A map declares more object events than the engine's map-object array holds.

    The overworld copies a map's object events into `wMapObjects`, a fixed
    16-slot WRAM array whose first slot is the player — so 15 remain. The copy
    doesn't check: `CopyMapObjectHeaders` (home/map.asm) writes `declared_count`
    entries unconditionally, so a 16th spills past the array's end into whatever
    WRAM sits after it. Assembles cleanly; corrupts at load. This is keyed on the
    count byte the engine actually reads, so it doesn't double-report a map whose
    count is simply wrong — that is :func:`obj_count`'s job.

    NPCs, trainers and boulders are one pool, not three: they are all
    `person_event`s under the one object-events list, so the 15 is shared.
    """
    out = []
    for const, info in sorted(ctx.map_infos.items()):
        header = ctx.header(const)
        if header is None:
            continue
        lst = header.lists[ListKind.OBJECT_EVENTS]
        if lst.declared_count <= _MAX_OBJECT_EVENTS:
            continue
        out.append(Diagnostic(
            "object-overflow", Severity.ERROR, ctx.rel(info.path),
            lst.count_lineno + 1,
            f"{lst.declared_count} object events, but the engine loads a map's "
            f"objects into a {_MAX_OBJECT_EVENTS + 1}-slot array with the player "
            f"in slot 0 — only {_MAX_OBJECT_EVENTS} fit, and the rest overflow "
            f"into the WRAM after it at load. NPCs, trainers and boulders all "
            f"count against this one limit",
        ))
    return out


def event_overlap(ctx: LintContext) -> list[Diagnostic]:
    """Two entries of the *same* list standing on one tile. The second is dead.

    Each list is scanned linearly and the first hit wins. `GetDestinationWarpNumber`
    (home/map.asm:99) walks the warps comparing coordinates and returns on the first
    match; the signpost scan (home/map.asm:1556) does the same, and so does
    `RunCurrentMapXYTriggers`. So a second warp on a tile is not a second way out —
    it is a line nobody will ever reach. Two *objects* on a tile both spawn, which
    is worse rather than better: one is drawn over the other, and the one you can
    talk to is whichever the facing check finds first.

    Three refinements, all of them things the repo taught rather than things the
    rule assumed:

    **A shadowed warp is still a destination.** `warp_to` counts its way to a
    warp by *index*, so MoundB2F's three warps on (40, 8) — the author marked
    them ``; FIXME`` — are two dead exits and three live arrivals. Deleting one
    renumbers the repo. That is why this is a warning and not an error, and why
    it says so.

    **Coord events are keyed by the scene as well as the tile.**
    `RunCurrentMapXYTriggers` (home/map.asm:1592) compares the trigger's first
    byte with the active scene id and skips it if it differs — and a five-argument
    ``xy_trigger`` also carries an event flag it is gated on. LaurelForestPokemonOnly
    stacks three triggers on one tile, each gated on which Pokémon is in your
    party, and every one of them is reachable. So a coord event only shadows the
    one below it if it is *unconditional*: no event gate, and a scene that matches
    everything the later one matches.

    **Different lists on one tile are a note, not a fault** — see
    :func:`event_stack`.
    """
    out = []
    for const, info in sorted(ctx.map_infos.items()):
        header = ctx.header(const)
        if header is None:
            continue
        path = ctx.rel(info.path)
        for kind in ListKind:
            for tile, group in _by_tile(header.lists[kind].entries).items():
                for pos, (i, entry) in enumerate(group):
                    hidden = _shadowed_by(kind, group[:pos], entry)
                    if hidden is None:
                        continue
                    out.append(Diagnostic(
                        "event-overlap", Severity.WARNING, path, entry.lineno + 1,
                        f"{_ONE[kind]} #{_shown(kind, i)} is on ({tile[0]}, {tile[1]}), "
                        f"where {_ONE[kind]} #{_shown(kind, hidden)} already is — the "
                        f"engine scans the {_LIST_NAMES[kind]} in order and takes the "
                        f"first one on the tile, so this one never {_NEVER[kind]}"
                        f"{_STILL.get(kind, '')}",
                    ))
    return out


def event_stack(ctx: LintContext) -> list[Diagnostic]:
    """Entries of *different* lists on one tile.

    Not a bug, and reported anyway. Nothing shadows anything here — the lists are
    scanned by different code at different moments, so an NPC standing in a
    doorway and the warp under his feet both work exactly as written, and seven
    maps do that on purpose (he is what stops you using the door until he moves).
    But the same picture is also what a mis-typed coordinate looks like, and the
    tile knows which of the two it is no better than this rule does. So: info.
    """
    out = []
    for const, info in sorted(ctx.map_infos.items()):
        header = ctx.header(const)
        if header is None:
            continue
        path = ctx.rel(info.path)
        everything: dict[tuple[int, int], list[tuple[ListKind, int, object]]] = {}
        for kind in ListKind:
            for i, entry in enumerate(header.lists[kind].entries):
                y, x = entry.coords
                if y is not None and x is not None:
                    everything.setdefault((y, x), []).append((kind, i, entry))

        for tile, here in sorted(everything.items()):
            kinds = {k for k, _, _ in here}
            if len(kinds) < 2:
                continue
            what = ", ".join(f"{_ONE[k]} #{_shown(k, i)}"
                             for k, i, _ in sorted(here, key=lambda t: LIST_ORDER.index(t[0])))
            first = min(here, key=lambda t: t[2].lineno)     # report it once, up top
            out.append(Diagnostic(
                "event-stack", Severity.INFO, path, first[2].lineno + 1,
                f"({tile[0]}, {tile[1]}) holds {what} — different lists, so none of "
                f"them shadows the others and all of them work. Said here because a "
                f"mistyped coordinate looks exactly like this",
            ))
    return out


#: What one entry of each list is called, in the singular, when a message has to
#: point at one.
_ONE = {
    ListKind.WARPS: "warp",
    ListKind.COORD_EVENTS: "coord event",
    ListKind.BG_EVENTS: "BG event",
    ListKind.OBJECT_EVENTS: "object",
}

#: What the shadowed one no longer does. Each list is *used* for a different thing,
#: and "never fires" would be nonsense about a signpost.
_NEVER = {
    ListKind.WARPS: "takes you anywhere",
    ListKind.COORD_EVENTS: "fires",
    ListKind.BG_EVENTS: "can be read",
    ListKind.OBJECT_EVENTS: "can be talked to (and is drawn under the other)",
}

#: …and the one case where the dead entry is still doing a job.
_STILL = {
    ListKind.WARPS: ". It is still a valid *arrival*, though — another map's "
                    "`warp_to` counts its way here by index — so deleting it "
                    "renumbers every warp below it",
}


def _shown(kind: ListKind, i: int) -> int:
    """Warps are numbered from 1 by `warp_to`, and by everything that talks about
    them. The other three lists are 0-based everywhere they are indexed."""
    return i + 1 if kind == ListKind.WARPS else i


def _by_tile(entries: list) -> dict[tuple[int, int], list[tuple[int, object]]]:
    """The entries of one list, grouped by the tile they stand on, in source order.

    An entry whose coordinates are an expression rather than a number is left out
    entirely: it is on some tile, and nothing here can say which.
    """
    out: dict[tuple[int, int], list[tuple[int, object]]] = {}
    for i, entry in enumerate(entries):
        y, x = entry.coords
        if y is None or x is None:
            continue
        out.setdefault((y, x), []).append((i, entry))
    return {tile: group for tile, group in out.items() if len(group) > 1}


def _shadowed_by(kind: ListKind, above: list[tuple[int, object]], entry) -> int | None:
    """The index of the earlier entry on this tile that hides `entry`, if one does.

    For three of the lists that is simply the first one there. Coord events have
    to earn it: see :func:`event_overlap`.
    """
    for i, other in above:
        if kind != ListKind.COORD_EVENTS or _unconditional(other, entry):
            return i
    return None


def _unconditional(earlier, later) -> bool:
    """Whether `earlier` fires on every scene `later` would, with nothing to stop it.

    `xy_trigger scene, y, x, script[, event]`. The engine takes the trigger if its
    scene is the active one *or* is -1, and — in the five-argument form — only if
    the event flag it names is set. So an earlier trigger shadows a later one only
    when it is ungated and its scene is the same one, or the wildcard.
    """
    if len(earlier.args) > 4:
        return False                       # gated on an event flag; it may not fire
    scene, theirs = earlier.int_arg(0), later.int_arg(0)
    return scene == -1 or (scene is not None and scene == theirs)


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


ALL = (obj_count, object_overflow, event_overlap, event_stack,
       sprite_outdoor, sprite_static_walker)
