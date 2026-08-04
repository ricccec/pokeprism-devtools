"""A family linter that knows only text, and answers the seam's `Lints`.

This is the first thing that makes `Hack.ctx` non-`None` for a family tree. The
session lints through it exactly as it lints through prism's `LintContext` — it
calls `lint()`, `mentions()`, `source_lines()`, `invalidate()` and never learns
which rules sit behind them. Prism's runs every rule it has; this one runs the
two overflow rules and nothing else, and the session cannot tell the difference,
which is the whole point of the capability living on the context.

It is deliberately tree-agnostic below the width reader: the box, the dialogue
parse and the rules are the same for every family tree, so it is handed its
`Metrics` and its map catalog rather than reaching for either. `build` wires the
vanilla ones; a polished build will pass polished's n-gram `Metrics` and reuse
everything else here.
"""

from __future__ import annotations

from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from ....contract import Diagnostic
from ....contract.suppressions import apply_suppressions
from .. import box
from ..box import Box
from ..metrics import Metrics, engine_is_readable
from . import dialogue, rules

if TYPE_CHECKING:
    from . import dialogue as _dialogue


class FamilyLintContext:
    """One family tree, in the shape the text rules ask about.

    `labels` is const -> map label; `load_metrics` builds the tree's own width
    reader when first asked — deferred so mounting a tree whose engine files are
    mid-edit or absent does not fail; the linter degrades to silence instead.
    `engine_files` is the set of files the box, the charmap and the widths are
    read from; it is engine-specific data the caller declares, because the file
    the widths come from is exactly what forks — vanilla reads `home/text.asm`,
    polished reads its n-gram table — so the guard cannot name one tree's file.
    The text of each map is parsed lazily and cached, so linting the repo parses
    each file once and asking about one map does not pay for the rest.
    """

    def __init__(self, root: Path, load_metrics: Callable[[Path], Metrics],
                 labels: dict[str, str], engine_files: tuple[str, ...]) -> None:
        self.root = root
        self._load_metrics = load_metrics
        self._labels = labels
        self._engine_files = engine_files
        self._text: dict[str, list[_dialogue.Block]] = {}
        self._source: dict[str, list[str]] = {}
        self._rel: dict[Path, str] = {}

    @cached_property
    def metrics(self) -> Metrics:
        return self._load_metrics(self.root)

    # -- the lint capability ------------------------------------------------- #
    def lint(self) -> list[Diagnostic]:
        """Every overflow finding in the repo, suppressions applied.

        The family's own small `run`: it does not borrow `maplint.run`, which
        would run prism's whole rule set against a context that only knows text.
        The suppression pass and the finding type are the shared, hack-neutral
        channel; the rules are the family's. A tree missing any engine file —
        mid-edit, or a fixture that is only a few maps — cannot be measured, so
        the lint degrades to silence rather than crashing on the first
        `read_text`, the way the seam says an absent capability must."""
        if not engine_is_readable(self.root, self._engine_files):
            return []
        found: list[Diagnostic] = []
        for rule in rules.ALL:
            found.extend(rule(self))
        files = {d.path: self.source_lines(d.path) for d in found}
        found = apply_suppressions(found, files)
        return sorted(found, key=lambda d: (d.path, d.line, d.code))

    def mentions(self, d: Diagnostic, only: str) -> bool:
        """Whether a finding is about one map. Every family text finding lands in
        that map's own file, so this is just: does the finding sit in it? — there
        is no shared cross-map file for overflow the way connections have one."""
        label = self._labels.get(only, only)
        return d.path == f"maps/{label}.asm"

    def source_lines(self, rel: str) -> list[str]:
        """One file's lines, by repo-relative path, cached — what a suppression
        comment is read from and what a finding's location points into."""
        if rel not in self._source:
            path = self.root / rel
            self._source[rel] = path.read_text().split("\n") if path.is_file() else []
        return self._source[rel]

    def invalidate(self, paths) -> None:
        """Forget what these files told us, so the next lint sees the tree as it
        now is. Repo-relative paths; called after an edit lands."""
        by_stem = {label: const for const, label in self._labels.items()}
        for rel in paths:
            self._source.pop(rel, None)
            if rel.startswith("maps/") and rel.endswith(".asm"):
                if const := by_stem.get(Path(rel).stem):
                    self._text.pop(const, None)

    # -- what the rules read -------------------------------------------------- #
    @property
    def box(self) -> Box:
        return box.speech_box(self.root)

    @cached_property
    def map_files(self) -> dict[str, Path]:
        """const -> map file, for every map whose asm exists on disk."""
        out: dict[str, Path] = {}
        for const, label in self._labels.items():
            path = self.root / "maps" / f"{label}.asm"
            if path.exists():
                out[const] = path
        return out

    def text_blocks(self, const: str) -> list[_dialogue.Block]:
        if const not in self._text:
            path = self.map_files.get(const)
            self._text[const] = dialogue.parse(self.root, path, self.metrics) if path else []
        return self._text[const]

    def rel(self, path: Path) -> str:
        if (cached := self._rel.get(path)) is None:
            cached = self._rel[path] = str(path.relative_to(self.root))
        return cached
