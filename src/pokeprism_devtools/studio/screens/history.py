"""Everything you have written this session, and whether you can take it back.

One action at a time is the studio's whole design — there is no Save key, because
applying *is* saving — and the cost of that is that a session leaves a trail you
cannot see. This is the trail: what was done, which files it touched, which lines
of them, and, for the ones that can no longer be undone, why.

**Why** is the part worth the window. An undo can be refused for two quite
different reasons, and "greyed out" tells you neither:

* a **later change wrote the same file**, so putting this one's text back would
  wipe that one out. The fix is to undo the later one first, and the row says
  which file and which change.
* the **file has changed since we wrote it** — somebody edited it, in an editor
  or another tool — and restoring our idea of "before" would throw their work
  away. That is not a failure to be worked around; it is the guard working.

Undo is all-or-nothing per change. If one file of a paired warp has moved, the
other is left alone too: half a paired warp is worse than either warp.
"""

from __future__ import annotations

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Static

from ..session import Mutation


class History(ModalScreen["int | None"]):
    """The session's mutations. Dismisses with the one to undo, if you pick one."""

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("u", "undo", "Undo this one"),
    ]

    CSS = """
    History { align: center middle; }
    #history-box { width: 90%; height: 85%; border: round $accent;
                   background: $surface; }
    #history-title { padding: 0 1; background: $accent; color: $text; }
    #history-table { height: 1fr; }
    #history-why { height: auto; max-height: 6; padding: 0 1; color: $warning; }
    """

    def __init__(self, mutations: list[Mutation]) -> None:
        super().__init__()
        #: Newest first: the thing you are most likely to want to undo is the
        #: thing you just did, and it should not be at the bottom of a scroll.
        self._rows = list(reversed(mutations))

    def compose(self) -> ComposeResult:
        with Vertical(id="history-box"):
            yield Static(" What you have changed this session", id="history-title")
            yield DataTable(id="history-table", cursor_type="row",
                            zebra_stripes=True)
            yield Static(id="history-why")

    def on_mount(self) -> None:
        table = self.query_one("#history-table", DataTable)
        table.add_columns("", "change", "files", "lines")
        for m in self._rows:
            first, *rest = m.files or [("—", "")]
            table.add_row(
                Text("↶" if m.undoable else "·",
                     style="bold green" if m.undoable else "dim"),
                Text(m.summary, style="" if m.undoable else "dim"),
                _stack(f[0] for f in [first, *rest]),
                _stack(f[1] for f in [first, *rest]),
                height=len(m.files) or 1,
            )
        if not self._rows:
            self.query_one("#history-why", Static).update(
                Text("nothing written yet", style="dim"))
        table.focus()
        self._explain()

    # -- the reason under the table -------------------------------------------- #
    @on(DataTable.RowHighlighted, "#history-table")
    def _moved(self) -> None:
        self._explain()

    def _selected(self) -> Mutation | None:
        row = self.query_one("#history-table", DataTable).cursor_row
        return self._rows[row] if 0 <= row < len(self._rows) else None

    def _explain(self) -> None:
        m = self._selected()
        panel = self.query_one("#history-why", Static)
        if m is None:
            panel.update("")
            return
        out = Text()
        if m.blocked:
            out.append("can't undo: ", style="bold")
            out.append(m.blocked + "\n")
        else:
            out.append("u to undo this change\n", style="dim")
        for note in m.notes:
            out.append(note + "\n", style="dim")
        panel.update(out)

    # -- leaving --------------------------------------------------------------- #
    @on(DataTable.RowSelected, "#history-table")
    def _chose(self) -> None:
        self.action_undo()

    def action_undo(self) -> None:
        m = self._selected()
        if m is None or not m.undoable:
            self.app.bell()
            return
        self.dismiss(m.index)

    def action_close(self) -> None:
        self.dismiss(None)


def _stack(values) -> Text:
    """One cell, several lines — a change that wrote four files is one change."""
    return Text("\n".join(values))
