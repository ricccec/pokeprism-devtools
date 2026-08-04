"""A block of dialogue, and what it measures to in the box that draws it.

Text is measured in **tiles**, not characters: the engine's charmap, its control
codes and its buffer tokens are what decide how wide a line prints, and a tree
the adapter cannot read those out of answers nothing at all rather than guessing.
See the `Measures` capability, which is optional for exactly that reason.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TextRef:
    """A block of dialogue already in the game, as prose. The adapter parses
    its own text macros into this; the macros go back positionally on the way
    home (`wiring/text.reword`), which is what lets the record hold none."""
    label: str          # what a script jumps to, or `.local` under an owner
    owner: str          # the top-level label that owns it
    lineno: int
    prose: str
    #: Which box it is drawn in — the key :meth:`Session.measure` takes. Nearly
    #: everything is "speech"; the full-screen "sign" box is the rarity.
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
