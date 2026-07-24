"""Polished's map file, read from the head.

The event block *opens* a polished map file — `<Label>_MapScriptHeader:`
first, everything else below — which is the anchor the mount tells the
family apart by. The carving into labelled blocks is vanilla's
(:func:`~..vanilla.events.parse` with the other anchor); what this module
owns is what polished changed about the entries themselves:

* `object_event` has twelve args, not thirteen: the palette column is gone
  and one time-of-day arg stands where two hour bytes stood. The trailing
  args shift with the type — `OBJECTTYPE_COMMAND` spends them on a command
  and its argument, an item ball on `PLAYEREVENT_*`, item and an optional
  quantity — so the *last* arg is the flag, not arg twelve.
* Hidden items moved inline: `BGEVENT_ITEM + FULL_HEAL` names the item in
  the kind expression, no `hiddenitem` block to walk to.
* A trainer is either a `trainer` or a `generictrainer` block — same three
  leading args, different macro — and the object's type says which.
* Objects are spelled two ways: the long `object_event`, and ten convenience
  macros each assembling to one — item balls, fruit trees, boulders, a wild
  mon. `parse` is handed `..shorthand.SHORTHANDS` so it expands each in place,
  and the object list carries all of them, in the engine order the object
  consts number by. Vanilla writes none, so it hands `parse` nothing.
"""

from __future__ import annotations

from pathlib import Path

from ...shared import coords
from ...shared.coords import Tile
from ...studio import panels
from ..vanilla.events import (MapSource, arg, first_words, macro_args, mark,
                              parse, prose, yx)
from .shorthand import SHORTHANDS

ANCHOR = "_MapScriptHeader"

#: OBJECTTYPE_* -> the macro its script block declares a battle with.
_TRAINER_MACROS = {"OBJECTTYPE_TRAINER": "trainer",
                   "OBJECTTYPE_GENERICTRAINER": "generictrainer"}

#: The `jumpstd` predefineds that mark a thing on the floor rather than a person,
#: and the prop kind each reads as. A cut tree and the two boulders are command
#: objects exactly like an NPC that `jumptextfaceplayer`s — the type byte says
#: `OBJECTTYPE_COMMAND` for all of them — so only the command tells them apart.
#: Reading over the command, not the shorthand, means a hand-written long
#: `object_event` carrying the same `jumpstd` reads as a prop too, not just the
#: `cuttree_event` shorthand it usually came from.
_FLOOR_STD = {"cuttree": "cuttree",
              "strengthboulder": "boulder",
              "smashrock": "rock"}


def tables(path: Path) -> panels.MapTables:
    """One map's events, carved into the six lists the tabs draw."""
    src = parse(path, anchor=ANCHOR, expand=SHORTHANDS)
    marks: dict[Tile, str] = {}
    named = len(src.names) == len(src.object_events)

    warps = []
    for i, args in enumerate(src.warp_events):
        y, x = yx(args)
        mark(marks, y, x, coords.WARP)
        warps.append(panels.Warp(
            handle=("warp", i), index=i, y=y, x=x,
            to_map=arg(args, 2), their_warp=arg(args, 3)))

    triggers = []
    for i, args in enumerate(src.coord_events):
        y, x = yx(args)
        mark(marks, y, x, coords.TRIGGER)
        triggers.append(panels.Trigger(
            handle=("coord", i), index=i, y=y, x=x,
            scene=arg(args, 2), runs=arg(args, 3)))

    signs: list[panels.Signpost] = []
    props: list[panels.Prop] = []
    for i, args in enumerate(src.bg_events):
        y, x = yx(args)
        mark(marks, y, x, coords.SIGN)
        kind, target = arg(args, 2), arg(args, 3)
        if kind.startswith("BGEVENT_ITEM"):
            # The item is written into the kind itself: BGEVENT_ITEM + ETHER.
            props.append(panels.Prop(
                handle=("bg", i), index=i, y=y, x=x, kind="hidden",
                what=kind.partition("+")[2].strip(), qty="", flag=target))
        else:
            signs.append(panels.Signpost(
                handle=("bg", i), index=i, y=y, x=x,
                kind=kind.removeprefix("BGEVENT_"), points_at=target))

    npcs: list[panels.Npc] = []
    trainers: list[panels.Trainer] = []
    says = first_words(src)
    for i, args in enumerate(src.object_events):
        if len(args) < 12:
            continue
        y, x = yx(args)
        handle = src.names[i] if named else ("object", i)
        sprite = args[2].removeprefix("SPRITE_")
        movement = args[3].removeprefix("SPRITEMOVEDATA_")
        objtype, flag = args[8], args[-1]

        if (battle := _TRAINER_MACROS.get(objtype)) is not None:
            t = macro_args(src, args[10], battle)
            mark(marks, y, x, coords.TRAINER)
            trainers.append(panels.Trainer(
                handle=handle, index=i, y=y, x=x, sprite=sprite,
                cls=arg(t, 0), party=arg(t, 1), sight=args[9],
                flag=arg(t, 2)))
        elif objtype == "OBJECTTYPE_ITEMBALL":
            # PLAYEREVENT_*, item, then a quantity only when there are
            # thirteen args to spend one on — key items never carry a count.
            mark(marks, y, x, coords.ITEM)
            props.append(panels.Prop(
                handle=handle, index=i, y=y, x=x, kind="itemball",
                what=args[10], qty=args[11] if len(args) >= 13 else "",
                flag=flag))
        elif objtype == "OBJECTTYPE_COMMAND":
            command, argument = args[9], args[10]
            if command == "fruittree":
                # `fruittree TREE, ITEM`: the object is the tree, a thing on the
                # floor the player harvests — a prop, filed by the tree it is.
                mark(marks, y, x, coords.ITEM)
                props.append(panels.Prop(
                    handle=handle, index=i, y=y, x=x, kind="fruittree",
                    what=argument, qty="", flag=flag))
            elif (floor := _FLOOR_STD.get(argument)) is not None:
                # `jumpstd cuttree|strengthboulder|smashrock`: an obstacle the
                # player clears, on the Objects tab beside the balls and trees.
                mark(marks, y, x, coords.ITEM)
                props.append(panels.Prop(
                    handle=handle, index=i, y=y, x=x, kind=floor,
                    what="", qty="", flag=flag))
            else:
                # The object *is* its command: jumptextfaceplayer straight at a
                # text label, or a nurse or clerk `jumpstd` — a person either
                # way, no script block in between to hop through.
                mark(marks, y, x, coords.PERSON)
                npcs.append(panels.Npc(
                    handle=handle, index=i, y=y, x=x, sprite=sprite,
                    movement=movement, says=says.get(argument, argument),
                    flag=flag))
        else:
            script = args[10]
            mark(marks, y, x, coords.PERSON)
            npcs.append(panels.Npc(
                handle=handle, index=i, y=y, x=x, sprite=sprite,
                movement=movement, says=says.get(script, script), flag=flag))

    return panels.MapTables(npcs=npcs, trainers=trainers, props=props,
                            signposts=signs, warps=warps, triggers=triggers,
                            marks=marks)


def texts(path: Path) -> list[panels.TextRef]:
    """Every text block in one map, as prose. Like vanilla, one box."""
    src = parse(path, anchor=ANCHOR)
    return [panels.TextRef(label=b.label, owner=b.owner, lineno=b.lineno,
                           prose=p, box="speech")
            for b in src.blocks.values()
            if (p := prose(b.lines))]
