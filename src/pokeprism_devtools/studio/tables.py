"""What goes in the tables under the grid — and what a selected row *is*.

Pure functions: each returns `(columns, rows)`, so the contents of every tab can
be tested without starting a terminal and the widgets stay dumb. Nothing here
opens a file — and nothing here parses one either. Each tab's input is a
**declared record** (:class:`~..contract.Npc`, :class:`~..contract.Warp`,
:class:`~..contract.WildMon`, …) out of the contract package: that side declares
the vocabulary, an adapter fills it in from whatever its grammar happens to be,
and this side renders six lists it is handed and never learns what a
`person_event` is.

The carve-up into six is the contract's, not any engine's; what is decided *here*
is only how each of them is drawn — which columns, in what order, and what a cell
says when the record has nothing to put in it.

Every coordinate shown is the number **written in the source**, because that is
the number you would type to change it. Offsets a macro adds while assembling
belong to the assembled bytes and appear nowhere in this file.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..contract import (Attributes, Link, Npc, Prop, Ref, Roof, Signpost,
                        Trainer, Trigger, Warp, WildMon)
from ..shared.coords import Tile

_NONE = "—"


# --------------------------------------------------------------------------- #
# what a row is                                                               #
# --------------------------------------------------------------------------- #


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


#: Marks a row whose entry is in the file but past its list's count byte. The
#: engine reads `db N` and stops, so it is written down and not in the game.
#: Only an adapter whose lists *have* a count byte can ever set the flag this
#: renders — prism's `db N` is the outlier; the `def_*` macros self-count, so a
#: vanilla or polished row simply never carries it.
UNDECLARED = "⚠"


def _yx(r) -> tuple[str, str]:
    return (_NONE if r.y is None else str(r.y), _NONE if r.x is None else str(r.x))


def _num(r, shown: int | None = None) -> str:
    """The `#` cell — and a mark on it when the engine will never get this far.

    PhloxLab1F says `db 6 ; FIXME` over seven `person_event`s, so its seventh
    object — a Max Revive on the floor — is in the source and not in the game.
    The row is here because *the line is in the file*: the way to fix an object
    that doesn't spawn is to look at it, and a table that hid it left you staring
    at a map with a ball drawn on it that the studio said did not exist. What it
    cannot do is pretend the count byte is right, so the row says so, and the
    linter's `obj-count` says why.
    """
    n = r.index if shown is None else shown
    return f"{n} {UNDECLARED}" if r.undeclared else str(n)


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


def _tile(r) -> Tile | None:
    """The tile it stands on, or None when the coordinates aren't literal numbers.

    An object whose `y` is a constant expression rather than a number still gets a
    row — you can see it and delete it — but nothing can point at it on the grid,
    and pretending otherwise would put it at (0, 0).
    """
    return None if r.y is None or r.x is None else Tile(y=r.y, x=r.x)


# --------------------------------------------------------------------------- #
# the object tabs                                                             #
# --------------------------------------------------------------------------- #

def npcs(recs: list[Npc]) -> Table:
    cols = ["#", "y", "x", "sprite", "movement", "says", "event flag"]
    rows = [Row([_num(r), *_yx(r), r.sprite, r.movement, r.says or _NONE, r.flag],
                Ref("npc", r.handle), _tile(r))
            for r in recs]
    return cols, rows


def trainers(recs: list[Trainer]) -> Table:
    cols = ["#", "y", "x", "sprite", "class", "party", "sight", "event flag"]
    rows = [Row([_num(r), *_yx(r), r.sprite, r.cls or _NONE, r.party or _NONE,
                 r.sight or _NONE, r.flag or _NONE],
                Ref("trainer", r.handle), _tile(r))
            for r in recs]
    return cols, rows


def objects(recs: list[Prop]) -> Table:
    """Item balls, TM balls, fruit trees, rocks, boulders — and the hidden items,
    which an engine may keep in the other list entirely. See the module
    docstring: none of them is a person, and that is what the tab is for."""
    cols = ["#", "y", "x", "kind", "what", "qty", "event flag"]
    rows = [Row([_num(r), *_yx(r), r.kind, r.what or _NONE, r.qty or _NONE,
                 r.flag or _NONE],
                Ref("prop", r.handle), _tile(r))
            for r in recs]
    return cols, rows


def signposts(recs: list[Signpost]) -> Table:
    """Every sign — the things you read. The hidden items an engine files with
    them are on the Objects tab, where a person would look."""
    cols = ["#", "y", "x", "kind", "points at"]
    rows = [Row([_num(r), *_yx(r), r.kind or _NONE, r.points_at or _NONE],
                Ref("signpost", r.handle), _tile(r))
            for r in recs]
    return cols, rows


def warps(recs: list[Warp]) -> Table:
    """`their warp #` is an index into the *destination* map's warp list, not a
    map id. Off by one and you land in the wrong doorway."""
    cols = ["#", "y", "x", "to map", "their warp #"]
    rows = [Row([_num(r, r.index + 1), *_yx(r), r.to_map or _NONE,
                 r.their_warp or _NONE],
                Ref("warp", r.handle), _tile(r))
            for r in recs]
    return cols, rows


def triggers(recs: list[Trigger]) -> Table:
    cols = ["#", "scene", "y", "x", "runs"]
    rows = [Row([_num(r), r.scene, *_yx(r), r.runs or _NONE],
                Ref("trigger", r.handle), _tile(r))
            for r in recs]
    return cols, rows


def connections(links: list[Link]) -> Table:
    """`delta` is the alignment between the two maps' coordinate systems. The
    map on the other side must carry exactly its negation, or the seam tears —
    which is why it's a column and not a detail.

    The computed columns exist only when some row fills them: the modern
    `def_*` dialect writes just the offset and lets the assembler derive the
    rest, so there is nothing written in the source for those cells to show.
    """
    links = sorted(links, key=lambda c: c.direction)
    computed = any(c.coord is not None for c in links)
    cols = (["direction", "to map", "coord", "offset", "strip", "delta"]
            if computed else ["direction", "to map", "offset"])
    rows = []
    for c in links:
        cells = [c.direction, c.target]
        if computed:
            cells += [_NONE if c.coord is None else str(c.coord), str(c.offset),
                      _NONE if c.strip is None else str(c.strip),
                      _NONE if c.delta is None else f"{c.delta:+d}"]
        else:
            cells += [str(c.offset)]
        rows.append(Row(cells, Ref("connection", key=c.direction)))
    return cols, rows


# --------------------------------------------------------------------------- #
# the read-only tabs                                                          #
# --------------------------------------------------------------------------- #


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



def roof(r: Roof) -> Table:
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



def wild(blocks: dict[str, dict[str, list[WildMon]]]) -> Table:
    """The map's encounters, keyed by which table they came from (GRASS, WATER),
    then by time of day."""
    formed = any(m.form for times in blocks.values()
                 for mons in times.values() for m in mons)
    cols = ["table", "time", "#", "level", "species"] + (["form"] if formed else [])
    rows: list[Row] = []
    for kind, times in blocks.items():
        for t, (time, mons) in enumerate(times.items()):
            for i, m in enumerate(mons):
                cells = [kind if t == 0 and i == 0 else "",
                         time if i == 0 else "",
                         str(i + 1), str(m.level), m.species]
                rows.append(Row(cells + ([m.form] if formed else [])))
    return cols, rows
