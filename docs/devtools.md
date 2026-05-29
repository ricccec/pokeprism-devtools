# Devtools Reference

User-facing reference for the Python devtools under [`/tools/`](../tools/).
For the rationale, roadmap, and architecture decisions, see
[`devtools-plan.md`](devtools-plan.md). For the in-codebase debug menu and
the `DEBUG_MODE` build flag, see [`debug-mode.md`](debug-mode.md).

## Setup

Python 3.10+ is required. The shared library (`tools/_lib/`) is stdlib-only.
The only external dependency is `questionary`, used by the `start-state`
TUI; pin in `tools/requirements.txt`. Install it however you prefer — a
venv is the safest, or `--break-system-packages` if you don't mind:

```bash
# Option A: venv (recommended on macOS with Homebrew Python / PEP 668)
python3 -m venv .venv && .venv/bin/pip install -r tools/requirements.txt
# then run tools via .venv/bin/python tools/start-state/start-state.py

# Option B: user install, opting out of PEP 668
python3 -m pip install --user --break-system-packages -r tools/requirements.txt
```

If `questionary` isn't installed, the TUI prints a one-line hint and
exits cleanly; the non-interactive flow (`--no-tui`) is stdlib-only and
works either way.

The tools find the repo root automatically by walking up from the current
working directory until they hit `Makefile` + `main.asm`, so they can be run
from anywhere inside the repo:

```bash
./tools/sym-lookup/sym-lookup.py TryLoadSaveFile     # from repo root
cd engine && ../tools/sym-lookup/sym-lookup.py ...   # works the same
```

Each tool requires a built ROM — specifically the `.sym` file that's emitted
alongside it. Run `make nodebug` (release) or `make` (debug) once first; the
tools will pick up whichever ROM is present.

## Status

| Tool                                  | Status     | Purpose                                                          |
|---------------------------------------|------------|------------------------------------------------------------------|
| [`sym-lookup`](#sym-lookup)           | shipped    | Query the `.sym` file by label or address.                       |
| [`test_lib.py`](#smoke-test)          | shipped    | Smoke test for `_lib/` parsers (run after each rebuild).         |
| [`test_maps.py`](#map-sweep)          | shipped    | Sweep every map through the `start-state` apply pipeline.        |
| [`start-state`](#start-state)         | partial    | Inventory + save patcher + map-change support + dev-server TUI shipped. Party / items / event flags pending. |
| `flag-finder`                         | planned    | Cross-reference `EVENT_*` set/check sites across the codebase.   |
| `map-inspect`                         | planned    | Dump map metadata (warps, NPCs, signs, connections) as JSON.     |
| `sram-diff`                           | planned    | Diff two `.sav` files field-by-field using the SRAM layout.      |
| `trainer-inspect`                     | planned    | Dump trainer parties from `trainers/*.asm`.                      |
| `bank-usage`                          | planned    | Pretty-print bank free space (ANSI bars, near-full warnings).    |
| `build-watch`                         | planned    | `fswatch` → `make nodebug` → optional emulator relaunch.         |

---

## sym-lookup

Query the RGBDS symbol table that the build emits next to the ROM
(`pokeprism_nodebug.sym` or `pokeprism.sym`). Useful any time you're looking
for a function, RAM variable, or save data field by name — or you have an
address from a debugger and want to know what it points at.

### Synopsis

```bash
sym-lookup LABEL                  # exact match; falls back to substring search
sym-lookup --addr BB:AAAA         # reverse: address → label(s) at or before
sym-lookup --prefix STR           # list labels starting with STR
sym-lookup --search STR           # case-insensitive substring search
sym-lookup --region SRAM ...      # filter results by memory region
sym-lookup --debug ...            # use the debug ROM's .sym (pokeprism.sym)
sym-lookup -n N                   # cap results at N (default 50; 0 = unlimited)
```

Address format is RGBDS-standard: `BB:AAAA` where `BB` is the bank in hex
and `AAAA` is the GB address in hex (e.g. `05:4f9b`, `01:a009`).

Memory regions: `ROM0`, `ROMX`, `VRAM`, `SRAM`, `WRAM0`, `WRAMX`, `OAM`,
`IO`, `HRAM`, `ECHO`, `UNUSED`.

### Examples

**Find a function:**

```text
$ ./tools/sym-lookup/sym-lookup.py TryLoadSaveFile
05:4f9b TryLoadSaveFile
```

The output is the raw `BB:AAAA Label` line from the `.sym`. For scripts and
debugger hookup, that's the canonical format.

**Reverse lookup (debugger PC → source):**

```text
$ ./tools/sym-lookup/sym-lookup.py --addr 01:a020
01:a009 sPlayerData  (+0x17)  [SRAM]
01:a009 sGameData    (+0x17)  [SRAM]
```

Multiple labels share `01:a009` because `sPlayerData` and `sGameData` are
defined at the same SECTION boundary in `sram.asm`. `+0x17` is the offset
from the matched label to the address you asked about — handy when you're
poking inside a struct.

**Find all related labels:**

```text
$ ./tools/sym-lookup/sym-lookup.py --prefix sValidCheck
01:a008 sValidCheck1  [SRAM]
01:ad0f sValidCheck2  [SRAM]

$ ./tools/sym-lookup/sym-lookup.py --prefix wPartyMon1 -n 5
00:c61f wPartyMon1Species  [WRAM0]
00:c620 wPartyMon1Item     [WRAM0]
00:c621 wPartyMon1Moves    [WRAM0]
00:c625 wPartyMon1ID       [WRAM0]
00:c627 wPartyMon1Exp      [WRAM0]
... (truncated to 5; pass --limit 0 for all)
```

**Filter by region:**

```text
$ ./tools/sym-lookup/sym-lookup.py --search map --region SRAM -n 5
00:ba33 sBackupMapData  [SRAM]
01:a833 sMapData        [SRAM]
```

**No exact match → falls back to substring search:**

```text
$ ./tools/sym-lookup/sym-lookup.py partymon1
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
if addr=$(./tools/sym-lookup/sym-lookup.py SomeLabel 2>/dev/null); then
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

`tools/test_lib.py` exercises the `_lib/` parsers against the real
`.sym`, `constants.asm`, and `.sav` files. It's a stdlib script, no pytest.

```bash
python3 tools/test_lib.py
```

Run it after every rebuild of the ROM to catch parser regressions early —
for example if a constants file adopts a new macro that the parser doesn't
recognize, or if the `.sym` format changes between RGBDS versions.

Exits non-zero on the first failed check, so it's safe in CI / git hooks.

---

## Map sweep

`tools/start-state/test_maps.py` iterates every map in `inventory.json`
and runs the `start-state` apply pipeline (block-data load, `wScreenSave`
recompute, people-reset, checksum) against a fresh in-memory copy of the
template `.sav`. Nothing is written to disk — it just reports which maps
trigger exceptions.

```bash
python3 tools/start-state/test_maps.py            # all maps, quiet
python3 tools/start-state/test_maps.py -v         # also print [OK] lines
python3 tools/start-state/test_maps.py --map MAP  # one specific map
python3 tools/start-state/test_maps.py --limit 50 # only first 50 (smoke)
python3 tools/start-state/test_maps.py --show-traceback
```

Useful any time you touch `_lib/blockdata.py`, `_lib/lz.py`,
`_lib/people.py`, or `tools/start-state/apply.py` — those are the
modules the sweep exercises. Runs in ~0.1s for all 448 maps. Exits
non-zero if any map fails.

---

## start-state

The headline tool — launches the game in an arbitrary state (team, map,
flags) by patching a `.sav` and handing it off to SameBoy. See the deep
spec in [`devtools-plan.md`](devtools-plan.md#deep-spec-toolsstart-state).

### Phase A — inventory (shipped)

Phase A scans the codebase + built `.sym` and emits
`tools/start-state/inventory.json`. The JSON catalogs every map, pokemon,
item, move, and event flag, plus the .sav file offsets for every WRAM
field the launcher will eventually write.

```bash
./tools/start-state/start-state.py
```

The inventory is cached and only rebuilt when the `.sym` is newer.
Force a rebuild with `--rebuild-inventory`. Pass `--debug` to source from
the debug ROM's `.sym` instead of release.

Current scope: 254 pokemon, 256 items, 254 moves, ~1163 event flags, 448
maps. SRAM offsets resolved for: `wPlayerName`, `wMoney`, `wNumItems`,
`wItems`, `wEventFlags`, `wMapGroup`, `wMapNumber`, `wXCoord`, `wYCoord`,
`wPartyCount`, `wPartySpecies`, `wPartyMons`, `wBadges`.

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

Schema for `tools/start-state/state.json` (or a `presets/*.json`):

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

**Out of scope in v1** (will arrive in follow-up commits): party, items,
event flags. Those fields are left untouched in the template — so if you
need a Larvitar in your party, save the game with the larvitar caught and
use that as the template.

Usage:

```bash
./tools/start-state/start-state.py                # patch the .sav next to
                                                  # the ROM and launch SameBoy
./tools/start-state/start-state.py --no-launch    # patch only, don't run
./tools/start-state/start-state.py --out PATH     # write somewhere else
                                                  # (implies --no-launch)
./tools/start-state/start-state.py --template PATH # use a different .sav
                                                  # as input (preserves the
                                                  # ROM's .sav)
./tools/start-state/start-state.py --state PATH   # alternate state.json
./tools/start-state/start-state.py --keep-people  # don't clear NPC slots
                                                  # on map change (see below)
```

Existing `.sav` files are backed up to `tools/start-state/sav-backups/`
before being overwritten — you can always recover.

### Map change — what happens under the hood

Changing `map.name` (or `map.x`/`map.y`) in `state.json` is more involved
than just writing the four group/number/x/y bytes. The game's
`MAPSETUP_CONTINUE` script assumes the saved state is consistent with the
current map, so several engine-state fields must also be updated. The
tool handles this automatically — but if you're debugging or extending
the patcher, here's the chain:

1. **Block-data lookup** (`_lib/blockdata.py`): walks
   `MapGroupPointers` → primary header → secondary header to find the new
   map's LZ-compressed blockdata in ROM. Uses `_lib/lz.py` (a Python port
   of `home/decompress.asm`) to decompress into a `height × width` block
   grid.
2. **`wScreenSave` recomputation**: the game's `LoadNeighboringBlockData`
   step in `MAPSETUP_CONTINUE` overlays `wScreenSave` onto `wOverworldMap`
   *after* loading the new map's blocks from ROM — so a stale
   `wScreenSave` corrupts the area around the player. We compute the
   correct 30-byte window for the new (x, y) using the same anchor formula
   the game uses (`engine/warp_connection.asm:343`) and write it.
3. **Player engine state reset** (`_lib/people.py`): updates
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
./tools/start-state/start-state.py            # opens the TUI
./tools/start-state/start-state.py --no-tui   # bypass; use the one-shot flow
```

The TUI also bypasses itself when stdin isn't a TTY (piped input) or any
of `--out`, `--no-launch`, `--inventory-only` is set.

#### Menu

```
=========================================================
  pokeprism start-state  —  dev server
=========================================================

  Build:   pokeprism_nodebug.gbc    sym mtime: 2026-05-29 16:46:58
  State:   tools/start-state/state.json
           player: name='RED'  money=9999  badges=[0, 0, 0]
           map:    EMBER_BROOK  at (10, 8)
  SameBoy: not running

? What now?
» Launch  (patch .sav, spawn SameBoy)
  Edit player...
  Edit map / position...
  Reset state from preset...
  ───────────────────────────────
  Edit party        — v2 — coming soon
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

Party / items / event flags are surfaced as disabled menu entries
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

Select a JSON file from `tools/start-state/presets/`; the TUI copies it
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

## Extending the toolset

All tools share `tools/_lib/`. To add a new one:

1. Make a sibling directory, e.g. `tools/foo/`, with an executable
   `foo.py` (`#!/usr/bin/env python3`, `chmod +x`).
2. At the top:

   ```python
   import sys
   from pathlib import Path
   sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

   from _lib import paths, symfile, constants, savefile
   ```

3. Use `paths.repo_root()`, `paths.rom_path()`, `paths.sym_path()` to
   locate artifacts — never hardcode paths.
4. Add a row to the **Status** table above and a section here.
