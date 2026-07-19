"""Prism's maps, poured into the seam's records.

The port declares the vocabulary — `studio/panels` owns :class:`~...studio.
panels.Npc`, :class:`Warp`, :class:`Roof` and the rest — and this module fills
it in from prism's grammar. The import runs adapter → port on purpose: a record
the port declares is a record every adapter can fill without the port learning
any adapter's macros, which is the same arrangement `Attributes` and `WildMon`
already live under.

The carve-up implemented here is the seam's (a *person's*: NPCs talk, trainers
battle, objects lie on the floor), and prism's engine disagrees with it twice —
item balls are `person_event`s while hidden items are `signpost`s, and both
belong on the Objects tab. The one that had to be *found* is the rock. A
`SPRITE_ROCK` is a JUMPSTD like a mart clerk is, so it sat on the NPC tab with
a sprite box, a movement box and an empty field asking what it says. It is not
a person and it has never said anything; what makes it not a person is written
down in `eventmodel.Entry.prop`, and it is not the sprite.
"""

from __future__ import annotations

from pathlib import Path

from ...studio import panels
from . import eventheader as eh
from . import roofs

TRAINER_TYPES = ("PERSONTYPE_TRAINER", "PERSONTYPE_GENERICTRAINER")
PICKUP_TYPES = ("PERSONTYPE_ITEMBALL", "PERSONTYPE_TMHMBALL", "PERSONTYPE_FRUITTREE")
HIDDEN_ITEM = "SIGNPOST_ITEM"


def tables(header: eh.EventHeader, says: dict[str, str]) -> panels.MapTables:
    """One map's event header, carved into the six lists the tabs draw.

    `says` maps a text label to its first words, so an NPC's row can show what
    he actually says instead of the name of the block that says it.
    """
    npcs: list[panels.Npc] = []
    trainers: list[panels.Trainer] = []
    props: list[panels.Prop] = []

    for i, e in enumerate(header.object_events):
        if len(e.args) <= 9:
            continue
        h = eh.Handle(eh.ListKind.OBJECT_EVENTS, i)
        late = _late(header, eh.ListKind.OBJECT_EVENTS, i)
        y, x = e.coords

        if e.persontype in TRAINER_TYPES:
            # The flag that remembers you beat a trainer lives on the inline
            # `trainer` macro, not on his person_event — which carries a `-1`
            # where every other object keeps its flag. `trainer_of` walks there.
            t = eh.trainer_of(header, e)
            trainers.append(panels.Trainer(
                handle=h, index=i, y=y, x=x, sprite=e.sprite,
                cls=t.cls if t else "", party=t.party if t else "",
                sight=e.arg(10) if len(e.args) > 10 else "",
                flag=t.flag if t else "", undeclared=late))
        elif e.persontype in PICKUP_TYPES or e.prop is not None:
            # The item ball is the only one that carries a quantity: `\11` is
            # the count and `\12` the item. A TM ball spends `\11` on the item
            # itself and a fruit tree keeps its tree id in the pointer slot, so
            # for both of those the count column is meaningless rather than 1.
            if (prop := e.prop) is not None:
                # A rock's slot 11 is a std script id, and its "flag" is the -1
                # that means "always here" — the only thing a rock could be.
                kind, what = prop, e.arg(11)
            else:
                kind = e.persontype.replace("PERSONTYPE_", "").lower()
                what = e.pointer if e.persontype != "PERSONTYPE_TMHMBALL" else e.arg(10)
            props.append(panels.Prop(
                handle=h, index=i, y=y, x=x, kind=kind, what=what or "",
                qty=e.arg(10) if e.persontype == "PERSONTYPE_ITEMBALL" else "",
                flag=e.event_flag, undeclared=late))
        else:
            pointer = e.pointer or ""
            npcs.append(panels.Npc(
                handle=h, index=i, y=y, x=x, sprite=e.sprite,
                movement=e.movement.replace("SPRITEMOVEDATA_", ""),
                says=says.get(pointer, pointer), flag=e.event_flag,
                undeclared=late))

    signs: list[panels.Signpost] = []
    for i, e in enumerate(header.bg_events):
        h = eh.Handle(eh.ListKind.BG_EVENTS, i)
        late = _late(header, eh.ListKind.BG_EVENTS, i)
        y, x = e.coords
        kind = e.arg(2) if len(e.args) > 2 else ""
        if kind == HIDDEN_ITEM:
            # A hidden item's item and flag are in the record it points at, not
            # in the bg_event: `dw EVENT_… / db ITEM`. It goes on the Objects
            # tab: it is a thing on the floor, however the engine files it.
            record = eh.script_block(header, e.pointer)
            flag = next((ln.split()[-1] for ln in record
                         if ln.strip().startswith("dw ")), "")
            item = next((ln.split()[-1] for ln in record
                         if ln.strip().startswith("db ")), "")
            props.append(panels.Prop(
                handle=h, index=i, y=y, x=x, kind="hidden", what=item, qty="",
                flag=flag, undeclared=late))
        else:
            signs.append(panels.Signpost(
                handle=h, index=i, y=y, x=x,
                kind=kind.replace("SIGNPOST_", ""), points_at=e.pointer or "",
                undeclared=late))

    warps = [panels.Warp(
                handle=eh.Handle(eh.ListKind.WARPS, i), index=i,
                y=e.coords[0], x=e.coords[1],
                # warp_def y, x, id, map — `id` indexes the destination's list.
                to_map=e.arg(3) if len(e.args) > 3 else "",
                their_warp=e.arg(2) if len(e.args) > 2 else "",
                undeclared=_late(header, eh.ListKind.WARPS, i))
             for i, e in enumerate(header.warps)]

    triggers = [panels.Trigger(
                    handle=eh.Handle(eh.ListKind.COORD_EVENTS, i), index=i,
                    y=e.coords[0], x=e.coords[1], scene=e.arg(0),
                    runs=e.pointer or "",
                    undeclared=_late(header, eh.ListKind.COORD_EVENTS, i))
                for i, e in enumerate(header.coord_events)]

    return panels.MapTables(npcs=npcs, trainers=trainers, props=props,
                            signposts=signs, warps=warps, triggers=triggers,
                            marks=eh.markers(header))


def _late(header: eh.EventHeader, kind: eh.ListKind, i: int) -> bool:
    """Past the list's `db N`: written down, and not in the game. The count
    byte is prism's alone in its family — the `def_*` macros self-count — so
    only this adapter ever sets the flag."""
    return i >= header.lists[kind].declared_count


def roof(root: Path, group: int) -> panels.Roof:
    """The roof the engine will actually load for this map's group — including
    the two ways prism's source disagrees with itself about it, which is
    :mod:`.roofs`' finding; this is only that finding crossing the seam."""
    r = roofs.for_group(root, group)
    return panels.Roof(group=r.group, tiles=r.tiles, tile_file=r.tile_file,
                       colors=r.colors, mislabelled=r.mislabelled,
                       past_end=r.past_end, entries=r.entries)
