"""prism-studio — the shell.

You pick a map, you see its shape, you see what has been placed on it and what
the linter thinks of it, and you put something new on it: `a` opens the palette,
the form comes up prefilled with the tile the cursor is standing on, and what you
approve is a diff of the exact bytes that land.

**This file opens no files.** Everything it draws arrives from `Session.load` as
plain data — colours, marker positions, tables already reduced to columns and
rows — and everything it changes goes out through an `Action` whose fields
:mod:`.forms` renders without knowing what they mean. The only path from here to
the repo is `main()`, finding the root to hand to the `Session`. That rule is what
keeps `person_event`'s argument order, and the `+4` its macro adds behind your
back, on one side of one line. See `docs/adapter-plan.md`.

Two things are worth knowing about how it loads.

The linter is **not** on the path to the first map. A cold `LintContext` plus a
full run is 1.7 seconds, and blocking on it would mean staring at an empty screen
before you can look at anything. So the grid comes up immediately from source,
and the diagnostics arrive when they arrive, in a thread.

Maps that don't parse are still **in the list**. A map with a broken event header
has a perfectly good shape, and the one thing you must not do to somebody looking
for a bug is hide the map the bug is in. It gets its grid, and the parse error
where its objects would have been.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (DataTable, Footer, Header, Input, OptionList, Static,
                             TabbedContent, TabPane)

from ..maplint.diagnostics import Diagnostic, Severity
from ..shared import coords, paths
from .actions import Action, EditText
from .catalog import CATALOG
from .forms import Confirm, Form, Palette, Picker
from .grid import MapGrid
from .session import MapData, Preview, Session, SessionError, TextRef

_SEVERITY_STYLE = {
    Severity.ERROR: "bold red",
    Severity.WARNING: "yellow",
    Severity.INFO: "dim cyan",
}

_TABS = ("Objects", "Warps", "Signposts", "Triggers", "Connections", "Wild")

#: The studio shows wild encounters and will not edit them, and that had better
#: be on screen rather than in a design document: a wild record is a fixed-size
#: slot in a table the engine indexes by *position*, so writing a short one
#: silently shifts every map below it onto somebody else's Pokémon.
_WILD_IS_READ_ONLY = (
    "read-only — wild records are fixed-size and read by position; "
    "a short one shifts every map below it. Edit data/wild/*.asm by hand."
)


def _marker_style(glyph: str) -> str:
    return (f"bold {coords.hex_color(coords.MARKER_INK[glyph])} "
            f"on {coords.hex_color(coords.MARKER_BG[glyph])}")


class Studio(App):
    TITLE = "prism-studio"

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
    #tabs { height: 16; border-top: solid $panel; }
    #wild-note { height: 1; padding: 0 1; color: $text-disabled; }
    DataTable { height: 1fr; }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("a", "act", "Add…"),
        ("e", "edit_text", "Edit text"),
        ("u", "undo", "Undo"),
        ("slash", "focus_filter", "Filter"),
        ("plus", "zoom(1)", "Zoom in"),
        ("minus", "zoom(-1)", "Zoom out"),
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
        #: it. Keyed by label because a write can bring a *different* map with it:
        #: adding one selects it, and (9, 11) on the map you left is not (9, 11) on
        #: the one you arrived at.
        self._keep_cursor: tuple[str, tuple[int, int]] | None = None
        self._texts: list[TextRef] = []
        self._linted = False

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
        with TabbedContent(id="tabs"):
            for name in _TABS:
                with TabPane(name, id=f"tab-{name.lower()}"):
                    if name == "Wild":
                        yield Static(_WILD_IS_READ_ONLY, id="wild-note")
                    yield DataTable(id=f"table-{name.lower()}", cursor_type="row",
                                    zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        self._fill_list("")
        self.query_one("#diagnostics", Static).update(Text("linting…", style="dim"))
        self._lint()
        self.query_one("#maps", OptionList).focus()

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

        for name in _TABS:
            table = self.query_one(f"#table-{name.lower()}", DataTable)
            table.clear(columns=True)
            if name in data.tables:
                cols, rows = data.tables[name]
                table.add_columns(*cols)
                table.add_rows(rows)
            elif "error" in data.tables:
                # The map has a shape but its header doesn't parse. Say so where
                # the objects would have been, rather than showing an empty table
                # that reads as "this map has no NPCs".
                table.add_columns("unreadable")
                table.add_row(data.tables["error"][0][0])

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

        rank = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}
        found = sorted(self.session.diagnostics(const),
                       key=lambda d: (rank[d.severity], d.line))
        if not found:
            panel.update(Text("clean", style="bold green"))
            return
        panel.update(self._as_text(found))

    def _as_text(self, found: list[Diagnostic]) -> Text:
        out = Text()
        for d in found:
            out.append(f"{d.severity.value:>7}  ", style=_SEVERITY_STYLE[d.severity])
            out.append(f"{d.code}\n", style="bold")
            out.append(f"         {d.message}\n", style="none")
            out.append(f"         {d.location}\n\n", style="dim")
        return out

    # -- changing the map ---------------------------------------------------------- #
    def action_act(self) -> None:
        """Pick an action, fill it in, look at the diff, apply it. One at a time.

        Deliberately one at a time, and `session.py` says why at length: two
        actions built against the same starting file and applied one after the
        other do not merge — the second silently overwrites the first, and both
        NPCs get handed the same event-flag slot. So there is no queue here and
        no Save key. Applying *is* saving.
        """
        if self._const is None:
            self.bell()
            return
        self.push_screen(Palette(CATALOG), self._picked)

    def _picked(self, index: int | None) -> None:
        if index is None or self._const is None:
            return
        chosen: type[Action] = CATALOG[index]
        grid = self.query_one("#grid", MapGrid)
        cursor = grid.cursor if grid.view is not None else None
        self.push_screen(Form(chosen, self.session, self._const, cursor), self._filled)

    def action_edit_text(self) -> None:
        """Reword something the map already says.

        The map's text blocks, as prose. Pick one and you get the same form as
        anything else — with the same tile counter under it, measured against the
        box that block is really drawn in, which is not always the one you'd
        guess.
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
        self.push_screen(Picker("Which text?", rows), self._picked_text)

    def _picked_text(self, index: int | None) -> None:
        if index is None or self._const is None:
            return
        chosen = self._texts[index]
        self.push_screen(
            Form(EditText, self.session, self._const,
                 values={"label": chosen.label, "text": chosen.prose},
                 boxes={"text": chosen.box}),
            self._filled,
        )

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
            self.notify(str(exc), severity="error", timeout=10)
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
