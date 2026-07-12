"""The map, on screen, with a cursor you can move.

Every colour here comes from :func:`..shared.swatches.tile_color` and every
letter from :func:`..shared.coords.glyph_cells` — the same two functions
`prism-map --grid` draws with. That is deliberate: a second implementation that
agreed with the first today would disagree with it by P4, and the whole point of
the grid is that it can be trusted about *where things are*.

The cursor is the reason the grid exists at all. A form asking for a bare `y` and
`x` — with three competing definitions of "tile" in play and a `+4` the assembler
adds behind your back — is a trap. A cursor you can see, on a tile you can see,
that hands its coordinates to the form, is not.
"""

from __future__ import annotations

from rich.segment import Segment
from rich.style import Style
from textual.binding import Binding
from textual.geometry import Region, Size
from textual.message import Message
from textual.reactive import reactive
from textual.scroll_view import ScrollView
from textual.strip import Strip

# The pure renderer: given block ids and resolved colours, which cell gets which
# colour and which letter. It opens nothing — the geometry it draws was read by
# `Session.load` and handed over as plain data.
from ..shared import coords, swatches
from .session import MapGeometry

#: The foreground paints the top half of the cell, the background the bottom —
#: so one cell holds two stacked pixels and the grid's vertical resolution is
#: half-rows. That is what lets a tile be `zoom` cells wide and `zoom` half-rows
#: tall, i.e. square, on a terminal whose cells are twice as tall as they're wide.
_HALF = "▀"

ZOOMS = (1, 2, 3, 4)


def _cursor_tint(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    """The cursor, whatever it lands on.

    Halfway to white keeps the tile's own colour readable underneath — you can
    still tell you're standing on water, or on a warp — while being the brightest
    thing on screen. A cursor drawn as a *colour* rather than a character also
    survives zoom 1, where a tile is half a cell tall and there is nowhere to put
    a character at all.
    """
    return tuple((v + 255) // 2 for v in rgb)   # type: ignore[return-value]


class MapGrid(ScrollView):
    """A map as coloured half-blocks, with a cursor in coordinate tiles."""

    BINDINGS = [
        Binding("up,k", "move(-1, 0)", "Move", show=False),
        Binding("down,j", "move(1, 0)", "Move", show=False),
        Binding("left,h", "move(0, -1)", "Move", show=False),
        Binding("right,l", "move(0, 1)", "Move", show=False),
        Binding("plus,equals_sign", "zoom(1)", "Zoom in", show=False),
        Binding("minus,underscore", "zoom(-1)", "Zoom out", show=False),
    ]

    can_focus = True

    view: reactive[MapGeometry | None] = reactive(None, always_update=True)
    zoom: reactive[int] = reactive(2)
    cursor: reactive[tuple[int, int]] = reactive((0, 0))

    class Moved(Message):
        """The cursor is on a new coordinate tile."""

        def __init__(self, y: int, x: int, glyph: str | None) -> None:
            super().__init__()
            self.y = y
            self.x = x
            self.glyph = glyph

    class Hovered(Message):
        """The mouse is over a coordinate tile — or has left the map.

        Not the same thing as the cursor, and worth its own message. The linter
        talks in coordinates ("warp 2 is broken"; the only thing you know about
        warp 2 is that its row says 2, 17), and the fastest way to find out what
        is standing at 2, 17 is to put the mouse on 2, 17 and read it off. Doing
        that with the keyboard cursor would mean walking there, which moves the
        coordinates every form is about to be prefilled with.
        """

        def __init__(self, y: int, x: int, glyph: str | None,
                     inside: bool = True) -> None:
            super().__init__()
            self.y = y
            self.x = x
            self.glyph = glyph
            self.inside = inside

    def show(self, view: MapGeometry) -> None:
        self.view = view
        self.cursor = (0, 0)
        self.scroll_to(0, 0, animate=False)
        self._resize()
        self.post_message(self.Moved(0, 0, view.marks.get((0, 0))))

    # -- reacting -------------------------------------------------------------- #
    def watch_zoom(self) -> None:
        self._resize()
        self._keep_cursor_visible()
        self.refresh()

    def watch_cursor(self, cursor: tuple[int, int]) -> None:
        if self.view is None:
            return
        self._keep_cursor_visible()
        self.refresh()
        self.post_message(self.Moved(*cursor, self.view.marks.get(cursor)))

    def _resize(self) -> None:
        if self.view is None:
            self.virtual_size = Size(0, 0)
            return
        rows, cols = self.view.size
        self.virtual_size = Size(cols * self.zoom, rows * self.zoom // 2)

    def _keep_cursor_visible(self) -> None:
        """Scroll so the cursor's tile is on screen — all of it, not just its
        first cell, or moving down a long map would park the cursor on the last
        line and every step would scroll."""
        z = self.zoom
        ty, tx = self.cursor
        self.scroll_to_region(
            Region(tx * z, ty * z // 2, z, max(1, z // 2)),
            animate=False, force=True,
        )

    # -- actions --------------------------------------------------------------- #
    def action_move(self, dy: int, dx: int) -> None:
        if self.view is None:
            return
        rows, cols = self.view.size
        ty, tx = self.cursor
        # Clamped, not wrapped: walking off the east edge and reappearing in the
        # west would be a lie about a map that has a west edge.
        self.cursor = (min(max(ty + dy, 0), rows - 1), min(max(tx + dx, 0), cols - 1))

    def action_zoom(self, delta: int) -> None:
        i = ZOOMS.index(self.zoom) + delta
        if 0 <= i < len(ZOOMS):
            self.zoom = ZOOMS[i]

    # -- the mouse ------------------------------------------------------------- #
    def _tile_at(self, offset) -> tuple[int, int] | None:
        """The coordinate tile under a point in the widget, or None if past the
        edge of the map. Scroll has to be added back in: `offset` is where the
        pointer is on *screen*, and the map may have been scrolled under it."""
        if self.view is None:
            return None
        scroll_x, scroll_y = self.scroll_offset
        z = self.zoom
        # A cell is one tile wide and half a tile tall — see `_HALF` — so the
        # column divides by the zoom and the row divides by half of it.
        tx = (offset.x + scroll_x) // z
        ty = (2 * (offset.y + scroll_y)) // z
        rows, cols = self.view.size
        if not (0 <= ty < rows and 0 <= tx < cols):
            return None
        return ty, tx

    def on_mouse_move(self, event) -> None:
        at = self._tile_at(event.offset)
        if at is None:
            self.post_message(self.Hovered(0, 0, None, inside=False))
            return
        assert self.view is not None
        self.post_message(self.Hovered(*at, self.view.marks.get(at)))

    def on_leave(self) -> None:
        self.post_message(self.Hovered(0, 0, None, inside=False))

    def on_click(self, event) -> None:
        """Click to put the cursor there.

        The cursor is what fills a form's coordinates in, so this is the short
        way round: point at the tile you mean, click, and the next thing you add
        lands on it. Focus follows the click too, or the arrow keys would still
        be driving the map list.
        """
        at = self._tile_at(event.offset)
        if at is None:
            return
        self.focus()
        self.cursor = at

    # -- drawing ---------------------------------------------------------------- #
    def render_line(self, y: int) -> Strip:
        view, z = self.view, self.zoom
        if view is None:
            return Strip.blank(self.size.width)

        scroll_x, scroll_y = self.scroll_offset
        row = y + scroll_y                       # a half-row of the whole map
        rows, cols = view.size
        if row >= rows * z // 2:
            return Strip.blank(self.size.width)

        glyphs = coords.glyph_cells(view.marks, z)
        cy, cx = self.cursor
        # Where the cursor tile's own letter would go, by the very same rule — so
        # that a cursor sitting on an NPC tints the letter's cell too, instead of
        # ringing it with a bright border around an untinted middle.
        cursor_cell = next(iter(coords.glyph_cells({self.cursor: ""}, z)))

        def color(ty: int, tx: int) -> tuple[int, int, int]:
            rgb = swatches.tile_color(view.blocks, view.width, view.swatches,
                                      view.marks, ty, tx)
            return _cursor_tint(rgb) if (ty, tx) == (cy, cx) else rgb

        segments: list[Segment] = []
        for c in range(scroll_x, min(scroll_x + self.size.width, cols * z)):
            tx = c // z
            if (glyph := glyphs.get((row, c))) is not None:
                # A letter costs the whole cell — there is no half a character —
                # so it is drawn on its marker's own colour rather than on the
                # terrain, and the tile stays one solid, readable block.
                bg = coords.MARKER_BG[glyph]
                if (row, c) == cursor_cell:
                    bg = _cursor_tint(bg)
                segments.append(Segment(glyph, Style(
                    color=coords.hex_color(coords.MARKER_INK[glyph]),
                    bgcolor=coords.hex_color(bg),
                    bold=True)))
            else:
                segments.append(Segment(_HALF, Style(
                    color=coords.hex_color(color((2 * row) // z, tx)),
                    bgcolor=coords.hex_color(color((2 * row + 1) // z, tx)))))

        return Strip(segments).adjust_cell_length(self.size.width)
