"""How each family tree spells an event entry — the records, not the forms.

Split from :mod:`.actions` so the declaration a dialect makes about itself
stands apart from the forms built out of it, and so :mod:`.write` may read the
declaration without importing the actions that ride on it.

Everything here is *measured*. The slot orders were taken off the two macro
bodies and checked by round-tripping all 9,257 real entries in the two trees;
the argument that pays for the whole file is `object_event`'s fifth and sixth,
which are the movement radius in both dialects and are swapped between them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ...contract import ActionError

if TYPE_CHECKING:                      # pragma: no cover
    from .eventblock import EventBlock


@dataclass(frozen=True)
class ObjectShape:
    """How one dialect spells an `object_event`'s argument list.

    `slots` is the written order, by the name this module's fields use;
    `defaults` is what a slot nobody typed into gets. Declared beside the warp
    grammar and the constant sets, and for the same reason: it is the third
    thing about the family that a plausible reading gets wrong, and the only
    defence against that is measuring one tree and writing it down.
    """
    slots: tuple[str, ...]
    defaults: dict[str, str]

    def args(self, values: dict[str, str]) -> list[str]:
        """One entry line's arguments, in this dialect's order.

        A slot with neither a value nor a declared default *refuses*, rather
        than falling back to zero. The fallback was here and it was a trap: an
        NPC built with no movement wrote `object_event 5, 5, SPRITE_GRAMPS, 0,
        …`, and 0 is a perfectly good `SPRITEMOVEDATA_*` — the line assembles,
        the NPC stands in the wrong pose, and nothing anywhere says so. Every
        slot this dialect writes is either answered or declared, and a gap in
        the declaration is a bug in the record rather than a zero in a map.
        """
        out = []
        for s in self.slots:
            got = (values.get(s) or self.defaults.get(s, "")).strip()
            if not got:
                raise ActionError(
                    f"{s} has no value and this dialect declares no default "
                    f"for it — an object_event needs all {len(self.slots)}.")
            out.append(got)
        return out

    def values(self, args: list[str]) -> dict[str, str]:
        """The turn back: a parsed line into form values. The inverse of
        :meth:`args`, and the reason an editor can open on what is there."""
        return dict(zip(self.slots, args))


#: pokecrystal's thirteen. `h1`/`h2` are hour limits — a pair, and `-1, -1`
#: means always, which is what every object that is not a night-only NPC says.
VANILLA_OBJECT = ObjectShape(
    slots=("x", "y", "sprite", "movement", "radius_x", "radius_y", "h1", "h2",
           "palette", "type", "sight", "script", "flag"),
    defaults={"radius_x": "0", "radius_y": "0", "h1": "-1", "h2": "-1",
              "sprite": "SPRITE_GRAMPS",
              "movement": "SPRITEMOVEDATA_STANDING_DOWN",
              "palette": "PAL_NPC_RED", "type": "OBJECTTYPE_SCRIPT",
              "sight": "0", "flag": "-1"},
)

#: polished's twelve: the two hour bytes collapsed into one time-of-day arg,
#: the palette moved up past it, and the radius pair swapped. Four differences
#: in eight columns, none of them announced anywhere but the macro body.
POLISHED_OBJECT = ObjectShape(
    slots=("x", "y", "sprite", "movement", "radius_y", "radius_x", "time",
           "palette", "type", "sight", "script", "flag"),
    defaults={"radius_x": "0", "radius_y": "0", "time": "-1",
              "sprite": "SPRITE_GRAMPS",
              "movement": "SPRITEMOVEDATA_STANDING_DOWN",
              "palette": "PAL_NPC_RED", "type": "OBJECTTYPE_SCRIPT",
              "sight": "0", "flag": "-1"},
)


def prefill(block: EventBlock, kind: str, index: int,
            shape: ObjectShape) -> dict[str, str]:
    """A parsed entry back into form values — the editor's opening state.

    The turn from what the macro wrote to what the form shows happens here and
    nowhere above: every one of these lists is written `x, y` and every table
    above the seam is `(y, x)`, so the two coordinates swap names exactly once,
    on the way in and on the way back out through :meth:`ObjectShape.args`.
    """
    entry = block.lists[kind].entries[index]
    a = entry.args
    values = {"index": str(index)}
    if kind == "object":
        # Only when the count matches; a line whose trailing arguments mean
        # something else would fill the boxes with plausible nonsense, and the
        # editor refuses such a line on submit anyway.
        if len(a) == len(shape.slots):
            values.update(shape.values(a))
        else:
            values.update({"y": _at(a, 1), "x": _at(a, 0)})
        return values
    names = {"warp": ("to_map", "their_warp"), "coord": ("scene", "script"),
             "bg": ("kind", "points_at")}[kind]
    values.update({"x": _at(a, 0), "y": _at(a, 1),
                   names[0]: _at(a, 2), names[1]: _at(a, 3)})
    if kind == "bg" and len(a) > 4:
        # Polished's `BGEVENT_JUMPSTD` takes a fifth. Carried through so the
        # form can show it and hand it back — see :class:`EditSignpost`.
        values["extra"] = _at(a, 4)
    return values


def _at(args: list[str], i: int) -> str:
    return args[i] if len(args) > i else ""
