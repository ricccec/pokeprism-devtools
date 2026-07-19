"""What goes in the tables under the grid — and what a selected row *is*.

Pure functions: each returns `(columns, rows)`, so the contents of every tab can
be tested without starting a terminal and the widgets stay dumb. Nothing here
opens a file. An :class:`~..shared.eventheader.EventHeader` carries the whole map
asm in `.lines`, so reading a trainer's class off the script block it points at is
a walk over data we were already handed — not a second read of the repo.

Every coordinate shown is the number **written in the source**, because that is
the number you would type to change it. The `+4` the `person_event` macro adds
belongs to the assembled bytes and appears nowhere in this file.

The tabs are a *person's* carve-up of a map, not the engine's. The engine keeps
two lists — object events and bg events — and puts item balls in the first and
hidden items in the second, which is an implementation detail of how they are
found, not a difference in what they are. Both are things lying about on the
floor, so both are Objects. Likewise a trainer is a `person_event` like any other
and the thing that makes him a trainer is his persontype. So:

    NPCs        person_events that are SCRIPT / TEXT / TEXTFP / JUMPSTD / MART,
                and are *people* — see `Entry.prop`
    Trainers    person_events that are TRAINER / GENERICTRAINER
    Objects     person_events that are ITEMBALL / TMHMBALL / FRUITTREE, plus the
                rocks and boulders, plus the SIGNPOST_ITEM bg_events
    Signposts   every other bg_event

The one that had to be *found* is the rock. A `SPRITE_ROCK` is a JUMPSTD like a
mart clerk is, so it sat on the NPC tab with a sprite box, a movement box and an
empty field asking what it says. It is not a person and it has never said
anything; what makes it not a person is written down in `eventmodel.Entry.prop`,
and it is not the sprite.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..maplint.context import Connection
from ..shared import eventheader as eh
from ..shared import roofs, wilddata
from ..shared.coords import Tile

_NONE = "—"

#: The trainer macro, which is where a trainer keeps the two things his
#: `person_event` does not: the flag that remembers you beat him, and the party
#: he battles with. `trainer FLAG, CLASS, PARTY, seen, defeated`.
_TRAINER_RE = re.compile(r"^\s*trainer\s+(\w+)\s*,\s*(\w+)\s*,\s*(\w+)\s*,")

TRAINER_TYPES = ("PERSONTYPE_TRAINER", "PERSONTYPE_GENERICTRAINER")
PICKUP_TYPES = ("PERSONTYPE_ITEMBALL", "PERSONTYPE_TMHMBALL", "PERSONTYPE_FRUITTREE")
HIDDEN_ITEM = "SIGNPOST_ITEM"


# --------------------------------------------------------------------------- #
# what a row is                                                               #
# --------------------------------------------------------------------------- #

#: The `what` of the Ref an "Add new…" row carries. Minted by :func:`add_ref`,
#: recognised by the session's adders — the view only ever sees it as a truthy
#: :attr:`Ref.adds`.
ADD = "add"


@dataclass(frozen=True)
class Ref:
    """What `e` and `d` act on: enough to name one thing on one map.

    **Opaque to the view.** `tabs.py` reads a Ref off the highlighted row and
    hands it straight back to the session, which is the only side of the seam
    allowed to know a `person_event` from a `signpost`. The view's whole share
    of the knowledge is the three declared affordances — "this row names
    something" (the Ref exists at all), :attr:`adds`, :attr:`deletable` — plus
    equality, for finding the row that carries a Ref again. The *fields* are the
    port's own, and no view code may read them: today identity is a list kind
    and a position, because that is all prism's source can say about an object;
    the rest of the gen-2 family names its objects (`object_const_def`), and the
    day an adapter carries a named handle here instead, a view that never read
    the fields is a view that does not notice.
    """
    #: npc | trainer | prop | signpost | warp | trigger | connection | map
    what: str
    #: The `ListKind` it lives in, when it is an event-header entry. A prop can be
    #: in either list — a hidden item is a `signpost` — which is exactly why this
    #: is not implied by `what`.
    kind: str = ""
    #: Its position in that list.
    index: int = -1
    #: A connection's direction, or the kind an "Add new…" row offers.
    key: str = ""

    # -- the view-facing surface -------------------------------------------- #
    @property
    def adds(self) -> str:
        """The kind of thing this row would add — the word the tab declared in
        `Tab.adds` — or "" for a row that names something that already exists."""
        return self.key if self.what == ADD else ""

    @property
    def deletable(self) -> bool:
        """Whether `d` exists on this row. The map's own rows say no — deleting
        a whole map is not something the studio does — and so does an "Add
        new…" row, which names nothing yet."""
        return self.what not in (ADD, "map")


def add_ref(kind: str) -> Ref:
    """The Ref an "Add new…" row carries. Minted here, on the port side, so the
    view never assembles a Ref of its own — it draws the dim row because
    `Tab.adds` told it to, and hands back what it was given."""
    return Ref(ADD, key=kind)


@dataclass(frozen=True)
class Row:
    cells: list[str]
    #: None for a row that names nothing you can act on — a wild encounter, a
    #: roof colour. The footer reads this to decide whether `e` and `d` exist.
    ref: Ref | None = None
    #: Where this row's object stands, in coordinate tiles — which is what makes
    #: the grid a way to *navigate* rather than a picture beside the table: point
    #: at a tile, and the row that owns it is the row that says so here.
    #:
    #: The number written in the source, like every other coordinate on this side
    #: of the seam, and that is not a coincidence — a coordinate tile *is* the
    #: source number. The `+4` the `person_event` macro adds exists only in the
    #: assembled struct, which is why `play.boot` can hand the grid's cursor
    #: straight to `wYCoord` and be right.
    #:
    #: None for a row that is not on the map at all: a connection is a property of
    #: the whole edge, a wild encounter is not a place.
    tile: Tile | None = None


Table = tuple[list[str], list[Row]]


@dataclass(frozen=True)
class Tab:
    """One tab: its table, and what "Add new…" would mean on it."""
    name: str
    table: Table
    #: What the dim last row offers, e.g. "NPC". Empty = no adding here (Wild,
    #: Roof, Attributes), and the row is not drawn at all.
    adds: str = ""
    #: Why this tab is read-only, when it is. Shown above the table.
    note: str = ""


#: The studio shows wild encounters and will not edit them, and that had better
#: be on screen rather than in a design document: a wild record is a fixed-size
#: slot in a table the engine indexes by *position*, so writing a short one
#: silently shifts every map below it onto somebody else's Pokémon.
WILD_IS_READ_ONLY = (
    "read-only — wild records are fixed-size and read by position; "
    "a short one shifts every map below it. Edit data/wild/*.asm by hand."
)

ROOF_IS_READ_ONLY = (
    "read-only — a roof belongs to the whole map group, not to this map. "
    "Editing it here would repaint every town in the group."
)


def _yx(entry: eh.Entry) -> tuple[str, str]:
    y, x = entry.coords
    return (_NONE if y is None else str(y), _NONE if x is None else str(x))


#: Marks a row whose entry is in the file but past its list's count byte. The
#: engine reads `db N` and stops, so it is written down and not in the game.
UNDECLARED = "⚠"


def _num(header: eh.EventHeader, kind: eh.ListKind, i: int, shown: int) -> str:
    """The `#` cell — and a mark on it when the engine will never get this far.

    PhloxLab1F says `db 6 ; FIXME` over seven `person_event`s, so its seventh
    object — a Max Revive on the floor — is in the source and not in the game.
    The row is here because *the line is in the file*: the way to fix an object
    that doesn't spawn is to look at it, and a table that hid it left you staring
    at a map with a ball drawn on it that the studio said did not exist. What it
    cannot do is pretend the count byte is right, so the row says so, and the
    linter's `obj-count` says why.
    """
    past = i >= header.lists[kind].declared_count
    return f"{shown} {UNDECLARED}" if past else str(shown)


#: The columns that hold numbers. A DataTable column is as wide as its widest
#: cell, and the dim "Add new NPC…" row at the foot of every tab was putting
#: twenty characters of prose in the first one — so `#`, a column of single
#: digits, was drawn twenty cells wide on every tab, and every number in it sat
#: under a stripe of empty air. The prompt has to go somewhere; it goes in the
#: first column that is *words*, where its width costs nothing.
NUMERIC = {"#", "y", "x", "qty", "scene", "sight", "coord", "offset", "strip", "delta"}


def prompt_column(cols: list[str]) -> int:
    """Which cell of the "Add new…" row its words are written in.

    Never column 0, which is where the ▸ goes: one cell wide, and a caret at the
    left edge is what makes the row scan as a row you can stand on.
    """
    return next((i for i, name in enumerate(cols) if i and name not in NUMERIC), 0)


def _tile(entry: eh.Entry) -> Tile | None:
    """The tile it stands on, or None when the coordinates aren't literal numbers.

    An object whose `y` is a constant expression rather than a number still gets a
    row — you can see it and delete it — but nothing can point at it on the grid,
    and pretending otherwise would put it at (0, 0).
    """
    y, x = entry.coords
    return None if y is None or x is None else Tile(y=y, x=x)


def _block(header: eh.EventHeader, label: str | None) -> list[str]:
    """The lines of the script block `label` names, if this map defines it.

    From the header's own copy of the file. An item ball's "pointer" is an item
    const rather than a label, so this correctly finds nothing for one.
    """
    if not label:
        return []
    lines = header.lines
    start = next((i for i, ln in enumerate(lines) if ln.startswith(f"{label}:")), None)
    if start is None:
        return []
    end = start + 1
    while end < len(lines):
        ln = lines[end]
        if ln[:1].isalnum() or ln[:1] == "_":
            if re.match(r"^\w+:", ln):
                break                     # the next top-level label
        end += 1
    return lines[start:end]


def _trainer_macro(header: eh.EventHeader, entry: eh.Entry) -> tuple[str, str, str]:
    """`(flag, class, party)` off the `trainer` macro in this entry's block.

    A trainer's `person_event` carries `-1` where every other object keeps its
    event flag, because the flag that remembers you beat him lives in the macro
    instead. Showing the `-1` would be showing a column that is always the same
    lie, so the table reads the macro.
    """
    for line in _block(header, entry.pointer):
        if m := _TRAINER_RE.match(line):
            return m.group(1), m.group(2), m.group(3)
    return _NONE, _NONE, _NONE


# --------------------------------------------------------------------------- #
# the object tabs                                                             #
# --------------------------------------------------------------------------- #

def _people(header: eh.EventHeader, wanted) -> list[tuple[int, eh.Entry]]:
    """Object events that `wanted` accepts, with their *real* index.

    The index is the entry's position in the engine's object_events list, not its
    position on this tab. Three tabs are cut out of one list, and an edit that
    used the row number would rewrite whichever NPC happened to be third.
    """
    return [(i, e) for i, e in enumerate(header.object_events)
            if len(e.args) > 9 and wanted(e)]


def _is_npc(e: eh.Entry) -> bool:
    return e.persontype not in TRAINER_TYPES + PICKUP_TYPES and e.prop is None


def _is_object(e: eh.Entry) -> bool:
    return e.persontype in PICKUP_TYPES or e.prop is not None


def npcs(header: eh.EventHeader, says: dict[str, str]) -> Table:
    cols = ["#", "y", "x", "sprite", "movement", "says", "event flag"]
    rows = []
    for i, e in _people(header, _is_npc):
        y, x = _yx(e)
        pointer = e.pointer or ""
        rows.append(Row(
            [_num(header, eh.ListKind.OBJECT_EVENTS, i, i), y, x, e.sprite,
             e.movement.replace("SPRITEMOVEDATA_", ""),
             says.get(pointer, pointer or _NONE), e.event_flag],
            Ref("npc", eh.ListKind.OBJECT_EVENTS.value, i), _tile(e),
        ))
    return cols, rows


def trainers(header: eh.EventHeader) -> Table:
    cols = ["#", "y", "x", "sprite", "class", "party", "sight", "event flag"]
    rows = []
    for i, e in _people(header, lambda e: e.persontype in TRAINER_TYPES):
        y, x = _yx(e)
        flag, cls, party = _trainer_macro(header, e)
        sight = e.arg(10) if len(e.args) > 10 else _NONE
        rows.append(Row(
            [_num(header, eh.ListKind.OBJECT_EVENTS, i, i), y, x, e.sprite,
             cls, party, sight, flag],
            Ref("trainer", eh.ListKind.OBJECT_EVENTS.value, i), _tile(e),
        ))
    return cols, rows


def objects(header: eh.EventHeader) -> Table:
    """Item balls, TM balls, fruit trees, rocks, boulders — and the hidden items,
    which the engine keeps in the other list entirely. See the module docstring:
    none of them is a person, and that is what the tab is for."""
    cols = ["#", "y", "x", "kind", "what", "qty", "event flag"]
    rows = []
    for i, e in _people(header, _is_object):
        y, x = _yx(e)
        # The item ball is the only one that carries a quantity: `\11` is the
        # count and `\12` the item. A TM ball spends `\11` on the item itself and
        # a fruit tree keeps its tree id in the pointer slot, so for both of those
        # the count column is meaningless rather than 1.
        ball = e.persontype == "PERSONTYPE_ITEMBALL"
        if (prop := e.prop) is not None:
            # A rock's slot 11 is a std script id, and its "flag" is the -1 that
            # means "always here" — which is the only thing a rock could ever be.
            kind, what = prop, e.arg(11)
        else:
            kind = e.persontype.replace("PERSONTYPE_", "").lower()
            what = e.pointer if e.persontype != "PERSONTYPE_TMHMBALL" else e.arg(10)
        rows.append(Row(
            [_num(header, eh.ListKind.OBJECT_EVENTS, i, i), y, x, kind, what or _NONE,
             e.arg(10) if ball else _NONE, e.event_flag],
            Ref("prop", eh.ListKind.OBJECT_EVENTS.value, i), _tile(e),
        ))

    for i, e in enumerate(header.bg_events):
        if len(e.args) < 3 or e.arg(2) != HIDDEN_ITEM:
            continue
        y, x = _yx(e)
        # A hidden item's item and flag are in the record it points at, not in
        # the bg_event: `dw EVENT_… / db ITEM`.
        record = _block(header, e.pointer)
        flag = next((ln.split()[-1] for ln in record if ln.strip().startswith("dw ")), _NONE)
        item = next((ln.split()[-1] for ln in record if ln.strip().startswith("db ")), _NONE)
        rows.append(Row(
            [_num(header, eh.ListKind.BG_EVENTS, i, i), y, x, "hidden", item, _NONE, flag],
            Ref("prop", eh.ListKind.BG_EVENTS.value, i), _tile(e),
        ))
    return cols, rows


def signposts(header: eh.EventHeader) -> Table:
    """Every bg_event that isn't a hidden item — the ones you read."""
    cols = ["#", "y", "x", "kind", "points at"]
    rows = []
    for i, e in enumerate(header.bg_events):
        kind = e.arg(2) if len(e.args) > 2 else _NONE
        if kind == HIDDEN_ITEM:
            continue                                   # it's an object, not a sign
        y, x = _yx(e)
        rows.append(Row(
            [_num(header, eh.ListKind.BG_EVENTS, i, i), y, x,
             kind.replace("SIGNPOST_", ""), e.pointer or _NONE],
            Ref("signpost", eh.ListKind.BG_EVENTS.value, i), _tile(e),
        ))
    return cols, rows


def warps(header: eh.EventHeader) -> Table:
    """`warp_def y, x, id, map` — `id` is the *warp's* index in the destination
    map's list, not a map id. Off by one and you land in the wrong doorway."""
    cols = ["#", "y", "x", "to map", "their warp #"]
    rows = []
    for i, e in enumerate(header.warps):
        y, x = _yx(e)
        dest = e.arg(3) if len(e.args) > 3 else _NONE
        which = e.arg(2) if len(e.args) > 2 else _NONE
        rows.append(Row([_num(header, eh.ListKind.WARPS, i, i + 1), y, x, dest, which],
                        Ref("warp", eh.ListKind.WARPS.value, i), _tile(e)))
    return cols, rows


def triggers(header: eh.EventHeader) -> Table:
    cols = ["#", "scene", "y", "x", "runs"]
    rows = []
    for i, e in enumerate(header.coord_events):
        y, x = _yx(e)
        rows.append(Row([_num(header, eh.ListKind.COORD_EVENTS, i, i),
                         e.arg(0), y, x, e.pointer or _NONE],
                        Ref("trigger", eh.ListKind.COORD_EVENTS.value, i), _tile(e)))
    return cols, rows


def connections(conns: list[Connection]) -> Table:
    """`delta` is the alignment between the two maps' coordinate systems. The
    map on the other side must carry exactly its negation, or the seam tears —
    which is why it's a column and not a detail."""
    cols = ["direction", "to map", "coord", "offset", "strip", "delta"]
    rows = [Row([c.direction, c.target, str(c.coord), str(c.offset),
                 str(c.strip), f"{c.delta:+d}"],
                Ref("connection", key=c.direction))
            for c in sorted(conns, key=lambda c: c.direction)]
    return cols, rows


# --------------------------------------------------------------------------- #
# the read-only tabs                                                          #
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Attributes:
    """A map's header, as it is written down. Assembled by the session, which is
    the side that knows which five files these eight facts are spread across."""
    label: str
    const: str
    group: int
    map_id: int
    height: int
    width: int
    tileset: str = _NONE
    permission: str = _NONE
    landmark: str = _NONE
    music: str = _NONE
    palette: str = _NONE
    fishgroup: str = _NONE
    phone: str = "0"
    border_block: str = _NONE
    blk: str = _NONE
    #: section name -> the bank it is pinned to in contents/romx.link, or "" for
    #: a section that floats. Three of them: blockdata, script, secondary.
    banks: dict[str, str] = field(default_factory=dict)


def attributes(attrs: Attributes) -> Table:
    """The map itself, as a field/value table. Every row carries the same Ref, so
    `e` opens the map form wherever the cursor happens to be sitting."""
    ref = Ref("map")
    pairs = [
        ("Label", attrs.label),
        ("Map id", attrs.const),
        ("Group", f"{attrs.group}  (map {attrs.map_id} within it)"),
        ("Size", f"{attrs.height} × {attrs.width} blocks"),
        ("Blocks", attrs.blk),
        ("Tileset", attrs.tileset),
        ("Permission", attrs.permission),
        ("Landmark", attrs.landmark),
        ("Music", attrs.music),
        ("Palette", attrs.palette),
        ("Fish group", attrs.fishgroup),
        ("Phone service", attrs.phone),
        ("Border block", attrs.border_block),
    ]
    pairs += [(f"Section: {name}", bank or "floating — not pinned to a bank")
              for name, bank in attrs.banks.items()]
    return ["field", "value"], [Row([k, v], ref) for k, v in pairs]


def roof(r: roofs.Roof) -> Table:
    """The roof the engine loads for this map's group — and the two ways the
    source disagrees with itself about it.

    Both are worth a row rather than a footnote. `MapGroupRoofs` is indexed by
    the group number with no adjustment, but every byte in it is commented with
    the group *after* the one that reads it; and the table has 28 entries while
    the game has 96 map groups, so most groups index past its end and pick up
    whatever assembles next as a roof. Neither is this tool's to fix. Both are
    things you would want to know before wondering why your town has no roof.
    """
    cols = ["field", "value"]
    rows = [Row(["Group", str(r.group)])]

    if r.past_end:
        rows.append(Row([
            "Roof", f"group {r.group} is past the end of MapGroupRoofs, which "
                    f"has {r.entries} entries. The engine still indexes it, so "
                    f"it reads whatever assembles after the table."]))
    elif r.tiles is None:
        rows.append(Row(["Roof", "none — MapGroupRoofs says -1 for this group"]))
    else:
        rows.append(Row(["Roof tiles", r.tile_file or
                         f"roof {r.tiles}, which has no file behind it"]))

    if r.colors:
        morn, day, nite1, nite2 = r.colors
        rows.append(Row(["Morn / day", f"{morn}   {day}"]))
        rows.append(Row(["Nite", f"{nite1}   {nite2}"]))

    if r.mislabelled is not None:
        rows.append(Row([
            "⚠ source", f"roofs.asm comments this byte '; group {r.mislabelled}', "
                        f"but the engine reads it for group {r.group} "
                        f"(LoadMapGroupRoof indexes by wMapGroup, no offset)."]))
    return cols, rows


def wild(blocks: dict[str, wilddata.WildBlock]) -> Table:
    """The map's encounters, keyed by which table they came from (GRASS, WATER)."""
    cols = ["table", "time", "#", "level", "species"]
    rows: list[Row] = []
    for kind, block in blocks.items():
        for time, encounters in block.mons.items():
            for i, e in enumerate(encounters):
                first = not rows or rows[-1].cells[0] != kind
                rows.append(Row([kind if first else "", time if i == 0 else "",
                                 str(i + 1), str(e.level), e.species]))
    return cols, rows
