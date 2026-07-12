"""The diff, the warnings, and a yes.

What is shown here is not a rendering of what *would* happen — it is the diff of
the very :class:`~..shared.edits.Edit` objects that will be written, against the
very text they were computed from. There is no second code path that could
disagree with it.

The **notes** above the diff matter as much as the diff, and are the reason this
screen exists rather than a yes/no toast. They are what the wiring layer decided
a person has to be told before agreeing: that deleting this trainer leaves his
party behind as an orphan, because deleting the party would renumber every party
below it and re-team every trainer citing them. That is not something to discover
afterwards from a linter, and it is not something a tool should decide for you.
So it is on the screen, in the wiring layer's own words, above the button.
"""

from __future__ import annotations

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from ..session import Preview

_DIFF_STYLE = {"+": "green", "-": "red", "@": "cyan"}


class Confirm(ModalScreen[bool]):
    """Everything one action would do, and a button."""

    BINDINGS = [
        Binding("escape", "no", "Cancel"),
        Binding("enter", "yes", "Apply"),
    ]

    CSS = """
    Confirm { align: center middle; }
    #confirm { width: 92; height: auto; max-height: 90%;
               border: round $success; background: $surface; }
    #confirm-title { padding: 0 1; background: $success; color: $text; }
    #confirm-notes { padding: 0 1; color: $warning; height: auto; }
    #confirm-diff { height: auto; max-height: 28; padding: 1; }
    #confirm-buttons { height: 3; align: right middle; padding: 0 1; }
    """

    def __init__(self, preview: Preview) -> None:
        super().__init__()
        self._preview = preview

    def compose(self) -> ComposeResult:
        p = self._preview
        with Vertical(id="confirm"):
            yield Static(f"{p.summary}  —  {', '.join(p.touches)}", id="confirm-title")
            yield Static(Text("\n".join(p.notes)), id="confirm-notes")
            yield VerticalScroll(Static(_diff(p.diff())), id="confirm-diff")
            with Horizontal(id="confirm-buttons"):
                yield Button("Cancel", id="no")
                yield Button("Apply", variant="success", id="yes")

    def on_mount(self) -> None:
        self.query_one("#yes", Button).focus()

    @on(Button.Pressed, "#yes")
    def action_yes(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#no")
    def action_no(self) -> None:
        self.dismiss(False)


def _diff(text: str) -> Text:
    out = Text()
    for line in text.split("\n"):
        style = ("bold" if line[:3] in ("+++", "---")
                 else _DIFF_STYLE.get(line[:1], "dim"))
        out.append(line + "\n", style=style)
    return out
