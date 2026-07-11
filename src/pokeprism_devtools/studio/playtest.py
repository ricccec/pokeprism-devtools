"""The screen you watch while the map you just made becomes a game you can walk in.

`make` takes minutes and can fail, and when it fails the reason is in its output
— usually naming your map, because your map is what changed. So this screen shows
that output as it arrives rather than a spinner that cannot tell you anything. If
the build fails you are left looking at the error, with the log still on screen.

If it succeeds, the save is patched to stand you on the tile the cursor was on,
and SameBoy comes up. That is the whole loop closed: a `.blk` drawn in
polished-map, added to the game, wired, populated, and now walked through, from
the same screen, without a shell.

The build runs in a thread — a Textual app that blocks its event loop for four
minutes is an app that has hung, and it looks exactly like one too.
"""

from __future__ import annotations

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, RichLog, Static

from .session import Session, SessionError


class Playtest(ModalScreen[None]):
    """Build, patch, launch. Dismisses when you close it, not when it finishes."""

    BINDINGS = [Binding("escape", "close", "Close")]

    CSS = """
    Playtest { align: center middle; }
    #playtest { width: 90%; height: 80%; border: round $accent;
                background: $surface; }
    #playtest-title { padding: 0 1; background: $accent; color: $text; }
    #playtest-log { height: 1fr; margin: 0 1; background: $surface;
                    border: solid $panel; }
    #playtest-status { padding: 0 1; height: auto; }
    #playtest-buttons { height: auto; padding: 1; align-horizontal: right; }
    """

    def __init__(self, session: Session, const: str, label: str,
                 cursor: tuple[int, int]) -> None:
        super().__init__()
        self._session = session
        self._const = const
        self._label = label
        self._cursor = cursor

    def compose(self) -> ComposeResult:
        y, x = self._cursor
        with Vertical(id="playtest"):
            yield Label(f" Playtest {self._label} at ({y}, {x})", id="playtest-title")
            yield RichLog(id="playtest-log", wrap=False, markup=False, auto_scroll=True)
            yield Static("Building…", id="playtest-status")
            with Vertical(id="playtest-buttons"):
                yield Button("Close", id="close")

    def on_mount(self) -> None:
        self._run()

    # -- the work -------------------------------------------------------------- #
    @work(thread=True, exclusive=True)
    def _run(self) -> None:
        """Off the event loop: `make` owns this thread for as long as it takes."""
        log = self.query_one("#playtest-log", RichLog)
        status = self.query_one("#playtest-status", Static)

        def line(text: str) -> None:
            self.app.call_from_thread(log.write, text)

        def say(text: str) -> None:
            self.app.call_from_thread(status.update, text)

        try:
            built = self._session.build(line)
        except OSError as e:
            say(f"[b]could not run make:[/b] {e}")
            return

        if not built:
            # The output is already on screen, and it is the answer. Don't bury
            # it under a summary that says less than the last line it printed.
            say("[b]the build failed[/b] — the reason is above")
            return

        say("Built. Patching the save…")
        y, x = self._cursor
        try:
            changes = self._session.boot(self._const, y, x)
        except SessionError as e:
            say(f"[b]{e}[/b]")
            return

        for c in changes:
            line(c)
        say(f"Launched. You are standing on {self._label} at ({y}, {x}).")

    # -- getting out of the way ------------------------------------------------ #
    @on(Button.Pressed, "#close")
    def _close(self) -> None:
        self.action_close()

    def action_close(self) -> None:
        # The emulator is the session's, not this screen's — closing the log does
        # not close the game you are playing.
        self.dismiss(None)
