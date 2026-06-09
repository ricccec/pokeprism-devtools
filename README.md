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
├── mapfile.py          — parse RGBDS .map files (per-bank free space, section sizes)
├── usage.py            — `prism-usage` CLI: link-map bank/section analysis
├── packing.py          — two-tier best-fit / worst-fit bank packer
├── mapspec.py          — map spec (TOML) read/write + derived per-map section names
├── mapsource.py        — parse map asm sources by label (headers, paths, sections)
├── blobsizes.py        — map blob sizes (lzcomp blk, header formulas)
├── mapwire.py          — idempotent wiring of the map source files + romx.link pins
├── mapfit.py           — `prism-mapfit` CLI: allocate / park / consolidate map blobs
├── map_show.py         — `prism-map` CLI: inspect one map + export its spec
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

This exposes several commands (see [`docs/devtools.md`](docs/devtools.md) for full usage):

| Command        | Purpose                                                          |
|----------------|------------------------------------------------------------------|
| `prism-dev`    | Launch the game in an arbitrary state (the headline tool).       |
| `prism-sym`    | Query the `.sym` by label or address.                            |
| `prism-maps`   | Filterable table of per-map metadata (dimensions, sizes, NPCs).  |
| `prism-map`    | Inspect one map (header fields, section banks, blob sizes) + export its spec. |
| `prism-usage`  | RGBDS link-map analysis: bank usage, section sizes, diffs.       |
| `prism-mapfit` | Find ROM banks for a new map, wire it in, and re-pack a near-full ROM. |
| `prism-mapview`| Render a map to an image and open it.                            |
| `prism-gfx`    | Visualize tilesets and BG palettes.                              |

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

# Allocate banks for a new map and wire it in
prism-mapfit add --park --spec mymap.toml          # park a still-growing map
prism-mapfit consolidate --spec a.toml --spec b.toml   # re-pack once sizes settle

# Inspect an existing map and export its spec
prism-map OlcanDock                                # full report
prism-map OlcanDock -o olcan.toml                  # export the prism-mapfit spec

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
