"""Every finding in the repo, in one place — not just the map you are looking at.

The panel beside the grid shows what is wrong with *this* map, which is what you
want ninety percent of the time and exactly the wrong thing the other ten: a
cross-file linter exists precisely because the change you made here breaks
something over there, and a panel that only ever shows "here" can never tell you
so. This window is "there".

It filters over everything on the row — the map, the rule, the message — because
the two questions you actually arrive with are "what is still broken" and "who
else has this problem", and one filter box answers both. Enter on a finding takes
you to the map it is about.
"""

from __future__ import annotations

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Input, Static

from ..model import Finding

_SEVERITY_STYLE = {"error": "bold red", "warning": "yellow", "info": "dim cyan"}


class Findings(ModalScreen["str | None"]):
    """The whole repo's diagnostics. Dismisses with a map label to jump to."""

    BINDINGS = [Binding("escape", "close", "Close")]

    CSS = """
    Findings { align: center middle; }
    #findings-box { width: 90%; height: 85%; border: round $accent;
                    background: $surface; }
    #findings-title { padding: 0 1; background: $accent; color: $text; }
    #findings-filter { border: none; height: 3; background: $surface; }
    #findings-table { height: 1fr; }
    #findings-count { height: 1; padding: 0 1; color: $text-muted; }
    """

    def __init__(self, found: list[Finding]) -> None:
        super().__init__()
        self._all = found
        self._shown: list[Finding] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="findings-box"):
            yield Static(" Findings", id="findings-title")
            yield Input(placeholder="filter — a map, a rule, a word in the message",
                        id="findings-filter")
            yield DataTable(id="findings-table", cursor_type="row",
                            zebra_stripes=True)
            yield Static(id="findings-count")

    def on_mount(self) -> None:
        table = self.query_one("#findings-table", DataTable)
        table.add_columns("", "map", "rule", "message", "where")
        self._fill("")
        self.query_one("#findings-filter", Input).focus()

    def _fill(self, needle: str) -> None:
        needle = needle.strip().lower()
        table = self.query_one("#findings-table", DataTable)
        table.clear()

        self._shown = [f for f in self._all if needle in f.haystack]
        for f in self._shown:
            table.add_row(
                Text(f.severity, style=_SEVERITY_STYLE.get(f.severity, "")),
                f.map_label or "—", f.code, f.message, f.location)

        clean = "nothing to report" if not self._all else ""
        self.query_one("#findings-count", Static).update(
            clean or f"{len(self._shown)} of {len(self._all)}   —   "
                     f"enter to open the map it is about")

    @on(Input.Changed, "#findings-filter")
    def _filtered(self, event: Input.Changed) -> None:
        self._fill(event.value)

    @on(Input.Submitted, "#findings-filter")
    def _to_the_table(self) -> None:
        self.query_one("#findings-table", DataTable).focus()

    @on(DataTable.RowSelected, "#findings-table")
    def _chose(self, event: DataTable.RowSelected) -> None:
        row = event.cursor_row
        if 0 <= row < len(self._shown) and self._shown[row].map_label:
            self.dismiss(self._shown[row].map_label)

    def action_close(self) -> None:
        self.dismiss(None)
