# pokeprism-devtools

Python devtools for working on [pokeprism](https://github.com/ricccec/pokeprism)
— a Pokémon Crystal disassembly fork (RGBDS 0.7.0, ~2MB GBC ROM hack).

User-facing reference: [`docs/devtools.md`](docs/devtools.md).
Plan/status: [`docs/devtools-plan.md`](docs/devtools-plan.md).
Map-blockdata design record: [`docs/blockdata-plan.md`](docs/blockdata-plan.md).

## What's in here

```
src/pokeprism_devtools/
├── paths.py            — find repo root, ROM, .sym, .map, .sav
├── symfile.py          — parse RGBDS .sym files
├── constants.py        — parse constants/*.asm enums
├── maps.py             — parse map_dimension_constants.asm
├── savefile.py         — SaveFile I/O + checksum + GB charset encoder
├── lz.py               — LZ decompressor (port of home/decompress.asm)
├── blockdata.py        — read map blockdata from ROM, compute wScreenSave
├── people.py           — reset player struct + clear NPC slots
├── sym_lookup.py       — `prism-sym` CLI: query the .sym by label or address
└── dev_server/
    ├── cli.py          — `prism-dev` CLI entrypoint
    ├── tui.py          — questionary-driven dev-server menu
    ├── inventory.py    — build/refresh the .sym → .sav offset catalog
    ├── apply.py        — mutate a .sav from a state.json
    ├── launcher.py     — locate SameBoy and spawn it (Spotlight / $SAMEBOY_BIN)
    └── test_maps.py    — sweep every map through apply (regression check)
tests/test_lib.py       — stdlib smoke test against real build artifacts
docs/                   — devtools.md, devtools-plan.md, blockdata-plan.md
```

## Setup

Requires Python 3.10+ and a clone of pokeprism with a built ROM (the tools
read its `.sym`). Install via `pipx` so the CLIs land on your `$PATH`:

```bash
pipx install -e /path/to/pokeprism-devtools
```

This exposes two commands:

| Command       | Purpose                                                    |
|---------------|------------------------------------------------------------|
| `prism-dev`   | Launch the game in an arbitrary state (the headline tool). |
| `prism-sym`   | Query the `.sym` by label or address.                      |

Both anchor themselves to your pokeprism repo by walking the current
working directory up until they find `Makefile` + `main.asm`, so run them
from anywhere inside your pokeprism checkout:

```bash
cd /path/to/pokeprism
prism-dev --inventory-only
prism-sym TryLoadSaveFile
```

Runtime artifacts (`inventory.json`, `state.json`, `sav-backups/`, plus
optional `presets/`) live under `<pokeprism>/.devtools/` — they're
per-game, so one tool install can serve multiple pokeprism clones without
collisions.

If SameBoy isn't at `/Applications/SameBoy.app`, set `$SAMEBOY_BIN` to the
inner binary path, or let `prism-dev` find it via Spotlight on macOS.

## Quick start

```bash
cd /path/to/pokeprism            # any subdirectory works too

# Interactive dev-server TUI (default on a TTY)
prism-dev
prism-dev --no-tui             # bypass the TUI, one-shot patch + launch

# Query the .sym
prism-sym TryLoadSaveFile
prism-sym --addr 01:a020
prism-sym --prefix wParty -n 5

# Smoke test (after rebuilding the ROM)
python /path/to/pokeprism-devtools/tests/test_lib.py

# Regression sweep: every map through the apply pipeline (~0.1s, 448 maps)
python -m pokeprism_devtools.dev_server.test_maps
```

See [`docs/devtools.md`](docs/devtools.md) for full per-tool usage.

## Development

`pipx install -e <path>` installs in editable mode — changes to source in
this repo take effect immediately, no reinstall needed.

To pick up new `[project.scripts]` entries, run
`pipx install --force /path/to/pokeprism-devtools` (only required when
the entry-point list itself changes).
