"""Everything about one map, read once, in a form the view can draw.

Split out of :mod:`.session` when that module grew past the size where one file
is still one idea: the session is the *model* — it owns the linter, the history
and the writing — and this is the reading. Nothing in here mutates anything, and
nothing in here takes a lock, which is what lets `Session.load` run it on a
thread while the UI stays alive.

Nothing in here opens a file either, any more. Every question about the tree
goes to the mounted hack's read adapter (`hacks/mount`), which answers in the
seam's records — `contract.MapTables`, `contract.Blocks`, `contract.Attributes` — and
this module only assembles those answers into the :class:`MapData` the view
draws. Which five files a map's eight header facts are spread across, and what
each of them calls the map, is exactly the knowledge that made this module
prism's; it is the adapter's now, and that is why the view is still not allowed
to ask.

A map whose event tables don't parse still comes back **with its geometry**,
and the parse error where its objects would have been. Hiding a broken map from
the person looking for the break is the worst thing this could do.
"""

from __future__ import annotations

from .. import contract
from . import panels
from .model import MapData, MapGeometry


def read_map(reads, label: str) -> MapData:
    """One map, whole, from the mounted adapter. No state."""
    const = reads.maps().get(label, label)
    tabs: list[panels.Tab] = []
    error = None

    tables = None
    try:
        tables = reads.tables(label)
    except contract.Unreadable as exc:
        error = str(exc)

    tabs.append(panels.Tab("Attributes",
                           panels.attributes(reads.attributes(label, const))))

    if tables is not None:
        tabs += [
            panels.Tab("NPCs", panels.npcs(tables.npcs), adds="NPC"),
            panels.Tab("Trainers", panels.trainers(tables.trainers), adds="trainer"),
            panels.Tab("Objects", panels.objects(tables.props), adds="object"),
            panels.Tab("Warps", panels.warps(tables.warps), adds="warp"),
            panels.Tab("Signposts", panels.signposts(tables.signposts), adds="signpost"),
            panels.Tab("Triggers", panels.triggers(tables.triggers), adds="trigger"),
        ]
    else:
        # The map has a shape but its tables can't be read. Say so where the
        # objects would have been, rather than showing empty tables that read as
        # "this map has nothing on it".
        tabs.append(panels.Tab(
            "Unreadable", (["why"], [panels.Row([error or ""])]),
            note="this map's events do not parse, so nothing on it can be "
                 "listed or edited. Its shape is still real."))

    tabs.append(panels.Tab("Connections",
                           panels.connections(reads.connections(const)),
                           adds="connection"))

    if (r := reads.roof(const)) is not None:
        tabs.append(panels.Tab("Roof", panels.roof(r),
                               note=panels.ROOF_IS_READ_ONLY))
    tabs.append(panels.Tab("Wild", panels.wild(reads.wild(const)),
                           note=panels.WILD_IS_READ_ONLY))

    try:
        bd = reads.geometry(label)
    except contract.Unreadable as exc:
        return MapData(label, const, None, str(exc), tabs)

    geometry = MapGeometry(
        label=label, blocks=bd.blocks, height=bd.height, width=bd.width,
        swatches=bd.swatches,
        marks=tables.marks if tables is not None else {},
    )
    return MapData(label, const, geometry, error, tabs)


def sketch(reads, action) -> MapGeometry | None:
    """A picture of what an action would put on the grid, before it exists.

    Only the new-map action has anything to show — see `Action.sketch`. The form
    calls this on every keystroke and either draws the result or prints why it
    can't, which is how a `.blk` of the wrong size stops being an arithmetic
    complaint and becomes a map of the wrong shape.

    Raises `ActionError` for a form that isn't ready yet. That is the normal state
    of a form you are typing into, not a failure.
    """
    bd = reads.sketch(action)
    if bd is None:
        return None
    return MapGeometry(
        label=bd.label, blocks=bd.blocks, height=bd.height, width=bd.width,
        swatches=bd.swatches,
        marks={},                        # nothing stands on it yet
    )
