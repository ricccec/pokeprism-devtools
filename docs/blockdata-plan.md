# Plan: `_lib/blockdata.py` and the wScreenSave fix

Sub-plan under [`devtools-plan.md`](devtools-plan.md). Scope: the second of
two new modules we need so that `start-state` can change maps without the
overworld rendering garbage.

## Context — why this is needed

When `start-state` changes `wMapGroup` / `wMapNumber` / `wXCoord` / `wYCoord`
without updating `wScreenSave`, the game's `MAPSETUP_CONTINUE` script
(`engine/map_setup.asm:200-219`) overlays the stale `wScreenSave` onto the
freshly-loaded `wOverworldMap` (`home/map.asm:1257-1294`). The 30-byte area
visible around the player ends up with whatever blocks were there at *save
time on the previous map* — same-tile-on-loop, glitch, or black.

The fix: compute the correct 30 bytes of `wScreenSave` for the target
(map, x, y) ourselves, mirroring what the game would have written if the
player had been standing at that position when they saved.

We already have:
- `_lib/lz.py` — LZ decompressor (168/168 build assets pass byte-for-byte)
- `_lib/symfile.py` — symbol lookup
- `_lib/savefile.py` — .sav read/write/offsets
- `_lib/maps.py` — map name → (group, map_id, width, height)
- `_lib/constants.py` — generic enum parser

Still missing: ROM blockdata reader + the `wScreenSave` window logic.

## What's actually in ROM (from reading the codebase)

The chain `(group, map_id) → blockdata bytes` requires walking three tables.

**1. `MapGroupPointers`** — `maps/map_headers.asm:2`, in ROM at `25:4000`.
An array of 95 `dw` pointers (one per map group). Indexed by `group - 1`.
Each entry points to a `MapGroup<N>` label in bank `$25`.

**2. `MapGroup<N>`** — same file, lines 99+. An array of primary
`map_header` structs (8 bytes each, see `macros/map.asm:91-99`):

| offset | size | meaning                              |
|-------:|-----:|--------------------------------------|
|   0    |  1   | bank of `_SecondMapHeader`           |
|   1    |  1   | tileset                              |
|   2    |  1   | permission                           |
|   3    |  2   | pointer to `_SecondMapHeader`        |
|   5    |  1   | location/landmark                    |
|   6    |  1   | music                                |
|   7    |  1   | (time-of-day << 4) \| fishing group  |
|   —    |  1   | phone-service flag                   |

Indexed by `map_id - 1` within the group. Both group and map id are
1-based — verified in `LoadSpawnPoint` etc.

**3. `<MapName>_SecondMapHeader`** — `maps/second_map_headers.asm`, plus
`macros/map.asm:101-110`. 12 bytes:

| offset | size | meaning                                          |
|-------:|-----:|--------------------------------------------------|
|   0    |  1   | border block ID                                  |
|   1    |  1   | HEIGHT (in **blocks**, not tiles)                |
|   2    |  1   | WIDTH  (in **blocks**)                           |
|   3    |  3   | `dba BlockData` — bank, then 16-bit pointer      |
|   6    |  3   | `dba MapScriptHeader`                            |
|   9    |  2   | `dw MapEventHeader`                              |
|  11    |  1   | connections bitfield (N/S/W/E)                   |

The block data is **LZ-compressed**. The game calls
`FarDecompressAtB_D000` from `home/map.asm:518` in `ChangeMap`.

Decompressed: `height * width` bytes, row-major, one byte per map block.

A "block" is the game's 4×4 metatile unit; the player's (X, Y) coordinates
in `wXCoord`/`wYCoord` are in **tiles** (which equates to a 2×2 grid per
block, since the game positions the player at half-block granularity).

## `wOverworldMap` layout in WRAM

`wOverworldMap` at `00:c800` is `(height + 6) * (width + 6)` bytes. It
has a 3-block padding on each side. `ChangeMap` (`home/map.asm:502-556`):

1. Zero-fills the whole region (line 490-493 of `LoadBlockData`).
2. Writes the `height × width` decompressed block grid starting at row 3,
   column 3 — i.e. offset `3 * (width + 6) + 3` from `wOverworldMap`.
3. `FillMapConnections` overlays the padding rows/columns with neighbor
   maps' edge blocks (if the map has connections).

So: padding regions are **zero** unless the map declares a connection that
fills that edge. For interior positions on indoor maps (CAPER_HOUSE,
houses, gyms — connections=0), padding stays zero.

## `wOverworldMapAnchor` math

From `GetCoordOfUpperLeftCorner` (`engine/warp_connection.asm:343`):

```
anchor_col = (X >> 1) + 1     (for both X even and X odd — same result)
anchor_row = (Y >> 1) + 1
wOverworldMapAnchor = wOverworldMap + anchor_col + anchor_row * (width + 6)
```

I worked the asm out byte-by-byte; both the "increment then halve" (X odd)
and "halve then increment" (X even) branches collapse to the same formula.

## `wScreenSave` write layout

From `LoadNeighboringBlockData` + `SaveScreen_LoadNeighbor`
(`home/map.asm:1257-1294`):

- 5 outer iterations (rows), 6 inner iterations (columns) → 30 bytes total
- Source increment per inner step: +1 (linear `wScreenSave`)
- Source increment per outer step: +6 (rows of `wScreenSave` are 6 wide)
- Destination increment per inner step: +1 (linear `wOverworldMap` from
  anchor)
- Destination increment per outer step: +(width + 6) (next row in
  `wOverworldMap`)

So `wScreenSave[row * 6 + col]` overlays
`wOverworldMap[anchor_row + row][anchor_col + col]` for
`row ∈ 0..4, col ∈ 0..5`.

The fix: compute that exact 6×5 window from the decompressed block grid
(plus zero padding) and write it to `wScreenSave`.

## Module layout

```
tools/_lib/
├── blockdata.py
│   ├── BlockData          (dataclass: bank, ptr, width, height, border, grid)
│   ├── load(rom, sym, group, map_id) -> BlockData
│   ├── compute_screen_save(bd, x, y) -> bytes (30 bytes)
│   └── _read_secondary_header(rom, header_addr, header_bank) -> (...)
```

`tools/start-state/start-state.py` only needs `load` + `compute_screen_save`.
Everything else is internal.

`blockdata.py` depends on `lz`, `paths`, `savefile` (for ROM bank math),
and `symfile`. It does **not** depend on `start-state` — pure utility,
reusable.

## Function signatures

```python
@dataclass(frozen=True)
class BlockData:
    name: str                  # map name (debug)
    group: int                 # 1-based group
    map_id: int                # 1-based within group
    width: int                 # in blocks
    height: int                # in blocks
    border_block: int          # for diagnostics; padding stays 0 in wOverworldMap
    blocks: bytes              # height * width bytes, row-major

def load(
    rom: Path,
    syms: symfile.SymFile,
    group: int,
    map_id: int,
    *,
    map_name: str = "",        # for error messages
) -> BlockData: ...

def compute_screen_save(bd: BlockData, x: int, y: int) -> bytes:
    """Return the 30 bytes the game would have written to wScreenSave
    if the player were standing at (x, y) in this map."""
```

## ROM bank → file offset math

GBC ROM has 16KB banks. Bank 0 is mapped at `$0000-$3FFF`; banks 1+ swap
in at `$4000-$7FFF`. So:

```python
def rom_offset(bank: int, addr: int) -> int:
    if addr < 0x4000:
        return addr                       # bank 0
    return bank * 0x4000 + (addr - 0x4000)
```

`MapGroupPointers` is at `25:4000` → file offset `0x94000`. We resolve
this via `syms["MapGroupPointers"]`, not a hardcoded value, so it stays
correct across builds.

## End-to-end test plan

After writing `blockdata.py`:

1. **Smoke test** — extend `tools/test_lib.py`:
   - `load(rom, syms, group=2, map_id=5)` for CAPER_HOUSE → width=4, height=4
   - `load(...)` for ACQUA_TUTORIAL (group=31, map_id=2) → width=25, height=30
   - Decompressed `len(blocks) == width * height`
   - For CAPER_HOUSE: visually inspect the 4×4 grid (manageable size)

2. **Cross-check against the user's real save**: the user is currently at
   ACQUA_TUTORIAL (31, 2) at position (X=31, Y=12). Compute the
   `wScreenSave` window for that (map, x, y) using our new code, compare
   to the actual `wScreenSave` bytes in their (currently-restored) .sav.
   **They should match exactly** — that's the strongest possible test.

3. **End-to-end in SameBoy**: patch state.json with a different map
   (CAPER_HOUSE or OXALIS_CITY), run start-state, boot in SameBoy. The
   overworld should now render correctly — no glitch, no black.

## Limitations (document, don't hide)

- **Connections**: if the target map has `connections != 0` in the
  secondary header AND the player position is near an edge, the padding
  region overlapped by `wScreenSave` should contain neighbor blocks (which
  `FillMapConnections` fills). v1 writes zeros there, so the very edge of
  the visible area may look wrong for ~1 block until the player walks.
  Most "I want to teleport to X town" cases place the player in the
  interior of the map, far from edges — won't matter in practice.
  Documented as a known limitation; v2 can read neighbor maps.

- **Maps with map-script tile mods**: a few maps run `MAPCALLBACK_TILES`
  that mutate `wOverworldMap` after `LoadBlockData` (e.g., draw a custom
  trainer sprite, flip a switch state). We don't replicate those. Edge
  case; document.

## Implementation order (within this plan)

1. Write `_lib/blockdata.py` with `load` (no `compute_screen_save` yet).
2. Smoke test: load CAPER_HOUSE + ACQUA_TUTORIAL, assert dimensions, dump
   a small grid for sanity.
3. Add `compute_screen_save`. Test against the user's real save (the
   strong test). If it doesn't match, iterate.
4. Commit `_lib/blockdata.py` with tests.
5. Wire `start-state` to call `compute_screen_save` whenever map changes
   (and whenever coords change on the same map — those are also stale).
6. Remove the wScreenSave-zeroing hack from `start-state.py`.
7. End-to-end test in SameBoy. Commit.

## Open questions

- The "user's save cross-check" in step 3 above is the linchpin. If our
  computed `wScreenSave` doesn't match the bytes the game wrote, our
  model of the game's behavior is wrong somewhere — almost certainly in
  the anchor formula or in handling of connection padding. The good news
  is the bytes are right there in the .sav, so the test is unambiguous.

- Whether to also recompute `wScreenSave` when only coords change (no
  map change). I think yes — same-map coord change has the same staleness
  bug. Cheap to always recompute.
