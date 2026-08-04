"""The six lists of things standing on a map, and the one record that holds them.

The carve-up is a *person's*, not any engine's, and it is this side's to declare:
things that talk (NPCs), things that battle (Trainers), things lying about on the
floor (Props — item balls, rocks, and the hidden items the engine files under
signs), things you read (Signposts), places you leave from (Warps), and tiles that
fire (Triggers). An adapter's job is to pour its own lists into those six, however
its engine happens to shelve them — which entry is an NPC and which is an item
ball is a reading of one hack's macros, so the classification lives with the
adapter and never here.

Every coordinate is the number **written in the source**, because that is the
number you would type to change it. Offsets a macro adds while assembling belong
to the assembled bytes and appear nowhere in this package — and a hack that
writes (x, y) has already been turned around by its adapter, the way
`shared.coords.Tile` says.

Shared conventions across all six:

    handle       the adapter's name for the entry, carried into the row's Ref
    index        the entry's position in the engine list it came from — the
                 number scripts address it by where scripts do that — not its
                 position on the tab, which cuts three tabs out of one list
    y, x         the numbers written in the source, or None where the source
                 writes an expression; the row still exists, the grid just
                 can't point at it
    undeclared   in the file but past a count byte the engine trusts

Display strings (sprite, movement, kind, …) arrive display-ready: the adapter
knows its own prefixes (`SPRITEMOVEDATA_`, `SIGNPOST_`, `BGEVENT_`) and strips
them before crossing; "" means "nothing to say" and renders as a dash.
"""

from __future__ import annotations

from collections.abc import Hashable
from dataclasses import dataclass, field

from ..shared.coords import Tile


@dataclass(frozen=True)
class Npc:
    handle: Hashable
    index: int
    y: int | None
    x: int | None
    sprite: str
    movement: str
    says: str            # what they say, or the label that says it — resolved
    flag: str
    undeclared: bool = False


@dataclass(frozen=True)
class Trainer:
    handle: Hashable
    index: int
    y: int | None
    x: int | None
    sprite: str
    cls: str             # trainer class
    party: str           # prism's 1-based ordinal; a name where hacks name them
    sight: str
    flag: str            # the flag that remembers you beat them
    undeclared: bool = False


@dataclass(frozen=True)
class Prop:
    """Something lying about: an item ball, a fruit tree, a rock, a hidden item."""
    handle: Hashable
    index: int
    y: int | None
    x: int | None
    kind: str            # "itemball", "hidden", "rock", …: the adapter's word
    what: str            # the item, the tree id, the std script
    qty: str             # "" for the kinds where a count would be meaningless
    flag: str
    undeclared: bool = False


@dataclass(frozen=True)
class Signpost:
    handle: Hashable
    index: int
    y: int | None
    x: int | None
    kind: str
    points_at: str
    undeclared: bool = False


@dataclass(frozen=True)
class Warp:
    handle: Hashable
    index: int
    y: int | None
    x: int | None
    to_map: str
    their_warp: str      # index into the *destination's* warp list, 1-based
    undeclared: bool = False


@dataclass(frozen=True)
class Trigger:
    handle: Hashable
    index: int
    y: int | None
    x: int | None
    scene: str
    runs: str
    undeclared: bool = False


@dataclass(frozen=True)
class MapTables:
    """Everything standing on one map, already carved into the six lists the
    tabs draw. The adapter's whole answer about a map's events — plus `marks`,
    the same objects again as glyphs for the grid, so the two pictures come
    from one enumeration and cannot disagree."""
    npcs: list[Npc]
    trainers: list[Trainer]
    props: list[Prop]
    signposts: list[Signpost]
    warps: list[Warp]
    triggers: list[Trigger]
    marks: dict[Tile, str] = field(default_factory=dict)
