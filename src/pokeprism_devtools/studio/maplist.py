"""The map list, and the box you filter it with.

Four hundred and fifty maps is too many to scroll, so the filter is the way in and
it matches the label *or* the const — you remember a map as `Route30` or as
`ROUTE_30` depending on which file you last had open, and being made to remember
which is a tax on nothing.

Split out of `app.py`, which had grown past the size where one file is still one
idea. Reads no files: it is handed labels.
"""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Input, OptionList

from .model import MapRef


class MapList(Vertical):
    """Every map, filtered, with one of them highlighted."""

    DEFAULT_CSS = """
    MapList { width: 30; border-right: solid $panel; }
    MapList Input { border: none; height: 3; }
    MapList OptionList { height: 1fr; border: none; }
    """

    class Chosen(Message):
        """A map is highlighted, and should now be on screen. Highlighting *is*
        choosing here — there is no second key to press, because the whole point of
        the list is to walk down it and watch the maps go by."""

        def __init__(self, label: str) -> None:
            super().__init__()
            self.label = label

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._maps: list[MapRef] = []
        self._shown: list[str] = []

    def compose(self) -> ComposeResult:
        yield Input(placeholder="filter maps", id="filter")
        yield OptionList(id="maps")

    @property
    def needle(self) -> str:
        return self.query_one("#filter", Input).value

    def fill(self, maps: list[MapRef], select: str | None = None) -> None:
        """Redraw the list. `select` is what to highlight, if it survived.

        Called on every write, because a write can change what maps exist: adding
        one puts it in the list, and undoing that takes it back out — and the map
        you were looking at can be the one that has just stopped existing.
        """
        self._maps = maps
        self._refilter(self.needle, select)

    def go_to(self, label: str) -> None:
        """Jump to a map from somewhere else — the findings window does this.

        The filter is cleared first: a map you were *sent* to is one you probably
        could not have found under whatever you had typed, and a jump that lands on
        an empty list looks like a jump that did nothing.
        """
        if label in [m.label for m in self._maps]:
            self.query_one("#filter", Input).value = ""
            self._refilter("", label)

    def _refilter(self, needle: str, select: str | None) -> None:
        needle = needle.strip().lower()
        self._shown = [m.label for m in self._maps
                       if needle in m.label.lower() or needle in m.const.lower()]
        options = self.query_one("#maps", OptionList)
        options.clear_options()
        options.add_options(self._shown)
        if self._shown:
            # Set once, to what we actually want. Highlighting the first map and
            # then correcting it would load two maps and show you the wrong one on
            # the way, because highlighting is what loads a map.
            options.highlighted = (self._shown.index(select)
                                   if select in self._shown else 0)

    @on(Input.Changed, "#filter")
    def _typed(self, event: Input.Changed) -> None:
        self._refilter(event.value, None)

    @on(Input.Submitted, "#filter")
    def _entered(self) -> None:
        self.query_one("#maps", OptionList).focus()

    @on(OptionList.OptionHighlighted, "#maps")
    def _highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option_index < len(self._shown):
            self.post_message(self.Chosen(self._shown[event.option_index]))

    def focus_filter(self) -> None:
        self.query_one("#filter", Input).focus()

    def focus_list(self) -> None:
        self.query_one("#maps", OptionList).focus()
