"""What a form may offer — every list behind every combo box, in one place.

The other half of "the view reads no files". A field says *what sort* of thing it
wants (`choices=SPRITES`) and this says which ones exist, because this is the side
of the seam that knows sprites live in `constants/sprite_constants.asm` and that a
trainer class with a `dw NULL` in the pointer table cannot be battled.

Three of these lists are not what you would guess, and each is a bug avoided:

**The TMs are not in the item list.** `TM_HAIL` is pasted together by a macro at
assembly time and appears nowhere in the source — scan the item constants for
`TM_` and you find `TM_CASE`, which is the bag. See `wiring/pickups.tmhms`.

**The event flags do not bound what you may type.** Every other list here is a set
of names the wiring layer will check you against. That one is a *suggestion*: a
flag you name that doesn't exist is a flag that gets created, and a combo that
held you to the list would mean the only NPCs you could gate are the gated ones.

**The parties depend on the class.** Which is why :func:`for_kind` takes the form
as it stands. There is no useful list of "every party in the repo" — all but a
handful of them would be the wrong team.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from ..shared import consts, eventflags, spritesets, trainerparty, trainerstats
from ..wiring import connections, pickups, scaffold
from . import actions, newmap
from .actions import Action


def for_kind(root: Path, kind: str, maps: tuple[str, ...],
             values: dict[str, str] | None = None) -> list[str]:
    """The constants a field of this kind will accept.

    An unknown kind is empty — i.e. free text, not an error. A new action with a
    new kind should degrade to a plain box, not crash the form.
    """
    if kind == actions.PARTIES:
        cls = (values or {}).get("cls", "").strip()
        return trainerstats.rosters(root, cls) if cls else []
    if kind == actions.MAPS:
        return list(maps)
    return list(_index(root).get(kind, ()))


def follows(root: Path, action: type[Action], changed: str,
            values: dict[str, str]) -> dict[str, str]:
    """What the form should fill in for itself, now that one field has changed.

    The action decides (:meth:`Action.follows`); this hands it the repo, because
    the answer is *measured* from the repo — the sprite a SKIER wears is a fact
    about this fork, not a fact about skiers.
    """
    return action.follows(root, changed, values)


def warm(root: Path) -> None:
    """Read the lot, off the UI thread. Otherwise the first form to open pays for
    every sprite, item, class and flag in the repo, while you look at an empty box
    wondering whether the key registered."""
    _index(root)
    trainerstats.defaults(root, "YOUNGSTER")     # builds the whole class index


def forget() -> None:
    """Drop the index, because we have just written to the repo. A new NPC's flag
    is a new entry in the flag list, and a form that offered yesterday's flags
    would be a form that quietly allocated a second one with the same name."""
    _index.cache_clear()


@lru_cache(maxsize=4)
def _index(root: Path) -> dict[str, tuple[str, ...]]:
    """Every list that doesn't depend on the form. Cached on the *function*, so
    `shared/caches.py` finds it and `Session.reload` drops it along with all the
    rest — which is the whole reason that module discovers caches rather than
    naming them."""
    backed = [cls for cls, group in trainerparty.class_groups(root).items() if group]
    return {
        actions.SPRITES: tuple(sorted(spritesets.sprite_ids(root))),
        actions.MOVEMENTS: tuple(sorted(spritesets.movedata_ids(root))),
        actions.PALETTES: tuple(sorted(
            consts.with_prefix(root, consts.SPRITES, "PAL_OW_"))),
        actions.ITEMS: tuple(sorted(consts.names(root, consts.ITEMS))),
        actions.TMHMS: tuple(sorted(pickups.tmhms(root))),
        actions.TREES: tuple(sorted(pickups.trees(root))),
        actions.FLAGS: tuple(eventflags.load(root).by_name),
        actions.CLASSES: tuple(sorted(backed)),
        actions.DIRECTIONS: tuple(sorted(connections.OPPOSITE)),
        actions.FACINGS: tuple(f.removeprefix("SIGNPOST_").lower()
                               for f in scaffold.FACINGS),
        # The map header's enums, from the same table the new-map action checks
        # them against — so the form cannot suggest a constant that the action
        # would then refuse.
        actions.PERMISSIONS: newmap.PERMS,
        **{kind: tuple(sorted(consts.with_prefix(root, rel, prefix)))
           for kind, (rel, prefix) in (
               (actions.TILESETS, newmap.ENUMS["tileset"]),
               (actions.LANDMARKS, newmap.ENUMS["landmark"]),
               (actions.MUSIC, newmap.ENUMS["music"]),
               (actions.TIMES, newmap.ENUMS["palette"]),
               (actions.FISHGROUPS, newmap.ENUMS["fishgroup"]),
           )},
    }
