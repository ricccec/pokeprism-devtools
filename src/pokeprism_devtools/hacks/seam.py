"""What a hack must answer to be mounted. **The contract, and nothing else.**

This module is provably free of hack names — that is the point of it being a
separate file, and it is meant to be checked rather than believed: grep this
file for the name of any hack in `hacks/` and the empty result is the rule
holding. `mount.py` is the module allowed to know those names; this one is not.
Everything above the seam — the session, the reader, the view — speaks to
whatever :func:`mount.mount` hands back and branches only on the *capabilities*
declared here, never on the name; everything below it lives in a
`hacks/<name>/` package and knows only its own dialect. `docs/adapter-plan.md`
argues the line.

The adapters answer in the seam's records (see `studio/panels`); what they must
answer is :class:`Reads` and :class:`Writes` below, and *why* each answer is
shaped that way is the prose on each method. The protocols are structural, so
nothing inherits them and no adapter imports this module for its own sake —
they describe the surface three independently written adapters already present,
and exist so that a fourth one is told what it owes before it is mounted rather
than after.

A capability the adapter does not declare degrades to *absence* above the
seam: no Diagnostics findings, no edit forms, no boot key — never a crash, and
never an `if <hack name>`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:  # annotations are lazy, so a probe pays for no studio import
    from collections.abc import Callable, Mapping

    from ..maplint.diagnostics import Diagnostic
    from ..studio import panels


@runtime_checkable
class Reads(Protocol):
    """What the studio may ask any mounted tree. Nine questions, no options.

    `runtime_checkable` buys presence, not signatures — `isinstance` here says
    "has these names", which is the cheap half. The other half is
    `tests/test_seam.py`, which checks the shapes against every adapter at once.
    """

    def maps(self) -> dict[str, str]:
        """The catalog: file label -> map constant. Everything else in this
        protocol is keyed by one or the other, and this is the only method that
        says which names exist at all."""

    def parses(self, const: str) -> bool:
        """Whether this map's events can be read, asked *without* reading them.
        The catalog is drawn before any map is opened, so this has to be cheap
        and it has to be total — a map that will fail is listed, and marked."""

    def connections(self, const: str) -> list[panels.Link]:
        """The maps this one borders, one Link each."""

    def tables(self, label: str) -> panels.MapTables:
        """The six event lists. Raises `panels.Unreadable` — with the reason —
        rather than returning empty ones, because empty tables read as "this map
        has nothing on it", which is a different and much worse claim."""

    def attributes(self, label: str, const: str) -> panels.Attributes:
        """The header facts. Takes *both* names because in every tree so far
        they live in different files under different keys."""

    def geometry(self, label: str) -> panels.Blocks:
        """The blocks, for drawing. Raises `panels.Unreadable`. Independent of
        `tables` on purpose: a map whose events don't parse still has a shape,
        and hiding it from the person looking for the break helps nobody."""

    def wild(self, const: str) -> dict[str, dict[str, list[panels.WildMon]]]:
        """Encounters, by table then by time of day. Empty when the map has
        none — unlike `tables`, absence here is a fact, not a failure."""

    def roof(self, const: str) -> panels.Roof | None:
        """The roof palette, or None where the tree has no such concept."""

    def texts(self, label: str) -> list[panels.TextRef]:
        """Every string in the map's file, in source order."""


@runtime_checkable
class Measures(Protocol):
    """`measures=True` only. Text measured in tiles is engine physics — a
    charmap, control-code expansions, buffer tokens — so a tree the studio cannot
    read those out of cannot answer, and the session refuses with that sentence
    rather than guessing in characters. Tiles, not pixels: what a proportional
    font would need is a per-glyph width, and the trees that have one keep it off
    the dialogue path."""

    def measure(self, text: str, box: str) -> panels.TextPreview: ...


@runtime_checkable
class Sketches(Protocol):
    """Reachable only from an action whose `sketches` is True. Draws what a form
    would create before it exists, which is how a `.blk` of the wrong size stops
    being an arithmetic complaint and becomes a map of the wrong shape."""

    def sketch(self, action) -> panels.Blocks | None: ...


@runtime_checkable
class Plays(Protocol):
    """`Hack.plays is not None` only. Build-and-boot wiring — the one capability
    that leaves the source tree: everything else in the studio reads and writes
    `.asm`, this runs a compiler and a game. What a `make` target is, what a
    save's bytes are, which emulator comes up: all of it is the adapter's, and
    the session drives it knowing none of it. A tree with no play adapter has no
    boot key, never a crash.

    The emulator is the *adapter's*, not the session's, and it is held across
    boots: booting a second map replaces the window you are already looking at
    instead of opening another behind it. That is why this is an object with
    state and not four free functions."""

    def targets(self) -> tuple[str, ...]:
        """The build targets to offer, the default first. The studio shows these
        and hands one back to :meth:`build`/:meth:`boot`; it never learns what
        distinguishes them — that a target is a debug build, say, is the
        adapter's knowledge, not the build screen's."""

    def keeps(self, line: str) -> bool:
        """Whether a line of build output is one a *quiet* build still shows —
        the errors worth stopping on, out of the thousands of lines of compiler
        chatter. The studio streams `make` output and asks this per line, so
        which lines are noise stays the engine's to know."""

    def build(self, log: Callable[[str], None], *,
              target: str | None = None, jobs: int | None = None,
              env: Mapping[str, str] | None = None) -> bool:
        """`make` the named target, streamed a line at a time through `log`.
        True if the ROM built. `target=None` means the adapter's default (its
        `targets()[0]`), so the session carries no default target of its own.

        `env` overrides the build's toolchain environment (an `rgbds` a family
        of trees shares in one place but two versions of, say). `None` means the
        adapter's own declared default — so a hack that pins nothing keeps
        pinning nothing and a caller that knows better can still say so, without
        the session having to learn what a toolchain is or which one this tree
        wants. The mapping is laid over the inherited environment for the build."""

    def boot(self, const: str, y: int, x: int, *,
             target: str | None = None, keep_people: bool = False) -> list[str]:
        """Patch a save to stand at (y, x) on this map, then open the game.
        Returns the changes worth showing. Raises :class:`PlayError` when
        nothing built or the save could not be patched — the session catches it
        and puts the sentence on screen. `target=None` is the adapter default."""


@runtime_checkable
class Lints(Protocol):
    """`Hack.ctx is not None` only. A tree's linter, running its *own* rules and
    answering the two questions the session asks around them — never told which
    rules a tree supports, because that is knowledge the context owns and the
    session must not. Prism's :class:`~..maplint.context.LintContext` satisfies
    this; a family context that knows only text satisfies it just as well, and
    the session cannot tell them apart."""

    def lint(self) -> list[Diagnostic]:
        """Every finding in the repo, suppressions applied — the whole rule set
        this context carries, run against the tree it describes."""

    def mentions(self, d: Diagnostic, only: str) -> bool:
        """Whether a finding is 'about' one map: in its file, or naming it from a
        shared file (connections live in one, not in the map)."""

    def source_lines(self, rel: str) -> list[str]:
        """One file's lines, by repo-relative path — what a finding's location
        points into, for the view that shows the offending line."""

    def invalidate(self, paths) -> None:
        """Forget what these files told us, so the next lint sees the tree as it
        now is. The session calls this after every edit it writes: a cached
        finding you just fixed must stop being reported, and one you just broke
        must start. Repo-relative paths."""


@runtime_checkable
class Writes(Protocol):
    """What a tree mounted for writing must answer. `None` in place of one of
    these is not how a write adapter says no — :class:`Refused` is, with the
    reason. Absence is for whole capabilities; a refusal is for one operation.
    """

    def adders(self, kind: str) -> tuple:
        """The Action subclasses behind a tab's "Add new…" row. `()` where this
        tree has no writer for that kind yet — which is how a half-built adapter
        shows up as a missing row instead of a traceback."""

    def form(self, name: str):
        """The Action behind a named top-level form ("newmap", "resize",
        "reword"), or None where this tree has none."""

    def editor(self, label: str, const: str, ref,
               said: list) -> tuple[type, dict[str, str], dict[str, str]]:
        """What Enter opens on an existing row: the Action, the values to
        prefill it with, and the text boxes it owns."""

    def deletion(self, label: str, const: str, ref):
        """The Action `d` would run on this row."""

    def choices(self, kind: str, map_consts: tuple[str, ...],
                values: dict[str, str] | None = None) -> list[str]:
        """The constants a field will accept, enumerated from this repo. Takes
        the form as it stands, because some lists depend on another field."""

    def follows(self, action, changed: str,
                values: dict[str, str]) -> dict[str, str]:
        """What the form fills in for itself now one field has changed."""

    def sprite_hint(self, map_const: str, sprite: str) -> str:
        """One line about a chosen sprite — usually what it costs."""

    def warm(self) -> None:
        """Build the constants caches, off the UI thread."""

    def forget(self) -> None:
        """Drop them, because something was written."""


class Refused(RuntimeError):
    """A write adapter's "no": the operation exists in the protocol and this
    adapter will not do it here, for the reason the message gives. Defined at
    the seam because it is the seam's word, not any one hack's — the session
    catches it and puts the sentence on screen, whichever adapter said it."""


class PlayError(RuntimeError):
    """A play adapter's failure: nothing built, or the save could not be
    patched. Carries a message for a human, because every one of these is
    something you can do something about. Defined at the seam for the same
    reason as :class:`Refused` — it is the seam's word, caught by the session,
    not any one hack's — so the session need not import the adapter that raised
    it to know how to show it."""


@dataclass(frozen=True)
class Hack:
    """One mounted tree: its adapter, and what it declared it can do."""
    name: str
    #: The read adapter: :class:`Reads`, plus :class:`Measures` when `measures`
    #: is set and :class:`Sketches` when a form of this tree draws one.
    reads: Reads
    #: The linter's context, for the hack the linter is written against. The
    #: session lints exactly when this is not None, and hands it back to
    #: everything that asks repo-wide questions. A :class:`Lints`: it runs its
    #: own rules, so the session never learns which rules a tree supports.
    ctx: Lints | None = None
    #: The write adapter — the studio's actions, forms and undo apply to this
    #: tree through it. None mounts the tree read-only, and everything above
    #: the seam that would change the repo degrades to absence.
    writes: Writes | None = None
    #: Build-and-boot wiring — run the compiler, patch a save, open the game.
    #: A :class:`Plays`, holding its own emulator across boots. None mounts the
    #: tree unplayable, and the studio's boot key degrades to absence.
    plays: Plays | None = None
    #: Text is measured in tiles against the engine's own charmap and widths,
    #: rather than guessed at in characters. Adapters read this off the tree
    #: rather than hardcoding it: the charmap and the widths *are* the
    #: measurement, so a checkout that is missing them declares False and the
    #: gutter is absent instead of wrong.
    measures: bool = False
