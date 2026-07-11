"""What goes in the tables under the grid.

Pure functions: each returns `(columns, rows)` of plain strings, so the contents
of every tab can be tested without starting a terminal, and the widgets stay
dumb. Nothing here reads a file — the caller hands in what it already parsed.

Every coordinate shown is the number **written in the source**, because that is
the number you would type to change it. The `+4` the `person_event` macro adds
belongs to the assembled bytes and appears nowhere in this file.
"""

from __future__ import annotations

from ..maplint.context import Connection
from ..shared import eventheader as eh
from ..shared import wilddata

Table = tuple[list[str], list[list[str]]]

_NONE = "—"


def _yx(entry: eh.Entry) -> tuple[str, str]:
    y, x = entry.coords
    return (_NONE if y is None else str(y), _NONE if x is None else str(x))


def objects(header: eh.EventHeader) -> Table:
    cols = ["#", "y", "x", "sprite", "type", "movement", "points at", "event flag"]
    rows = []
    for i, e in enumerate(header.object_events):
        y, x = _yx(e)
        rows.append([str(i), y, x, e.sprite, e.persontype.replace("PERSONTYPE_", ""),
                     e.movement.replace("SPRITEMOVEDATA_", ""),
                     e.pointer or _NONE, e.event_flag])
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
        rows.append([str(i), y, x, dest, which])
    return cols, rows


def bg_events(header: eh.EventHeader) -> Table:
    cols = ["#", "y", "x", "kind", "points at"]
    rows = []
    for i, e in enumerate(header.bg_events):
        y, x = _yx(e)
        kind = e.arg(2) if len(e.args) > 2 else _NONE
        rows.append([str(i), y, x, kind.replace("SIGNPOST_", ""), e.pointer or _NONE])
    return cols, rows


def coord_events(header: eh.EventHeader) -> Table:
    cols = ["#", "y", "x", "scene", "points at"]
    rows = []
    for i, e in enumerate(header.coord_events):
        y, x = _yx(e)
        rows.append([str(i), y, x, e.arg(0), e.pointer or _NONE])
    return cols, rows


def connections(conns: list[Connection]) -> Table:
    """`delta` is the alignment between the two maps' coordinate systems. The
    map on the other side must carry exactly its negation, or the seam tears —
    which is why it's a column and not a detail."""
    cols = ["direction", "to map", "coord", "offset", "strip", "delta"]
    rows = [[c.direction, c.target, str(c.coord), str(c.offset),
             str(c.strip), f"{c.delta:+d}"]
            for c in sorted(conns, key=lambda c: c.direction)]
    return cols, rows


def wild(blocks: dict[str, wilddata.WildBlock]) -> Table:
    """The map's encounters, keyed by which table they came from (GRASS, WATER).

    Read-only, and it stays that way: wild records are fixed-size and read
    positionally, so writing a short one doesn't error — it silently shifts every
    map below it in the table onto the wrong encounters.
    """
    cols = ["table", "time", "#", "level", "species"]
    rows = []
    for kind, block in blocks.items():
        for time, encounters in block.mons.items():
            for i, e in enumerate(encounters):
                rows.append([kind if not rows or rows[-1][0] != kind else "",
                             time if i == 0 else "",
                             str(i + 1), str(e.level), e.species])
    return cols, rows
