"""What a lint rule produces.

In the contract because the `Lints` capability answers in these and adapters
build them: the family linter writes its own findings, prism's writes its own,
and the panel that shows them can tell the two apart only by reading the `code`.
How a finding is *suppressed* is not here — that is a reading of source comments,
and it belongs with the linter that does the reading.
"""

from __future__ import annotations

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
