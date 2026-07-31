"""The family's map-to-map actions: connecting a neighbour and unconnecting one.

Mirrors prism's :mod:`..prism.actions`, and kept out of :mod:`.actions` for the
same reason prism keeps `Connect` out of `content.py`: these are not `_Entry`
adders. An event adder splices one line into one map's own file; a connection is
a *pair* of lines in the shared `data/maps/attributes.asm`, one under each map,
two-sided and cross-map. So the shape is prism's `Connect`/`Disconnect`, not the
family's in-map adders — the map const is a first positional seat the form fills,
not a field, exactly as :func:`..prism.actions.Connect` takes it.

Both trees write the identical modern `connection` macro, so unlike the event
adders these fork on nothing and mount one class each — which is why `actions.fork`
injects the adder unstamped rather than stamping an event anchor onto it. The
work all lives in :mod:`.connections`; these are the thin studio-facing wrappers
that turn a form into a call and a `WiringError` into an `ActionError`.
"""

from __future__ import annotations

from pathlib import Path

from ...studio.actions import (DIRECTIONS, MAPS, Action, ActionError, Field,
                               Result)
from . import connections


class FamilyConnect(Action):
    """Wire a neighbour onto one side of this map, both directions written."""
    name = "connect"
    title = "Connect a neighbouring map"
    FIELDS = (
        Field("b", "Neighbour", choices=MAPS, help="the map on the other side"),
        Field("direction", "Direction", choices=DIRECTIONS,
              help="which side of THIS map the neighbour sits on"),
        Field("offset", "Offset", kind="int", default="0",
              help="how far the neighbour slides along the shared edge, in blocks"),
    )

    def __init__(self, a: str, **values: str) -> None:
        super().__init__(**values)
        self.a = a

    def describe(self) -> str:
        return (f"connect {self.text('b')} {self.text('direction')} of {self.a} "
                f"at offset {self.text('offset')}")

    def run(self, root: Path) -> Result:
        try:
            edit = connections.connect(
                root, self.a, self.text("direction"), self.text("b"),
                self.integer("offset"))
        except connections.WiringError as e:
            raise ActionError(str(e)) from e
        return Result(edit.detail, [edit] if edit.changed else [],
                      [] if edit.changed else ["already connected — nothing to do"])


class FamilyDisconnect(Action):
    """Remove one side of this map's connection, and the neighbour's side of it.

    Built by the write adapter's `deletion`, not offered as an adder — you point
    at the connection row and press `d`, so its direction is a `fixed` field
    carried across rather than typed."""
    name = "disconnect"
    title = "Remove a connection"
    FIELDS = (Field("direction", "Direction", kind="fixed"),)

    def __init__(self, a: str, **values: str) -> None:
        super().__init__(**values)
        self.a = a

    def describe(self) -> str:
        return f"remove {self.a}'s {self.text('direction')} connection"

    def run(self, root: Path) -> Result:
        try:
            edit, notes = connections.disconnect(
                root, self.a, self.text("direction"))
        except connections.WiringError as e:
            raise ActionError(str(e)) from e
        return Result(edit.detail, [edit] if edit.changed else [],
                      notes or ([] if edit.changed else ["unchanged"]))
