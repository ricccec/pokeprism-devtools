"""What an IDE and a hack adapter must agree on before either can be written.

The noun list and the question list, and nothing else. Nothing here parses a
file, opens one, or draws anything: it exists to be *pointed at*, so that the
two sides depend on it instead of on each other. Read it in one sitting — that
is the size it is meant to be.

Two halves. The **nouns** are what a Gen-2 map is made of: the six lists of
things standing on it (:mod:`.events`), the header, its edges and its roof
(:mod:`.attributes`), its shape (:mod:`.blocks`), its encounters (:mod:`.wild`),
its dialogue (:mod:`.dialogue`), and the opaque handle that names any one of
them (:mod:`.ref`). The **questions** are the capabilities an adapter declares.

A capability an adapter does not implement degrades to *absence* on the other
side — no lint panel, no boot key, no edit forms. Never a crash, and never an
`if <hack name>`.

The only thing this package imports beyond the standard library is `shared/` —
`coords.Tile` and `swatches` — because a coordinate tile and a colour are Gen-2
facts that already live there, and that library cannot depend on this one
without turning the arrow round.
"""

from __future__ import annotations

from .attributes import Attributes, Link, Roof
from .blocks import Blocks, Rgb, Sketch, Swatch
from .dialogue import Measured, TextPreview, TextRef
from .events import MapTables, Npc, Prop, Signpost, Trainer, Trigger, Warp
from .reads import Unreadable
from .ref import ADD, Ref, add_ref
from .wild import WildMon

__all__ = ["ADD", "Attributes", "Blocks", "Link", "MapTables", "Measured", "Npc",
           "Prop", "Ref", "Rgb", "Roof", "Signpost", "Sketch", "Swatch",
           "TextPreview", "TextRef", "Trainer", "Trigger", "Unreadable", "Warp",
           "WildMon", "add_ref"]
