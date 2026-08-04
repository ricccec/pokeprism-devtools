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

from .action import Action, ActionError, Field, Result
from .attributes import UNSAID, Attributes, Link, Roof
from .blocks import Blocks, Rgb, Sketch, Swatch
from .choices import (BLOCK_SECTIONS, BLOCKS, CLASSES, DIRECTIONS,
                      FACINGS, FISHGROUPS, FLAGS, GROUPS, ITEMS,
                      LANDMARKS, MAPS, MOVEMENTS, MUSIC, PALETTES,
                      PARTIES, PERMISSIONS, SCRIPT_SECTIONS, SIGNS,
                      SPRITES, TILESETS, TIMES, TMHMS, TREES)
from .diagnostic import Diagnostic, Severity
from .dialogue import Measured, TextPreview, TextRef
from .events import MapTables, Npc, Prop, Signpost, Trainer, Trigger, Warp
from .hack import Hack
from .lints import Lints
from .plays import PlayError, Plays
from .reads import Measures, Reads, Sketches, Unreadable
from .ref import ADD, Ref, add_ref
from .wild import WildMon
from .writes import Refused, Writes

__all__ = ["ADD", "Action", "ActionError", "Attributes", "BLOCKS",
           "BLOCK_SECTIONS", "Blocks", "CLASSES", "DIRECTIONS", "Diagnostic",
           "FACINGS", "FISHGROUPS", "FLAGS", "Field", "GROUPS", "Hack", "ITEMS",
           "LANDMARKS", "Link", "Lints", "MAPS", "MOVEMENTS", "MUSIC",
           "MapTables", "Measured", "Measures", "Npc", "PALETTES", "PARTIES",
           "PERMISSIONS", "PlayError", "Plays", "Prop", "Reads", "Ref",
           "Refused", "Result", "Rgb", "Roof", "SCRIPT_SECTIONS", "SIGNS",
           "SPRITES", "Severity", "Signpost", "Sketch", "Sketches", "Swatch",
           "TILESETS", "TIMES", "TMHMS", "TREES", "TextPreview", "TextRef",
           "UNSAID",
           "Trainer", "Trigger", "Unreadable", "Warp", "WildMon", "Writes",
           "add_ref"]
