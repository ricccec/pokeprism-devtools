#!/usr/bin/env python3
"""A console script must say why it cannot work. It must never dump a stack.

Two ways a tree can be wrong, and the same invariant covers both:

  * **no tree** — run from somewhere with no `Makefile` beside a `main.asm` in
    any parent. `RepoNotFound` subclasses `RuntimeError`, so an
    `except FileNotFoundError` does not catch it.
  * **the wrong tree** — run inside a *valid* pret tree belonging to another
    hack. The root resolves, and a prism-only file is missing three frames
    later.

The second case is why the exit code is asserted only for the first. Product A
is hack-neutral by construction, so `prism-sym` and `prism-usage` **should**
work in a pokecrystal tree; prism's own tools should refuse it. Both satisfy
*no traceback*, which is the invariant — and asserting a shared exit code would
force one of the two groups to be wrong.

The check is strict about tracebacks and loose about wording: three scripts are
gated by argparse before they reach the lookup, and those that do reach it print
in three spellings (`prism-maps:`, `error:`, `Error:`). Demanding one wording
would fail on code that works. A traceback is the defect; the wording is taste.

**The script list is discovered, not written down**, so this file keeps working
after the products are carved: it asks the installed distributions which
`pokeprism_devtools` console scripts exist. In this tree that is twelve; in a
carved repo it is that repo's own.

    python tests/test_cli_refusals.py
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from importlib.metadata import entry_points
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

#: A real pret tree that is not prism's. Its absence skips that half rather
#: than failing it — the trees are a developer's checkout, not a fixture.
FOREIGN_TREE = Path.home() / "code/ricccec/pokecrystal"

#: The studio is a full-screen TUI: it takes the terminal rather than returning,
#: so it cannot answer this question in a subprocess. Named, not silently
#: skipped, so that the day it grows a non-interactive path somebody decides.
INTERACTIVE = {"prism-studio"}

#: Long enough that a slow import is not a failure, short enough that a CLI
#: which waits for input is.
TIMEOUT_SECONDS = 60

TRACEBACK = "Traceback (most recent call last)"

_failures = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global _failures
    ok = bool(cond)
    if not ok:
        _failures += 1
    print(f"  {'ok  ' if ok else 'FAIL'} {label}"
          f"{(': ' + detail) if detail and not ok else ''}")


def find_console_scripts() -> list[str]:
    """The installed `prism-*` scripts that live in this namespace."""
    return sorted(e.name for e in entry_points(group="console_scripts")
                  if e.value.startswith("pokeprism_devtools."))


def run_in(script: str, cwd: Path) -> tuple[int, str]:
    path = Path(sys.executable).parent / script
    try:
        done = subprocess.run(
            [str(path)], cwd=cwd, stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=TIMEOUT_SECONDS,
            env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"},
        )
    except subprocess.TimeoutExpired:
        return -1, f"no answer in {TIMEOUT_SECONDS}s"
    return done.returncode, done.stdout + done.stderr


def last_line(out: str) -> str:
    lines = out.strip().splitlines()
    return lines[-1][:110] if lines else ""


def test_outside_any_tree(tmp: Path) -> None:
    scripts = find_console_scripts()
    check("the installed scripts were discovered, not assumed",
          len(scripts) > 0, "no console_scripts in this namespace")
    for name in scripts:
        if name in INTERACTIVE:
            continue
        code, out = run_in(name, tmp)
        check(f"{name} does not traceback with no tree at all",
              TRACEBACK not in out, last_line(out))
        check(f"{name} fails rather than pretending it worked",
              code != 0, f"exit {code}")


def test_inside_another_hacks_tree() -> None:
    if not (FOREIGN_TREE / "main.asm").exists():
        print(f"  skip the wrong-tree half — no checkout at {FOREIGN_TREE}")
        return
    for name in find_console_scripts():
        if name in INTERACTIVE:
            continue
        _, out = run_in(name, FOREIGN_TREE)
        check(f"{name} does not traceback inside a foreign pret tree",
              TRACEBACK not in out, last_line(out))


def test_the_check_can_fail(tmp: Path) -> None:
    """A check that cannot fail is not checking.

    `find_repo_root()` raises from a directory with no tree above it, and
    prism's reader raises inside a tree that is not prism's. Both are the
    traceback this file exists to detect; if either stops producing one, the
    detector is looking for the wrong string.
    """
    def traceback_from(code: str, cwd: Path) -> str:
        return subprocess.run([sys.executable, "-c", code], cwd=cwd,
                              capture_output=True, text=True,
                              timeout=TIMEOUT_SECONDS).stderr

    err = traceback_from(
        "from pokeprism_devtools.shared import paths; paths.find_repo_root()", tmp)
    check("an unguarded find_repo_root() tracebacks, so the detector works",
          TRACEBACK in err and "RepoNotFound" in err, err.strip()[-110:])

    if (FOREIGN_TREE / "main.asm").exists():
        err = traceback_from(
            "from pathlib import Path\n"
            "from pokeprism_devtools.hacks.prism import maps\n"
            f"maps.parse_maps(Path({str(FOREIGN_TREE)!r})"
            " / 'constants/map_dimension_constants.asm')", FOREIGN_TREE)
        check("an unguarded prism read in a foreign tree tracebacks too",
              TRACEBACK in err, err.strip()[-110:])


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d).resolve()
        print(f"no tree at all: {tmp}")
        test_the_check_can_fail(tmp)
        test_outside_any_tree(tmp)
        print(f"\na valid pret tree that is not prism's: {FOREIGN_TREE}")
        test_inside_another_hacks_tree()
    print(f"\n{'FAILURES: ' + str(_failures) if _failures else 'all ok'}")
    sys.exit(1 if _failures else 0)
