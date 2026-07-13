"""The surfaces that tell you things: where you are, what is wrong, what moved.

Three read-only panels, split out of `app.py`. None of them opens a file — each is
handed what it draws.

The one that is new is :class:`Banner`, and it is the visible half of a guarantee.
The studio holds the whole repo in memory and every write is checked against that
memory, so a repo that changes underneath it is not a stale dropdown — it is a
write checked against a repo that no longer exists. `shared/world.py` notices
within a few seconds; this is how you find out. Which matters, because the
alternative is finding out at the moment you press enter on a form you have just
spent a minute filling in.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Static

from ..shared import coords
from .grid import MapGrid
from .model import Finding

_SEVERITY_STYLE = {"error": "bold red", "warning": "yellow", "info": "dim cyan"}


def marker_style(glyph: str) -> str:
    return (f"bold {coords.hex_color(coords.MARKER_INK[glyph])} "
            f"on {coords.hex_color(coords.MARKER_BG[glyph])}")


class Banner(Static):
    """The repo changed on disk, and nothing may be written until it is re-read."""

    DEFAULT_CSS = """
    Banner { height: 1; padding: 0 1; background: $warning; color: $text; display: none; }
    """

    def show(self, moved: list[str]) -> None:
        """`moved` empty puts it away again — which happens by itself the moment
        you press `r`, so the banner needs no dismissing and cannot be dismissed
        while it is still true."""
        self.display = bool(moved)
        if not moved:
            return
        names = ", ".join(moved[:2])
        rest = f" and {len(moved) - 2} more" if len(moved) > 2 else ""
        self.update(f"⚠  {len(moved)} file(s) changed on disk ({names}{rest}) "
                    f"— press r to re-read the repo. Writing is refused until you do.")


class Where(Static):
    """The cursor, and the mouse. Both, because they answer different questions.

    The cursor is where the next thing you add will land. The mouse is how you look
    something up: the linter says "warp 2", the table says warp 2 is at (2, 17),
    and the way to find out *which door that is* is to put the pointer on 2, 17 and
    read the marker off. Walking the cursor there would work too — and would move
    the coordinates every form is about to be prefilled with.
    """

    DEFAULT_CSS = """
    Where { height: 1; padding: 0 1; background: $panel; color: $text-muted; }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._cursor: MapGrid.Moved | None = None
        self._mouse: MapGrid.Hovered | None = None
        #: How many objects share the cursor's tile. `marks` cannot say — it is a
        #: dict keyed by tile, so the second object on a square silently overwrites
        #: the first. The rows can, so the count arrives from there.
        self._stacked = 0

    def cursor(self, at: MapGrid.Moved, stacked: int = 0) -> None:
        self._cursor, self._stacked = at, stacked
        self._draw()

    def mouse(self, at: MapGrid.Hovered | None) -> None:
        self._mouse = at
        self._draw()

    def error(self, message: str) -> None:
        self._say(message, "bold red")

    def note(self, message: str) -> None:
        """Something true about what is on the grid that no coordinate can say —
        that it is a map which does not exist yet, for instance."""
        self._say(message, "bold")

    def _say(self, message: str, style: str) -> None:
        # Whatever is on the grid is not the map these coordinates were about.
        self._cursor = self._mouse = None
        self.update(Text(message, style=style))

    def _draw(self) -> None:
        line = Text()
        if (at := self._cursor) is not None:
            block = coords.block_of(at.y, at.x)
            quadrant = coords.quadrant_of(at.y, at.x)
            line.append(f"y {at.y}  x {at.x}", style="bold")
            line.append(f"   block {block[0]},{block[1]} "
                        f"q{quadrant[0]}{quadrant[1]}", style="dim")
            if at.glyph:
                line.append("   ")
                line.append(f" {at.glyph} ", style=marker_style(at.glyph))
            if self._stacked > 1:
                line.append(f"  {self._stacked} here", style="dim")

        if (mouse := self._mouse) is not None:
            line.append("        mouse ", style="dim")
            line.append(f"y {mouse.y}  x {mouse.x}", style="bold")
            if mouse.glyph:
                line.append("  ")
                line.append(f" {mouse.glyph} ", style=marker_style(mouse.glyph))

        self.update(line)


class Legend(Static):
    DEFAULT_CSS = """
    Legend { height: 1; padding: 0 1; }
    """

    def on_mount(self) -> None:
        out = Text()
        for glyph, name in (("W", "warp"), ("S", "signpost"), ("N", "npc"),
                            ("T", "trainer"), ("I", "item"), ("X", "trigger")):
            out.append(f" {glyph} ", style=marker_style(glyph))
            out.append(f" {name}  ", style="dim")
        self.update(out)


class Diagnostics(VerticalScroll):
    """What the linter thinks of the map you are looking at."""

    DEFAULT_CSS = """
    Diagnostics { width: 46; border-left: solid $panel; padding: 0 1; }
    """

    def compose(self) -> ComposeResult:
        yield Static(id="found")

    def waiting(self) -> None:
        """A cold lint is 1.7 seconds and does not go on the path to the first map,
        so for those 1.7 seconds this says so rather than saying "clean"."""
        self.query_one("#found", Static).update(Text("linting…", style="dim"))

    def show(self, found: list[Finding]) -> None:
        panel = self.query_one("#found", Static)
        if not found:
            panel.update(Text("clean", style="bold green"))
            return
        rank = {"error": 0, "warning": 1, "info": 2}
        out = Text()
        for d in sorted(found, key=lambda d: (rank[d.severity], d.line)):
            style = _SEVERITY_STYLE[d.severity]
            out.append(f"{d.severity:>7}  ", style=style)
            out.append(f"{d.code}\n", style="bold")
            out.append(f"         {d.message}\n", style="none")
            out.append(f"         {d.location}\n\n", style="dim")
        panel.update(out)


class Centre(Vertical):
    """The grid, and the two lines under it."""

    DEFAULT_CSS = """
    Centre { width: 1fr; }
    Centre MapGrid { height: 1fr; }
    """

    def compose(self) -> ComposeResult:
        yield MapGrid(id="grid")
        yield Where(id="where")
        yield Legend()
