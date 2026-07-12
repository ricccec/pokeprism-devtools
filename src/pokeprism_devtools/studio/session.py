"""The studio's model. No Textual in here — the TUI is a view over this.

**The view reads no files.** Every byte the studio shows comes out of
:meth:`Session.load`, which hands back plain data: block ids, resolved colours,
where the markers go, and the tables already reduced to columns and rows. The TUI
opens nothing and parses nothing — it draws what it is given. That is what keeps
the knowledge of what a `person_event` is (and of the `+4` its macro adds behind
your back) on this side of the line, where exactly one module has to be right
about it. `docs/adapter-plan.md` is the longer version of why that line is where
it is.

Everything the app does to the repo goes through :meth:`Session.apply`, one action
at a time. That is not an accident of implementation, it is the whole design, and
`shared/edits.py` explains why: an :class:`Edit` carries the entire file text plus
the `base` it was derived from, so two edits built against the same starting file
and applied in sequence do **not** merge — the second overwrites the first, and
the first silently never happened. Stage two NPCs before saving and the flag
allocator hands both the same ``const skip`` slot, because when the second one
looked, the first hadn't been written yet.

So: **build → preview → apply → build the next.** Three things fall out of it.

*Failure is free.* Every scaffold builds its complete set of edits before
anything is written, so an action that raises leaves the tree byte-identical.
There is no half-applied state to recover from and no sandbox tree to recover it
in.

*The preview is exact.* It is not a simulation — it is the very edits that will
land, diffed against the very text they were computed from.

*Undo is honest.* Each edit already records the text it replaced, so undo is that
text, written back. It refuses if the file has moved since, because a file that
changed under us is one whose old contents we have no business restoring.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import cached_property
from pathlib import Path

from .. import maplint
from ..dev_server import playtest as devplay
from ..maplint.context import LintContext
from ..maplint.diagnostics import Diagnostic, Severity
from ..shared import caches, eventheader, textbox, world
from ..shared.edits import StaleEdit, apply_edits
from ..wiring import objedit
from . import actions, content, edits, offers, panels, play, reader, undo
from .actions import Action
# The shapes of the answers — see `model.py`. Re-exported, because whatever wants
# a `MapData` wants it *from the session*: the session is the only thing that can
# hand it one, and the split between the two files is a size, not a boundary.
from .model import (Applied, Finding, MapData, MapGeometry, MapRef, Measured,
                    Mutation, Preview, TextPreview, TextRef)  # noqa: F401

__all__ = ["Applied", "Finding", "MapData", "MapGeometry", "MapRef", "Measured",
           "Mutation", "Preview", "Session", "SessionError", "StaleWorld",
           "TextPreview", "TextRef"]


class SessionError(RuntimeError):
    pass


class StaleWorld(SessionError):
    """The repo changed under us, so everything we believe about it is suspect.

    Not an error in the sense of a bug — it is the studio noticing that you (or
    git, or another tool) moved the ground it was standing on. It carries the
    files, because "something changed" is not actionable and
    `constants/trainer_constants.asm changed` is.
    """

    def __init__(self, paths: list[str]) -> None:
        self.paths = paths
        rest = f" and {len(paths) - 3} more" if len(paths) > 3 else ""
        super().__init__(
            f"{len(paths)} file(s) changed on disk since the studio last read the "
            f"repo ({', '.join(paths[:3])}{rest}). Everything it would check this "
            f"against is out of date, so it will not write. Press r to re-read.")


def _entry_of(header: eventheader.EventHeader, label: str,
              ref: panels.Ref) -> eventheader.Entry:
    entries = header.list_of(eventheader.ListKind(ref.kind)).entries
    if not 0 <= ref.index < len(entries):
        raise SessionError(
            f"{label} no longer has a {ref.what} at position {ref.index} — the "
            f"map changed under the table. Select it again.")
    return entries[ref.index]


class Session:
    """One repo, open for editing."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.ctx = LintContext(root)
        self.history: list[Applied] = []
        self._found: list[Diagnostic] | None = None
        # The repo as it was when we read it. Everything this object believes was
        # derived from exactly these bytes — see :mod:`..shared.world`.
        self.world = world.World.stamp(root)
        # Held across playtests, so booting again replaces the window you are
        # already looking at instead of opening a second one behind it.
        self._emulator = devplay.Emulator()

    # -- has the ground moved? ------------------------------------------------ #
    def drifted(self) -> list[str]:
        """Which source files have changed since we read them. ~22ms.

        The app sweeps on a timer and puts a banner up. Cheap enough to ask often;
        see :meth:`..shared.world.World.drift` for why it is only that cheap.
        """
        return self.world.drift(self.root)

    def _fresh(self) -> None:
        """Refuse to reason about a repo we have not read.

        The gate in front of every write. It is not that the *model* is merely out
        of date — it is that `scaffold.require()` and every validator like it are
        about to check your sprite, your item and your trainer class against a
        cache, and pass something the repo no longer contains. The validation is
        already there and already good; all it needs is to be aimed at the truth.
        """
        if moved := self.drifted():
            raise StaleWorld(moved)

    # -- maps ---------------------------------------------------------------- #
    @property
    def maps(self) -> list[MapRef]:
        """Every wired map, by label. Includes the few that don't parse — they
        still have a grid and a name, and hiding them is how you fail to notice
        that a map is broken."""
        return sorted(
            (MapRef(const, label) for label, const in self.ctx.label_to_const.items()),
            key=lambda m: m.label,
        )

    def parses(self, const: str) -> bool:
        return self.ctx.header(const) is not None

    def load(self, label: str) -> MapData:
        """Everything about one map, from source — see :mod:`.reader`.

        Slow enough to want a thread (five files), so it takes no locks and
        touches no state.
        """
        return reader.read_map(self.root, self.ctx, label, self._boxes)

    def sketch(self, action: Action) -> MapGeometry | None:
        """A picture of what an action would put on the grid, before it exists —
        see :func:`.reader.sketch`. Not gated on :meth:`_fresh`: the form calls this
        on every keystroke, and it draws rather than writes."""
        return reader.sketch(self.root, action)

    # -- what a form may offer ------------------------------------------------ #
    def choices(self, kind: str, values: dict[str, str] | None = None) -> list[str]:
        """The constants a field of this kind will accept — see :mod:`.offers`.

        `values` is the form as it stands, because some lists depend on another
        field: which parties exist depends entirely on which class you picked.
        """
        return offers.for_kind(self.root, kind, self._map_consts, values)

    def follows(self, action: type[Action], changed: str,
                values: dict[str, str]) -> dict[str, str]:
        """What the form should fill in for itself, now one field has changed — a
        trainer class knows what it usually wears."""
        return offers.follows(self.root, action, changed, values)

    def warm(self) -> None:
        """Read everything a form will want, before a form asks."""
        offers.warm(self.root)

    @property
    def _map_consts(self) -> tuple[str, ...]:
        """The one list `offers` can't build for itself: which maps exist is a
        question for the lint context, which is this object's, not the module's."""
        return tuple(m.const for m in self.maps)

    # -- what a selected row can do ------------------------------------------- #
    def adders(self, kind: str) -> tuple[type[Action], ...]:
        """What the dim "Add new…" row at the foot of a tab opens.

        Keyed by the word the tab carries in `Tab.adds`, so the view knows that a
        tab can be added to and never learns what it would be adding. More than
        one means the view asks which — a pickup is four different things wearing
        the same coat, and until they share one form the honest thing is to ask.
        """
        return edits.ADDERS.get(kind, ())

    def _header(self, label: str) -> eventheader.EventHeader:
        try:
            return eventheader.parse_map(self.root / f"maps/{label}.asm")
        except (eventheader.UnparseableHeader, FileNotFoundError) as exc:
            raise SessionError(str(exc)) from exc

    def entry(self, label: str, ref: panels.Ref) -> eventheader.Entry:
        """The event-header entry a Ref names, re-read from the file.

        Re-read rather than remembered: a Ref is only as good as the file it came
        from, and between drawing the table and pressing `d` the map may have been
        written to. Reading it again is one file and costs nothing on a keypress —
        and if the entry has moved, saying so beats deleting whatever is standing
        in its place now.
        """
        return _entry_of(self._header(label), label, ref)

    def deletion(self, label: str, const: str, ref: panels.Ref) -> Action:
        """The action `d` would run on this row.

        Raises :class:`SessionError` for the things that cannot be deleted, and
        says *why* — which beats an absent key, because the reason is the
        interesting part.
        """
        if ref.what == "map":
            raise SessionError("deleting a whole map is not something this does.")

        # Neither of these is an entry in an event list, so neither is named the
        # way the objects below are. A warp is named by its *position*, because
        # that is what the rest of the repo counts to; a connection by its
        # direction, because a map has at most one each way.
        if ref.what == "warp":
            return content.RemoveWarp(const, index=str(ref.index))
        if ref.what == "connection":
            return content.Disconnect(const, direction=ref.key)

        # `entry` is not how the object is found — `kind` and `index` are, and they
        # came off the row. It is read to *name* the thing on the confirm screen,
        # and re-read from the file rather than remembered, so a Ref that has gone
        # stale says so instead of describing whatever is standing in its place.
        #
        # This is the difference between a description and an identity. Owsauri's
        # game corner runs sixteen slot machines off one script and Saffron Gates
        # has eight guards with one name between them; asking `removal` to find
        # "the one called X" would refuse all twenty-four. You did not describe the
        # thing you want gone — you pointed at it.
        entry = _entry_of(self._header(label), label, ref)
        y, x = entry.coords
        return content.Remove(
            const, index=str(ref.index), kind=ref.kind,
            label=entry.pointer or "",
            y="" if y is None else str(y), x="" if x is None else str(x))

    def editor(self, label: str, const: str,
               ref: panels.Ref) -> tuple[type[Action], dict[str, str], dict[str, str]]:
        """The form `e` would open on this row, filled in with what is there.

        The mirror of :meth:`deletion`, and like it, it refuses by *explaining* —
        an absent key tells you nothing, and the reason is the interesting part.
        """
        if (action := edits.EDITORS.get(ref.what)) is None:
            raise SessionError(edits.NOT_YET.get(
                ref.what, f"editing a {ref.what} is not wired up yet."))
        try:
            # A map's header lives in two *other* files, and a couple of maps here
            # have one without having a script file at all — the dark Mound floors
            # borrow their neighbour's. So the words are read only for a row that
            # could have any.
            said = [] if ref.what == "map" else self.texts(label)
            values, boxes = edits.prefill(self.root, label, const, ref, said)
        except (objedit.EditError, FileNotFoundError) as exc:
            raise SessionError(str(exc)) from exc
        return action, values, boxes

    # -- the words ------------------------------------------------------------ #
    def texts(self, label: str) -> list[TextRef]:
        """Every text block in one map, as prose — see :func:`.reader.texts`."""
        return reader.texts(self.root, label, self._boxes)

    def measure(self, text: str, box: str = "speech") -> TextPreview:
        """Dialogue-in-progress against the box it lands in, in *tiles*."""
        return reader.measure(self.root, self.ctx, text, self._boxes[box])

    @cached_property
    def _boxes(self) -> dict[str, textbox.Box]:
        return textbox.boxes(self.root)

    # -- diagnostics --------------------------------------------------------- #
    def lint(self) -> list[Diagnostic]:
        """Every finding in the repo. Cached until something is written.

        Deliberately the whole repo, not the selected map: `only=` filters the
        output rather than scoping the work, and a warm pass is 64ms anyway.
        Linting everything also means a change here shows up in the map it breaks
        *over there* — which is the entire reason a cross-file linter exists.
        """
        if self._found is None:
            self._found = maplint.run(self.ctx)
        return self._found

    def diagnostics(self, const: str) -> list[Diagnostic]:
        """The findings *about* one map — those in its file, plus those in the
        shared second_map_headers.asm that name it, since a map's connections
        live there rather than in the map."""
        return [d for d in self.lint() if maplint.mentions(d, self.ctx, const)]

    def findings_for(self, const: str) -> list[Finding]:
        """The findings about one map, flattened for the side panel.

        The panel is handed `Finding`s rather than `Diagnostic`s for the same
        reason the lint window is: a `Diagnostic` carries a `Severity` enum and a
        path, and a view that could read either of those would be a view that knew
        where a map lives. See :meth:`findings`.
        """
        return [self._finding(d) for d in self.diagnostics(const)]

    def findings(self) -> list[Finding]:
        """Every finding in the repo, flattened for the view, worst first.

        The map is resolved *here* because the view cannot: a `Diagnostic` names
        a file, and turning `maps/CastroForest.asm` into the entry the map list
        is keyed by needs the set of labels that are really maps. A finding in a
        shared file — `second_map_headers.asm` holds every map's connections —
        belongs to no one map, so it gets no label and enter does nothing on it,
        which is the truth rather than a guess at which map you meant.
        """
        rank = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}
        worst_first = sorted(self.lint(),
                             key=lambda d: (rank[d.severity], d.code, d.path))
        return [self._finding(d) for d in worst_first]

    def _finding(self, d: Diagnostic) -> Finding:
        stem = Path(d.path).stem
        known = d.path.startswith("maps/") and stem in set(self.ctx.label_to_const)
        return Finding(
            severity=d.severity.value, code=d.code, message=d.message,
            location=d.location, line=d.line, map_label=stem if known else "",
        )

    # -- the history, as something you can look at ---------------------------- #
    def mutations(self) -> list[Mutation]:
        """Everything written this session, oldest first, and whether each can still
        be taken back — see :func:`.undo.mutations`."""
        return undo.mutations(self.root, self.history)

    # -- changing things ----------------------------------------------------- #
    def preview(self, action: Action) -> Preview:
        """Build the edits without writing them.

        Raises :class:`StaleWorld` if the repo moved since we read it — because an
        action validates itself against the model, and a model that is out of date
        will wave through a sprite the repo no longer has. Raises `ActionError` if
        the action can't be built at all, which is a clean no-op, not a partial
        failure.
        """
        self._fresh()
        return Preview(action, action.run(self.root))

    def apply(self, preview: Preview) -> Applied:
        """Write the previewed edits, then bring the linter back in step.

        Applies exactly the edits that were shown. Checked twice, against two
        different things: :meth:`_fresh` says the *repo* has not moved since we
        read it, and `apply_edits` says each *file we are about to write* is still
        the file the edit was computed from. Minutes can pass between opening a
        form and confirming it, and both of those can go stale in that time.
        """
        self._fresh()
        changed = [e for e in preview.edits if e.changed and (e.new_text or e.binary)]
        if not changed:
            raise SessionError(f"{preview.summary}: nothing to change")

        applied = Applied(preview.summary, [e.path for e in changed],
                          notes=list(preview.notes),
                          select=preview.action.selects())
        for e in changed:
            path = self.root / e.path
            applied.undo_to[e.path] = undo.read(path, e.binary)
            applied.wrote[e.path] = e.data if e.binary else e.new_text  # type: ignore[assignment]

        # The findings as they stood *before* — already computed and cached, so
        # this costs nothing, and it has to be taken before the write.
        before = {d.key() for d in self.lint()}

        try:
            apply_edits(self.root, changed, dry_run=False)
        except StaleEdit as exc:
            raise SessionError(str(exc)) from exc

        self._invalidate(applied.paths)
        self.history.append(applied)
        # What it broke. Keyed without the line number (`Diagnostic.key`), so
        # inserting an NPC does not report every finding below it as newly
        # introduced by you.
        applied.introduced = [self._finding(d) for d in self.lint()
                              if d.key() not in before]
        return applied

    def act(self, action: Action) -> Applied:
        """preview + apply, for callers that don't want to look first."""
        return self.apply(self.preview(action))

    # -- taking it back ------------------------------------------------------- #
    @property
    def can_undo(self) -> bool:
        return bool(self.history)

    def undo(self) -> Applied:
        """Put back what the last action replaced."""
        if not self.history:
            raise SessionError("nothing to undo")
        return self.undo_at(len(self.history) - 1)

    def undo_at(self, index: int) -> Applied:
        """Put back what *one* action replaced, wherever it sits in the history.

        Undone **whole or not at all**, and refused for reasons rather than rules —
        see :mod:`.undo`, which is where both of those live.

        Deliberately **not** gated on :meth:`_fresh`. A write is refused against a
        repo that moved because a write is *reasoned* from the repo, and reasoning
        from a stale one gets it wrong. An undo reasons about nothing: it restores
        bytes it can prove are still its own, and it checks that file by file. A
        change elsewhere in the repo is no argument against putting our own file
        back, and refusing on one would mean a `git pull` could strand you with a
        mutation you could no longer take back.
        """
        found = next((m for m in self.mutations() if m.index == index), None)
        if found is None:
            raise SessionError("no such change")
        if found.blocked:
            raise SessionError(f"{found.summary}: {found.blocked}. Left alone.")

        applied = self.history[index]
        undo.restore(self.root, applied)
        del self.history[index]
        self._invalidate(applied.paths)
        return applied

    # -- playing it ----------------------------------------------------------- #
    def build(self, log: Callable[[str], None]) -> bool:
        """`make`, streamed a line at a time. True if the ROM built."""
        return play.build(self.root, log)

    def boot(self, const: str, y: int, x: int, *, keep_people: bool = False) -> list[str]:
        """Stand at (y, x) on this map, in the game, now — see :mod:`.play`."""
        try:
            return play.boot(self.root, self._emulator, const, y, x,
                             keep_people=keep_people)
        except play.PlayError as e:
            raise SessionError(str(e)) from e

    # -- keeping the linter honest -------------------------------------------- #
    def _invalidate(self, paths: list[str]) -> None:
        self.ctx.invalidate(paths)
        self._found = None
        # A new map is a new entry in every list of maps, and a new NPC's flag is
        # a new entry in the list the forms offer.
        offers.forget()
        # And the files we just wrote are not "the repo moving under us" — they
        # are us. Without this the very next sweep would report our own edit as
        # drift, and the studio would spend its life telling you that you had just
        # done something.
        self.world = self.world.restamp(self.root, paths)

    def reload(self) -> None:
        """Forget everything and read the repo again.

        `_invalidate` drops the caches for the files *we* wrote, which is right
        and fast — but it can only know about our own writes. The repo is not ours
        alone: you add a trainer class in an editor, pull a branch, run
        `prism-mapfit`. This is what puts the studio back in step, and
        :meth:`drifted` is what knows when it needs to be — the app sweeps for it
        on a timer, and every write refuses until it has been done.

        Everything cached goes — and "everything" is the load-bearing word.
        Dropping this object's caches is not enough: half the `shared` modules
        memoise their reads with an `@lru_cache`, which lives on the *function*
        and therefore outlives any session that thought it owned it. Clear only
        what is on `self` and `consts.names` will go on serving the items it read
        an hour ago, with total confidence. See :mod:`..shared.caches`.

        The **history stays**, deliberately. An undo checks each file against
        exactly what it wrote, so a mutation whose file you have since edited by
        hand refuses of its own accord and says so. Dropping the history would
        silently give up that guard instead of exercising it.
        """
        caches.clear()          # which finds `offers._index` too, by discovery
        self.ctx = LintContext(self.root)
        self._found = None
        self.__dict__.pop("_boxes", None)
        # The stamp is taken now and the repo is re-read lazily, on the next
        # question anybody asks. So the stamp is always *older* than the reads it
        # vouches for, and a file that changes in the gap is reported as drift
        # again rather than missed. Erring that way round is the whole point.
        self.world = world.World.stamp(self.root)
