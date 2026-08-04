"""What the studio may ask a mounted tree, and the one way it may be told no.

The read half of the contract, and all of it hangs off `Hack.reads`: nine
questions every adapter answers, plus two an adapter may simply not have —
:class:`Measures` when the tree cannot be read for a charmap, :class:`Sketches`
when no form of it draws. An absent one is absent above the seam; it is never
an error and never an `if <hack name>`.

The protocols are structural, so nothing inherits them and no adapter imports
this module for its own sake — they describe the surface three independently
written adapters already present, and exist so a fourth is told what it owes
before it is mounted rather than after.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .attributes import Attributes, Link, Roof
from .blocks import Blocks
from .dialogue import TextPreview, TextRef
from .events import MapTables
from .wild import WildMon


class Unreadable(RuntimeError):
    """An adapter's answer when a map's source cannot be read into records —
    the event block doesn't fit its shape, the blocks file is missing. The
    message is the interesting part: it is what the view shows in place of the
    tables, so it should name the file and the way it disappointed."""


@runtime_checkable
class Reads(Protocol):
    """What the studio may ask any mounted tree. Nine questions, no options.

    `runtime_checkable` buys presence, not signatures — `isinstance` here says
    "has these names", which is the cheap half. The other half is
    `tests/test_seam.py`, which checks the shapes against every adapter at once.
    """

    def maps(self) -> dict[str, str]:
        """The catalog: file label -> map constant. Everything else in this
        protocol is keyed by one or the other, and this is the only method that
        says which names exist at all."""

    def parses(self, const: str) -> bool:
        """Whether this map's events can be read, asked *without* reading them.
        The catalog is drawn before any map is opened, so this has to be cheap
        and it has to be total — a map that will fail is listed, and marked."""

    def connections(self, const: str) -> list[Link]:
        """The maps this one borders, one Link each."""

    def tables(self, label: str) -> MapTables:
        """The six event lists. Raises `Unreadable` — with the reason —
        rather than returning empty ones, because empty tables read as "this map
        has nothing on it", which is a different and much worse claim."""

    def attributes(self, label: str, const: str) -> Attributes:
        """The header facts. Takes *both* names because in every tree so far
        they live in different files under different keys."""

    def geometry(self, label: str) -> Blocks:
        """The blocks, for drawing. Raises `Unreadable`. Independent of
        `tables` on purpose: a map whose events don't parse still has a shape,
        and hiding it from the person looking for the break helps nobody."""

    def wild(self, const: str) -> dict[str, dict[str, list[WildMon]]]:
        """Encounters, by table then by time of day. Empty when the map has
        none — unlike `tables`, absence here is a fact, not a failure."""

    def roof(self, const: str) -> Roof | None:
        """The roof palette, or None where the tree has no such concept."""

    def texts(self, label: str) -> list[TextRef]:
        """Every string in the map's file, in source order."""


@runtime_checkable
class Measures(Protocol):
    """`measures=True` only. Text measured in tiles is engine physics — a
    charmap, control-code expansions, buffer tokens — so a tree the studio cannot
    read those out of cannot answer, and the session refuses with that sentence
    rather than guessing in characters. Tiles, not pixels: what a proportional
    font would need is a per-glyph width, and the trees that have one keep it off
    the dialogue path."""

    def measure(self, text: str, box: str) -> TextPreview: ...


@runtime_checkable
class Sketches(Protocol):
    """Reachable only from an action whose `sketches` is True. Draws what a form
    would create before it exists, which is how a `.blk` of the wrong size stops
    being an arithmetic complaint and becomes a map of the wrong shape."""

    def sketch(self, action) -> Blocks | None: ...
