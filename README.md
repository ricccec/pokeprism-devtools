# tools/

Python 3 devtools for working on pokeprism. See
[`../docs/devtools-plan.md`](../docs/devtools-plan.md) for the full plan and
roadmap, and [`../docs/debug-mode.md`](../docs/debug-mode.md) for the
in-codebase debug features that complement these tools.

## Layout

- `_lib/` — shared parsers (sym file, constants files, save file). Don't
  invoke directly; tools import from it.
- `test_lib.py` — smoke test for `_lib/`. Run with
  `python3 tools/test_lib.py` after a build to confirm parsing still works.

Tool subdirectories will land here as they're built. Current status: scaffold
only.

## Setup

Python 3.10+ is required. No external dependencies yet — `_lib/` is stdlib
only. Future tools may add `questionary` (for TUI menus) via
`tools/requirements.txt`.

The tools find the repo root automatically by walking up from cwd, so they
can be run from anywhere inside the repo.
