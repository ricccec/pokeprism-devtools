"""The studio's model. No Textual in here — the TUI is a view over this.

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

import difflib
from dataclasses import dataclass, field
from pathlib import Path

from .. import maplint
from ..maplint.context import LintContext
from ..maplint.diagnostics import Diagnostic
from ..shared.edits import Edit, StaleEdit, apply_edits
from .actions import Action, Result


@dataclass(frozen=True)
class MapRef:
    const: str
    label: str

    def __str__(self) -> str:
        return self.label


@dataclass(frozen=True)
class Preview:
    """What an action *would* do. Nothing has been written.

    Holds the actual edits, so applying it writes exactly what was shown rather
    than re-deriving something that might differ.
    """
    action: Action
    result: Result

    @property
    def edits(self) -> list[Edit]:
        return self.result.edits

    @property
    def summary(self) -> str:
        return self.result.summary

    @property
    def notes(self) -> list[str]:
        return self.result.notes

    @property
    def touches(self) -> list[str]:
        return [e.path for e in self.edits]

    def diff(self, context: int = 3) -> str:
        """Unified diff of every file this touches."""
        out: list[str] = []
        for e in self.edits:
            before = (e.base or "").split("\n")
            after = e.new_text.split("\n")
            out.extend(difflib.unified_diff(
                before, after,
                fromfile=f"a/{e.path}", tofile=f"b/{e.path}",
                lineterm="", n=context,
            ))
        return "\n".join(out)


@dataclass
class Applied:
    """An action that landed, and everything needed to take it back."""
    summary: str
    paths: list[str]
    #: path -> the text that was there before. None means the file did not exist,
    #: so undoing means deleting it again.
    undo_to: dict[str, str | None] = field(default_factory=dict)
    #: path -> what we wrote. Undo refuses if the file no longer matches this.
    wrote: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


class SessionError(RuntimeError):
    pass


class Session:
    """One repo, open for editing."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.ctx = LintContext(root)
        self.history: list[Applied] = []
        self._found: list[Diagnostic] | None = None

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
        changed = [e for e in preview.edits if e.changed and e.new_text]
        if not changed:
            raise SessionError(f"{preview.summary}: nothing to change")

        applied = Applied(preview.summary, [e.path for e in changed],
                          notes=list(preview.notes))
        for e in changed:
            path = self.root / e.path
            applied.undo_to[e.path] = path.read_text() if path.exists() else None
            applied.wrote[e.path] = e.new_text

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
        """Put back what the last action replaced.

        Refuses if any file it would restore no longer holds what we wrote. That
        means somebody edited it in the meantime — in their editor, in another
        tool — and restoring our idea of "before" would throw their work away.
        """
        if not self.history:
            raise SessionError("nothing to undo")
        last = self.history[-1]

        for rel, written in last.wrote.items():
            path = self.root / rel
            current = path.read_text() if path.exists() else None
            if current != written:
                raise SessionError(
                    f"{rel} has changed since '{last.summary}' was applied, so "
                    f"undoing it would discard whatever changed it. Left alone."
                )

        for rel, before in last.undo_to.items():
            path = self.root / rel
            if before is None:
                path.unlink(missing_ok=True)
            else:
                path.write_text(before)

        self.history.pop()
        self._invalidate(last.paths)
        return last

    # -- keeping the linter honest -------------------------------------------- #
    def _invalidate(self, paths: list[str]) -> None:
        self.ctx.invalidate(paths)
        self._found = None
