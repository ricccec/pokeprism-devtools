# tools/

Python 3 devtools for working on pokeprism. See
[`../docs/devtools.md`](../docs/devtools.md) for the user-facing reference,
[`../docs/devtools-plan.md`](../docs/devtools-plan.md) for the plan/roadmap,
and [`../docs/debug-mode.md`](../docs/debug-mode.md) for the in-codebase
debug features (in-game debug menus + the `DEBUG_MODE` build flag).

## Layout

```
tools/
├── README.md
├── requirements.txt        — Python deps (questionary, for the start-state TUI)
├── test_lib.py             — smoke test for _lib/
├── _lib/                   — shared parsers / helpers (imported, not run)
│   ├── paths.py            — find repo root, ROM, .sym, .map, .sav
│   ├── symfile.py          — parse RGBDS .sym files
│   ├── constants.py        — parse constants/*.asm enums
│   ├── maps.py             — parse map_dimension_constants.asm
│   ├── savefile.py         — SaveFile I/O + checksum + GB charset encoder
│   ├── lz.py               — LZ decompressor (port of home/decompress.asm)
│   ├── blockdata.py        — read map blockdata from ROM, compute wScreenSave
│   └── people.py           — reset player struct + clear NPC slots
├── sym-lookup/             — query the .sym by label or address
│   └── sym-lookup.py
└── start-state/            — launch the game in an arbitrary state
    ├── start-state.py      — CLI entrypoint
    ├── tui.py              — questionary-driven dev-server menu
    ├── inventory.py        — build/refresh the .sym → .sav offset catalog
    ├── apply.py            — mutate a .sav from a state.json
    ├── launcher.py         — locate SameBoy (Spotlight / $SAMEBOY_BIN), launch + focus
    ├── test_maps.py        — sweep every map through apply (regression check)
    ├── presets/            — example state.json files (checked in)
    │   └── default.json
    ├── inventory.json      — generated, gitignored
    ├── state.json          — user's working state, gitignored
    └── sav-backups/        — auto-backups before .sav overwrite, gitignored
```

## Setup

Python 3.10+. The shared `_lib/` is stdlib-only. The `start-state` TUI
needs one external package, `questionary`, pinned in `requirements.txt`:

```bash
# Recommended on macOS / PEP 668 systems
python3 -m venv .venv && .venv/bin/pip install -r tools/requirements.txt
```

If `questionary` isn't installed, the TUI prints a one-line hint and
exits — the non-interactive flow (`--no-tui`) is stdlib-only and works
either way. See [`../docs/devtools.md`](../docs/devtools.md#setup) for
install alternatives.

The tools find the repo root by walking up from cwd until they hit
`Makefile` + `main.asm`, so they run from anywhere inside the repo.

A built ROM is required (the tools read its `.sym`). Run `make nodebug`
(or `make` for the debug build) once first.

If SameBoy isn't at `/Applications/SameBoy.app` (the canonical macOS
path), `launcher.py` finds it via Spotlight automatically. To skip the
lookup or point at a specific build, set `SAMEBOY_BIN` to the inner
binary path.

## Quick start

```bash
# Interactive dev-server TUI (bare invocation on a TTY)
./tools/start-state/start-state.py
./tools/start-state/start-state.py --no-tui          # skip the menu, one-shot

# Query the .sym
./tools/sym-lookup/sym-lookup.py TryLoadSaveFile
./tools/sym-lookup/sym-lookup.py --addr 01:a020
./tools/sym-lookup/sym-lookup.py --prefix wParty -n 5

# Smoke test (after rebuilding the ROM)
python3 tools/test_lib.py

# Regression sweep: every map through the apply pipeline (~0.1s, 448 maps)
python3 tools/start-state/test_maps.py
```

See [`../docs/devtools.md`](../docs/devtools.md) for full per-tool usage.
