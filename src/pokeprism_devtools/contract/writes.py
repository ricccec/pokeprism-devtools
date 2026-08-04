"""What a tree mounted for writing must answer, and how it says no.

Absence is for whole capabilities — `Hack.writes is None` mounts a tree
read-only and every form above the seam degrades to nothing. :class:`Refused`
is for one operation: the adapter has the method and will not do it *here*,
for the reason the message carries.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


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
