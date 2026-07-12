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
from ..shared import caches, eventheader, swatches, textbox
from ..shared.edits import StaleEdit, apply_edits
from . import actions, content, offers, panels, play, reader
from .actions import Action
# The shapes of the answers — see `model.py`. Re-exported, because whatever wants
# a `MapData` wants it *from the session*: the session is the only thing that can
# hand it one, and the split between the two files is a size, not a boundary.
from .model import (Applied, Finding, MapData, MapGeometry, MapRef, Measured,
                    Mutation, Preview, TextPreview, TextRef)  # noqa: F401

__all__ = ["Applied", "Finding", "MapData", "MapGeometry", "MapRef", "Measured",
           "Mutation", "Preview", "Session", "SessionError", "TextPreview",
           "TextRef"]


class SessionError(RuntimeError):
    pass


#: What each tab's "Add new…" row opens. See :meth:`Session.adders`.
#:
#: One action per tab now, including Pickups: the four kinds of pickup are one
#: form that changes shape, rather than four entries in a menu you have to choose
#: between before you know what the fields are. See `content.AddPickup`.
ADDERS: dict[str, tuple[type[Action], ...]] = {
    "NPC": (content.AddNpc,),
    "trainer": (content.AddTrainer,),
    "pickup": (content.AddPickup,),
    "warp": (actions.AddWarp,),
    "signpost": (content.AddSignpost,),
    "connection": (actions.Connect,),
}

#: The rows `d` cannot act on yet, and the reason — which is the useful part, and
#: is why these are messages rather than a missing key.
_NOT_YET = {
    "warp": ("deleting a warp renumbers every warp in the repo that points at "
             "this map, because `warp_to` is a position in this map's list. "
             "Not wired up yet."),
    "trigger": "deleting a trigger isn't wired up yet.",
    "connection": ("deleting a connection has to rewrite the neighbour's side "
                   "and both flag nibbles. Not wired up yet."),
    "map": "deleting a whole map is not something this does.",
}


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
        # Held across playtests, so booting again replaces the window you are
        # already looking at instead of opening a second one behind it.
        self._emulator = devplay.Emulator()

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
        """A picture of what an action would put on the grid, before it exists.

        Only the new-map action has anything to show — see :meth:`Action.sketch`.
        The form calls this on every keystroke and either draws the result or
        prints why it can't, which is how a `.blk` of the wrong size stops being
        an arithmetic complaint and becomes a map of the wrong shape.

        Raises :class:`~.actions.ActionError` for a form that isn't ready yet.
        That is the normal state of a form you are typing into, not a failure.
        """
        bd = action.sketch(self.root)
        if bd is None:
            return None
        return MapGeometry(
            label=bd.name, blocks=bd.blocks, height=bd.height, width=bd.width,
            swatches=swatches.for_map(self.root, bd.tileset_id, bd.permission),
            marks={},                    # nothing stands on it yet
        )

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
        return ADDERS.get(kind, ())

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

        Raises :class:`SessionError` for the things that cannot yet be deleted
        safely, and says *why* — which beats an absent key, because the reason is
        the interesting part.
        """
        if ref.what in _NOT_YET:
            raise SessionError(_NOT_YET[ref.what])

        header = self._header(label)
        entry = _entry_of(header, label, ref)

        # Name it by its script label when it has one, and by its position when
        # it hasn't. Two item balls of the same item are told apart by where they
        # are; two objects on one tile are told apart by what they point at.
        # Between them that covers everything, and `removal` refuses an ambiguous
        # name rather than guessing — which is the behaviour we want to reach.
        pointer = entry.pointer
        if pointer and any(ln.startswith(f"{pointer}:") for ln in header.lines):
            return content.Remove(const, label=pointer, y="", x="")

        y, x = entry.coords
        if y is None or x is None:
            raise SessionError(
                f"this {ref.what} has neither a script label nor readable "
                f"coordinates, so there is no unambiguous way to name it.")
        return content.Remove(const, label="", y=str(y), x=str(x))

    def dialogue_of(self, label: str, ref: panels.Ref) -> TextRef | None:
        """The text block this row's object points at, if it points at one.

        What `e` opens for now. An item ball points at an item const and a trainer
        at a script, so this is None for them and the key stays quiet — until the
        edit forms land and `e` can mean what it should.
        """
        entry = self.entry(label, ref)
        if not entry.pointer:
            return None
        return next((t for t in self.texts(label) if t.label == entry.pointer), None)

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
        known = set(self.ctx.label_to_const)
        out = []
        for d in sorted(self.lint(), key=lambda d: (rank[d.severity], d.code, d.path)):
            stem = Path(d.path).stem
            out.append(Finding(
                severity=d.severity.value, code=d.code, message=d.message,
                location=d.location, line=d.line,
                map_label=stem if d.path.startswith("maps/") and stem in known else "",
            ))
        return out

    # -- the history, as something you can look at ---------------------------- #
    def mutations(self) -> list[Mutation]:
        """Everything written this session, oldest first, and whether each can
        still be taken back.

        Two things can stop an undo, and both are worth stating rather than
        greying out a button. A **later mutation touched the same file**, so
        putting this one's text back would wipe that one out — the fix is to undo
        the later one first, and this says which. Or the **file has changed since
        we wrote it**, which means somebody else did it, in their editor or in
        another tool, and restoring our idea of "before" would throw their work
        away. Neither is an error. Both are reasons.
        """
        out = []
        for i, applied in enumerate(self.history):
            later = {p for a in self.history[i + 1:] for p in a.paths}
            clash = sorted(set(applied.paths) & later)
            moved = [rel for rel, written in applied.wrote.items()
                     if _read(self.root / rel, isinstance(written, bytes)) != written]

            if clash:
                blocked = (f"{clash[0]} was written again by a later change — "
                           f"undo that one first")
            elif moved:
                blocked = (f"{moved[0]} has changed since this was applied, so "
                           f"undoing would discard whatever changed it")
            else:
                blocked = ""

            out.append(Mutation(index=i, summary=applied.summary,
                                files=applied.touched(), notes=applied.notes,
                                blocked=blocked))
        return out

    # -- changing things ----------------------------------------------------- #
    def preview(self, action: Action) -> Preview:
        """Build the edits without writing them. Raises ActionError if the action
        can't be built at all — which is a clean no-op, not a partial failure."""
        return Preview(action, action.run(self.root))

    def apply(self, preview: Preview) -> Applied:
        """Write the previewed edits, then bring the linter back in step.

        Applies exactly the edits that were shown. `apply_edits` refuses any whose
        file has changed since they were computed, so a stale preview raises
        rather than quietly discarding somebody else's work.
        """
        changed = [e for e in preview.edits if e.changed and (e.new_text or e.binary)]
        if not changed:
            raise SessionError(f"{preview.summary}: nothing to change")

        applied = Applied(preview.summary, [e.path for e in changed],
                          notes=list(preview.notes),
                          select=preview.action.selects())
        for e in changed:
            path = self.root / e.path
            applied.undo_to[e.path] = _read(path, e.binary)
            applied.wrote[e.path] = e.data if e.binary else e.new_text  # type: ignore[assignment]

        try:
            apply_edits(self.root, changed, dry_run=False)
        except StaleEdit as exc:
            raise SessionError(str(exc)) from exc

        self._invalidate(applied.paths)
        self.history.append(applied)
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

        Undone **whole or not at all**. Every file the mutation wrote is checked
        against exactly what we wrote there, and the checking finishes before any
        restoring begins — so a mutation that wrote `A.asm` and `B.asm`, with
        `B.asm` since edited by hand, leaves `A.asm` alone too. One file that
        moved guards the whole change. There is no half-undo, because half a
        paired warp is worse than either warp.

        A mutation a *later* one has written over is refused for a different
        reason and :meth:`mutations` explains it: restoring this one's text would
        wipe out the later one, so the later one has to go first.
        """
        found = next((m for m in self.mutations() if m.index == index), None)
        if found is None:
            raise SessionError("no such change")
        if found.blocked:
            raise SessionError(f"{found.summary}: {found.blocked}. Left alone.")

        applied = self.history[index]
        for rel, before in applied.undo_to.items():
            path = self.root / rel
            if before is None:
                path.unlink(missing_ok=True)
            elif isinstance(before, bytes):
                path.write_bytes(before)
            else:
                path.write_text(before)

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

    def reload(self) -> None:
        """Forget everything and read the repo again.

        `_invalidate` drops the caches for the files *we* wrote, which is right
        and fast — but it can only know about our own writes. The repo is not
        ours alone: you add a trainer class in an editor, pull a branch, run
        `prism-mapfit`, and the studio goes on offering the autocomplete it read
        at startup. There is no way to notice that cheaply (watching every `.asm`
        in the tree for a change is a lot of machinery to keep one dropdown
        honest), so this is the key you press when you know you changed something.

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


def _read(path: Path, binary: bool) -> str | bytes | None:
    """What is in a file, in the units the edit that wrote it speaks. None if it
    isn't there — which is a state undo has to be able to restore."""
    if not path.exists():
        return None
    return path.read_bytes() if binary else path.read_text()
