# Plan: `prism-usage` — RGBDS link-map analyzer

**Status: planned.** Spec only; no code yet. Sub-plan under
[`devtools-plan.md`](devtools-plan.md). Supersedes the one-liner
`bank-usage` row in that doc's priority table.

## Context — why this is needed

Pokeprism is a 2 MB GBC ROM hack laid out across 128 banks (`pokeprism_nodebug.gbc`).
The day-to-day budgeting questions a developer asks are:

- Which banks are nearly full?
- Where's the free space — where should I put this new asset / script / table?
- What's consuming a specific bank? Which sections live there?
- Did my last edit push a bank over the limit?
- What are the largest sections in the ROM?

All of this is sitting in `pokeprism_nodebug.map` (the link map emitted by
`rgblink -m`, regenerated every build, 850 lines for the current build).
Today you either grep it by hand or rely on `make freespace`, which runs
`utils/bankends` (a 60-line C tool) and dumps a flat list of bank ends to
`contents/bank_ends.txt`. That's ROM-only, no section attribution, no RAM
breakdown.

`prism-usage` is a Python CLI that parses the full `.map`, models banks
and sections explicitly, and exposes the data through a small set of
focused subcommands. It joins `prism-sym` and `prism-dev` in the
`pokeprism-devtools` suite.

### Naming

The original draft called the tool `prism-map`. We deliberately renamed
it to `prism-usage`. In pokeprism, "map" overwhelmingly means *game map*
(`maps/<MapName>.asm` — warps, NPCs, tilesets), and a future tool
`map-inspect` (P2 in `devtools-plan.md`) already lays claim to that
namespace. RGBDS calling its link-output `.map` is an unrelated
coincidence we shouldn't bake into the CLI name.

### Relationship to existing tooling

- **`utils/bankends` + `contents/bank_ends.txt`** — we do **not** replace
  these. They're wired into `make freespace` and other contributors may
  rely on the text artifact. `prism-usage` is a richer, interactive
  superset; the C tool keeps its job in the build.
- **`prism-sym`** — no overlap. `prism-sym` parses `.sym` (labels ↔ addresses);
  `prism-usage` parses `.map` (sections, banks, sizes). The draft's
  optional `--sym` cross-reference flag is dropped; if you have an
  address and want a label, that's what `prism-sym --addr` is for.
- **Planned `map-inspect`** — unrelated (game maps, not link maps).

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| CLI name | `prism-usage` | Avoids collision with `map-inspect`. |
| Spec home | `docs/bank-usage-plan.md` | Matches `blockdata-plan.md` naming. |
| `check --max-bank-usage` | **MVP** | Cheap; useful as pre-commit / Makefile guard. |
| `diff old.map new.map` | **MVP** | Killer use-case ("did my edit push bank 23 over?"). |
| `--json` machine output | **deferred** | No consumer today; add when one appears. |
| `heatmap` / `search` from draft | **dropped** | Folded / replaced by shell pipe. |
| Address lookup (`addr`, `--sym`) | **dropped** | `prism-sym` already does this. |
| HTML report | **dropped** | Out of scope for a CLI tool. |

## Command surface (MVP)

All commands auto-locate the `.map` via the existing
`paths.map_path()` helper (release ROM by default, debug ROM with
`--debug`). Pass `--map PATH` to override.

| Command | Purpose |
|---|---|
| `prism-usage` / `prism-usage summary` | Headline stats: ROM used / free / utilization, top-N most-full banks, top-N most-free banks. RAM regions summarized in a one-line tail. |
| `prism-usage banks` | ANSI bar chart of every ROM bank's occupancy (folds the draft's `heatmap`). `--region SRAM\|WRAMX\|...` to show RAM regions instead. |
| `prism-usage bank N` | Section-by-section breakdown of a single bank, with sizes and remaining free space. Bank number accepts decimal (`23`), hex (`$17`, `0x17`), or RGBDS-style (`17` interpreted as hex if it has letters). |
| `prism-usage largest [-n N]` | Top-N sections globally by size (default 20). |
| `prism-usage free` | Banks sorted by free space (descending) — answers "where do I put new data?". |
| `prism-usage section NAME` | Show every bank a named section lives in, with sizes. Multi-bank sections like `engine/battle` span several banks; this surfaces the full footprint. Exact match first, falls back to substring. |
| `prism-usage check [--max-bank-usage P]` | Exit 1 if any ROM bank exceeds threshold P (default 95). One-liner per offending bank. Pre-commit / Makefile-guard friendly. |
| `prism-usage diff OLD.map NEW.map` | Per-bank and per-section deltas between two map files. `OLD` / `NEW` are absolute or relative paths; no auto-location. |

Common flags (where they apply): `--debug` (use the debug ROM's `.map`),
`--map PATH` (override the auto-located file).

Exit codes (matches `prism-sym`):
- `0` — success / passing
- `1` — no results / threshold exceeded
- `2` — usage error (missing file, bad argument)

### Explicitly dropped from the draft spec

- **`heatmap`** — folded into `banks`. Only difference in the draft was the bar character. One command, one job.
- **`search`** — replaced by shell pipe: `prism-usage largest -n 0 | grep battle`.
- **`addr` / `--sym`** — `prism-sym --addr` already covers this.
- **`--json` output** — no consumer today; add when one appears (e.g. CI dashboard, status-line integration).
- **HTML report** — out of scope; the existing devtools are terminal-first by design.

## Architecture

Mirrors the existing `symfile.py` + `sym_lookup.py` split — parser
module + CLI module, clean boundary.

```
src/pokeprism_devtools/
├── mapfile.py        # parser + Bank / Section dataclasses (~150 lines)
└── usage.py          # `prism-usage` CLI dispatcher       (~250 lines)
```

`pyproject.toml` gains one new entry alongside `prism-dev` and `prism-sym`:

```toml
[project.scripts]
prism-usage = "pokeprism_devtools.usage:main"
```

### Data model

```python
@dataclass(frozen=True)
class Section:
    name: str          # e.g. "Map Scripts 5"
    region: str        # ROM0 | ROMX | WRAM0 | WRAMX | SRAM | HRAM | VRAM
    bank: int          # 0 for ROM0 / WRAM0 / HRAM
    start: int         # absolute GB address
    end: int           # inclusive (matches RGBDS's printed range)
    size: int          # bytes (== end - start + 1)

@dataclass
class Bank:
    region: str
    number: int
    capacity: int      # derived from region — see table below
    used: int          # Σ section sizes
    free: int          # capacity - used  (== RGBDS's TOTAL EMPTY)
    sections: list[Section]

    @property
    def utilization(self) -> float:  # 0.0–1.0
        return self.used / self.capacity if self.capacity else 0.0

class MapFile:
    banks: dict[tuple[str, int], Bank]   # (region, number) → Bank

    @classmethod
    def parse(cls, path: Path) -> "MapFile": ...

    def rom_banks(self) -> list[Bank]: ...
    def banks_by_region(self, region: str) -> list[Bank]: ...
    def all_sections(self) -> list[Section]: ...
    def find_section(self, name: str) -> list[Section]: ...   # exact, then substring
```

### Bank capacities

Constants from the GB memory map:

| Region | Range          | Capacity (bytes) |
|--------|----------------|-----------------:|
| ROM0   | `$0000–$3FFF`  |           16,384 |
| ROMX   | `$4000–$7FFF`  |           16,384 |
| VRAM   | `$8000–$9FFF`  |            8,192 |
| SRAM   | `$A000–$BFFF`  |            8,192 |
| WRAM0  | `$C000–$CFFF`  |            4,096 |
| WRAMX  | `$D000–$DFFF`  |            4,096 |
| HRAM   | `$FF80–$FFFE`  |              127 |

Held in a `dict[str, int]`. The current pokeprism map has no VRAM
sections (VRAM is runtime-only) but the parser handles them
unconditionally — if a future RGBDS or build config emits them, they'll
flow through.

### Parser

Regex-driven line scanner over the `.map` file. ~850 lines today, parses
in well under 50 ms. State machine:

1. Skip the `SUMMARY:` preamble (we recompute its values from the
   sections; the printed summary is used as a sanity-check assertion at
   parse-time).
2. `^(\w+) bank #(\d+):` → start a new bank context. Region is the first
   capture (ROM0 / ROMX / WRAMX / …), number is the second.
3. `^\s+SECTION: \$([0-9a-f]+)-\$([0-9a-f]+) \(\$([0-9a-f]+) bytes\) \["(.+)"\]`
   → emit a `Section` attached to the current bank.
4. `^\s+EMPTY: \$([0-9a-f]+)-\$([0-9a-f]+) \(\$([0-9a-f]+) bytes\)`
   → tracked but not stored; derivable from capacity minus section sum.
5. `^\s+TOTAL EMPTY: \$([0-9a-f]+) bytes` → close the current bank,
   cross-check that `capacity - sum(section.size) == total_empty`. Raise
   on mismatch — that would mean either the parser missed a section or
   the map format changed.

Sample input (`pokeprism_nodebug.map:9–24`):

```text
ROM0 bank #0:
    SECTION: $0000-$003f ($0040 bytes) ["RSTs"]
    SECTION: $0040-$0060 ($0021 bytes) ["Interrupts"]
    ...
    EMPTY: $3cc7-$3fff ($0339 bytes)
    TOTAL EMPTY: $0339 bytes
```

The `EMPTY:` lines are a per-gap breakdown of one bank's free space.
Useful for "where exactly is the slack?" diagnostics; out of scope for
MVP but cheap to surface later under `bank N --verbose`.

## CLI shape

### `summary` (default)

```text
$ prism-usage
pokeprism_nodebug.map   (built: 2026-05-29 16:46:58)

ROM     1,904,233 / 2,097,152 bytes used   (90.8%)
        192,919 free across 118 banks

WRAMX   27,707 / 28,672 bytes used   (96.6%)
WRAM0   4,058 /  4,096 bytes used   (99.1%)
SRAM    27,946 / 32,768 bytes used   (85.3%)
HRAM    127  /  127 bytes used      (100%)

Most-full ROM banks
  Bank $0e   $7ff9    7 bytes free   99.96%
  Bank $17   $7ff6   10 bytes free   99.94%
  Bank $15   $7ff4   12 bytes free   99.93%
  Bank $3c   $7fff    1 byte  free   99.99%
  ...

Most-free ROM banks
  Bank $25  5,507 bytes free   66.4% used
  Bank $19    889 bytes free   94.6% used
  Bank $4f    889 bytes free   94.6% used
  ...
```

(Numbers above are illustrative; final formatting can iterate.)

### `banks`

```text
$ prism-usage banks
Bank $00  ████████████████░  98%   825 free
Bank $01  ████████████████░  99%   257 free
Bank $02  ███████████████░░  95%   741 free
Bank $03  ███████████████░░  97%   458 free
...
Bank $25  ██████████░░░░░░░  66% 5,507 free
...
```

ROM by default. `--region SRAM` / `--region WRAMX` for RAM regions.

### `bank N`

```text
$ prism-usage bank 5
Bank $05 (ROMX)
  Used: 16,047 / 16,384 bytes   (97.9%)
  Free: 337 bytes

Sections
  $4000–$5fe4  $1fe5 bytes  Code 4
  $5fe5–$7eb0  $1ecc bytes  Debug Menu
```

### `largest`

```text
$ prism-usage largest -n 5
Section                          Size   Banks
Map Scripts 5                  14,838   $17
Effect Commands (main)         15,239   $0d
Battle Core                    15,119   $0f
Battle Tower data               8,442   $07
Tilesets 1                     14,669   $08
```

### `free`

```text
$ prism-usage free
Bank $25   5,507 bytes free
Bank $19     889 bytes free
Bank $4f     889 bytes free
Bank $25     889 bytes free
...
```

Sorted ROM-bank-only by default. `--region` works here too.

### `section`

```text
$ prism-usage section "Map Scripts"
Map Scripts 1     $0e   4,423 bytes
Map Scripts 2    $12  12,039 bytes
Map Scripts 3    $15  13,158 bytes
Map Scripts 4    $0c   2,074 bytes
...
Total: 11 occurrences, 87,541 bytes across 11 banks
```

Exact match first; substring fallback (same UX as `prism-sym`).

### `check`

```text
$ prism-usage check --max-bank-usage 99
ERROR: Bank $0e exceeds threshold
  Usage: 99.96%   (limit: 99%)
  Used:  16,377 / 16,384 bytes

ERROR: Bank $15 exceeds threshold
  Usage: 99.93%   (limit: 99%)
  Used:  16,372 / 16,384 bytes
```

Exit 0 if all banks pass, 1 if any fail. Multiple failures print one
block per bank, then a single non-zero exit. Default threshold: 95%.
Useful in a git pre-commit hook:

```bash
# .git/hooks/pre-commit
prism-usage check --max-bank-usage 98 || exit 1
```

### `diff`

```text
$ prism-usage diff prev.map pokeprism_nodebug.map
ROM utilization:  +0.3%   (1,901,012 → 1,904,233)

Banks
  Bank $0e   +512 bytes used   (519 → 7)   free   ⚠ now 99.96%
  Bank $17    -64 bytes used   (...)
  Bank $25  +1,024 bytes used  (...)

Sections
  Map Scripts 5            +512    14,326 → 14,838
  Effect Commands (main)   +1,024  14,215 → 15,239
  Debug Battle Tower       -64        235 → 171

New sections   (2)
  Code Foo  $25  +128

Removed sections   (0)
```

The `⚠` flag marks any bank that crossed 95% in the new map (also
configurable via `--max-bank-usage`).

## Critical files

| Path | Why |
|---|---|
| `pokeprism/pokeprism_nodebug.map` | Primary input (sample). |
| `pokeprism-devtools/src/pokeprism_devtools/paths.py` | `map_path()` already exists — debug/release fallback handled. |
| `pokeprism-devtools/src/pokeprism_devtools/symfile.py` | Reference shape for `mapfile.py` (dataclasses, factory parser, `from __future__ import annotations`). |
| `pokeprism-devtools/src/pokeprism_devtools/sym_lookup.py` | Reference shape for `usage.py` (argparse, exit codes, `--debug` flag, no-result fallback). |
| `pokeprism-devtools/tests/test_lib.py` | Where the parser smoke test will live. |
| `pokeprism-devtools/pyproject.toml` | One-line addition under `[project.scripts]`. |
| `pokeprism-devtools/docs/devtools.md` | User-facing reference section to be added **after** the implementation lands (a follow-up PR; this plan only specs). |
| `pokeprism/utils/bankends.c` | Reference C implementation; we do not replace it. |
| `pokeprism/contents/bank_ends.txt` | Generated output of `bankends`; used as a cross-check during verification. |

## Verification

### Parser-level (in `tests/test_lib.py`)

- Parse `paths.map_path()`. Assert it returns ≥1 ROM0 bank, ≥117 ROMX banks, plus the WRAM / SRAM / HRAM regions present in the current map.
- Per-region totals: `sum(bank.used for bank in banks_by_region(R)) == values printed in the .map's SUMMARY: header` for each region. Parser raises on mismatch — the test just confirms no raise.
- Bank-level invariant: for every bank, `capacity == used + free` and `used == sum(s.size for s in sections)`.
- Spot checks against `contents/bank_ends.txt`:
  - Bank `$00` free = `$0339`
  - Bank `$01` free = `$0101`
  - Bank `$3f` free = `$0122`
  - Bank `$3c` free = `$0001` (the tightest bank in the current build)

### CLI-level (manual + lightweight)

- `prism-usage check --max-bank-usage 100` on the current build → exit 0.
- `prism-usage check --max-bank-usage 0` → exit 1 with one failure per ROM bank (every bank is over 0%).
- `prism-usage diff <map> <map>` → empty output, exit 0 (symmetric property).
- `prism-usage bank $3c` → one section, near-zero free space.
- `prism-usage banks` visually matches `cat contents/bank_ends.txt` (bars inverse-proportional to bank-end values).
- `prism-usage section nonexistent_name_xyz` → exit 1, no crash.

### UX

- `prism-usage` (no args) is a useful overview in <1 second.
- `prism-usage bank $3c` accepts both `$3c`, `0x3c`, `3c`, `60` (decimal), and errors helpfully on `999`.

## Implementation order (when this gets built)

1. `src/pokeprism_devtools/mapfile.py` — parser + dataclasses. Verify against the SUMMARY header.
2. Add smoke test to `tests/test_lib.py`. Confirm it passes against the current build.
3. `src/pokeprism_devtools/usage.py` — start with `summary`, then `banks`, then `bank N`. Each command is ~20–40 lines.
4. Add `largest`, `free`, `section` — straightforward iterators over the data model.
5. `check` — small but new exit-code path.
6. `diff` — biggest new piece. Implement after the rest is solid; reuse `MapFile` on both inputs.
7. `pyproject.toml` entry, then `pipx install --force` to land the shim.
8. Update `docs/devtools.md`: add a `prism-usage` row to the status table and a per-command reference section modelled on the `prism-sym` one.
9. Update `devtools-plan.md` to mark the `bank-usage` row shipped (and rename it to `prism-usage` in the priority table).

## Future work / known v1 limitations

- **`--json` machine output** — add when a real consumer appears (CI dashboard, status-line integration, a `prism-dev` TUI panel showing live bank usage between rebuilds).
- **`bank N --verbose`** — surface the `EMPTY:` gap-by-gap breakdown for fragmentation diagnostics.
- **Section-name aliasing / grouping** — collapse `Code 1..15` into a single row in `largest`, with per-bank detail behind `--expand`. Bikeshed-prone; defer until someone asks.
- **Git-aware diff** — `prism-usage diff --vs HEAD~1` would read the previous `.map` from `git show HEAD~1:pokeprism_nodebug.map`. Cheap, useful, but requires the prior build to have committed its `.map` (today they're not tracked).
- **VRAM coverage** — parser handles it; today's map has no VRAM sections, so it's exercised only synthetically. If a future RGBDS or build adds them, surfacing happens automatically.
- **Replacement of `utils/bankends`** — only viable once `prism-usage` is universally installed for everyone touching pokeprism. Not a goal of MVP.
