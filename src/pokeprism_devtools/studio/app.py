"""prism-studio — the shell.

You pick a map, you see its shape, you see what has been placed on it and what
the linter thinks of it. Then you point at one of those things and act on it: `e`
edits what is highlighted, `d` deletes it, and enter on the dim row at the foot of
a tab adds another. The keys on offer are a function of what you have selected —
there is no `e` on a wild encounter, because a wild encounter cannot be edited and
a key you cannot use should not be advertised.

**This file opens no files.** Everything it draws arrives from `Session` as plain
data — colours, marker positions, tables already reduced to rows — and everything
it changes goes out through an `Action` whose fields `screens/forms.py` renders
without knowing what they mean. A selected row hands back an opaque `Ref` that
this file never looks inside. That rule is what keeps `person_event`'s argument
order, and the `+4` its macro adds behind your back, on one side of one line.

Three things are worth knowing about how it behaves.

The linter is **not** on the path to the first map. A cold `LintContext` plus a
full run is 1.7 seconds, and blocking on it would mean staring at an empty screen
before you can look at anything. So the grid comes up immediately from source,
and the diagnostics arrive when they arrive, in a thread.

Maps that don't parse are still **in the list**. A map with a broken event header
has a perfectly good shape, and the one thing you must not do to somebody looking
for a bug is hide the map the bug is in. It gets its grid, and the parse error
where its objects would have been.

And the command palette is on **`p`**, not `ctrl+p`, because this is mostly run
inside VSCode's terminal and VSCode eats `ctrl+p`. Which is why `b` builds.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Footer, Header, Input, OptionList, Static

from ..shared import coords, paths
from .actions import Action, EditText
from .grid import MapGrid
from .newmap import NewMap
from .panels import Ref
from .screens import Build, Confirm, Findings, Form, History, Picker
from .session import MapData, Preview, Session, SessionError, TextRef
from .tabs import ADD, Tabs

_SEVERITY_STYLE = {"error": "bold red", "warning": "yellow", "info": "dim cyan"}

#: What `e` can do, given what is selected. Editing an object in place is P3; for
#: now `e` reaches the one thing that is already writable — the words it says.
_NO_EDIT_YET = ("trainer", "warp", "trigger", "connection", "pickup")


def _marker_style(glyph: str) -> str:
    return (f"bold {coords.hex_color(coords.MARKER_INK[glyph])} "
            f"on {coords.hex_color(coords.MARKER_BG[glyph])}")


class Studio(App):
    TITLE = "prism-studio"

    #: Textual puts its command palette on ctrl+p. VSCode's terminal takes that
    #: key before we ever see it, and this is mostly run inside VSCode.
    COMMAND_PALETTE_BINDING = "p"

    CSS = """
    #body { height: 1fr; }
    #sidebar { width: 30; border-right: solid $panel; }
    #filter { border: none; height: 3; }
    #maps { height: 1fr; border: none; }
    #centre { width: 1fr; }
    #grid { height: 1fr; }
    #status { height: 1; padding: 0 1; background: $panel; color: $text-muted; }
    #legend { height: 1; padding: 0 1; }
    #findings { width: 46; border-left: solid $panel; padding: 0 1; }
    #tabs-pane { height: 18; border-top: solid $panel; }
    """

    BINDINGS = [
        Binding("e", "edit", "Edit"),
        Binding("d", "delete", "Delete"),
        Binding("a", "add_map", "Add map"),
        Binding("b", "build", "Build & run"),
        Binding("t", "texts", "All text"),
        Binding("u", "undo", "Undo"),
        Binding("L", "findings", "Findings"),
        Binding("H", "history", "History"),
        Binding("slash", "focus_filter", "Filter", show=False),
        Binding("plus", "zoom(1)", "Zoom in", show=False),
        Binding("minus", "zoom(-1)", "Zoom out", show=False),
        Binding("q", "quit", "Quit", show=False),
    ]

    def __init__(self, root: Path) -> None:
        super().__init__()
        self.session = Session(root)
        self._maps = self.session.maps
        self._shown: list[str] = []
        #: The map the user last asked for. A slower load that lands after it has
        #: moved on is dropped — otherwise arrowing down the list leaves you
        #: looking at whichever map happened to finish last.
        self._wanted: str | None = None
        self._const: str | None = None
        #: Where to put the cursor back after a reload, and on which map. Re-reading
        #: the map is how a new NPC appears on the grid, but it would also send the
        #: cursor home — off the tile you were working on, the moment you worked on
        #: it. Keyed by label because a write can bring a *different* map with it.
        self._keep_cursor: tuple[str, tuple[int, int]] | None = None
        self._texts: list[TextRef] = []
        self._linted = False
        #: What is highlighted in the tabs. The footer is a function of this.
        self._ref: Ref | None = None

    # -- layout ---------------------------------------------------------------- #
    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            with Vertical(id="sidebar"):
                yield Input(placeholder="filter maps", id="filter")
                yield OptionList(id="maps")
            with Vertical(id="centre"):
                yield MapGrid(id="grid")
                yield Static(id="status")
                yield Static(self._legend(), id="legend")
            yield VerticalScroll(Static(id="diagnostics"), id="findings")
        yield Tabs(id="tabs-pane")
        yield Footer()

    def on_mount(self) -> None:
        self._fill_list("")
        self.query_one("#diagnostics", Static).update(Text("linting…", style="dim"))
        self._lint()
        self._warm()
        self.query_one("#maps", OptionList).focus()

    @work(thread=True, group="warm")
    def _warm(self) -> None:
        """Read the constants a form autocompletes from, before a form asks.

        Every sprite, movement, item, trainer class, tileset, landmark and piece
        of music in the repo — two seconds of parsing, cached on the session for
        the rest of the run. Left to happen lazily it happens on the keystroke
        that opens the first form, and a form that takes two seconds to appear is
        a form you pressed the key for twice.
        """
        self.session.choices("maps")

    def _legend(self) -> Text:
        out = Text()
        for glyph, name in (("W", "warp"), ("S", "signpost"), ("N", "npc"),
                            ("T", "trainer"), ("I", "item")):
            out.append(f" {glyph} ", style=_marker_style(glyph))
            out.append(f" {name}   ", style="dim")
        return out

    # -- the map list ----------------------------------------------------------- #
    def _fill_list(self, needle: str, select: str | None = None) -> None:
        needle = needle.strip().lower()
        self._shown = [m.label for m in self._maps
                       if needle in m.label.lower() or needle in m.const.lower()]
        options = self.query_one("#maps", OptionList)
        options.clear_options()
        options.add_options(self._shown)
        if self._shown:
            # Highlighting is what loads a map, so it is set once, to what we
            # actually want — highlighting the first map and then correcting it
            # would load two maps and show you the wrong one on the way.
            options.highlighted = (self._shown.index(select)
                                   if select in self._shown else 0)

    @on(Input.Changed, "#filter")
    def _filtered(self, event: Input.Changed) -> None:
        self._fill_list(event.value)

    @on(Input.Submitted, "#filter")
    def _submitted(self) -> None:
        self.query_one("#maps", OptionList).focus()

    @on(OptionList.OptionHighlighted, "#maps")
    def _highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option_index < len(self._shown):
            label = self._shown[event.option_index]
            self._wanted = label
            self._load(label)

    def _go_to(self, label: str) -> None:
        """Select a map from somewhere other than the list — the findings window
        jumps here. Clearing the filter first, because a map you were sent to is
        one you probably could not have found under whatever you had typed."""
        if label not in [m.label for m in self._maps]:
            return
        self.query_one("#filter", Input).value = ""
        self._wanted = label
        self._fill_list("", select=label)

    # -- loading, off the UI thread ---------------------------------------------- #
    @work(thread=True, exclusive=True, group="map")
    def _load(self, label: str) -> None:
        self.call_from_thread(self._loaded, self.session.load(label))

    def _loaded(self, data: MapData) -> None:
        if data.label != self._wanted:
            return
        self._const = data.const

        grid = self.query_one("#grid", MapGrid)
        status = self.query_one("#status", Static)
        if data.geometry is None:
            grid.display = False
            status.update(Text(data.error or "", style="bold red"))
        else:
            grid.display = True
            grid.show(data.geometry)
            if self._keep_cursor and self._keep_cursor[0] == data.label:
                grid.cursor = self._keep_cursor[1]

        self.query_one(Tabs).show(data.tabs)
        self._show_diagnostics(data.const)

    # -- diagnostics ------------------------------------------------------------- #
    @work(thread=True, exclusive=True, group="lint")
    def _lint(self) -> None:
        self.session.lint()
        self.call_from_thread(self._lint_done)

    def _lint_done(self) -> None:
        self._linted = True
        if self._wanted:
            self._show_diagnostics(
                self.session.ctx.label_to_const.get(self._wanted, self._wanted))

    def _show_diagnostics(self, const: str) -> None:
        panel = self.query_one("#diagnostics", Static)
        if not self._linted:
            panel.update(Text("linting…", style="dim"))
            return

        rank = {"error": 0, "warning": 1, "info": 2}
        found = sorted(self.session.diagnostics(const),
                       key=lambda d: (rank[d.severity.value], d.line))
        if not found:
            panel.update(Text("clean", style="bold green"))
            return

        out = Text()
        for d in found:
            style = _SEVERITY_STYLE[d.severity.value]
            out.append(f"{d.severity.value:>7}  ", style=style)
            out.append(f"{d.code}\n", style="bold")
            out.append(f"         {d.message}\n", style="none")
            out.append(f"         {d.location}\n\n", style="dim")
        panel.update(out)

    # -- what is selected, and therefore what the keys mean ----------------------- #
    @on(Tabs.Selected)
    def _selected(self, event: Tabs.Selected) -> None:
        self._ref = event.ref
        # The footer is a function of the selection, so it has to be recomputed
        # when the selection moves. Textual will call check_action() again.
        self.refresh_bindings()

    def check_action(self, action: str, parameters: tuple) -> bool | None:
        """Which keys exist right now. None hides one from the footer entirely.

        Hidden rather than greyed: a disabled key still reads as an offer, and
        the footer is the only place the studio ever tells you what you can do.
        """
        ref = self._ref
        if action == "edit":
            return True if ref is not None else None
        if action == "delete":
            return True if ref is not None and ref.what not in (ADD, "map") else None
        if action in ("build", "texts"):
            return True if self._const is not None else None
        if action == "undo":
            return True if self.session.can_undo else None
        return True

    @on(Tabs.Chosen)
    def _chosen(self, event: Tabs.Chosen) -> None:
        # Enter on a row. The DataTable eats the key before our bindings see it,
        # so it arrives as a message — and has to land exactly where `e` lands,
        # because they are the same gesture.
        self._act_on(event.ref)

    def action_edit(self) -> None:
        if self._ref is None:
            self.bell()
            return
        self._act_on(self._ref)

    def _act_on(self, ref: Ref) -> None:
        """`e`, or enter: edit what is selected — or add, on the "Add new…" row."""
        if self._const is None or self._wanted is None:
            self.bell()
            return

        if ref.what == ADD:
            self._add(ref.key)
            return
        if ref.what == "map":
            self.notify("editing a map's header is not wired up yet", timeout=6)
            return

        # For now `e` reaches the one thing already writable: what the object
        # says. Editing the object itself — its sprite, its tile, its flag — is
        # the next phase, and saying so beats a key that silently does nothing.
        try:
            text = self.session.dialogue_of(self._wanted, ref)
        except SessionError as exc:
            self.notify(str(exc), severity="error", timeout=10)
            return

        if text is None:
            what = "this" if ref.what in _NO_EDIT_YET else ref.what
            self.notify(f"{what} has no dialogue to edit, and editing the object "
                        f"itself is not wired up yet", timeout=6)
            return
        self._reword(text)

    def _add(self, kind: str) -> None:
        """The dim row at the foot of a tab. What it opens is the session's call."""
        adders = self.session.adders(kind)
        if not adders:
            self.notify(f"adding a {kind} is not wired up yet", timeout=6)
            return
        if len(adders) == 1:
            self._open(adders[0])
            return
        # More than one thing wears this coat — a pickup is an item ball or a
        # hidden item, and until they share one form the honest thing is to ask.
        self.push_screen(
            Picker(f"What kind of {kind}?", [a.title for a in adders]),
            lambda i: None if i is None else self._open(adders[i]),
        )

    def _open(self, action: type[Action], **values: str) -> None:
        grid = self.query_one("#grid", MapGrid)
        cursor = grid.cursor if grid.view is not None else None
        self.push_screen(
            Form(action, self.session, self._const or "", cursor, values=values or None),
            self._filled)

    # -- adding a map ------------------------------------------------------------- #
    def action_add_map(self) -> None:
        """The one thing that isn't reached by pointing at a row, because the map
        it makes is the one map you cannot point at yet."""
        self.push_screen(Form(NewMap, self.session, self._const or ""), self._filled)

    # -- rewording ---------------------------------------------------------------- #
    def action_texts(self) -> None:
        """Every text block in this map, whether or not anything points at it.

        `e` on an NPC gets you *its* words. This gets you the ones nothing is
        standing next to — a sign's, a script's, the ones you would otherwise have
        to go and find.
        """
        if self._const is None or self._wanted is None:
            self.bell()
            return
        self._texts = self.session.texts(self._wanted)
        if not self._texts:
            self.notify(f"{self._wanted} says nothing yet")
            return
        rows = [Text.assemble((t.label, "bold"), ("  " + t.opening, " dim"))
                for t in self._texts]
        self.push_screen(Picker("Which text?", rows, filterable=True),
                         lambda i: None if i is None else self._reword(self._texts[i]))

    def _reword(self, text: TextRef) -> None:
        self.push_screen(
            Form(EditText, self.session, self._const or "",
                 values={"label": text.label, "text": text.prose},
                 boxes={"text": text.box}),
            self._filled)

    # -- deleting ------------------------------------------------------------------ #
    def action_delete(self) -> None:
        """Take the selected thing out of the map.

        The confirmation is not a formality. `removal` decides what a deletion
        drags with it — a private event flag goes back to `const skip`, a shared
        one is left alone, and a trainer's *party* is deliberately not touched
        because deleting it would renumber every party below it in the group and
        re-team every trainer citing them by position. All of that arrives as
        notes on the preview, and the preview is what you are agreeing to.
        """
        if self._ref is None or self._const is None or self._wanted is None:
            self.bell()
            return
        try:
            action = self.session.deletion(self._wanted, self._const, self._ref)
            preview = self.session.preview(action)
        except SessionError as exc:
            self.notify(str(exc), severity="warning", timeout=10)
            return
        except Exception as exc:                       # ActionError, and its kin
            self.notify(str(exc), severity="error", timeout=10)
            return
        self._filled(preview)

    # -- the two windows ------------------------------------------------------------ #
    def action_findings(self) -> None:
        if not self._linted:
            self.notify("still linting…")
            return
        self.push_screen(Findings(self.session.findings()),
                         lambda label: label and self._go_to(label))

    def action_history(self) -> None:
        self.push_screen(History(self.session.mutations()), self._undo_at)

    def _undo_at(self, index: int | None) -> None:
        if index is None:
            return
        try:
            last = self.session.undo_at(index)
        except SessionError as exc:
            self.notify(str(exc), severity="error", timeout=12)
            return
        self.notify(f"undone: {last.summary}")
        self._after_write()

    # -- playing it ------------------------------------------------------------------ #
    def action_build(self) -> None:
        """Build the game and stand on the tile the cursor is on.

        The cursor is the point. Everywhere else you'd have to know the map's
        coordinates and type them into a launcher; here you have already moved to
        the spot you want to look at, so that spot is where you spawn.
        """
        grid = self.query_one("#grid", MapGrid)
        if self._const is None or self._wanted is None or grid.view is None:
            self.bell()
            return
        self.push_screen(Build(self.session, self._const, self._wanted, grid.cursor))

    # -- applying ---------------------------------------------------------------------- #
    def _filled(self, preview: Preview | None) -> None:
        if preview is None:
            return
        if not preview.edits:
            self.notify(f"{preview.summary}: nothing to change")
            return
        self.push_screen(Confirm(preview), lambda ok: self._confirmed(preview, ok))

    def _confirmed(self, preview: Preview, ok: bool | None) -> None:
        if not ok:
            return
        try:
            applied = self.session.apply(preview)
        except SessionError as exc:
            self.notify(str(exc), severity="error", timeout=10)
            return
        self.notify("\n".join([applied.summary, *applied.notes]),
                    timeout=10 if applied.notes else 5)
        self._after_write(applied.select)

    def action_undo(self) -> None:
        try:
            last = self.session.undo()
        except SessionError as exc:
            self.notify(str(exc), severity="error", timeout=12)
            return
        self.notify(f"undone: {last.summary}")
        # Deliberately not `last.select`: undoing the map you just made unmakes
        # it, and the one thing you must not be left looking at is that.
        self._after_write()

    def _after_write(self, select: str | None = None) -> None:
        """Bring the screen back in step with the repo.

        The session has already dropped the caches for the files that moved, so
        the re-lint is the cheap incremental one rather than the 1.7-second cold
        start — but it is still a hundred milliseconds and it is still not going
        on the UI thread. The grid, on the other hand, is re-read immediately:
        the NPC you just placed should be on the map before you have let go of
        the key.

        The list of maps is re-read too, and that is not decoration. Adding a map
        puts one in it; undoing that takes it back out, and the map you were
        looking at can be the one that has just stopped existing.
        """
        self._linted = False
        grid = self.query_one("#grid", MapGrid)
        if self._wanted and grid.view is not None:
            self._keep_cursor = (self._wanted, grid.cursor)

        self._maps = self.session.maps
        known = [m.label for m in self._maps]
        want = select if select in known else self._wanted
        if want not in known:
            want = known[0] if known else None
        self._wanted = want

        self._fill_list(self.query_one("#filter", Input).value, select=want)
        if want:
            self._load(want)
        self._lint()

    # -- keys --------------------------------------------------------------------- #
    def action_focus_filter(self) -> None:
        self.query_one("#filter", Input).focus()

    def action_zoom(self, delta: int) -> None:
        self.query_one("#grid", MapGrid).action_zoom(delta)

    @on(MapGrid.Moved)
    def _moved(self, event: MapGrid.Moved) -> None:
        block = coords.block_of(event.y, event.x)
        quadrant = coords.quadrant_of(event.y, event.x)
        here = Text()
        here.append(f"y {event.y}  x {event.x}", style="bold")
        here.append(f"   block {block[0]},{block[1]} q{quadrant[0]}{quadrant[1]}",
                    style="dim")
        if event.glyph:
            here.append("   ")
            here.append(f" {event.glyph} ", style=_marker_style(event.glyph))
        self.query_one("#status", Static).update(here)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="prism-studio",
        description="Author a map: see it, see what's on it, see what's wrong with it.")
    ap.add_argument("--root", type=Path, default=None, help="the pokeprism repo")
    args = ap.parse_args(argv)

    try:
        root = args.root or paths.repo_root()
    except paths.RepoNotFound as exc:
        print(f"prism-studio: {exc}", file=sys.stderr)
        return 2

    Studio(root).run()
    return 0
