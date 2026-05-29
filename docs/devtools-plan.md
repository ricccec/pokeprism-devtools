# Pokeprism DevTools — Implementation Plan

## Status snapshot (read me first)

This doc is the original plan, kept as a record of intent. For the current
user-facing reference of what's shipped, see
[`devtools.md`](devtools.md). At a glance:

| Phase | Status | Notes |
|---|---|---|
| `docs/debug-mode.md` | ✓ shipped | documents the existing in-game debug menu, `DEBUG_MODE` flag, `/patch/` framework |
| `_lib/{paths,symfile,constants,maps,savefile}.py` | ✓ shipped | with `tools/test_lib.py` smoke test |
| `sym-lookup` (P1) | ✓ shipped | exact / reverse / prefix / substring / region-filtered |
| `start-state` Phase A (inventory) | ✓ shipped | `tools/start-state/inventory.json`, regenerated from `.sym` |
| `start-state` Phase B (patch + launch) | ✓ shipped | player name, money, badges, map+coords; party/items/event flags deferred |
| Map-change support (LZ + blockdata + wScreenSave + people-reset) | ✓ shipped | required additional modules `_lib/{lz,blockdata,people}.py`; see [`blockdata-plan.md`](blockdata-plan.md) |
| TUI (`questionary` menu) | pending | next on the roadmap |
| Final pass of `docs/devtools.md` | pending | user-facing reference is current as of map-change work; add TUI section when shipped |
| Other tools (`flag-finder`, `map-inspect`, `sram-diff`, etc.) | pending | sketched only; no implementation yet |

Future work / deferred items live at the bottom of this doc under
[Future work / known v1 limitations](#future-work--known-v1-limitations).

## Context

Pokeprism is a 2MB GBC ROM hack (Pokémon Crystal disassembly fork) built with RGBDS
0.7.0. The dev loop today is: edit `.asm` → `make nodebug` → open the resulting
`pokeprism_nodebug.gbc` in an emulator → play through the intro/title to reach the
overworld → manually drive the game to whatever state you want to test.

The user wants a suite of CLI devtools that make patching and debugging this codebase
less painful. The headline tool: **start the game in an arbitrary state (team, map,
flags) without rebuilding the ROM**, with a fast configure-and-run loop.

Decisions taken upfront (from clarifying questions):
- **Language**: Python 3 (matches `dedenc.py`, `gfx.py`, `png.py` already in the repo)
- **Scope**: Full suite specced, but only `start-state` gets a deep spec
- **Emulator**: SameBoy on macOS
- **Boot path**: rely on the existing "Continue" menu option (no ROM patching) — the
  patched `.sav` makes Continue appear; user presses A once

A separate goal: **document existing in-codebase devtools/debug features** that we
discovered during exploration, so they're discoverable later.

---

## What's already in the codebase (document, don't rebuild)

Before adding anything, two things deserve documentation under `docs/`, because they
deliver a lot of what the user wants — they're just not currently visible.

### 1. In-game debug menu — `DEBUG_MODE` build flag
- **What**: A fully-featured in-game debug menu with **Get Pokémon**, **Manage Items**,
  **Manage Money**, **Warp Anywhere**, **Edit Flags**, **Memory Access**, **Pic Test**.
- **Source**: `engine/debug_menu.asm`, `engine/debug_menu_contents.asm`,
  `macros/debug_menu.asm`. Gated by `if DEF(DEBUG_MODE)` in `macros.asm:330`
  (`debug_mode_flag` macro) and `engine/main_menu.asm` ("Debug options" entry).
- **How to enable**: `make` (without `nodebug`) builds `pokeprism.gbc` with
  `-DDEBUG_MODE` (per `Makefile`: `$(pokeprism_obj): RGBASMFLAGS += -DDEBUG_MODE`).
- **Why important**: Half of what `start-state` would do is already available *inside*
  the debug ROM via this menu. The tool should be positioned as: "use the debug menu
  for one-off tweaks; use `start-state` when you want a repeatable, version-controlled
  initial state".

### 2. Patch system — `/patch/` and `bspcomp`
- A full patcher framework exists for post-build modifications. Files like
  `patch/save_patches.txt`, `patch/savefile.txt`, `patch/pokemon_functions.txt`,
  `patch/apply_party_patches.txt` are bspcomp-format scripts that can manipulate save
  files. `utils/bspcomp` compiles them. Save migration patches (RTC, Iron Head TM fix)
  are applied via this system at boot time.
- Worth documenting because future tools may want to leverage or extend it rather than
  reimplement save manipulation.

### 3. Existing build-time C utilities — `/utils/`
- `bankends`, `ipspatch`, `xorbanks`, `gbspatch`, `scaninc`, `pokepic`, `rendergifs`,
  `lzcomp`, `bspcomp`, etc. These are auto-invoked by the Makefile during builds. The
  new devtools should never duplicate their functionality — they should call them.

---

## Where the new tools live

- **Directory**: `/tools/` at the repo root. (Not `/utils/` — that's reserved for the
  build-time C utilities. Not `/devtools/` — `/tools/` is the more conventional name and
  shorter to type.)
- **Per-tool layout**: each tool gets its own subdirectory:
  ```
  tools/
  ├── README.md                 # 1-liner index of all tools + how to set up
  ├── _lib/                     # shared Python modules (see below)
  │   ├── __init__.py
  │   ├── symfile.py            # parse pokeprism_nodebug.sym
  │   ├── mapfile.py            # parse pokeprism_nodebug.map
  │   ├── constants.py          # parse constants/*.asm enum files
  │   ├── savefile.py           # read/write/checksum .sav
  │   └── paths.py              # locate ROM/sym/map/sav relative to repo root
  ├── start-state/              # the headline tool
  │   ├── start-state.py
  │   ├── inventory.json        # generated; gitignored
  │   ├── state.json            # last-used state; gitignored
  │   └── presets/              # checked-in example states
  ├── sym-lookup/
  ├── map-inspect/
  ├── sram-diff/
  ├── flag-finder/
  ├── trainer-inspect/
  ├── bank-usage/
  └── build-watch/
  ```
- **Dependencies**: stdlib-only where possible. The start-state TUI needs one external
  package (`questionary` — pure Python, no compiled deps). A `tools/requirements.txt`
  pins it. No virtualenv is mandated; user can `pip install -r tools/requirements.txt`
  globally or in a venv.
- **Entry**: each tool is a runnable script with shebang (`#!/usr/bin/env python3`) and
  `chmod +x`, so `./tools/start-state/start-state.py` works.

---

## The full devtool suite (priorities)

| P  | Tool             | Purpose                                                                      |
|----|------------------|------------------------------------------------------------------------------|
| P0 | `start-state`    | Launch game in arbitrary state. Deep spec below.                             |
| P1 | `sym-lookup`     | Query the `.sym` file: label→addr, addr→label, prefix search. Debugging gold.|
| P1 | `flag-finder`    | Grep `event_flags.asm` + cross-ref where each `EVENT_*` is set/checked in `.asm`. |
| P2 | `map-inspect`    | Parse a `maps/<MapName>.asm` → JSON: warps, NPCs, signs, connections, size.  |
| P2 | `sram-diff`      | Diff two `.sav` files field-by-field using the SRAM symbol layout.           |
| P2 | `trainer-inspect`| Dump trainer parties (species/level/moves/items) from `trainers/*.asm`.      |
| P3 | `bank-usage`     | Pretty-print `contents/bank_ends.txt` with bars; flag near-full banks.       |
| P3 | `build-watch`    | `fswatch` on `*.asm` → `make nodebug` → optional emulator relaunch.          |

Lightweight specs for P1–P3 are sketched at the bottom; only `start-state` gets the
full treatment.

---

## Deep spec: `tools/start-state/`

### Goal
Configure-and-launch a custom game state in **two steps or fewer**:
1. `./tools/start-state/start-state.py` → TUI menu
2. Either "Launch now" (uses last state) or edit a field, then launch.

### Architecture (binary-level)

The game expects an SRAM image with this layout (confirmed from `sram.asm`):
- **SRAM Bank 0** (file offset 0x0000–0x1FFF): scratch, RTC, RNG seed, backup save
- **SRAM Bank 1** (file offset 0x2000–0x3FFF): primary save
  - `sOptions` at 0x2000
  - `sValidCheck1` at 0x2008 (must equal `0x63`)
  - `sPlayerData` (2090 bytes) at 0x2009 — includes `wPlayerName`, money, items, event flags
  - `sMapData` (50 bytes) — includes `wMapGroup`, `wMapNumber`, `wXCoord`, `wYCoord`
  - `sPokemonData` (785 bytes) — `wPartyCount`, `wPartySpecies`, 6× `wPartyMons`, badges
  - `sExtraData` + `sExtraChecksum` (2 bytes)
  - `sChecksum` (2 bytes, at 0x2D0D)
  - `sValidCheck2` (must equal `0x7F`, at 0x2D0F)
- **SRAM Banks 2–3**: boxes (unused by `start-state` v1)

Exact byte offsets are **discovered at runtime from `pokeprism_nodebug.sym`**, not
hardcoded — the .sym is regenerated every build and is the source of truth. We resolve
WRAM symbols like `wPlayerName`, `wMapGroup`, `wPartyMons` to their SRAM mirror by
walking the `sPlayerData`/`sMapData`/`sPokemonData` blocks (which are exact-size copies
of the wram blocks per `sram.asm:67-71`).

The **checksum algorithm** is dead simple (`engine/save.asm:1050-1067`):
```
de = 0
for byte in region:
    e = e + byte
    if carry: d += 1   (the asm uses `adc d; sub e; ld d, a` which equals add-with-carry on the high byte)
```
Reimplement in Python verbatim. Two checksums must be recomputed: `sChecksum` over
`sGameData` (PlayerData + MapData + PokemonData) and `sExtraChecksum` over
`sExtraData`. The game also keeps a **backup save** in Bank 0 — we mirror the primary
to the backup so `VerifyChecksum` doesn't reject and try recovery.

### Two-phase tool flow

**Phase A: Inventory build (first run / when ROM is rebuilt)**

Trigger: `inventory.json` is missing, OR its `built_at` timestamp is older than
`pokeprism_nodebug.sym`'s mtime.

Steps:
1. Parse `pokeprism_nodebug.sym` → dict of `{label: (bank, addr)}`.
2. Parse `constants/map_constants.asm` → list of `{name: "ROUTE_69", id: 0x12, group: ..., number: ...}`.
3. Parse `constants/pokemon_constants.asm` → list of `{name: "BULBASAUR", id: 1}`.
4. Parse `constants/item_constants.asm` → list of items.
5. Parse `constants/event_flags.asm` → list of 1999 flags. Cross-reference with
   `data/events/sane_unused_flags.asm` or similar to mark obviously unused ones (best
   effort; not strictly needed for v1).
6. Parse `constants/move_constants.asm` → moves list (needed for party loadout).
7. Resolve SRAM field offsets for every field we plan to write (see "Editable fields"
   below). Store each as `{label: "wMapGroup", sav_offset: 0x2A65, size: 1}`.
8. Write `tools/start-state/inventory.json`.

Parsing the `.asm` enum files: the `const_def` / `const` pattern is consistent
(`docs/macros-and-constants.md` covers it). One regex-based parser in `_lib/constants.py`
handles all of them. Re-use whatever existing scripts do this if discoverable — initial
search didn't find one, so we write fresh.

**Phase B: TUI + launch (every run)**

1. Load `inventory.json` and `state.json` (or write a default state.json if missing,
   based on `tools/start-state/presets/default.json`).
2. Show a `questionary` menu with the current state summary at the top:
   ```
   Pokeprism start-state

   Current state:
     Player: RED (♂)
     Map:    ROUTE_69 (5, 8)
     Money:  ¥10000   Badges: 0
     Party:  CHARMANDER L5, PIKACHU L10

   > Launch now
     Edit player name / gender
     Edit map / position
     Edit party
     Edit money / badges
     Edit event flags
     Edit items
     Reset to preset...
     Quit
   ```
3. Each edit submenu is also `questionary`-driven, with autocomplete sourced from
   `inventory.json` (so the user can fuzzy-find `ROUTE_69` or `CHARMANDER`).
4. Every successful edit is saved back to `state.json` immediately — Ctrl-C is safe.
5. "Launch now": generates `.sav`, writes it next to the ROM, spawns SameBoy.

### Editable fields (v1 scope)

| Group  | Field             | Source WRAM symbol     | Notes                              |
|--------|-------------------|------------------------|-------------------------------------|
| Player | Name (8 chars)    | `wPlayerName`          | Apply GB charset encoding           |
| Player | Gender            | inside player data     | TBD exact offset from sym           |
| Player | Trainer ID        | (inside `wPlayerData`) | Random by default                   |
| Map    | Current map       | `wMapGroup`+`wMapNumber`| Pair derived from `MAP_*` constant |
| Map    | X/Y coords        | `wXCoord`, `wYCoord`   | Validate ≤ map dimensions if known  |
| Money  | Amount            | `wMoney` (3 bytes BCD) | 0–999999                            |
| Badges | Naljo/Rijon/Other | `wBadges` (3 bytes)    | Bitmask UI                          |
| Party  | 6 slots           | `wPartyCount`, `wPartySpecies`, `wPartyMons` | Each mon: species, level, 4 moves, optional nickname |
| Items  | Bag contents      | `wNumItems`, `wItems`  | id+count pairs                      |
| Flags  | Event flags       | `wEventFlags` (250 bytes ≈ 1999 bits) | Toggle by `EVENT_*` name |

Things explicitly **out of scope** for v1: boxes/PC, day-care, Pokédex seen/caught,
Hall of Fame, link battle stats, Battle Tower state, RTC time. All zero-filled. Can be
added in v2 once we trust the basics.

### Party-mon struct
Per `data-formats.md` and `constants/pokemon_data_constants.asm`, `PARTYMON_STRUCT_LENGTH`
is 48 bytes. We compute stats (HP, Atk, Def, etc.) from species base stats × level
using the game's existing formula (replicated in Python). Level + species + 4 moves +
nickname is all the user needs to provide; everything else (IVs, EVs, current HP =
max HP, status = 0, condition flags) is filled by the tool. EXP table matches the
species' growth rate from `data/pokemon/base_stats/*.asm`.

This is the most code-heavy part of the tool. If implementation gets complex, fall
back to: generate the mon at level 5 then use the symbol-resolved `wPartyMon1Exp`
fields to bump to the requested level by re-running the level-up formula in Python.

### Launching SameBoy

1. Resolve ROM path: prefer `pokeprism.gbc` (debug build with `DEBUG_MODE` — gives the
   user a fallback debug menu in-game). Fall back to `pokeprism_nodebug.gbc`.
2. Compute save path: SameBoy by convention loads `<rom>.sav` adjacent to the ROM, so
   write `pokeprism.sav` or `pokeprism_nodebug.sav` accordingly. **Back up any
   existing .sav first** to `tools/start-state/sav-backups/<timestamp>.sav` — never
   silently overwrite the user's progress.
3. Launch:
   ```python
   subprocess.Popen([
       "/Applications/SameBoy.app/Contents/MacOS/sameboy",
       rom_path,
   ])
   ```
   If SameBoy not at default path, fall back to `open -a SameBoy <rom>`. If neither
   works, print path to ROM and instructions.
4. The user presses A on "Continue" — overworld loads with custom state.

### Files written by the tool
- `tools/start-state/inventory.json` (gitignored) — large, regenerated
- `tools/start-state/state.json` (gitignored) — user's working state
- `tools/start-state/sav-backups/*.sav` (gitignored) — safety net
- `pokeprism*.sav` next to ROM (overwritten on every launch)
- `tools/start-state/presets/*.json` (checked in) — useful starting points
  (e.g., `default.json`, `endgame.json`, `route1-fresh.json`)

`.gitignore` additions: `tools/start-state/inventory.json`,
`tools/start-state/state.json`, `tools/start-state/sav-backups/`.

### Critical files to read during implementation
- `sram.asm` — confirmed SRAM layout (done)
- `wram.asm:2340-3018` — `wPlayerData` through `wPokemonDataEnd` definitions
- `engine/save.asm:1050-1067` — checksum algorithm
- `engine/save.asm:497-646` — load path, what fields the game actually reads on boot
- `engine/intro_menu.asm:233-405` — `Continue` → `FinishContinueFunction` (the entry
  point we're targeting; nothing to modify, just verify it reads from our fields)
- `constants/map_constants.asm` — map ID → (group, number) mapping
- `data/pokemon/base_stats/*.asm` — for stat computation
- `pokeprism_nodebug.sym` — runtime source of truth for all offsets

---

## Lightweight specs for the other tools

### `sym-lookup` (P1)
```
sym-lookup TryLoadSaveFile         # → 0d:5b3f (just an example)
sym-lookup --addr 0d:5b3f          # → TryLoadSaveFile (+ nearest preceding symbols)
sym-lookup --prefix wParty         # → all wPartyMon1*, wPartyMon2*, ...
sym-lookup --wram-only wMap        # filter by region
```
Implemented in `_lib/symfile.py`; thin CLI wrapper. ~50 lines.

### `flag-finder` (P1)
```
flag-finder EVENT_GIVEN_HM03
  → Defined: constants/event_flags.asm:412
  → Set in:  maps/RouteX.asm:88 (setflag), engine/events/foo.asm:43
  → Checked: maps/RouteY.asm:120 (checkflag), engine/events/bar.asm:91
```
Pure grep across `.asm` for `setflag`, `checkflag`, `clearflag`. Indispensable when
you're debugging "why isn't this event firing".

### `map-inspect` (P2)
```
map-inspect ROUTE_69
  → 20x18 tiles, tileset Johto
  → Connections: north→ROUTE_42, south→AZALEA_TOWN
  → Warps: 3 (door @ (5,2)→PlayerHouse, ...)
  → Persons: 4 NPCs
  → Coord events: 1
  → Signposts: 2
```
Parses `maps/<Name>.asm` macros (`warp_def`, `person_event`, `coord_event`, etc.,
documented in `docs/maps-and-events.md`).

### `sram-diff` (P2)
Diff two `.sav` files. Uses SRAM layout from `_lib/savefile.py` to label diffs
(`wMoney: 5000 → 5500`, `EVENT_GIVEN_HM03: 0 → 1`) instead of raw byte offsets.

### `trainer-inspect` (P2)
Dump all trainer parties from `trainers/*.asm` as JSON. Useful for difficulty balancing
or generating party data for tests.

### `bank-usage` (P3)
Pretty wrapper around `contents/bank_ends.txt` (already generated by
`make freespace`). ANSI bars per bank; flag banks >90% full.

### `build-watch` (P3)
File watcher (`watchdog` package) on `*.asm`. On change: invoke `make nodebug`,
optionally re-launch via `start-state`.

---

## Documentation deliverables (`docs/`)

Two new markdown files. Both go under `docs/` alongside the existing 7 docs.

1. **`docs/debug-mode.md`** — documents the *existing* debug menu, the `DEBUG_MODE`
   build flag, and the `/patch/` system. This is for stuff already in the codebase
   that's currently undocumented. Sections:
   - How to build the debug ROM
   - In-game debug menu features (one section per submenu)
   - The `DEBUG_MODE` macro pattern
   - The `/patch/` bspcomp framework (overview only)

2. **`docs/devtools.md`** — documents the *new* `/tools/` suite. Sections:
   - Quick start (install deps, run `start-state`)
   - Per-tool reference (with the table above)
   - Deep dive: `start-state` (the inventory build, the state.json schema, the
     SRAM layout reference, the checksum)
   - Adding a new tool (link to `_lib/` modules)

The `docs/devtools.md` doubles as the spec the user asked for. The `start-state`
section in particular will be richer than this plan, since it'll include the JSON
schemas and exact field tables.

---

## Verification

Per phase:

**Inventory build phase**
- `inventory.json` is generated and parses as JSON.
- Spot-check counts match: 182 maps, 254 Pokémon, 360 items, 1999 event flags.
- A handful of known SRAM offsets match the .sym (e.g., `sValidCheck1` at bank 1 +
  0x008, `sChecksum` at bank 1 + 0xD0D).

**Save-write phase (without launching)**
- Write a default-preset save. Open it in a hex editor; bytes at expected offsets
  match expected values (`0x63` at 0x2008, `0x7F` at 0x2D0F).
- Recompute checksum manually with a one-liner Python script over the relevant range
  → matches the bytes written at 0x2D0D.
- Copy the existing `pokeprism_nodebug.sav` aside, write a freshly-generated default
  save, diff → should differ only in the fields we wrote (and the recomputed
  checksums).

**End-to-end (launch)**
- Run `./tools/start-state/start-state.py`, accept default state (CHARMANDER L5 on
  ROUTE_69 at 5,8), select "Launch now".
- SameBoy opens, main menu shows "Continue" with the player name we set, press A.
- Overworld loads on ROUTE_69 at position (5,8) with CHARMANDER L5 in party.
- Modify state (change map to AZALEA_TOWN), relaunch — game now loads in Azalea.
- Backup .sav files exist in `tools/start-state/sav-backups/`.

**Failure mode tests**
- Corrupt one byte of checksum, launch → game should refuse and fall back to backup
  (which we wrote identically). Both saves valid → game loads either.
- Delete `.sym`, run tool → tool errors with a helpful "run `make nodebug` first".
- Run tool with `pokeprism.gbc` (debug) instead of `pokeprism_nodebug.gbc` — both
  should work because SRAM layout is identical.

**Documentation**
- A reader following `docs/devtools.md` Quick Start can install deps and launch a
  custom state in under 5 minutes.
- `docs/debug-mode.md` enables a reader to build the debug ROM and reach the debug
  menu without prior knowledge.

---

## Implementation order (suggested)

1. Write `docs/debug-mode.md` first (pure documentation of what's there — low risk,
   high information value for everything that follows).
2. Build `_lib/symfile.py`, `_lib/constants.py`, `_lib/savefile.py` with unit-test-y
   smoke checks (parse the real files, assert shapes).
3. Build `sym-lookup` (P1) — exercises `_lib/symfile.py`, gives confidence the parser
   works, useful immediately.
4. Build `start-state` Phase A (inventory build) — exercises everything.
5. Build `start-state` Phase B without TUI first: a `--non-interactive` mode that
   takes a `state.json` path and just writes the .sav + launches. Verify end-to-end.
6. Add the TUI menu layer (`questionary`).
7. Write `docs/devtools.md`.
8. Build P1/P2/P3 tools as time/need allows.

---

## Future work / known v1 limitations

### `--load-map-npcs` (planned)

Today the people-reset clears `wMapObjects[1..]` so the destination map shows
no NPCs. A future flag should *load* the new map's NPCs from ROM instead of
clearing.

Data flow:
1. The secondary map header (12 bytes per `macros/map.asm:101-110`) bytes 9-10
   point to `MapEventHeader`. We already locate the secondary header in
   `_lib/blockdata.py` — same path, different field.
2. `MapEventHeader` layout (from `home/map.asm:ReadMapEventHeader` /
   `ReadWarps`, `ReadCoordEvents`, `ReadSignposts`, `ReadObjectEvents`):
   - `db filler` × 2
   - `db num_warps; warps...`
   - `db num_coord_events; coord_events...`
   - `db num_signposts; signposts...`
   - `db num_object_events; object_events...` ← we want these
3. Each object event is the 13-byte `person_event` macro expansion
   (`macros/map.asm:19-46`): sprite, y+4, x+4, movement, radius nibble pair,
   clock hour, clock daytime, color/function nibble pair, parameter,
   pointer (2 bytes), event flag (2 bytes).
4. To write `wMapObjects[i]` (16 bytes, `MAPOBJECT_*` constants), we synthesize:
   `[OBJECT_STRUCT_ID=-1 or unused, sprite, y, x, movement, radius, hour,
    timeofday, color, param, ptr_lo, ptr_hi, flag_lo, flag_hi, pad, pad]`.
   The `OBJECT_STRUCT_ID` field tracks which active engine slot the NPC is
   bound to; -1 (not visible) is the safe initial value — the engine assigns
   slots as NPCs come into view.

Estimated size: ~80 lines in `_lib/people.py` (new function `load_map_npcs`)
plus a thin parser for the event-header preamble. No new external concepts
beyond what `_lib/blockdata.py` already does.

Default behaviour after this lands: clear-then-load, so teleported maps feel
"alive". `--keep-people` still skips both, for users who want the current
zero-NPC behaviour.

### Other planned items
- TUI on top of `start-state` (`questionary`-driven menu).
- Party/items/event-flag editing in `state.json` (v1 leaves party untouched).
- Connection-aware `wScreenSave` for player positions at map edges (today
  uses zero-padding outside the map — wrong for maps with N/S/E/W connections).
