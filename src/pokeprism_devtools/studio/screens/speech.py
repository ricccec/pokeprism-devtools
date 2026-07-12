"""A dialogue box that tells you what each line costs, on the line.

(Named `speech`, not `dialogue`: `shared/dialogue.py` is the parser, and the seam
test that keeps the view from importing a parser matches on the module name.)

The old form printed the speech twice: once in the box you were typing into, and
once again underneath with a tile count beside each line. Two copies of the same
words, and you had to count rows to match them up. The second copy earned its
place only if it *said something the first one couldn't* — so either it goes, or
it says something.

It goes. The count moves onto the line it is about, as a right-hand gutter, which
is where you were already looking. `render_line` is called once per *visible*
line with the widget's own scroll already applied, so a gutter built there stays
aligned with the text by construction — there is no second scroll position to
keep in step, which is the bug this design exists to not have.

What the gutter says is the thing you cannot see by looking:

* **the tiles**, not the characters. `#` is four tiles, `<PLAYER>` is up to seven,
  and the speech box is eighteen columns of *tiles*. A line that looks short can
  overflow and a line that looks long can fit.
* **the worst case**. A line that fits as written and not once the player is
  called BARTHOLOMEW is a line that overflows in somebody else's game and not in
  yours, which is the hardest kind of bug to be told about. It is yellow, and it
  says so.
* **where a new textbox starts.** A blank line is a page break — the engine opens
  a fresh box — and nothing about a blank line says that. Now it does.
"""

from __future__ import annotations

from rich.segment import Segment
from rich.style import Style
from textual.strip import Strip
from textual.widgets import TextArea

from ..session import TextPreview

#: Columns reserved on the right. Enough for "16/18  3 over at worst".
GUTTER = 24

_DIM = Style(color="grey50")
_OVER = Style(color="red", bold=True)
_RISKY = Style(color="yellow")
_BREAK = Style(color="grey37", italic=True)


class Dialogue(TextArea):
    """A `kind="lines"` field: the words, and what they cost in tiles."""

    def __init__(self, text: str = "", **kwargs) -> None:
        super().__init__(text, soft_wrap=False, **kwargs)
        self.tab_behavior = "focus"          # or you can never leave the box
        self._measured: TextPreview | None = None

    def measured(self, preview: TextPreview) -> None:
        """The form has re-measured what is in here. Redraw the gutter."""
        self._measured = preview
        self.refresh()

    def render_line(self, y: int) -> Strip:
        strip = super().render_line(y)
        if self._measured is None or not self.size.width:
            return strip

        # `y` is relative to the widget, so the document line is `y` plus however
        # far the box has been scrolled. Soft wrap is off, so one document line is
        # one rendered line and this stays a straight offset.
        line = y + self.scroll_offset.y
        if not 0 <= line < len(self._measured.lines):
            return strip

        note = self._note(line)
        if note is None:
            return strip

        body = strip.adjust_cell_length(max(0, self.size.width - GUTTER))
        return Strip([*body, *note]).adjust_cell_length(self.size.width)

    def _note(self, line: int) -> list[Segment] | None:
        assert self._measured is not None
        m = self._measured.lines[line]
        cols = self._measured.cols

        if not m.text.strip():
            # A blank line is a page break: the engine closes this box and opens
            # a fresh one. Nothing about an empty line says that, so say it.
            return [Segment("  ┈ new box", _BREAK)]

        if m.unknown:
            return [Segment(f"  not in charmap: {' '.join(m.unknown)}", _OVER)]

        count = f"  {m.tiles:>2}/{cols}"
        if m.over:
            return [Segment(count, _OVER), Segment(f"  {m.over} over", _OVER)]
        if m.over_at_worst:
            return [Segment(count, _RISKY),
                    Segment(f"  {m.over_at_worst} over at worst", _RISKY)]
        if m.unbounded:
            return [Segment(count, _RISKY),
                    Segment(f"  unbounded: {' '.join(m.unbounded)}", _RISKY)]
        return [Segment(count, _DIM)]
