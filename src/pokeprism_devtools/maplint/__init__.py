"""prism-maplint — a cross-file validator for the things rgbasm can't catch.

Every rule here targets a mistake that **assembles cleanly and only goes wrong
at runtime**: a connection wired one way, a warp pointing at the wrong index in
its destination, an NPC using a sprite the map's group never loads, a count byte
that doesn't match the list under it. The build stays green and the bug shows up
as garbage graphics or a phantom NPC.

    prism-maplint                 # lint the whole repo
    prism-maplint CastroForest    # one map (label or CONST)
    prism-maplint --json          # machine-readable
    prism-maplint --baseline      # ignore known findings, fail only on new ones

Suppress a finding in source, where the reason for it is:

    warp_def 2, 2, 9, CAVE_C   ; maplint: ignore[warp-target]
    ; maplint: ignore-file[text-width]    <- anywhere in the file

The inline form takes the offending line or the one above it (the one above is
what you need when the line has no room for a comment). The file form is for a
file that is the exception outright — PhanceroRoom's "Glitch City" text is
*meant* to spill out of the textbox, and saying so eleven times would still miss
the twelfth line somebody adds later.

Both name their codes: a rule you can switch off without saying which one stops
being a rule. To wave off findings wholesale instead, keep a `--baseline`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..shared.paths import RepoNotFound, repo_root
from . import (
    rules_content, rules_flags, rules_geometry, rules_objects, rules_sprites, rules_text,
)
from .context import LintContext
from .diagnostics import Diagnostic, Severity, apply_suppressions

BASELINE = ".devtools/maplint-baseline.json"

ALL_RULES = (*rules_geometry.ALL, *rules_objects.ALL, *rules_sprites.ALL,
             *rules_content.ALL, *rules_flags.ALL, *rules_text.ALL)

_COLOR = {Severity.ERROR: "\033[31m", Severity.WARNING: "\033[33m", Severity.INFO: "\033[36m"}
_RESET = "\033[0m"
_DIM = "\033[2m"


def run(ctx: LintContext, *, only: str | None = None) -> list[Diagnostic]:
    """Run every rule and return the findings, suppressions applied."""
    found: list[Diagnostic] = []
    for rule in ALL_RULES:
        found.extend(rule(ctx))

    files = {d.path: ctx.source_lines(d.path) for d in found}
    found = apply_suppressions(found, files)
    if only:
        found = [d for d in found if _mentions(d, ctx, only)]
    return sorted(found, key=lambda d: (d.path, d.line, d.code))


def _mentions(d: Diagnostic, ctx: LintContext, only: str) -> bool:
    """Findings 'about' one map: those in its file, plus those in the shared
    second_map_headers.asm that name it (connections live there, not in the map)."""
    const = only if only in ctx.map_defs else ctx.label_to_const.get(only, only)
    info = ctx.map_infos.get(const)
    if info and d.path == ctx.rel(info.path):
        return True
    return const in d.message


def _load_baseline(root: Path) -> set[tuple[str, str, str]]:
    path = root / BASELINE
    if not path.exists():
        return set()
    return {tuple(entry) for entry in json.loads(path.read_text())["findings"]}


def _write_baseline(root: Path, diagnostics: list[Diagnostic]) -> Path:
    path = root / BASELINE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "comment": "Known maplint findings. Regenerate with `prism-maplint "
                   "--write-baseline`; `--baseline` fails only on findings not listed here.",
        "findings": sorted(d.key() for d in diagnostics),
    }, indent=2) + "\n")
    return path


def _report(diagnostics: list[Diagnostic], *, color: bool) -> None:
    for d in diagnostics:
        tint, reset, dim = (_COLOR[d.severity], _RESET, _DIM) if color else ("", "", "")
        print(f"{d.location}: {tint}{d.severity.value}{reset}: {d.message} {dim}[{d.code}]{reset}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="prism-maplint", description=__doc__.split("\n")[0])
    p.add_argument("map", nargs="?", help="only report findings about this map (label or CONST)")
    p.add_argument("--root", type=Path, help="pokeprism repo root (default: search upward)")
    p.add_argument("--json", action="store_true", help="emit findings as JSON")
    p.add_argument("--baseline", action="store_true",
                   help=f"ignore findings recorded in {BASELINE}; fail only on new ones")
    p.add_argument("--write-baseline", action="store_true",
                   help=f"record the current findings to {BASELINE} and exit 0")
    p.add_argument("--severity", choices=[s.value for s in Severity], default="warning",
                   help="minimum severity that fails the run (default: warning)")
    args = p.parse_args(argv)

    try:
        root = args.root or repo_root()
    except RepoNotFound as e:
        print(f"prism-maplint: {e}", file=sys.stderr)
        return 2

    ctx = LintContext(root)
    found = run(ctx, only=args.map)

    if args.write_baseline:
        path = _write_baseline(root, found)
        print(f"wrote {len(found)} finding(s) to {path.relative_to(root)}")
        return 0

    new = found
    if args.baseline:
        known = _load_baseline(root)
        new = [d for d in found if d.key() not in known]

    if args.json:
        print(json.dumps([d.as_dict() for d in new], indent=2))
    else:
        _report(new, color=sys.stdout.isatty())
        counts = {s: sum(1 for d in new if d.severity is s) for s in Severity}
        summary = ", ".join(f"{counts[s]} {s.value}" for s in Severity if counts[s])
        suppressed = len(found) - len(new)
        tail = f" ({suppressed} known, baselined)" if suppressed else ""
        print(f"\n{summary or 'no findings'}{tail}")

    threshold = Severity(args.severity)
    return 1 if any(not d.severity < threshold for d in new) else 0


if __name__ == "__main__":
    sys.exit(main())
