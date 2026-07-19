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

from ..hacks.prism import swatches
from ..shared import coords
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
    marks: dict[coords.Tile, str]

    @property
    def size(self) -> tuple[int, int]:
        """Rows and columns, in coordinate tiles."""
        return coords.tile_size(self.height, self.width)


@dataclass(frozen=True)
class Draft:
    """A map that does not exist yet, and the form it would be made from.

    What comes back from the new-map form when you ask to *see* it rather than to
    make it. The picture goes on the main grid — full size, zoomable, scrollable —
    which is the whole reason the form gives it up rather than keeping a ten-row
    panel of its own: a route is forty blocks across, and a picture you can only
    see the top-left corner of cannot tell you the one thing you opened it to find
    out, which is whether the shape is right.

    The values ride along so the form can be handed back exactly as you left it.
    Nothing has been written; nothing is going to be until you say so.
    """
    values: dict[str, str]
    view: MapGeometry

    @property
    def label(self) -> str:
        return self.values.get("label", "").strip() or "the new map"


@dataclass(frozen=True)
class MapData:
    """One map, read off disk once, in a form the view can render without
    knowing what any of it means."""
    label: str
    const: str
    #: None only when the blocks themselves can't be read. A map whose *header*
    #: is broken still has geometry, and an "Objects" tab saying why.
    geometry: MapGeometry | None
    #: Why the header didn't parse, or the blocks couldn't be read. A map can
    #: have this *and* a geometry: the two failures are independent.
    error: str | None
    #: In tab order. A tab knows its own name, its table, whether it can be
    #: added to, and why it is read-only if it is — so the view iterates rather
    #: than consulting a list of tab names it would have to keep in step.
    tabs: list[panels.Tab]

    def tab(self, name: str) -> panels.Tab | None:
        return next((t for t in self.tabs if t.name == name), None)

    # -- the grid and the tables are one selection ----------------------------- #
    #
    # Both of these read the *rows*, and only the rows. A map's objects are laid
    # out twice — once as glyphs on the grid (`MapGeometry.marks`) and once as
    # table rows — and the temptation is to build this index from the glyphs,
    # since they are already keyed by tile. That would be a second enumeration of
    # the same event header, and a second enumeration is a chance to disagree with
    # the first: point at the third NPC, highlight the fourth. Deriving it from
    # the rows that carry the Refs means the index and the row cannot diverge,
    # because they are the same list.

    def at(self, tile: coords.Tile) -> tuple[panels.Ref, ...]:
        """Everything standing on this tile, in tab order.

        A tuple, not one Ref: two objects can share a tile — a signpost on the
        same square as the NPC in front of it — and `marks` cannot say so, because
        it is a dict keyed by tile and the second one silently overwrites the
        first. Here they both survive.
        """
        return tuple(row.ref for tab in self.tabs for row in tab.table[1]
                     if row.tile == tile and row.ref is not None)

    def tile_of(self, ref: panels.Ref) -> coords.Tile | None:
        """Where this row's object stands, if it stands anywhere. A connection is
        a property of the whole map edge and a wild encounter is not on the map at
        all, so for those the answer is None and the cursor stays where it is."""
        return next((row.tile for tab in self.tabs for row in tab.table[1]
                     if row.ref == ref), None)


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
    #: Findings that were not there before this landed — i.e. **what this change
    #: broke**. The backstop for the one thing a fresh model cannot catch: a
    #: mutation that read the repo correctly and reasoned about it wrongly. The
    #: linter already runs after every write, so knowing this costs a set
    #: difference, and it turns "it applied" into "it applied, and here is what it
    #: cost you".
    introduced: list[Finding] = field(default_factory=list)

    def touched(self) -> list[tuple[str, str]]:
        """`(path, which lines)` for every file this wrote.

        The line numbers are of the file *as it now stands*, which is the file
        you would open to look at them. A created file says so; a binary one says
        how big it is, because a diff of a `.blk` is one byte per block and could
        tell you nothing the grid didn't already show you in colour.
        """
        out = []
        for rel in self.paths:
            before, after = self.undo_to.get(rel), self.wrote.get(rel)
            if before is None:
                out.append((rel, "created"))
            elif isinstance(after, bytes) or isinstance(before, bytes):
                out.append((rel, f"{len(after or b'')} bytes"))
            else:
                out.append((rel, _ranges(before, after or "")))
        return out


def _ranges(before: str, after: str) -> str:
    """Which lines of `after` differ from `before`, as "12-18, 40"."""
    lines = [
        (i + 1)
        for group in difflib.SequenceMatcher(
            None, before.split("\n"), after.split("\n"), autojunk=False
        ).get_opcodes()
        if group[0] != "equal"
        for i in range(group[3], max(group[4], group[3] + 1))
    ]
    if not lines:
        return "no change"

    spans, start, last = [], lines[0], lines[0]
    for n in lines[1:]:
        if n == last + 1:
            last = n
            continue
        spans.append((start, last))
        start = last = n
    spans.append((start, last))
    return ", ".join(str(a) if a == b else f"{a}-{b}" for a, b in spans)


@dataclass(frozen=True)
class Finding:
    """One diagnostic, flattened for the view.

    The view is not handed a `Diagnostic`: it would have to know a `Severity`
    enum and, worse, would have to turn a map *const* into the *label* the map
    list is keyed by — and the only thing that can do that is the linter's
    context. So the session resolves it here and the view renders strings.
    """
    severity: str               # "error" | "warning" | "info"
    code: str
    message: str
    location: str
    map_label: str              # "" for a finding about no map in particular
    line: int

    @property
    def haystack(self) -> str:
        """Everything one filter box should match against, lowercased once."""
        return " ".join((self.severity, self.code, self.message,
                         self.location, self.map_label)).lower()


@dataclass(frozen=True)
class Mutation:
    """One entry in the history panel: what was done, and whether it can be
    taken back. See `Session.mutations` for why `blocked` is a sentence."""
    index: int                  # its position in the history, 0 = oldest
    summary: str
    files: list[tuple[str, str]]
    notes: list[str]
    #: Empty when this can be undone. Otherwise, why it can't — the file that
    #: moved under it, or the later mutation holding it down.
    blocked: str = ""
    #: What this change broke: findings that were not there before it landed. The
    #: history panel is the only place you can still see them attributed to the
    #: change that caused them, which is what makes it worth carrying here.
    introduced: list[Finding] = field(default_factory=list)

    @property
    def undoable(self) -> bool:
        return not self.blocked
