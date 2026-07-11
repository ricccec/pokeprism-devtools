"""What the studio hands the view: plain data, and nothing that knows how to draw.

Every byte the TUI shows arrives as one of these. They are the seam made
concrete — `Session` reads the repo and answers in these types; `grid.py` and
`forms.py` render them and open nothing. A dataclass here may know *what* a
marker is; it must never know where the file that says so lives.

Split out of :mod:`.session` when that module grew past the size where one file
is still one idea. The reading and writing is over there; this is only the shape
of the answers.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field

from ..shared import coords, swatches
from ..shared.edits import Edit
from . import panels
from .actions import Action, Result

@dataclass(frozen=True)
class MapRef:
    const: str
    label: str

    def __str__(self) -> str:
        return self.label


@dataclass(frozen=True)
class MapGeometry:
    """A map's shape, and what stands on it. Everything needed to draw it, and
    nothing that knows how to draw."""
    label: str
    blocks: bytes
    height: int                                    # in blocks
    width: int                                     # in blocks
    swatches: tuple[swatches.Swatch, ...]
    #: Coordinate tile -> marker glyph. Empty when the event header doesn't parse:
    #: the map still has a shape, and it is still worth looking at.
    marks: dict[tuple[int, int], str]

    @property
    def size(self) -> tuple[int, int]:
        """Rows and columns, in coordinate tiles."""
        return coords.tile_size(self.height, self.width)


@dataclass(frozen=True)
class MapData:
    """One map, read off disk once, in a form the view can render without
    knowing what any of it means."""
    label: str
    const: str
    #: None only when the blocks themselves can't be read. A map whose *header*
    #: is broken still has geometry — see `tables["error"]`.
    geometry: MapGeometry | None
    #: Why there is no geometry, when there isn't.
    error: str | None
    tables: dict[str, panels.Table]


@dataclass(frozen=True)
class TextRef:
    """A block of dialogue already in the game, as prose."""
    label: str          # what a script jumps to, or `.local` under an owner
    owner: str          # the top-level label that owns it
    lineno: int
    prose: str
    #: Which box it is drawn in — the key :meth:`Session.measure` takes. Nearly
    #: everything is "speech"; the full-screen "sign" box is only SIGNPOST_LOAD.
    box: str

    @property
    def opening(self) -> str:
        """Its first words, for a list you are choosing from."""
        first = next((line for line in self.prose.split("\n") if line.strip()), "")
        return first[:40]


@dataclass(frozen=True)
class Measured:
    """One line of dialogue, as the engine will draw it."""
    text: str
    #: Tiles it certainly prints. `#` is four of them.
    tiles: int
    #: Extra tiles if every bounded buffer (`<PLAYER>`, `<RIVAL>`) is at its
    #: longest. A line that fits *today* and not when the player is called
    #: BARTHOLOMEW is a line that overflows in somebody's game and not in yours.
    bounded: int
    #: Tokens whose length can't be bounded from the text at all (`<STRBF1>`).
    unbounded: list[str]
    #: Tokens with no charmap entry — a typo'd `<PLAYR>` prints as garbage.
    unknown: list[str]
    #: How many tiles past the right edge. 0 fits.
    over: int
    #: How many it would be over at the buffers' worst.
    over_at_worst: int


@dataclass(frozen=True)
class TextPreview:
    """A whole speech, measured against the box it will be drawn in."""
    box: str                # what to call it: "speech textbox", "signpost"
    cols: int               # tiles per line
    lines: list[Measured]

    @property
    def fits(self) -> bool:
        return all(m.over == 0 for m in self.lines)

    @property
    def risky(self) -> bool:
        """Fits as written, and won't once a name buffer is at its longest."""
        return self.fits and any(m.over_at_worst for m in self.lines)


@dataclass(frozen=True)
class Preview:
    """What an action *would* do. Nothing has been written.

    Holds the actual edits, so applying it writes exactly what was shown rather
    than re-deriving something that might differ.
    """
    action: Action
    result: Result

    @property
    def edits(self) -> list[Edit]:
        return self.result.edits

    @property
    def summary(self) -> str:
        return self.result.summary

    @property
    def notes(self) -> list[str]:
        return self.result.notes

    @property
    def touches(self) -> list[str]:
        return [e.path for e in self.edits]

    def diff(self, context: int = 3) -> str:
        """Unified diff of every file this touches.

        A binary edit gets a line saying so. A `.blk` is one byte per block and
        there is nothing a diff of it could tell you that the grid didn't already
        show you in colour.
        """
        out: list[str] = []
        for e in self.edits:
            if e.binary:
                out.append(f"+++ b/{e.path}")
                out.append(f"@@ {e.detail} @@")
                continue
            before = (e.base or "").split("\n")
            after = e.new_text.split("\n")
            out.extend(difflib.unified_diff(
                before, after,
                fromfile=f"a/{e.path}", tofile=f"b/{e.path}",
                lineterm="", n=context,
            ))
        return "\n".join(out)


@dataclass
class Applied:
    """An action that landed, and everything needed to take it back."""
    summary: str
    paths: list[str]
    #: path -> what was there before. None means the file did not exist, so
    #: undoing means deleting it again. `bytes` for a file that is not text —
    #: the whole point of adding a map is that one of its files is a `.blk`.
    undo_to: dict[str, str | bytes | None] = field(default_factory=dict)
    #: path -> what we wrote. Undo refuses if the file no longer matches this.
    wrote: dict[str, str | bytes] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    #: The map to be looking at now, if this action made one.
    select: str | None = None
