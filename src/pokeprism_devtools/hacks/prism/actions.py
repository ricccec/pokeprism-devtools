"""Prism's two map-to-map actions: connecting a neighbour, warping to one.

These lived in `studio/actions.py` next to the base class until the family
needed to write. They read as neutral — every gen-2 tree has connections and
warps — but they are not: both go through `wiring/connections` and
`wiring/warps`, and both of those parse prism's secondary map headers. Sitting
in the base module they meant that `hacks/vanilla/write.py` importing `Action`
imported prism, which is the dependency the seam exists to prevent.

So they moved here, where the modules they call already live, and the base is
left with nothing under it. The rule the move states: **adapters import the
base; the base imports no adapter.**

Their mirrors on the family side exist now — `hacks/vanilla/mapactions.py`, kept
out of that adapter's `content.py` for the same reason these are kept out of the
base — and the move is what let them: the family's `FamilyConnect` writes the
modern four-argument `connection` macro into the shared `attributes.asm`, which
is a different job from the one below, and neither had to know about the other.
"""

from __future__ import annotations

from pathlib import Path

from ...studio.actions import (DIRECTIONS, MAPS, Action, ActionError, Field,
                               Result)
from . import connections, warps


class Connect(Action):
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
            edit, conns = connections.connect(
                root, self.a, self.text("direction"), self.text("b"), self.integer("offset"))
        except connections.WiringError as e:
            raise ActionError(str(e)) from e
        return Result(edit.detail, [edit] if edit.changed else [],
                      [] if edit.changed else ["already connected — nothing to do"])


class AddWarp(Action):
    name = "warp"
    title = "Add a warp (both ways)"
    FIELDS = (
        Field("y", "Y here", kind="int", help="where you step in on THIS map"),
        Field("x", "X here", kind="int"),
        Field("b", "Destination", choices=MAPS),
        Field("by", "Y there", kind="int", help="where you come out"),
        Field("bx", "X there", kind="int"),
    )

    def __init__(self, a: str, **values: str) -> None:
        super().__init__(**values)
        self.a = a

    def describe(self) -> str:
        return (f"warp {self.a} ({self.text('y')}, {self.text('x')}) <-> "
                f"{self.text('b')} ({self.text('by')}, {self.text('bx')})")

    def run(self, root: Path) -> Result:
        try:
            edits, (wa, wb) = warps.add_paired_warp(
                root, self.a, self.coords(), self.text("b"), self.coords("by", "bx"))
        except warps.WarpError as e:
            raise ActionError(str(e)) from e
        return Result(
            f"{self.a} warp #{wa.index} <-> {self.text('b')} warp #{wb.index}",
            [e for e in edits if e.changed],
        )
