"""Build the ROM and stand in it — the one capability that leaves the tree.

Everything else in the contract reads and writes `.asm`. This runs a compiler
and a game, and what a `make` target is, what a save's bytes are and which
emulator comes up are all the adapter's. A tree with no play adapter has no
boot key, and that is the whole degradation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping


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


class PlayError(RuntimeError):
    """A play adapter's failure: nothing built, or the save could not be
    patched. Carries a message for a human, because every one of these is
    something you can do something about. Defined at the seam for the same
    reason as :class:`Refused` — it is the seam's word, caught by the session,
    not any one hack's — so the session need not import the adapter that raised
    it to know how to show it."""
