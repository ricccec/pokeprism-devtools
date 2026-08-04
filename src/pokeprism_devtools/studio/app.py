"""prism-studio — the shell.

You pick a map, you see its shape, you see what has been placed on it and what the
linter thinks of it. Then you point at one of those things and act on it: `e` edits
what is highlighted, `d` deletes it, and enter on the dim row at the foot of a tab
adds another. The keys on offer are a function of what you have selected — there is
no `e` on a wild encounter, because a wild encounter cannot be edited and a key you
cannot use should not be advertised.

**This file opens no files.** Everything it draws arrives from `Session` as plain
data — colours, marker positions, tables already reduced to rows — and everything
it changes goes out through an `Action` whose fields `screens/forms.py` renders
without knowing what they mean. A selected row hands back an opaque `Ref` that this
file never looks inside. That rule is what keeps `person_event`'s argument order,
and the `+4` its macro adds behind your back, on one side of one line.

Four things are worth knowing about how it behaves.

**The grid and the tables are one selection.** Put the cursor on an NPC — with the
arrow keys or by clicking it — and the NPCs tab comes up with that NPC highlighted,
so the map is a way of *reaching* a row and not a picture beside it. It mirrors:
walk down the warps table and the cursor walks the doors. Crossing bare ground
changes nothing, because a cursor that reshuffled the tabs every time it passed
over grass would be a cursor you could not think next to.

**The repo is watched.** Every few seconds the studio checks whether the source has
changed underneath it, and says so. This is not about a stale dropdown: the studio
checks your sprite, your item and your trainer class against what it read at
startup, so a repo that has moved is a repo we would validate a write against and
get wrong. While it has moved, writing is refused — see `shared/world.py`, and `r`.

**A map you have not made yet can still be on the grid.** The new-map form draws
what you have described on the real grid, full size, and gets out of the way while
you look at it — see `Flow._drafted`. While a draft is up, everything that belongs
to a *real* map goes quiet: the tables, the diagnostics, `b`, `e`, `d`. There is
nothing there to build or edit. `a` hands the form back with your answers in it.

The linter is **not** on the path to the first map. A cold `LintContext` plus a full
run is 1.7 seconds, and blocking on it would mean staring at an empty screen before
you can look at anything. So the grid comes up immediately from source, and the
diagnostics arrive when they arrive, in a thread.

Maps that don't parse are still **in the list**. A map with a broken event header
has a perfectly good shape, and the one thing you must not do to somebody looking
for a bug is hide the map the bug is in.

And the command palette is on **`p`**, not `ctrl+p`, because this is mostly run
inside VSCode's terminal and VSCode eats `ctrl+p`. Which is why `b` builds.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from textual import events, on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Footer, Header

from ..contract import mount as hackmount
from ..shared import paths
from ..shared.coords import Tile
from .flow import Flow
from .grid import MapGrid
from .maplist import MapList
from ..contract import Ref
from .screens import Build, Form, Picker
from .session import Draft, MapData, Session, SessionError, TextRef
from .status import Banner, Centre, Diagnostics, Where
from .tabs import MapTabs

#: How often to ask whether the repo moved. A sweep is ~22ms of `stat` on a thread,
#: so this is a fraction of a percent of one core — and the thing it is watching for
#: is a `git pull` in another window, which you want to hear about in seconds rather
#: than at the moment you press enter on a form.
WATCH_SECONDS = 5.0


class Studio(Flow, App):
    """The shell. `Flow` is the other half of it — see :mod:`.flow`: everything
    from agreeing to a preview to putting the map back on screen."""

    TITLE = "prism-studio"

    #: Textual puts its command palette on ctrl+p. VSCode's terminal takes that key
    #: before we ever see it, and this is mostly run inside VSCode.
    COMMAND_PALETTE_BINDING = "p"

    CSS = """
    #body { height: 1fr; }
    #tabs-pane { height: 18; border-top: solid $panel; }
    """

    BINDINGS = [
        Binding("e", "edit", "Edit"),
        Binding("d", "delete", "Delete"),
        Binding("a", "add_map", "Add map"),
        Binding("s", "resize", "Resize"),
        Binding("b", "build", "Build & run"),
        Binding("t", "texts", "All text"),
        Binding("u", "undo", "Undo"),
        Binding("r", "refresh", "Re-read"),
        Binding("L", "findings", "Findings"),
        Binding("H", "history", "History"),
        Binding("slash", "focus_filter", "Filter", show=False),
        Binding("plus", "zoom(1)", "Zoom in", show=False),
        Binding("minus", "zoom(-1)", "Zoom out", show=False),
        Binding("q", "quit", "Quit", show=False),
    ]

    def __init__(self, root: Path, hack_path: Path | None = None) -> None:
        super().__init__()
        self.session = Session(root, hack_path)
        #: The map the user last asked for. A slower load that lands after it has
        #: moved on is dropped — otherwise arrowing down the list leaves you looking
        #: at whichever map happened to finish last.
        self._wanted: str | None = None
        self._const: str | None = None
        #: The map on screen, as the session handed it over. What turns a tile into
        #: the row that owns it, and back — see :meth:`_moved`.
        self._data: MapData | None = None
        #: Where to put the cursor *and the scroll* back after a reload, and on which
        #: map. Re-reading the map is how a new NPC appears on the grid, but it would
        #: also send you home — cursor to the corner, the map scrolled back to the
        #: top-left — off the spot you were working on, the moment you worked on it.
        #: The scroll is kept as well as the cursor because restoring only the cursor
        #: leaves the map scrolled to wherever minimally shows it, which throws away
        #: any pan you had made across a map wider than the viewport. Keyed by label
        #: because a write can bring a *different* map with it.
        self._keep_cursor: tuple[str, tuple[int, int], tuple[int, int]] | None = None
        self._texts: list[TextRef] = []
        self._linted = False
        #: What is highlighted in the tabs. The footer is a function of this.
        self._ref: Ref | None = None
        #: The grid and the tables move each other, and each move announces itself.
        #: Without this they would take turns announcing forever.
        self._syncing = False
        #: The files that have changed on disk since we read them. While this is
        #: non-empty the studio will not write, because everything it would check a
        #: write against is out of date.
        self._moved: list[str] = []
        #: The map you are in the middle of describing, if you asked to look at it.
        #: The form went away to let you see it full size; this is what brings the
        #: form back with your answers still in it. Nothing of it is on disk — see
        #: :meth:`Flow._drafted`.
        self._draft: Draft | None = None

    # -- layout ---------------------------------------------------------------- #
    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            yield MapList(id="sidebar")
            yield Centre()
            yield Diagnostics(id="findings")
        yield MapTabs(id="tabs-pane")
        yield Banner(id="banner")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(MapList).fill(self.session.maps)
        if self.session.lints:
            self.query_one(Diagnostics).waiting()
        else:
            self.query_one(Diagnostics).absent()
        self._lint()
        self._warm()
        self.set_interval(WATCH_SECONDS, self._sweep)
        self.query_one(MapList).focus_list()

    @work(thread=True, group="warm")
    def _warm(self) -> None:
        """Read the constants a form autocompletes from, before a form asks.

        Every sprite, movement, item, trainer class, tileset, landmark and piece of
        music in the repo, plus what each trainer class usually wears — two seconds
        of parsing, cached on the session for the rest of the run. Left to happen
        lazily it happens on the keystroke that opens the first form, and a form
        that takes two seconds to appear is a form you pressed the key for twice.
        """
        self.session.warm()

    # -- watching the repo ------------------------------------------------------ #
    @work(thread=True, exclusive=True, group="watch")
    def _sweep(self) -> None:
        """Has the source changed under us? ~22ms of `stat`, on a thread.

        On a timer *and* on regaining focus. The timer is the one that matters:
        alt-tabbing back from an editor is only one of the ways the repo moves, and
        `git pull` in a tmux pane next door is not a focus change at all.
        """
        self.call_from_thread(self._swept, self.session.drifted())

    @on(events.AppFocus)
    def _refocused(self) -> None:
        self._sweep()

    def _swept(self, moved: list[str]) -> None:
        if moved == self._moved:
            return
        self._moved = moved
        self.query_one(Banner).show(moved)

    def _may_write(self) -> bool:
        """Refuse to open a form, or to write, against a repo we have not read.

        Asked *again* here rather than trusting the banner, because the banner is
        only as fresh as the last sweep and a form is opened by a keystroke. The
        session checks a third time inside `preview` and `apply` — which is the one
        that actually guarantees anything, since this is the view and the view is
        not what keeps the promise.
        """
        if moved := self.session.drifted():
            self._swept(moved)
            self.notify(
                f"{len(moved)} file(s) changed on disk ({moved[0]}…). The studio "
                f"would be checking this against a repo that no longer exists. "
                f"Press r to re-read, then try again.",
                severity="warning", timeout=12)
            return False
        return True

    # -- the map list ----------------------------------------------------------- #
    @on(MapList.Chosen)
    def _chose_map(self, event: MapList.Chosen) -> None:
        self._wanted = event.label
        self._load(event.label)

    @work(thread=True, exclusive=True, group="map")
    def _load(self, label: str) -> None:
        self.call_from_thread(self._loaded, self.session.load(label))

    def _loaded(self, data: MapData) -> None:
        if data.label != self._wanted:
            return
        self._const = data.const
        self._data = data

        grid = self.query_one("#grid", MapGrid)
        if data.geometry is None:
            grid.display = False
            self.query_one(Where).error(data.error or "")
        else:
            grid.display = True
            grid.show(data.geometry)
            if self._keep_cursor and self._keep_cursor[0] == data.label:
                _, cursor, scroll = self._keep_cursor
                grid.cursor = cursor
                # After the cursor, and it wins: setting the cursor scrolls to make
                # it visible, which is not the same as the scroll you actually had.
                grid.scroll_to(*scroll, animate=False)

        self.query_one(MapTabs).show(data.tabs)
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
                self.session.const_of(self._wanted))

    def _show_diagnostics(self, const: str) -> None:
        panel = self.query_one(Diagnostics)
        if not self.session.lints:
            panel.absent()
        elif self._linted:
            panel.show(self.session.findings_for(const))
        else:
            panel.waiting()

    # -- the grid and the tables are one selection -------------------------------- #
    @on(MapGrid.Moved)
    def _moved(self, event: MapGrid.Moved) -> None:
        """The cursor is on a tile. If anything is standing there, select it.

        Clicking a tile already moves the cursor (`grid.on_click`), so the mouse and
        the arrow keys arrive here together and there is one path, not two.

        **An empty tile selects nothing.** Crossing bare ground must leave the tabs
        exactly as they were: a cursor that reset the selection every time it passed
        over grass would make the tables useless to think next to.
        """
        refs = self._data.at(Tile(y=event.y, x=event.x)) if self._data else ()
        self.query_one(Where).cursor(event, stacked=len(refs))
        if refs and not self._syncing:
            self._syncing = True
            try:
                self.query_one(MapTabs).select(refs[0])
            finally:
                self._syncing = False

    @on(MapGrid.Hovered)
    def _hovered(self, event: MapGrid.Hovered) -> None:
        self.query_one(Where).mouse(event if event.inside else None)

    @on(MapTabs.Selected)
    def _selected(self, event: MapTabs.Selected) -> None:
        self._ref = event.ref
        # The footer is a function of the selection, so it has to be recomputed when
        # the selection moves. Textual will call check_action() again.
        self.refresh_bindings()

        # The mirror: walking down the warps table walks the cursor along the doors.
        # Only when the selection actually *moved* within a table, though — merely
        # switching tabs (or a load settling) announces the new row for the footer
        # but must leave the cursor where you put it. Otherwise switching to Items
        # to add a ball drags the cursor onto the first item and you drop on it.
        grid = self.query_one("#grid", MapGrid)
        if (not event.move or self._syncing or event.ref is None
                or self._data is None or grid.view is None):
            return
        tile = self._data.tile_of(event.ref)
        if tile is None or tile == grid.cursor:
            return
        self._syncing = True
        try:
            grid.cursor = tile
        finally:
            self._syncing = False

    def check_action(self, action: str, parameters: tuple) -> bool | None:
        """Which keys exist right now. None hides one from the footer entirely.

        Hidden rather than greyed: a disabled key still reads as an offer, and the
        footer is the only place the studio ever tells you what you can do.
        """
        ref = self._ref
        if action == "edit":
            return True if ref is not None else None
        if action == "delete":
            return True if ref is not None and ref.deletable else None
        if action == "add_map":
            return True if self.session.form("newmap") is not None else None
        if action == "resize":
            return (True if self._const is not None
                    and self.session.form("resize") is not None else None)
        if action == "build":
            # Build-and-boot is a declared capability, not a given: a tree
            # whose adapter has no emulator wiring simply has no `b`.
            return (True if self._const is not None
                    and self.session.plays else None)
        if action == "texts":
            return True if self._const is not None else None
        if action == "undo":
            return True if self.session.can_undo else None
        return True

    # -- acting on what is selected ------------------------------------------------ #
    @on(MapTabs.Chosen)
    def _chosen(self, event: MapTabs.Chosen) -> None:
        # Enter on a row. The DataTable eats the key before our bindings see it, so
        # it arrives as a message — and has to land exactly where `e` lands, because
        # they are the same gesture.
        self._act_on(event.ref)

    def action_edit(self) -> None:
        if self._ref is None:
            self.bell()
            return
        self._act_on(self._ref)

    def _act_on(self, ref: Ref) -> None:
        """`e`, or enter: edit what is selected — or add, on the "Add new…" row.

        The form that opens is the one you *added* this kind with, filled in with
        what is actually in the file — including its words, which is why `e` on an
        NPC still reaches its dialogue, and now reaches the rest of it too.
        """
        if self._const is None or self._wanted is None or not self._may_write():
            self.bell()
            return
        if ref.adds:
            self._add(ref.adds)
            return

        try:
            action, values, boxes = self.session.editor(
                self._wanted, self._const, ref)
        except SessionError as exc:
            self.notify(str(exc), severity="warning", timeout=10)
            return
        self.push_screen(
            Form(action, self.session, self._const, values=values, boxes=boxes,
                 target=ref),
            self._filled)

    def _add(self, kind: str) -> None:
        """The dim row at the foot of a tab. What it opens is the session's call."""
        adders = self.session.adders(kind)
        if not adders:
            self.notify(f"adding a {kind} is not wired up yet", timeout=6)
            return
        if len(adders) == 1:
            self._open(adders[0])
            return
        # More than one thing wears this coat. Until they share one form the honest
        # thing is to ask.
        self.push_screen(
            Picker(f"What kind of {kind}?", [a.title for a in adders]),
            lambda i: None if i is None else self._open(adders[i]),
        )

    def action_add_map(self) -> None:
        """The one thing that isn't reached by pointing at a row, because the map it
        makes is the one map you cannot point at yet.

        And the one thing you can come *back* to: if you asked to see the map you
        were describing, the form went away so you could look at it, and this is the
        key that returns you to it — with every answer where you left it.

        The form itself is the write adapter's — `session.form("newmap")` — so
        the key exists exactly when the mounted tree's adapter writes maps.
        """
        if (form := self.session.form("newmap")) is None or not self._may_write():
            self.bell()
            return
        self.push_screen(
            Form(form, self.session, self._const or "",
                 values=self._draft.values if self._draft else None),
            self._filled)

    # -- deleting ------------------------------------------------------------------ #
    def action_delete(self) -> None:
        """Take the selected thing out of the map.

        The confirmation is not a formality. `removal` decides what a deletion drags
        with it — a private event flag goes back to `const skip`, a shared one is
        left alone, and a trainer's *party* is deliberately not touched because
        deleting it would renumber every party below it in the group and re-team
        every trainer citing them by position. All of that arrives as notes on the
        preview, and the preview is what you are agreeing to.
        """
        if self._ref is None or self._const is None or self._wanted is None:
            self.bell()
            return
        try:
            action = self.session.deletion(self._wanted, self._const, self._ref)
            preview = self.session.preview(action)
        except SessionError as exc:
            self.notify(str(exc), severity="warning", timeout=12)
            return
        except Exception as exc:                       # ActionError, and its kin
            self.notify(str(exc), severity="error", timeout=10)
            return
        self._filled(preview)

    # -- playing it ------------------------------------------------------------------ #
    def action_build(self) -> None:
        """Build the game and stand on the tile the cursor is on.

        The cursor is the point. Everywhere else you'd have to know the map's
        coordinates and type them into a launcher; here you have already moved to the
        spot you want to look at, so that spot is where you spawn.
        """
        grid = self.query_one("#grid", MapGrid)
        if self._const is None or self._wanted is None or grid.view is None:
            self.bell()
            return
        self.push_screen(Build(self.session, self._const, self._wanted, grid.cursor))

    # -- keys --------------------------------------------------------------------- #
    def action_focus_filter(self) -> None:
        self.query_one(MapList).focus_filter()

    def action_zoom(self, delta: int) -> None:
        self.query_one("#grid", MapGrid).action_zoom(delta)

    def action_refresh(self) -> None:
        """Read the repo again, because you changed it from outside.

        The studio drops its caches for the files *it* writes, which it can do
        precisely because it knows what it wrote. It cannot know what you did in an
        editor, or what a `git pull` did — it can only *notice*, which is what the
        banner is. This is the key that acts on the noticing: the linter's context,
        the constants the forms autocomplete from, the map list, the map on screen.
        All of it, again. And with that, writing is allowed once more.
        """
        self.notify("re-reading the repo…")
        self.session.reload()
        self._swept([])
        self._linted = False

        maps = self.session.maps
        known = [m.label for m in maps]
        want = self._wanted if self._wanted in known else (known[0] if known else None)
        self._wanted = want
        self.query_one(MapList).fill(maps, select=want)
        if want:
            self._load(want)
        self._lint()
        self._warm()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="prism-studio",
        description="Author a map: see it, see what's on it, see what's wrong with it.")
    ap.add_argument("--root", type=Path, default=None, help="the pokeprism repo")
    ap.add_argument("--hack-path", type=Path, default=None, dest="hack_path",
                    help="a claim.py (or its directory) to mount alongside the "
                         "installed adapters — for authoring one without a reinstall")
    args = ap.parse_args(argv)

    try:
        root = args.root or paths.repo_root()
        # Mounted once here for the *error*: an unrecognisable tree should be
        # refused on stderr, before a full-screen TUI has repainted the
        # terminal. The session mounts its own, through the same override.
        hackmount.mount(root, args.hack_path)
    except (paths.RepoNotFound, hackmount.UnknownTree) as exc:
        print(f"prism-studio: {exc}", file=sys.stderr)
        return 2

    Studio(root, args.hack_path).run()
    return 0
