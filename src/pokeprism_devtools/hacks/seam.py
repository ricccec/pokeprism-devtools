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
    """`measures=True` only. Text measured in tiles is engine physics — a VWF,
    a charmap, buffer tokens — so a tree without one cannot answer this, and
    the session refuses with that sentence rather than guessing in characters."""

    def measure(self, text: str, box: str) -> panels.TextPreview: ...


@runtime_checkable
class Sketches(Protocol):
    """Reachable only from an action whose `sketches` is True. Draws what a form
    would create before it exists, which is how a `.blk` of the wrong size stops
    being an arithmetic complaint and becomes a map of the wrong shape."""

    def sketch(self, action) -> panels.Blocks | None: ...


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
    #: Build-and-boot (a patched save, an emulator) is wired for this tree.
    plays: bool = False
    #: Text is measured in tiles against the engine's own VWF and charmap,
    #: rather than guessed at in characters.
    measures: bool = False
