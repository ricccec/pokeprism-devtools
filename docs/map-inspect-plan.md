# prism-map-inspect — Spec

Inspects all pokeprism maps and reports per-map metadata in a filterable,
sortable terminal table. No ROM required — reads source files only.

Not to be confused w/ `map-inspect (planned)` in `devtools.md`.

---

## Synopsis

```
prism-maps [OPTIONS]
```

Run from anywhere inside the pokeprism checkout. Outputs a table of every
map defined in `constants/map_dimension_constants.asm` with the columns
below.

---

## Columns

| Column | Source | Notes |
|--------|--------|-------|
| `NAME` | `map_dimension_constants.asm` | Bare name, e.g. `CAPER_HOUSE` |
| `W` / `H` | same | Dimensions in blocks |
| `BLKS` | W × H | Total block count |
| `RAW` | `maps/blk/<Name>.ablk` file size | `—` if file missing |
| `LZ` | `maps/blk/<Name>.ablk.lz` file size | `—` if file missing |
| `RATIO` | LZ / RAW | Red if > 100% (LZ expands the file) |
| `SCRIPT` | `maps/<Name>.asm` source bytes | `—` if no script file |
| `NPCS` | `person_event` + `trainer` lines in script | `—` if no script file |
| `USED` | Referenced in `maps/blockdata.asm` | `✓` (green) / `✗` (red) |

---

## Options

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

`--used` and `--unused` are mutually exclusive. All filters compose
(AND logic).

---

## Data sources

All reads are from the pokeprism source tree. `paths.repo_root()` locates
it by walking up from `cwd` until `Makefile` + `main.asm` are found.

### 1. Dimensions

`maps.parse_maps(root / "constants/map_dimension_constants.asm")`

Already implemented in `maps.py`. Returns `list[MapDef]` with `name`,
`group`, `map_id`, `height`, `width`.

### 2. Block data sizes

Scan `maps/blk/`. For each file:
- `*.ablk` (excluding `*.ablk.lz`) → `blk_raw`
- `*.ablk.lz` → `blk_lz`

Match by stripping the extension(s) to get a bare name, then do a
case-insensitive lookup against `MapDef.name`.

Some maps have one file but not the other (e.g. the 3 unused maps have
both; a future map stub may have only one). Handle gracefully — missing →
`None` → rendered as `—`.

### 3. Used set

Parse `maps/blockdata.asm` and collect all names from lines of the form:

```
INCBIN "maps/blk/<Name>.ablk.lz"
```

Store as a set for O(1) lookup. A `MapDef` is "used" if its name appears
(case-insensitive) in this set.

### 4. Script file index

Scan `maps/*.asm`, exclude known aggregate files:
`blockdata.asm`, `map_headers.asm`, `second_map_headers.asm`,
`map_scripts.asm`.

Build a dict keyed by `stem.lower()` (no underscores, no case) →
`Path`. To match a `MapDef.name` (e.g. `CAPER_HOUSE`) to its file
(`CaperHouse.asm`): normalize both sides by `.replace("_","").lower()`.

### 5. NPC count

From the matched script file, count lines matching:

```python
re.match(r"\s+(person_event|trainer)\b", line)
```

No full parse — a line count is sufficient and matches what we computed
manually during analysis.

---

## Data model

```python
@dataclass
class MapInfo:
    name: str
    group: int
    map_id: int
    width: int
    height: int
    blocks: int              # width * height
    blk_raw: int | None
    blk_lz: int | None
    lz_ratio: float | None   # blk_lz / blk_raw
    script_src: int | None   # bytes
    npc_count: int | None
    used: bool
```

---

## Module layout

Single file: `src/pokeprism_devtools/map_inspect.py`

```
collect(root: Path) -> list[MapInfo]
    calls parse_maps(), builds blk/used/script indexes, assembles MapInfo list

render_table(rows: list[MapInfo], *, color: bool) -> str
    auto-sizes columns to content
    color: used=green ✓, unused=red ✗; ratio red if > 100%

main()
    argparse → collect() → filter → sort → render_table() or json.dumps()
```

Entry point in `pyproject.toml`:

```toml
prism-map-inspect = "pokeprism_devtools.map_inspect:main"
```

---

## Expected outputs (from session analysis)

```bash
# 3 unused maps
prism-maps --unused
# → LaurelForestBeach_NoWater, LaurelForestCharizardCaveButton1_BlockData,
#    MoundF1_BlownUp_BlockData

# Tiny maps that expand under compression (ratio > 100%)
prism-maps --max-blocks 20 --sort ratio --reverse
# → HaywardMartElevator: RAW=4, LZ=5, RATIO=125%

# Largest maps by footprint
prism-maps --sort blocks --reverse
# → SeviiIsland1: W=?, H=?, BLKS derived from 1299 raw bytes

# Routes, sorted by size
prism-maps --search Route --sort blocks --reverse

# Machine-readable for scripting
prism-maps --json | python3 -m json.tool
```

---

## Exit codes

- `0` — at least one row printed (or JSON array emitted)
- `1` — no maps matched the given filters
- `2` — usage error or repo not found

---

## `devtools.md` updates needed

1. Status table: `prism-maps` row → `shipped`, update purpose column.
2. New section `## prism-maps` with synopsis + examples (mirrors
   the `prism-sym` section style).
