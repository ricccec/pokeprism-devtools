"""One mounted tree: its adapter, and what it declared it can do.

The root of the contract, and the only place the optional capabilities are
listed together. Everything above the seam speaks to whatever the mount hands
back and branches on the *capabilities* declared here, never on the name —
this module is provably free of hack names, and that is meant to be checked
rather than believed: grep it for the name of any hack and the empty result is
the rule holding.
"""

from __future__ import annotations

from dataclasses import dataclass

from .lints import Lints
from .plays import Plays
from .reads import Reads
from .writes import Writes


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
