# Devtools Reference

User-facing reference for the Python devtools under [`/tools/`](../tools/).
For the rationale, roadmap, and architecture decisions, see
[`devtools-plan.md`](devtools-plan.md). For the in-codebase debug menu and
the `DEBUG_MODE` build flag, see [`debug-mode.md`](debug-mode.md).

## Setup

Python 3.10+ is required. The shared library (`tools/_lib/`) is stdlib-only;
no `pip install` step is needed yet.

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
| [`start-state`](#start-state-planned) | planned    | Launch the game in an arbitrary state without rebuilding.        |
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

## start-state (planned)

The headline tool — launches the game in an arbitrary state (team, map,
flags) by patching a `.sav` and handing it off to SameBoy. See the deep
spec in [`devtools-plan.md`](devtools-plan.md#deep-spec-toolsstart-state).

This section will be filled in once Phase B (the non-interactive launcher)
is shipped.

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
