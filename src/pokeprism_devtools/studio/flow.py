"""The write cycle: from "here is a preview" to "the screen is back in step".

Every change the studio makes takes the same four steps, whatever it is — a form
is filled in, the edits it would make are shown, you agree to them, and the screen
is re-read. Adding an NPC, rewording a sign and deleting a warp differ only in
which `Action` goes in at the top; from `_filled` onwards there is one path, and
this is it.

A mixin on `Studio` rather than a class of its own, because it is the app: it
pushes the app's screens and it puts the app's map back on screen. The split is a
size, not a boundary — the same admission `model.py` makes about `session.py`. What
it does buy is that the *cycle* is legible in one place, and it is the part where
being wrong is expensive.

The whole of it rests on one rule, which `shared/edits.py` argues at length:
**build an edit, apply it, then build the next.** An `Edit` carries the entire file
plus the text it was derived from, so two edits built against the same starting
file do not merge — the second silently overwrites the first. There is therefore no
"pending changes" tray here and there never will be. Applying *is* saving.
"""

from __future__ import annotations

from rich.text import Text

from .actions import Action
from .grid import MapGrid
from .maplist import MapList
from .screens import Confirm, Findings, Form, History, Picker
from .session import Draft, Preview, SessionError, TextRef
from .status import Where
from .tabs import MapTabs


class Flow:
    """Opening a form, agreeing to a preview, and putting the result on screen."""

    def _open(self, action: type[Action], **values: str) -> None:
        grid = self.query_one("#grid", MapGrid)
        cursor = grid.cursor if grid.view is not None else None
        self.push_screen(
            Form(action, self.session, self._const or "", cursor, values=values or None),
            self._filled)

    def _filled(self, result: Preview | Draft | None) -> None:
        if isinstance(result, Draft):
            self._drafted(result)
            return
        if result is None:
            # Backing out of the form. If a draft was on the grid it was that form's
            # draft — nothing else can be opened while one is up — so this is the
            # gesture that abandons it, and the real map comes back.
            self._undraft()
            return
        if not result.edits:
            self.notify(f"{result.summary}: nothing to change")
            return
        self.push_screen(Confirm(result), lambda ok: self._confirmed(result, ok))

    # -- the map that doesn't exist yet ------------------------------------------- #
    def _drafted(self, draft: Draft) -> None:
        """Put the map you have described on the grid, and hold on to the form.

        Everything the grid derives from a *real* map goes blank while it is up —
        the tables, the diagnostics, the selection. That is the point: those rows
        belong to some other map, the one you were looking at when you pressed `a`,
        and a grid where clicking a tile highlighted a warp in a different map
        would be worse than a grid with nothing under it. `b` and `e` and `d` go
        away for the same reason. There is nothing here to build or edit yet.

        The map list keeps its selection, so wandering off to look at the neighbour
        you are drawing this next to leaves the draft alone. `a` brings it back.
        """
        self._draft = draft
        self._const = None
        self._data = None
        self._ref = None
        self.refresh_bindings()

        grid = self.query_one("#grid", MapGrid)
        grid.display = True
        grid.show(draft.view)
        self.query_one(MapTabs).show([])
        self.query_one(Where).note(
            f"{draft.label} — a draft, not in the game. "
            f"Press a to go back to the form, or pick a map to put it away.")

    def _undraft(self) -> None:
        """Forget the draft and put the real map back. A no-op if there wasn't one."""
        if self._draft is None:
            return
        self._draft = None
        if self._wanted:
            self._load(self._wanted)

    def _confirmed(self, preview: Preview, ok: bool | None) -> None:
        """You said yes. Write it — and then say what it cost.

        The apply can still refuse at this point, and both of its reasons are worth
        reading rather than dismissing: the repo may have moved since the form was
        opened (`StaleWorld`), or one of the very files this edit rewrites may have
        been changed underneath it (`StaleEdit`). Minutes can pass between opening a
        form and agreeing to it.
        """
        if not ok:
            return
        try:
            applied = self.session.apply(preview)
        except SessionError as exc:
            self.notify(str(exc), severity="error", timeout=15)
            self._sweep()                 # a StaleWorld puts the banner up at once
            return

        # It exists now. A draft is a map that doesn't, so whatever we were holding
        # is either this one — in which case `_after_write` is about to put the real
        # thing on screen — or nothing at all.
        self._draft = None

        lines = [applied.summary, *applied.notes]
        severity = "information"
        if applied.introduced:
            # What it broke. A fresh repo stops a change that rests on a repo that
            # moved; nothing stops a change that read the repo correctly and was
            # wrong anyway, except the linter — and this is the only moment you would
            # ever be looking at it.
            worst = [f for f in applied.introduced if f.severity == "error"]
            lines.append(f"⚠  this introduced {len(applied.introduced)} new "
                         f"finding(s), {len(worst)} of them errors — u to undo")
            lines.extend(f"   {f.code}: {f.message}" for f in applied.introduced[:3])
            severity = "warning" if worst else "information"

        self.notify("\n".join(lines), severity=severity,
                    timeout=15 if applied.introduced else 5)
        self._after_write(applied.select)

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
        if (form := self.session.form("reword")) is None:
            self.notify("rewording text is not wired for this tree — "
                        "the words are on screen to read", timeout=8)
            return
        # Everything the record knows about *which* block this is, not just the
        # part that is a field. A label is not an identity — a family label can
        # hold two boxes — so the line it opens on rides along, and an adapter
        # that needs it to be sure has it. See `hacks/vanilla/text.py`.
        self.push_screen(
            Form(form, self.session, self._const or "",
                 values={"label": text.label, "owner": text.owner,
                         "at": str(text.lineno), "text": text.prose},
                 boxes={"text": text.box}),
            self._filled)

    # -- resizing ------------------------------------------------------------------ #
    def action_resize(self) -> None:
        """`s`: change the map's shape from an edge.

        The one thing `edits.EditMap` refuses on the Attributes tab, because
        doing it right means moving the block grid — and, at the top or left,
        every object's coordinates — with it. See `wiring/mapresize.py`.
        """
        form = self.session.form("resize")
        if (form is None or self._const is None or self._wanted is None
                or not self._may_write()):
            self.bell()
            return
        self._open(form)

    # -- taking it back --------------------------------------------------------- #
    def action_undo(self) -> None:
        try:
            last = self.session.undo()
        except SessionError as exc:
            self.notify(str(exc), severity="error", timeout=12)
            return
        self.notify(f"undone: {last.summary}")
        # Deliberately not `last.select`: undoing the map you just made unmakes it,
        # and the one thing you must not be left looking at is that.
        self._after_write()

    def action_history(self) -> None:
        self.push_screen(History(self.session.mutations()), self._undo_at)

    def _undo_at(self, index: int | None) -> None:
        """Undo something other than the last thing — which is allowed, and refused
        for reasons the panel has already shown you. See `Session.mutations`."""
        if index is None:
            return
        try:
            last = self.session.undo_at(index)
        except SessionError as exc:
            self.notify(str(exc), severity="error", timeout=12)
            return
        self.notify(f"undone: {last.summary}")
        self._after_write()

    def action_findings(self) -> None:
        if not self.session.lints:
            self.notify("no linter reads this tree — there are no findings to list")
            return
        if not self._linted:
            self.notify("still linting…")
            return
        self.push_screen(Findings(self.session.findings()),
                         lambda label: label and self.query_one(MapList).go_to(label))

    # -- back in step ------------------------------------------------------------ #
    def _after_write(self, select: str | None = None) -> None:
        """Bring the screen back in step with the repo.

        The session has already dropped the caches for the files that moved, so the
        re-lint is the cheap incremental one rather than the 1.7-second cold start —
        but it is still a hundred milliseconds and it is still not going on the UI
        thread. The grid, on the other hand, is re-read immediately: the NPC you just
        placed should be on the map before you have let go of the key.

        The list of maps is re-read too, and that is not decoration. Adding a map puts
        one in it; undoing that takes it back out, and the map you were looking at can
        be the one that has just stopped existing.
        """
        self._linted = False
        grid = self.query_one("#grid", MapGrid)
        if self._wanted and grid.view is not None:
            scroll = grid.scroll_offset
            self._keep_cursor = (self._wanted, grid.cursor, (scroll.x, scroll.y))

        maps = self.session.maps
        known = [m.label for m in maps]
        want = select if select in known else self._wanted
        if want not in known:
            want = known[0] if known else None
        self._wanted = want

        self.query_one(MapList).fill(maps, select=want)
        if want:
            self._load(want)
        self._lint()
