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
├── test_lib.py             — smoke test for _lib/
├── _lib/                   — shared parsers / helpers (imported, not run)
│   ├── paths.py            — find repo root, ROM, .sym, .map, .sav
│   ├── symfile.py          — parse RGBDS .sym files
│   ├── constants.py        — parse constants/*.asm enums
│   ├── maps.py             — parse map_dimension_constants.asm (mapgroup)
│   ├── savefile.py         — SaveFile I/O + checksum + GB charset encoder
│   ├── lz.py               — LZ decompressor (port of home/decompress.asm)
│   ├── blockdata.py        — read map blockdata from ROM, compute wScreenSave
│   └── people.py           — reset player struct + clear NPC slots
├── sym-lookup/             — query the .sym by label or address
│   └── sym-lookup.py
└── start-state/            — launch the game in an arbitrary state
    ├── start-state.py
    ├── presets/            — example state.json files (checked in)
    │   └── default.json
    ├── inventory.json      — generated, gitignored
    ├── state.json          — user's working state, gitignored
    └── sav-backups/        — auto-backups before .sav overwrite, gitignored
```

## Setup

Python 3.10+. Stdlib-only — no `pip install` step required. The tools find
the repo root by walking up from cwd until they hit `Makefile` + `main.asm`,
so they run from anywhere inside the repo.

A built ROM is required (the tools read its `.sym`). Run `make nodebug` (or
`make` for the debug build) once first.

## Quick start

```bash
# Query the .sym
./tools/sym-lookup/sym-lookup.py TryLoadSaveFile
./tools/sym-lookup/sym-lookup.py --addr 01:a020
./tools/sym-lookup/sym-lookup.py --prefix wParty -n 5

# Run the smoke test (after rebuilding the ROM)
python3 tools/test_lib.py

# Launch the game in a custom state
./tools/start-state/start-state.py            # patch pokeprism*.sav and launch
./tools/start-state/start-state.py --no-launch
./tools/start-state/start-state.py --out /tmp/test.sav
```

See [`../docs/devtools.md`](../docs/devtools.md) for full per-tool usage.
