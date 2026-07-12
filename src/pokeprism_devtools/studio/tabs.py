"""The tables under the grid, and the one thing they are for: being *selected*.

This is the inversion the studio was rebuilt around. The tables used to be a
read-out — you could look at a warp and then, to do anything about it, press `a`,
pick "Remove an object" from a list of nine, and type the label of the thing you
were already looking at. Now the selection *is* the verb's object: `e` edits what
is highlighted, `d` deletes it, and the footer only offers the keys that mean
something for the row you are on.

The widget knows none of that. It is handed a list of :class:`~.panels.Tab`, it
draws them, and it announces what is highlighted as an opaque :class:`~.panels.
Ref` — which it hands back to the session without ever looking inside. That is
the seam holding: `tabs.py` cannot tell a `person_event` from a `signpost`, and
does not need to, because the thing that can is on the other side of the message.

Two rows are special and neither is a special case in the code:

* the dim **"Add new…"** row at the foot of every tab you can add to is a row
  like any other, carrying `Ref("add")`. Pressing enter on it is the same code
  path as pressing enter on an NPC, and the session decides what that means.
* a row with **no Ref at all** — a wild encounter, a roof colour — is what makes
  `e` and `d` vanish from the footer, because a key you cannot use should not be
  advertised.

**The panes are mounted once and never again.** Every tab this app can show
exists from startup; loading a map refills the tables and hides the tabs that map
hasn't got. The obvious alternative — throw the panes away and mount the new
ones — measured at nearly two seconds per map, on a widget you move through by
holding down an arrow key. Mounting is the expensive part of a Textual widget and
a map does not change the *shape* of the tab strip, only its contents.
"""

from __future__ import annotations

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import DataTable, Static, TabbedContent, TabPane

from .panels import Ref, Tab

#: The Ref an "Add new…" row carries. `key` is the word the tab declared in
#: `Tab.adds` — "NPC", "warp" — which the session turns into an action.
ADD = "add"

#: Every tab the studio can show, in the order it shows them. A map gets the ones
#: it has; the rest are hidden. "Unreadable" is the one a map with a broken event
#: header gets *instead of* its objects — it still has a shape, and hiding a
#: broken map from the person looking for the break is the worst thing this could
#: do, so it comes up with the parse error where its NPCs would have been.
ALL = ("Attributes", "NPCs", "Trainers", "Pickups", "Warps", "Signposts",
       "Triggers", "Connections", "Unreadable", "Roof", "Wild")


class Tabs(Vertical):
    """Every tab of one map, and the row you are standing on."""

    DEFAULT_CSS = """
    Tabs { height: 100%; }
    Tabs .tab-note { height: auto; padding: 0 1; color: $text-disabled; }
    Tabs DataTable { height: 1fr; }
    """

    class Selected(Message):
        """The highlighted row changed — possibly to nothing at all."""

        def __init__(self, ref: Ref | None) -> None:
            super().__init__()
            self.ref = ref

    class Chosen(Message):
        """Enter, on a row worth acting on."""

        def __init__(self, ref: Ref) -> None:
            super().__init__()
            self.ref = ref

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        #: Per tab, the Ref of each row by its position in the table. A parallel
        #: list rather than a DataTable row key: the table is refilled wholesale
        #: on every load, and keys would only be a second thing to keep in step.
        self._refs: dict[str, list[Ref | None]] = {}

    def compose(self) -> ComposeResult:
        with TabbedContent(id="tabs"):
            for name in ALL:
                with TabPane(name, id=_pane(name)):
                    yield Static("", id=f"note-{_slug(name)}", classes="tab-note")
                    yield DataTable(id=f"table-{_slug(name)}", cursor_type="row",
                                    zebra_stripes=True)

    # -- filling it in --------------------------------------------------------- #
    def show(self, tabs: list[Tab]) -> None:
        """Draw a map's tabs. Synchronous, because nothing is mounted.

        The tab you were looking at survives if the new map has it. Arrowing down
        the map list while watching Warps should not throw you back to Attributes
        on every map that happens to have none.
        """
        panes = self.query_one(TabbedContent)
        was = panes.active
        have = {t.name: t for t in tabs}

        for name in ALL:
            tab = have.get(name)
            if tab is None:
                panes.hide_tab(_pane(name))
                self._refs[name] = []
                continue
            panes.show_tab(_pane(name))
            self._fill(tab)

        # The tab you were on may not exist on this map. Fall back to the first
        # one that does — never to nothing, which would leave the pane blank and
        # the footer offering keys for a row that isn't there.
        if was not in {_pane(t.name) for t in tabs}:
            panes.active = _pane(tabs[0].name) if tabs else ""
        self._announce()

    def _fill(self, tab: Tab) -> None:
        cols, rows = tab.table
        table = self.query_one(f"#table-{_slug(tab.name)}", DataTable)
        table.clear(columns=True)
        table.add_columns(*cols)

        refs: list[Ref | None] = []
        for row in rows:
            table.add_row(*row.cells)
            refs.append(row.ref)

        if tab.adds:
            # A row, not a button: the end of the list is where your hand already
            # is once you have looked down it and not found the thing you wanted.
            table.add_row(Text(f"▸  Add new {tab.adds}…", style="italic dim"),
                          *[""] * (len(cols) - 1))
            refs.append(Ref(ADD, key=tab.adds))

        self._refs[tab.name] = refs
        self.query_one(f"#note-{_slug(tab.name)}", Static).update(tab.note)
        self.query_one(f"#note-{_slug(tab.name)}", Static).display = bool(tab.note)

    # -- what is selected ------------------------------------------------------- #
    @property
    def ref(self) -> Ref | None:
        """The Ref of the highlighted row, or None if there isn't one."""
        panes = self.query_one(TabbedContent)
        pane = panes.active_pane
        if pane is None:
            return None
        name = _name(pane.id or "")
        refs = self._refs.get(name, [])
        row = pane.query_one(DataTable).cursor_row
        return refs[row] if 0 <= row < len(refs) else None

    @on(DataTable.RowHighlighted)
    @on(TabbedContent.TabActivated)
    def _moved(self) -> None:
        self._announce()

    def _announce(self) -> None:
        self.post_message(self.Selected(self.ref))

    @on(DataTable.RowSelected)
    def _chose(self, event: DataTable.RowSelected) -> None:
        # Enter on a row. The DataTable takes the key before the app's bindings
        # see it, so `enter` arrives here and `e` arrives there — and both have to
        # end in the same place, because they are the same gesture.
        event.stop()
        if (ref := self.ref) is not None:
            self.post_message(self.Chosen(ref))


def _pane(name: str) -> str:
    return f"pane-{_slug(name)}"


def _name(pane_id: str) -> str:
    return next((n for n in ALL if _pane(n) == pane_id), "")


def _slug(name: str) -> str:
    return name.lower().replace(" ", "-")
