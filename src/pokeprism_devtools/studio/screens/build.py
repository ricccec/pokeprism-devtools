"""The screen you watch while the map you just made becomes a game you can walk in.

It asks three questions first, and each of them was a wrong answer given silently
before it was a question.

**Which ROM.** `make` with no target is `all` — both ROMs, the GBS and the images
— and then the thing that goes looking for "the ROM" finds two of them and takes
whichever it prefers, which was not the one you were thinking of. Now the target is
named on the way in and named again on the way out, so the game you boot is the
game you built. The targets themselves come from the play adapter
(`session.build_targets`), because which builds exist is the engine's to say.

The box starts on the target this tree built with last time, kept in the tree
itself (`studio/prefs.py`). You build the same ROM every session — the debug one,
because the debug one is the one you can inspect — and the adapter's list is
ordered by what the `Makefile` declares, not by what you want, so the first entry
was a value to be corrected on every single build. It is written only after a
build succeeds: a prefilled field is read as an answer rather than a question, so
only an answer that has been tried belongs in it.

**How many jobs.** `make` is serial unless told otherwise, and this build is a few
hundred files. Nothing about that was a choice anybody made; it was just what
happens when you don't pass `-j`.

**Where you come out.** Prefilled from the grid cursor, because you have already
moved to the spot you want to look at — but a spawn tile is worth being able to
correct without going back to the map, and a `.blk` you have only just drawn has
tiles you cannot stand on.

**Quiet.** On by default, and the reason the build stopped feeling unusually long:
a `prism` build is a few thousand lines of compiler chatter, and putting every one
of them into the log — a widget write across a thread boundary, per line — is
itself minutes the compiler never asked for. Quiet keeps only the lines that carry
the answer (`session.keeps_build_line` — the errors, and the `make: ***` after
them), the same thing you would reach for a `grep` to do by hand, with a counter ticking
so a silent log does not read as a hung one. Uncheck it to watch the whole build.

Then `make` takes minutes and can fail, and when it fails the reason is in its
output — usually naming your map, because your map is what changed. So this shows
that output as it arrives rather than a spinner that cannot tell you anything. If
the build fails you are left looking at the error, with the log still on screen.

If it succeeds, the save is patched to stand you on the tile you named, and SameBoy
comes up. That is the whole loop closed: a `.blk` drawn in polished-map, added to
the game, wired, populated, and now walked through, from the same screen, without a
shell.

The build runs in a thread — a Textual app that blocks its event loop for four
minutes is an app that has hung, and it looks exactly like one too.
"""

from __future__ import annotations

import os
import time

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, RichLog, Static

from ..combo import Combo
from ..session import Session, SessionError

#: How often the log's line counter is allowed to touch the screen while a quiet
#: build streams past it. The whole point of quiet is *not* writing to the widget
#: on every line, so the heartbeat that proves the build is alive is throttled to
#: the same end — often enough to see it moving, rare enough to cost nothing.
_HEARTBEAT = 0.25


class Build(ModalScreen[None]):
    """Choose, build, patch, launch. Dismisses when you close it, not when it
    finishes — the emulator is the session's, and closing the log does not close
    the game you are playing."""

    BINDINGS = [Binding("escape", "close", "Close")]

    CSS = """
    /* The target combo's dropdown lives on its own layer, over everything else —
       see `studio/combo.py`, which mounts it on the screen for exactly that. */
    Build { align: center middle; layers: base dropdown; }
    #build { width: 90%; height: 80%; border: round $accent;
                background: $surface; }
    #build-title { padding: 0 1; background: $accent; color: $text; }
    #build-config { height: 3; padding: 0 1; }
    #build-config Label { padding: 1 1 0 1; color: $text-muted; }
    #build-config Input { width: 14; }
    #build-config .narrow { width: 8; }
    #build-log { height: 1fr; margin: 0 1; background: $surface;
                    border: solid $panel; }
    #build-status { padding: 0 1; height: auto; }
    #build-buttons { height: auto; padding: 1; align-horizontal: right; }
    """

    def __init__(self, session: Session, const: str, label: str,
                 cursor: tuple[int, int]) -> None:
        super().__init__()
        self._session = session
        self._const = const
        self._label = label
        self._cursor = cursor
        #: Once, and then never again while this screen is up. `make` is minutes and
        #: a second one started underneath the first would be two compilers writing
        #: the same object files.
        self._started = False

    def compose(self) -> ComposeResult:
        y, x = self._cursor
        with Vertical(id="build"):
            yield Label(f" Build, and stand on {self._label}", id="build-title")
            with Horizontal(id="build-config"):
                yield Label("Target")
                targets = self._session.build_targets()
                # Last time's answer if there is one, and the adapter's default
                # if there is not. The list is unchanged either way: it says what
                # this tree can build, which is not the same question.
                yield Combo(list(targets),
                            value=self._session.recall_build_target() or targets[0],
                            id="build-target")
                yield Label("Jobs")
                yield Input(value=str(os.cpu_count() or 1), id="build-jobs",
                            classes="narrow")
                yield Label("Y")
                yield Input(value=str(y), id="build-y", classes="narrow")
                yield Label("X")
                yield Input(value=str(x), id="build-x", classes="narrow")
                yield Checkbox("Quiet", value=True, id="build-quiet")
            yield RichLog(id="build-log", wrap=False, markup=False, auto_scroll=True)
            yield Static("", id="build-status")
            # TODO(build-only): offer a "build without running" path here — a
            # checkbox, or a second button beside "Build & run". Sometimes you
            # just want to know the map compiles and links, without patching a
            # save or opening SameBoy. `_run` would skip the boot step (stop
            # after "Built.") when it is set. Keep the default as build & run.
            with Horizontal(id="build-buttons"):
                yield Button("Cancel", id="close")
                yield Button("Build & run", variant="primary", id="go")

    def on_mount(self) -> None:
        self.query_one("#go", Button).focus()

    # -- what was asked for ------------------------------------------------------ #
    def _field(self, name: str) -> str:
        return self.query_one(f"#build-{name}", Input).value.strip()

    def _number(self, name: str) -> int:
        raw = self._field(name)
        try:
            return int(raw, 0)
        except ValueError:
            raise SessionError(f"{name} must be a number, not {raw!r}") from None

    # -- the work ---------------------------------------------------------------- #
    @on(Button.Pressed, "#go")
    def _go(self) -> None:
        if self._started:
            return
        status = self.query_one("#build-status", Static)
        try:
            target = self._field("target")
            jobs, y, x = self._number("jobs"), self._number("y"), self._number("x")
        except SessionError as e:
            status.update(f"[b]{e}[/b]")
            return

        quiet = self.query_one("#build-quiet", Checkbox).value
        self._started = True
        for widget in self.query("#build-config Input, #build-quiet"):
            widget.disabled = True
        self.query_one("#go", Button).disabled = True
        self._run(target, jobs, (y, x), quiet)

    @work(thread=True, exclusive=True)
    def _run(self, target: str, jobs: int, spawn: tuple[int, int], quiet: bool) -> None:
        """Off the event loop: `make` owns this thread for as long as it takes."""
        log = self.query_one("#build-log", RichLog)
        status = self.query_one("#build-status", Static)
        seen = [0]          # a box, so `line` can count across its own calls
        beat = [0.0]

        def line(text: str) -> None:
            seen[0] += 1
            if not quiet or self._session.keeps_build_line(text):
                self.app.call_from_thread(log.write, text)
            if not quiet:
                return
            # The heartbeat: a quiet build writes almost nothing, so without this
            # the log sits still for minutes and looks hung. The counter proves it
            # is not — throttled, because updating it every line would be the very
            # per-line widget write quiet exists to avoid.
            now = time.monotonic()
            if now - beat[0] >= _HEARTBEAT:
                beat[0] = now
                self.app.call_from_thread(
                    status.update, f"Building {target}… ({seen[0]} lines, quiet)")

        def say(text: str) -> None:
            self.app.call_from_thread(status.update, text)

        say(f"Building {target} with {jobs} job(s)…")
        try:
            built = self._session.build(line, target=target, jobs=jobs)
        except (OSError, SessionError) as e:
            say(f"[b]could not run make:[/b] {e}")
            return

        if not built:
            # The output is already on screen, and it is the answer. Don't bury
            # it under a summary that says less than the last line it printed.
            say("[b]the build failed[/b] — the reason is above")
            return

        # It built, so it is worth starting from next time. A tree that will not
        # take the file is said out loud and then carried on from — the build
        # worked, and a screen that reported a failed preference as a failed build
        # would be lying about the thing you were waiting four minutes for. Into
        # the log directly, not through `line`: a quiet build keeps only what the
        # play adapter calls a problem, and this line is ours rather than make's.
        try:
            self._session.remember_build_target(target)
        except SessionError as e:
            self.app.call_from_thread(log.write, str(e))

        say("Built. Patching the save…")
        y, x = spawn
        try:
            changes = self._session.boot(self._const, y, x, target=target)
        except SessionError as e:
            say(f"[b]{e}[/b]")
            return

        for c in changes:
            line(c)
        say(f"Launched. You are standing on {self._label} at ({y}, {x}).")

    # -- getting out of the way -------------------------------------------------- #
    @on(Button.Pressed, "#close")
    def _close(self) -> None:
        self.action_close()

    def action_close(self) -> None:
        self.dismiss(None)
