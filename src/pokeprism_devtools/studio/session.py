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

from collections.abc import Callable, Mapping
from pathlib import Path

from ..contract import Diagnostic, Severity
from ..hacks.mount import mount
from ..contract import PlayError, Refused
from ..shared import caches, world
from ..shared.edits import StaleEdit, apply_edits
from .. import contract
from . import prefs, reader, undo
from ..contract import Action
# The shapes of the answers — see `model.py`. Re-exported, because whatever wants
# a `MapData` wants it *from the session*: the session is the only thing that can
# hand it one, and the split between the two files is a size, not a boundary.
from .model import (Applied, Draft, Finding, MapData, MapGeometry, MapRef,
                    Measured, Mutation, Preview, TextPreview, TextRef)  # noqa: F401

__all__ = ["Applied", "Draft", "Finding", "MapData", "MapGeometry", "MapRef",
           "Measured", "Mutation", "Preview", "Session", "SessionError",
           "StaleWorld", "TextPreview", "TextRef"]


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


class Session:
    """One repo, open for editing."""

    def __init__(self, root: Path, hack_path: Path | None = None, *,
                 build_env: Mapping[str, str] | None = None) -> None:
        # The seam's own gate, not just the CLI's: a headless caller that points
        # a Session at a tree no adapter recognises gets an error naming the
        # tree, rather than a session that swears the repo has no maps in it.
        # `mount` is also where every question about *which hack this is* stops:
        # from here down, the session reads through `self.hack.reads` and
        # branches only on the capabilities the mount declared.
        self._hack_path = hack_path  # a `--hack-path` adapter, re-used on re-read
        self.hack = mount(root, hack_path)
        self.root = root
        # A toolchain override for `build`, or None to take the play adapter's own
        # default. The session never learns what a toolchain is — it only carries
        # the user's word from above the seam to the adapter that resolves it. Set
        # this when the machine's `rgbds` is not the one the tree assumes.
        self._build_env = build_env
        # The linter's context, for the hack the linter is written against.
        # None means "this tree has no linter", and every lint answer is [].
        self.ctx = self.hack.ctx
        self.history: list[Applied] = []
        self._found: list[Diagnostic] | None = None
        # The repo as it was when we read it. Everything this object believes was
        # derived from exactly these bytes — see :mod:`..shared.world`.
        self.world = world.World.stamp(root)

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

    # -- what this tree can do ------------------------------------------------ #
    def _writable(self) -> None:
        """The gate in front of everything that changes the repo, or reasons
        about changing it. Not a hack-name check: the mount declared what this
        tree can do, and "no" comes with the reason."""
        if self.hack.writes is None:
            raise SessionError(
                f"this {self.hack.name} tree is mounted read-only — the studio "
                "can look at it, not write it. Nothing about it declares a "
                "write adapter.")

    def _playable(self) -> None:
        if self.hack.plays is None:
            raise SessionError(
                f"this {self.hack.name} tree has no build-and-boot wiring — "
                "the studio can show its maps, not play them.")

    @property
    def plays(self) -> bool:
        """Whether build-and-boot is wired for this tree. The footer's `b` and
        the build screen ask before offering: a read-only family tree has no
        game to stand in, so the key is absent, not disabled."""
        return self.hack.plays is not None

    def build_targets(self) -> tuple[str, ...]:
        """The build targets the screen offers, the default first — the play
        adapter's own list. The studio shows them and hands one back; it never
        learns what a target means."""
        self._playable()
        return self.hack.plays.targets()

    def recall_build_target(self) -> str:
        """The target this tree last built with, or `""` if it has built none.

        Kept apart from :meth:`build_targets` on purpose. That list is what the
        adapter says *exists*; this is what you said you *wanted*, and the two
        are allowed to disagree — the target box is free text (see
        `studio/combo.py`), so a `make` target the adapter never enumerates is a
        target you can type, and having typed it once is the whole reason to
        remember it. Nothing here checks it against the list for the same
        reason: a target that has left the tree is refused by `make`, loudly,
        naming itself, which is a better sentence than any we could write.
        """
        return prefs.read_prefs(self.root).get(prefs.BUILD_TARGET, "")

    def remember_build_target(self, target: str) -> None:
        """Prefill this target next time the build screen opens on this tree.

        Called after a build that *worked*, not when the button is pressed:
        remembering is a small claim that this answer is a good one, and a
        prefilled field is trusted rather than re-read. A typo remembered is a
        typo you meet again at the start of every session; a target remembered
        only once it has actually built is one the field can be believed about.

        Raises `SessionError` if the tree will not take the file — the caller
        has the build log to say it in. Failing to remember is not a failed
        build, and must never be reported as one.
        """
        try:
            prefs.save_pref(self.root, prefs.BUILD_TARGET, target)
        except OSError as e:
            raise SessionError(
                f"built, but could not remember the target in "
                f"{prefs.PREFS}: {e}") from e

    def keeps_build_line(self, line: str) -> bool:
        """Whether a *quiet* build still shows this line of `make` output — the
        play adapter's grep, since which chatter is noise is the engine's to
        know."""
        self._playable()
        return self.hack.plays.keeps(line)

    @property
    def lints(self) -> bool:
        """Whether any linter reads this tree. The panes ask before drawing:
        a tree with no linter has *no findings to look for*, which is a
        different sentence from "clean", and the pane must say the true one."""
        return self.ctx is not None

    @property
    def measures(self) -> bool:
        """Whether this tree can say how wide a line draws. The dialogue
        gutter asks before measuring: on a tree with no text metrics the
        gutter is absent, not wrong."""
        return self.hack.measures

    # -- maps ---------------------------------------------------------------- #
    @property
    def maps(self) -> list[MapRef]:
        """Every wired map, by label. Includes the few that don't parse — they
        still have a grid and a name, and hiding them is how you fail to notice
        that a map is broken."""
        return sorted(
            (MapRef(const, label) for label, const in self.hack.reads.maps().items()),
            key=lambda m: m.label,
        )

    def const_of(self, label: str) -> str:
        """The map id a label names — the adapter's catalog, for the callers
        (the view among them) that only hold the label."""
        return self.hack.reads.maps().get(label, label)

    def parses(self, const: str) -> bool:
        return self.hack.reads.parses(const)

    def load(self, label: str) -> MapData:
        """Everything about one map, from source — see :mod:`.reader`.

        Slow enough to want a thread (five files), so it takes no locks and
        touches no state.
        """
        return reader.read_map(self.hack.reads, label)

    def sketch(self, action: Action) -> MapGeometry | None:
        """A picture of what an action would put on the grid, before it exists —
        see :func:`.reader.sketch`. Not gated on :meth:`_fresh`: the form calls this
        on every keystroke, and it draws rather than writes."""
        self._writable()
        return reader.sketch(self.hack.reads, action)

    # -- what a form may offer ------------------------------------------------ #
    def choices(self, kind: str, values: dict[str, str] | None = None) -> list[str]:
        """The constants a field of this kind will accept — the write adapter's
        enumeration of its own repo.

        `values` is the form as it stands, because some lists depend on another
        field: which parties exist depends entirely on which class you picked.
        """
        self._writable()
        return self.hack.writes.choices(kind, self._map_consts, values)

    def follows(self, action: type[Action], changed: str,
                values: dict[str, str]) -> dict[str, str]:
        """What the form should fill in for itself, now one field has changed — a
        trainer class knows what it usually wears."""
        self._writable()
        return self.hack.writes.follows(action, changed, values)

    def form(self, name: str) -> type[Action] | None:
        """The app-level forms — the ones not reached by pointing at a row:
        "newmap" is `a`, "resize" is `s`, "reword" is picking a text under `t`.
        None when this tree's write adapter doesn't write one, or there is no
        write adapter at all — either way the view renders the key's absence."""
        return self.hack.writes.form(name) if self.hack.writes else None

    def sprite_hint(self, map_const: str, sprite: str) -> str:
        """The sprite field's hint line: who plays this sprite, and whether
        they can walk here. Measured from the repo by the write adapter — see
        `hacks/prism/write.Writer.sprite_hint` for how prism counts it. "" on
        a tree whose adapter has nothing to say, which renders as no hint."""
        sprite = sprite.strip()
        if not sprite or self.hack.writes is None:
            return ""
        return self.hack.writes.sprite_hint(map_const, sprite)

    def warm(self) -> None:
        """Read everything a form will want, before a form asks. A tree with no
        forms has nothing worth warming."""
        if self.hack.writes is not None:
            self.hack.writes.warm()

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
        one means the view asks which — an object is six different things wearing
        the same coat, and until they share one form the honest thing is to ask.

        Empty on a read-only mount: the dim row draws, and offers nothing.
        """
        if self.hack.writes is None:
            return ()
        return self.hack.writes.adders(kind)

    def deletion(self, label: str, const: str, ref: contract.Ref) -> Action:
        """The action `d` would run on this row — the write adapter's answer.

        Raises :class:`SessionError` for the things that cannot be deleted, and
        says *why* — which beats an absent key, because the reason is the
        interesting part.
        """
        self._writable()
        try:
            return self.hack.writes.deletion(label, const, ref)
        except Refused as exc:
            raise SessionError(str(exc)) from exc

    def editor(self, label: str, const: str,
               ref: contract.Ref) -> tuple[type[Action], dict[str, str], dict[str, str]]:
        """The form `e` would open on this row, filled in with what is there.

        The mirror of :meth:`deletion`, and like it, it refuses by *explaining* —
        an absent key tells you nothing, and the reason is the interesting part.
        """
        self._writable()
        # A map's header lives in files of the adapter's own choosing, and a
        # couple of maps have one without having a script file at all — so the
        # words are read only for a row that could have any.
        said = [] if ref.what == "map" else self.texts(label)
        try:
            return self.hack.writes.editor(label, const, ref, said)
        except Refused as exc:
            raise SessionError(str(exc)) from exc

    # -- the words ------------------------------------------------------------ #
    def texts(self, label: str) -> list[TextRef]:
        """Every text block in one map, as prose — the adapter's reading of its
        own text macros."""
        return self.hack.reads.texts(label)

    def measure(self, text: str, box: str = "speech") -> TextPreview:
        """Dialogue-in-progress against the box it lands in, in *tiles*.

        Tiles are engine physics — a charmap, control-code expansions, buffer
        tokens — so only a hack that declared the capability can answer, and what
        it declares is whether those are on disk to be read. Refused with the
        reason, not with silence.
        """
        if not self.hack.measures:
            raise SessionError(
                f"this {self.hack.name} tree declares no text metrics — "
                "nothing here can say how wide a line will draw.")
        return self.hack.reads.measure(text, box)

    # -- diagnostics --------------------------------------------------------- #
    def lint(self) -> list[Diagnostic]:
        """Every finding in the repo. Cached until something is written.

        Deliberately the whole repo, not the selected map: `only=` filters the
        output rather than scoping the work, and a warm pass is 64ms anyway.
        Linting everything also means a change here shows up in the map it breaks
        *over there* — which is the entire reason a cross-file linter exists.

        A tree with no linter (no `ctx`) has no findings, and that is an
        answer, not an error: the Diagnostics pane renders the absence.
        """
        if self.ctx is None:
            return []
        if self._found is None:
            self._found = self.ctx.lint()
        return self._found

    def diagnostics(self, const: str) -> list[Diagnostic]:
        """The findings *about* one map — those in its file, plus those in the
        shared second_map_headers.asm that name it, since a map's connections
        live there rather than in the map."""
        return [d for d in self.lint() if self.ctx.mentions(d, const)]

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
        known = d.path.startswith("maps/") and stem in self.hack.reads.maps()
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
        self._writable()
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
        self._writable()
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
    def build(self, log: Callable[[str], None], *,
              target: str | None = None, jobs: int | None = None) -> bool:
        """`make` the target, streamed a line at a time. True if it built. No
        default target here: `None` means the play adapter's own default, so the
        session names no `make` target of its own. The toolchain env is likewise
        the adapter's default unless the session was given one to pass down."""
        self._playable()
        try:
            return self.hack.plays.build(log, target=target, jobs=jobs,
                                         env=self._build_env)
        except PlayError as e:
            raise SessionError(str(e)) from e

    def boot(self, const: str, y: int, x: int, *,
             target: str | None = None, keep_people: bool = False) -> list[str]:
        """Stand at (y, x) on this map, in the game, now — through the play
        adapter, which is where the target and the save format are argued and
        where the emulator lives. The session hands the map and the tile down
        and shows what comes back."""
        self._playable()
        try:
            return self.hack.plays.boot(const, y, x,
                                        target=target, keep_people=keep_people)
        except PlayError as e:
            raise SessionError(str(e)) from e

    # -- keeping the linter honest -------------------------------------------- #
    def _invalidate(self, paths: list[str]) -> None:
        if self.ctx is not None:
            self.ctx.invalidate(paths)
        self._found = None
        # A new map is a new entry in every list of maps, and a new NPC's flag is
        # a new entry in the list the forms offer.
        if self.hack.writes is not None:
            self.hack.writes.forget()
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
        # Mounted afresh: the adapter's own state (the linter's context among
        # it) was derived from the old tree, and a re-read is a re-mount —
        # through the same `--hack-path` override the session opened with.
        self.hack = mount(self.root, self._hack_path)
        self.ctx = self.hack.ctx
        self._found = None
        # The stamp is taken now and the repo is re-read lazily, on the next
        # question anybody asks. So the stamp is always *older* than the reads it
        # vouches for, and a file that changes in the gap is reported as drift
        # again rather than missed. Erring that way round is the whole point.
        self.world = world.World.stamp(self.root)
