"""Diagnostics: what a lint rule produces, and how findings are suppressed."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class Severity(Enum):
    ERROR = "error"      # the game is wrong at runtime — garbage GFX, phantom NPCs
    WARNING = "warning"  # probably a mistake, but could be deliberate
    INFO = "info"        # worth knowing; often intentional (one-way warps, …)

    def __lt__(self, other: "Severity") -> bool:
        order = [Severity.INFO, Severity.WARNING, Severity.ERROR]
        return order.index(self) < order.index(other)


@dataclass(frozen=True)
class Diagnostic:
    code: str            # stable, greppable: "conn-missing", "sprite-outdoor", …
    severity: Severity
    path: str            # repo-relative
    line: int            # 1-based; 0 when the finding isn't tied to a line
    message: str

    @property
    def location(self) -> str:
        return f"{self.path}:{self.line}" if self.line else self.path

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "severity": self.severity.value,
            "path": self.path,
            "line": self.line,
            "message": self.message,
        }

    def key(self) -> tuple[str, str, str]:
        """Identity for baselining. Deliberately excludes the line number so
        that editing a file above a finding doesn't resurrect it as 'new'."""
        return (self.code, self.path, self.message)


#: `; maplint: ignore[code1,code2]` — on the offending line, or the one above it.
_IGNORE_RE = re.compile(r";\s*maplint:\s*ignore\[([^\]]*)\]")


def suppressed_codes(line: str) -> set[str]:
    m = _IGNORE_RE.search(line)
    if not m:
        return set()
    return {c.strip() for c in m.group(1).split(",") if c.strip()}


def apply_suppressions(diagnostics: list[Diagnostic], files: dict[str, list[str]]) -> list[Diagnostic]:
    """Drop findings the source explicitly waves off.

    A finding is suppressed by an ``ignore`` comment on its own line or on the
    line directly above it — the line above is what you need when the offending
    line's syntax has no room for a comment.
    """
    kept = []
    for d in diagnostics:
        lines = files.get(d.path)
        if not lines or not d.line:
            kept.append(d)
            continue
        codes: set[str] = set()
        for idx in (d.line - 1, d.line - 2):     # own line, then the one above
            if 0 <= idx < len(lines):
                codes |= suppressed_codes(lines[idx])
        if d.code not in codes:
            kept.append(d)
    return kept
