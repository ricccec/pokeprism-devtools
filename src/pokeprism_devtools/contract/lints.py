"""A tree's own linter, and the two questions the session asks around it.

The session is never told which rules a tree supports: that is knowledge the
context owns. Prism's runs a full rule set; a family context that knows only
text satisfies this just as well, and nothing above the seam can tell them
apart.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .diagnostic import Diagnostic


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
