# Devtools Reference

User-facing reference for `pokeprism-devtools` — a standalone Python CLI
suite that sits alongside pokeprism (not inside it). For the rationale,
roadmap, and architecture decisions, see [`devtools-plan.md`](devtools-plan.md).
For pokeprism's in-codebase debug menu and the `DEBUG_MODE` build flag,
see [debug-mode.md](https://github.com/ricccec/pokeprism/blob/main/docs/debug-mode.md)
in the pokeprism repo.

## Setup

Python 3.10+ is required. The only external runtime dependency is
`questionary` (the `prism-dev` TUI), pulled in automatically by
`pyproject.toml`. The recommended install is `pipx`, which gives you the
`prism-dev` and `prism-sym` commands on `$PATH`:

```bash
pipx install -e /path/to/pokeprism-devtools
```

The `-e` makes the install editable — changes to source in this repo take
effect immediately. If you ever change the `[project.scripts]` table,
re-run with `--force` to refresh the entry-point shims.

The tools find your pokeprism checkout by walking up from the current
working directory until they hit `Makefile` + `main.asm`, so they can be
run from anywhere inside it:

```bash
cd /path/to/pokeprism
prism-sym TryLoadSaveFile                # from repo root
cd engine && prism-sym TryLoadSaveFile   # works the same
```

Each tool requires a built ROM — specifically the `.sym` file emitted
alongside it. Run `make nodebug` (release) or `make` (debug) inside
pokeprism once first; the tools will pick up whichever ROM is present.

Runtime artifacts (`inventory.json`, `state.json`, `sav-backups/`, and
optional `presets/`) live under `<pokeprism>/.devtools/`. The tool creates
the directory on first run.

## Status

| Tool                                  | Status     | Purpose                                                          |
|---------------------------------------|------------|------------------------------------------------------------------|
| [`prism-sym`](#prism-sym)           | shipped    | Query the `.sym` file by label or address.                       |
| [`test_lib.py`](#smoke-test)          | shipped    | Smoke test for the library (run after each rebuild).             |
| [`test_maps.py`](#map-sweep)          | shipped    | Sweep every map through the `prism-dev` apply pipeline.        |
| [`prism-dev`](#prism-dev)         | partial    | Inventory + save patcher + map-change support + dev-server TUI + party editor shipped. Items / event flags pending. |
| `flag-finder`                         | planned    | Cross-reference `EVENT_*` set/check sites across the codebase.   |
| `map-inspect`                         | planned    | Dump map metadata (warps, NPCs, signs, connections) as JSON.     |
| [`prism-maps`](#prism-maps)           | shipped    | Filterable terminal table of per-map metadata (dimensions, block sizes, NPC counts, compression ratio). No ROM needed. |
| `sram-diff`                           | planned    | Diff two `.sav` files field-by-field using the SRAM layout.      |
| `trainer-inspect`                     | planned    | Dump trainer parties from `trainers/*.asm`.                      |
| [`prism-usage`](#prism-usage)          | shipped    | RGBDS link-map analyzer: bank usage, section sizes, diffs, pre-commit check. |
| `prism-watch`                         | planned    | `fswatch` → `make nodebug` → optional emulator relaunch.         |

---

## prism-sym

Query the RGBDS symbol table that the build emits next to the ROM
(`pokeprism_nodebug.sym` or `pokeprism.sym`). Useful any time you're looking
for a function, RAM variable, or save data field by name — or you have an
address from a debugger and want to know what it points at.

### Synopsis

```bash
prism-sym LABEL                  # exact match; falls back to substring search
prism-sym --addr BB:AAAA         # reverse: address → label(s) at or before
prism-sym --prefix STR           # list labels starting with STR
prism-sym --search STR           # case-insensitive substring search
prism-sym --region SRAM ...      # filter results by memory region
prism-sym --debug ...            # use the debug ROM's .sym (pokeprism.sym)
prism-sym -n N                   # cap results at N (default 50; 0 = unlimited)
```

Address format is RGBDS-standard: `BB:AAAA` where `BB` is the bank in hex
and `AAAA` is the GB address in hex (e.g. `05:4f9b`, `01:a009`).

Memory regions: `ROM0`, `ROMX`, `VRAM`, `SRAM`, `WRAM0`, `WRAMX`, `OAM`,
`IO`, `HRAM`, `ECHO`, `UNUSED`.

### Examples

**Find a function:**

```text
$ prism-sym TryLoadSaveFile
05:4f9b TryLoadSaveFile
```

The output is the raw `BB:AAAA Label` line from the `.sym`. For scripts and
debugger hookup, that's the canonical format.

**Reverse lookup (debugger PC → source):**

```text
$ prism-sym --addr 01:a020
01:a009 sPlayerData  (+0x17)  [SRAM]
01:a009 sGameData    (+0x17)  [SRAM]
```

Multiple labels share `01:a009` because `sPlayerData` and `sGameData` are
defined at the same SECTION boundary in `sram.asm`. `+0x17` is the offset
from the matched label to the address you asked about — handy when you're
poking inside a struct.

**Find all related labels:**

```text
$ prism-sym --prefix sValidCheck
01:a008 sValidCheck1  [SRAM]
01:ad0f sValidCheck2  [SRAM]

$ sym-lookup --prefix wPartyMon1 -n 5
00:c61f wPartyMon1Species  [WRAM0]
00:c620 wPartyMon1Item     [WRAM0]
00:c621 wPartyMon1Moves    [WRAM0]
00:c625 wPartyMon1ID       [WRAM0]
00:c627 wPartyMon1Exp      [WRAM0]
... (truncated to 5; pass --limit 0 for all)
```

**Filter by region:**

```text
$ sym-lookup --search map --region SRAM -n 5
00:ba33 sBackupMapData  [SRAM]
01:a833 sMapData        [SRAM]
```

**No exact match → falls back to substring search:**

```text
$ sym-lookup partymon1
00:c617 wPartyMon1MiscSpecies  [WRAM0]
00:c617 wPartyMon1Misc         [WRAM0]
...
```

### Exit codes

- `0`: at least one result printed
- `1`: no match found (also when reverse-lookup finds nothing in that bank)
- `2`: usage error (bad address format, no query, missing `.sym`)

Useful in shell scripts:

```bash
if addr=$(sym-lookup SomeLabel 2>/dev/null); then
    echo "found at $addr"
fi
```

### When to use it

- **Debugging in an emulator**: SameBoy / mGBA shows you `PC = 05:4f9b`. Run
  `sym-lookup --addr 05:4f9b` to know what function (or nearest one) that is.
- **Locating save fields**: trying to figure out where `wPartyMon1Species`
  lives in SRAM? `sym-lookup wPartyMon1Species` gives you the WRAM address;
  its SRAM mirror is at `bank 1 + (addr - 0xA009)` offset within
  `sPlayerData` / `sMapData` / `sPokemonData`.
- **Exploring related symbols**: `sym-lookup --prefix sBox` lists every save
  field related to boxes.

---

## Smoke test

`tests/test_lib.py` (inside this repo) exercises the library against the
real `.sym`, `constants.asm`, and `.sav` files from a pokeprism build.
Stdlib only, no pytest.

```bash
cd /path/to/pokeprism                                    # any subdir works
python /path/to/pokeprism-devtools/tests/test_lib.py
```

Run it after every rebuild of the ROM to catch parser regressions early —
for example if a constants file adopts a new macro that the parser doesn't
recognize, or if the `.sym` format changes between RGBDS versions.

Exits non-zero on the first failed check, so it's safe in CI / git hooks.

---

## Map sweep

`test_maps` iterates every map in `inventory.json` and runs the
`start-state` apply pipeline (block-data load, `wScreenSave` recompute,
people-reset, checksum) against a fresh in-memory copy of the template
`.sav`. Nothing is written to disk — it just reports which maps trigger
exceptions.

```bash
cd /path/to/pokeprism
python -m pokeprism_devtools.dev_server.test_maps                # all maps, quiet
python -m pokeprism_devtools.dev_server.test_maps -v             # also print [OK] lines
python -m pokeprism_devtools.dev_server.test_maps --map MAP      # one specific map
python -m pokeprism_devtools.dev_server.test_maps --limit 50     # only first 50 (smoke)
python -m pokeprism_devtools.dev_server.test_maps --show-traceback
```

Useful any time you touch `blockdata.py`, `lz.py`, `people.py`, or
`start_state/apply.py` — those are the modules the sweep exercises. Runs
in ~0.1s for all 448 maps. Exits non-zero if any map fails.

---

## start-state

The headline tool — launches the game in an arbitrary state (team, map,
flags) by patching a `.sav` and handing it off to SameBoy. See the deep
spec in [`devtools-plan.md`](devtools-plan.md#deep-spec-toolsstart-state).

### Phase A — inventory (shipped)

Phase A scans the codebase + built `.sym` and emits
`<pokeprism>/.devtools/inventory.json`. The JSON catalogs every map,
pokemon, item, move, and event flag, plus the .sav file offsets for every
WRAM field the launcher will eventually write.

```bash
start-state
```

The inventory is cached and only rebuilt when the `.sym` is newer.
Force a rebuild with `--rebuild-inventory`. Pass `--debug` to source from
the debug ROM's `.sym` instead of release.

Current scope: 254 pokemon, 256 items, 254 moves, ~1163 event flags, 448
maps. The inventory also embeds each species' base stats + growth rate +
learnset and each move's PP — needed by the party editor to synthesize
PartyMon structs without re-parsing asm at apply time. SRAM offsets
resolved for: `wPlayerName`, `wMoney`, `wNumItems`, `wItems`,
`wEventFlags`, `wMapGroup`, `wMapNumber`, `wXCoord`, `wYCoord`,
`wPartyCount`, `wPartySpecies`, `wPartyMons`, `wPartyMonOT`,
`wPartyMonNicknames`, `wPlayerID`, `wBadges`.

The inventory file is gitignored — it's regenerated from the build
artifacts so it doesn't need to live in source control. A sibling tool
or external script can read it; it's stable JSON.

### Phase B — patch .sav + launch (shipped)

Reads a `state.json` describing the desired initial state, mutates the
`.sav` next to the ROM accordingly (recomputing both SRAM checksums), and
spawns SameBoy. Press A on "Continue" in the game's main menu and you
land in the overworld with the configured state.

**Prerequisite**: a "template" .sav — a real save the game has written
(validity bytes intact, valid checksum). To create one: run
`pokeprism.gbc` or `pokeprism_nodebug.gbc` in SameBoy once, play through
the intro to reach the overworld, then **save the game in-game** (Start →
Save). That writes `pokeprism*.sav` next to the ROM. After that,
`start-state` will use it as the template.

Schema for `.devtools/state.json` (or a `presets/*.json`):

```json
{
  "player": {
    "name": "RED",
    "money": 9999,
    "badges": [0, 0, 0]
  },
  "map": {
    "name": "CAPER_HOUSE",
    "x": 2,
    "y": 2
  }
}
```

All fields are optional — fields you don't set are left untouched in the
template. `map.name` is any `MAP_*` constant; consult `inventory.json` for
the full list. Badges is a 3-byte array `[naljo, rijon, other]` where each
byte is a bitmask of earned badges.

The optional `party` key replaces the template's party with synthesized mons:

```json
{
  "party": [
    {"species": "CHARMANDER", "level": 5},
    {"species": "PIKACHU",    "level": 10, "nickname": "SPARKY"},
    {"species": "BULBASAUR",  "level": 7, "moves": ["TACKLE", "GROWL"], "item": "ORAN_BERRY"}
  ]
}
```

Per-mon defaults: `nickname` = species name, `moves` = the last 4 moves
learnable at or below `level` (from `data/movesets/*.asm`), `item` =
`NO_ITEM`, DVs all 15, StatExp 0, happiness 70, OT name/ID inherited
from the player. HP/Atk/Def/Spd/SpA/SpD are computed from base stats
via the in-game formula; experience is set to the minimum for the
requested level using the species' growth rate.

**State resolution order**: `prism-dev` looks for state in this sequence:
1. `--state PATH` if given on the command line
2. `.devtools/state.json` if it exists (written by the TUI on every edit)
3. `.devtools/presets/default.json` if it exists
4. Empty state — the template `.sav` is written back unchanged

To give a fresh checkout a useful starting warp, create
`.devtools/presets/default.json` with the schema above. That file is not
tracked by pokeprism's git, so each developer keeps their own.

**Out of scope** (will arrive in follow-up commits): items, event flags.
Those fields are left untouched in the template. The party editor (above)
covers the most common need; bag inventory and event-flag toggling
remain template-driven.

Usage:

```bash
start-state                # patch the .sav next to
                                                  # the ROM and launch SameBoy
start-state --no-launch    # patch only, don't run
start-state --out PATH     # write somewhere else
                                                  # (implies --no-launch)
start-state --template PATH # use a different .sav
                                                  # as input (preserves the
                                                  # ROM's .sav)
start-state --state PATH   # alternate state.json
start-state --keep-people  # don't clear NPC slots
                                                  # on map change (see below)
```

Existing `.sav` files are backed up to `.devtools/sav-backups/`
before being overwritten — you can always recover.

### Map change — what happens under the hood

Changing `map.name` (or `map.x`/`map.y`) in `state.json` is more involved
than just writing the four group/number/x/y bytes. The game's
`MAPSETUP_CONTINUE` script assumes the saved state is consistent with the
current map, so several engine-state fields must also be updated. The
tool handles this automatically — but if you're debugging or extending
the patcher, here's the chain:

1. **Block-data lookup** (`blockdata.py`): walks
   `MapGroupPointers` → primary header → secondary header to find the new
   map's LZ-compressed blockdata in ROM. Uses `lz.py` (a Python port of
   `home/decompress.asm`) to decompress into a `height × width` block
   grid.
2. **`wScreenSave` recomputation**: the game's `LoadNeighboringBlockData`
   step in `MAPSETUP_CONTINUE` overlays `wScreenSave` onto `wOverworldMap`
   *after* loading the new map's blocks from ROM — so a stale
   `wScreenSave` corrupts the area around the player. We compute the
   correct 30-byte window for the new (x, y) using the same anchor formula
   the game uses (`engine/warp_connection.asm:343`) and write it.
3. **Player engine state reset** (`people.py`): updates
   `wObjectStructs[0]` positional fields to `(wXCoord + 4, wYCoord + 4)`
   so the player sprite renders at the right location. The `+4` is the
   game's screen-edge offset, verified against real saves.
4. **NPC clear**: by default, zeroes `wObjectStructs[1..]` and
   `wMapObjects[1..]` so ghost NPCs from the previous map don't render.
   Pass `--keep-people` to skip this (you'll see stale NPCs — useful only
   for debugging the difference).

After this, both SRAM checksums (primary `sChecksum` over `sGameData`,
plus `sExtraChecksum` over `sExtraData`) are recomputed and written.

### Known limitations on map change

- **Destination map has no NPCs** (default behaviour clears them; we don't
  yet reload from `MapEventHeader`). Tracked in
  [`devtools-plan.md`](devtools-plan.md#future-work--known-v1-limitations)
  under the planned `--load-map-npcs` flag.
- **Edge positions on connected maps**: `wScreenSave` zero-pads outside
  the map's block grid, which is wrong for maps with N/S/E/W connections
  (those padding regions should contain neighbor-map blocks). The screen
  may show one row/column of incorrect tiles at the very edge. Walking
  refreshes it.

### TUI (dev-server mode)

Bare `start-state.py` on a TTY drops you into a `questionary`-driven
interactive menu. The TUI is long-lived: edits autosave, SameBoy is
managed as a subprocess, and the inventory is refreshed in-process when
the ROM is rebuilt.

```bash
start-state            # opens the TUI
start-state --no-tui   # bypass; use the one-shot flow
```

The TUI also bypasses itself when stdin isn't a TTY (piped input) or any
of `--out`, `--no-launch`, `--inventory-only` is set.

#### Menu

```
=========================================================
  pokeprism start-state  —  dev server
=========================================================

  Build:   pokeprism_nodebug.gbc    sym mtime: 2026-05-29 16:46:58
  State:   .devtools/state.json
           player: name='RED'  money=9999  badges=[0, 0, 0]
           map:    EMBER_BROOK  at (10, 8)
  SameBoy: not running

? What now?
» Launch  (patch .sav, spawn SameBoy)
  Edit player...
  Edit map / position...
  Reset state from preset...
  ───────────────────────────────
  Edit party...
  Edit items        — v2 — coming soon
  Edit event flags  — v2 — coming soon
  ───────────────────────────────
  Quit
```

#### What's editable

| Field           | Notes                                                           |
|-----------------|-----------------------------------------------------------------|
| Player name     | 1–7 chars, GB charset (validated on input).                     |
| Money           | 0–999,999.                                                      |
| Badges          | 3 bytes — Naljo / Rijon / Other — each a 0–255 bitmask.         |
| Map name        | Tab-autocomplete from the inventory (~448 maps; fuzzy match).   |
| X / Y coord    | Range derived from the destination map's block grid (× 2 tiles per block); falls back to 0–255 if the map is unset. |
| Party (6 slots) | Per-slot editor for species (tab-autocomplete from `inventory.json`), level (1–100), nickname, and the 4 moves (autocomplete; `-` reverts to learnset default). New slots are dropped if you back out without picking a species. |

Items / event flags are surfaced as disabled menu entries
("v2 — coming soon"); editing them is on the roadmap (see
[`devtools-plan.md`](devtools-plan.md#future-work--known-v1-limitations)).

#### Dev-server semantics

- **Autosave**: every successful edit writes `state.json` immediately.
  Ctrl-C never loses the current state. (The file is gitignored;
  `presets/*.json` are read-only from the TUI's perspective.)
- **Inventory watching**: between menu cycles the TUI polls the `.sym`
  mtime. When it changes (you rebuilt the ROM in another terminal), the
  TUI prints `(detected new build — refreshing inventory from .sym)`
  and rebuilds `inventory.json` in-process. The next launch picks up the
  new symbols. You don't have to restart the TUI.
- **SameBoy lifecycle**: the menu's first option is **Launch** until a
  SameBoy process is running, then becomes **Re-launch**. On Re-launch,
  the previous SameBoy is `terminate()`d (then `kill()`ed if it doesn't
  exit within 2s) and a fresh one is spawned with the new `.sav`. If you
  close SameBoy yourself in between, the TUI notices and just spawns a
  fresh one. The SameBoy binary is resolved in this order: `$SAMEBOY_BIN`
  env var → `sameboy` / `SameBoy` on `$PATH` → macOS Spotlight
  (`mdfind` for `SameBoy.app`) → `open -a SameBoy` (last-ditch; can't
  track the spawned PID, so Re-launch will refocus instead of restart —
  set `$SAMEBOY_BIN` to fix).
- **Quit**: leaves a running SameBoy alone (with a closing note).

#### Reset from preset

Select a JSON file from `.devtools/presets/`; the TUI copies it
into `state.json` (after a confirm prompt). Presets are never written
back from the TUI — they're stable starting points you can `git diff`
against your working state.

### One-shot mode

When invoked with `--no-tui` (or `--out`, `--no-launch`,
`--inventory-only`, or non-TTY stdin), `start-state.py` patches the
`.sav` from `state.json` and either launches SameBoy or exits, exactly
as before the TUI shipped. The map-change pipeline (block-data load,
`wScreenSave`, people reset) is identical in both modes — the TUI calls
the same `apply` module.

---

## prism-maps

Inspects all maps defined in `constants/map_dimension_constants.asm` and
prints a filterable, sortable table of per-map metadata. No ROM or build
required — reads source files only.

### Synopsis

```bash
prism-maps [OPTIONS]
```

Run from anywhere inside the pokeprism checkout.

### Columns

| Column   | Source                          | Notes                              |
|----------|---------------------------------|------------------------------------|
| `NAME`   | `map_dimension_constants.asm`   | Bare name, e.g. `CAPER_HOUSE`      |
| `W` / `H`| same                            | Dimensions in blocks               |
| `BLKS`   | W × H                           | Total block count                  |
| `RAW`    | `maps/blk/<Name>.ablk` size     | `—` if file missing                |
| `LZ`     | `maps/blk/<Name>.ablk.lz` size  | `—` if file missing                |
| `RATIO`  | LZ / RAW                        | Red if > 100% (LZ expands the file)|
| `SCRIPT` | `maps/<Name>.asm` source bytes  | `—` if no script file              |
| `NPCS`   | `person_event` + `trainer` lines| `—` if no script file              |
| `USED`   | Referenced in `blockdata.asm`   | Green ✓ / red ✗                    |

### Options

```
--sort {name,width,height,blocks,raw,lz,ratio,script,npcs}
                    Sort column (default: name)
--reverse           Reverse the sort order
--used              Show only maps referenced in blockdata.asm
--unused            Show only maps NOT referenced in blockdata.asm
--search PATTERN    Case-insensitive substring match on map name
--min-blocks N      Only maps with BLKS >= N
--max-blocks N      Only maps with BLKS <= N
--json              Emit a JSON array instead of a table
```

`--used` and `--unused` are mutually exclusive. All filters compose (AND logic).

### Examples

```bash
# Full table (~300+ maps)
prism-maps

# The 3 maps that exist as .ablk.lz files but aren't INCBINed in blockdata.asm
prism-maps --unused

# Maps where LZ compression makes the file bigger, smallest first
prism-maps --max-blocks 20 --sort ratio --reverse

# Largest maps by block footprint
prism-maps --sort blocks --reverse

# Routes by size
prism-maps --search route --sort blocks --reverse

# Machine-readable
prism-maps --json | python3 -m json.tool
```

### Exit codes

- `0` — at least one row printed (or JSON array emitted)
- `1` — no maps matched the given filters
- `2` — usage error or pokeprism repo not found

---

## prism-usage

Parses the RGBDS link-map (`pokeprism_nodebug.map`) and exposes bank usage
through focused subcommands. Auto-locates the `.map` next to the built ROM;
use `--map PATH` to override or `--debug` to use the debug build's map.

**Synopsis**

```
prism-usage [--debug] [--map PATH] [SUBCOMMAND [ARGS]]
```

**Subcommands**

| Subcommand | Purpose |
|---|---|
| `summary` (default) | Headline ROM/RAM stats, top-5 most-full and most-free ROM banks. |
| `banks [--region R]` | ANSI bar chart of every ROM bank's occupancy (or a RAM region with `--region SRAM\|WRAMX\|…`). |
| `bank N` | Section-by-section breakdown of one bank. N accepts decimal (`60`), `$3c`, `0x3c`. |
| `largest [-n N]` | Top-N sections globally by size (default 20; `-n 0` for all). |
| `free [--region R]` | Banks sorted by free space — answers "where do I put new data?". |
| `section NAME` | All banks containing a section. Exact match first, then substring. |
| `check [--max-bank-usage P]` | Exit 1 if any ROM bank exceeds P% (default 95). Pre-commit–friendly. |
| `diff OLD.map NEW.map [--max-bank-usage P]` | Per-bank and per-section deltas between two map files. |

**Exit codes** — matches `prism-sym`:
- `0` — success / all checks pass
- `1` — no results / threshold exceeded
- `2` — usage error or file not found

**Examples**

```bash
prism-usage                                   # quick overview
prism-usage banks                             # visual utilization chart
prism-usage bank 5                            # what's in ROM bank 5?
prism-usage bank '$3c'                        # tightest bank by hex
prism-usage largest -n 10                     # 10 biggest sections
prism-usage free                              # where to put new data
prism-usage section "Map Scripts"            # find all map-script sections
prism-usage check --max-bank-usage 98        # exit 1 if any bank > 98%
prism-usage diff prev.map pokeprism_nodebug.map   # what did my edit cost?
```

**Pre-commit hook**

```bash
# .git/hooks/pre-commit
prism-usage check --max-bank-usage 98 || exit 1
```

---

## Extending the toolset

All tools share the `pokeprism_devtools` package. To add a new one:

1. Add a module under `src/pokeprism_devtools/`, e.g. `foo.py` (for a
   single-file tool) or `src/pokeprism_devtools/foo/` (subpackage with
   its own `cli.py`).
2. At the top, import from the package:

   ```python
   from pokeprism_devtools import paths, symfile, constants, savefile
   ```

3. Use `paths.repo_root()`, `paths.rom_path()`, `paths.sym_path()` to
   locate the user's pokeprism artifacts — never hardcode paths.
4. Expose the entry point in `pyproject.toml`:

   ```toml
   [project.scripts]
   foo = "pokeprism_devtools.foo:main"
   ```

   Run `pipx install --force <repo>` once so the new shim lands on
   `$PATH`; subsequent edits to source pick up automatically.
5. Add a row to the **Status** table above and a section here.
