#!/usr/bin/env python3
"""Prove a package split moved code without changing it.

The refactor's tests cannot certify these moves: measured by line, the packages
being split run 0-54% of themselves, and the uncovered majority is the render
and CLI half a split relocates wholesale (docs/refactor-phase-1-STATE.md). So a
move is proved textually instead.

    python scripts/surface-snapshot.py map_inspect > /tmp/before.txt
    ...split...
    python scripts/surface-snapshot.py map_inspect > /tmp/after.txt
    diff /tmp/before.txt /tmp/after.txt

Two sections, because a split changes one and must not change the other.

CONTENT is every function, class and constant the package defines, anywhere in
it, with a digest of its source and no mention of which file holds it. Moving a
function between files does not touch this section; editing one does.

**What CONTENT is asked to prove depends on the commit**, and both phases ask
the same question — "did anything else change?" — expecting different answers:

- **A move** (Phase 1's package splits, and Phase 1b's step 9). CONTENT must not
  change *at all*. Anything that fails this was not a move.
- **An edit by intent** (Phase 1b's shortenings). CONTENT is expected to change,
  so the check is that the change is **confined**: the digests that differ must
  be exactly the functions the commit set out to change, plus the new names it
  extracted, and nothing else. A shrink that silently altered a neighbour shows
  up as an extra changed digest. A rename done right appears as one name leaving
  and one arriving with an *unchanged* digest; if the digest moved too, the
  rename was not just a rename.

SURFACE is what `import <package>` exposes. It is *expected* to shrink: an
`__init__.py` re-exports its own imports by accident, so `map_show` exposes nine
foreign modules and seven stdlib names that were never its API. **SURFACE may
only lose names, never gain or alter them.**

Digests are taken after `textwrap.dedent`, so a function that changes nesting
depth but not code still matches. Values are described with a stable repr —
plain `repr` is not stable, because a set's iteration order changes with the
interpreter's hash seed and a function's repr carries its address, both of which
occur in these packages and would report a diff on every run.
"""

from __future__ import annotations

import hashlib
import importlib
import inspect
import pkgutil
import sys
import textwrap
from pathlib import Path

PACKAGE_ROOT = "pokeprism_devtools"

#: Present in every module that uses `from __future__ import annotations`, and
#: not something the package defines.
_NOT_CONTENT = frozenset({"annotations"})

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def body_digest(obj) -> str:
    """A hash of the object's source, indentation-normalised. `no-source` when
    the source is unavailable — a C builtin, or a class built by a decorator."""
    try:
        source = inspect.getsource(obj)
    except (OSError, TypeError):
        return "no-source"
    return hashlib.sha256(textwrap.dedent(source).encode()).hexdigest()[:16]


def describe_value(obj) -> str:
    """A repr that is the same on every run."""
    if isinstance(obj, (set, frozenset)):
        return "{" + ", ".join(sorted(describe_value(v) for v in obj)) + "}"
    if isinstance(obj, dict):
        return "{" + ", ".join(
            f"{k!r}: {describe_value(v)}" for k, v in sorted(obj.items(), key=repr)
        ) + "}"
    if isinstance(obj, (list, tuple)):
        body = ", ".join(describe_value(v) for v in obj)
        return f"[{body}]" if isinstance(obj, list) else f"({body})"
    if callable(obj):
        return body_digest(obj)
    return repr(obj)


def is_defined_here(obj, module_name: str) -> bool:
    """Whether this module defines the object, rather than importing it.

    `__module__` is only consulted for functions and classes. Other objects may
    carry one that says where their *type* was written, not where the value was:
    a compiled regex reports `re`, which would drop every `_FOO_RE` constant in
    these packages out of CONTENT and hide an edit to one. A constant is instead
    credited to every module it appears in — harmless, because CONTENT is a
    deduplicated set and a re-exported constant has the same digest either way.
    """
    if inspect.ismodule(obj):
        return False
    if inspect.isfunction(obj) or inspect.isclass(obj):
        return getattr(obj, "__module__", None) == module_name
    return True


def describe(obj) -> str:
    if inspect.isfunction(obj) or inspect.isclass(obj):
        return body_digest(obj)
    return describe_value(obj)[:120]


def kind_of(obj) -> str:
    if inspect.isfunction(obj):
        return "def"
    if inspect.isclass(obj):
        return "class"
    return "value"


def package_modules(package) -> list:
    """The package's own modules, `__init__` first, then every submodule."""
    modules = [package]
    if hasattr(package, "__path__"):
        for info in sorted(pkgutil.iter_modules(package.__path__),
                           key=lambda i: i.name):
            modules.append(importlib.import_module(f"{package.__name__}.{info.name}"))
    return modules


def content_lines(package) -> list[str]:
    """Everything the package defines, without saying which file holds it."""
    seen = set()
    for module in package_modules(package):
        for name, obj in vars(module).items():
            if name.startswith("__") or name in _NOT_CONTENT:
                continue
            if not is_defined_here(obj, module.__name__):
                continue
            seen.add(f"{kind_of(obj):<8}{name:<34}{describe(obj)}")
    return sorted(seen)


def surface_lines(package) -> list[str]:
    """What `import <package>` exposes, and where each name comes from."""
    lines = []
    for name in sorted(vars(package)):
        if name.startswith("__") or name in _NOT_CONTENT:
            continue
        obj = getattr(package, name)
        if inspect.ismodule(obj):
            lines.append(f"{'module':<8}{name:<34}{obj.__name__}")
            continue
        own = is_defined_here(obj, package.__name__) or any(
            is_defined_here(obj, m.__name__) for m in package_modules(package))
        lines.append(f"{'own' if own else 'foreign':<8}{name:<34}{describe(obj)}")
    return lines


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    package = importlib.import_module(f"{PACKAGE_ROOT}.{args[0]}")
    print("=== CONTENT (must not change) ===")
    for line in content_lines(package):
        print(line)
    print("\n=== SURFACE (may only shrink) ===")
    for line in surface_lines(package):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
