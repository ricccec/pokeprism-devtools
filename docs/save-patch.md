# The save-file patcher — how a `.sav` is stood on a map

**Status: reference.** This is the standing explanation of what it means to patch
a Gen-2 `.sav` so the game boots with the player standing on a chosen map, why
it is more than writing four bytes, where stock pokecrystal genuinely diverges
from prism, and the two sprite-VRAM bugs that were latent in the patcher until a
cross-map playtest surfaced them. It is drawn from the code in
`src/pokeprism_devtools/shared/overworld/` and `hacks/vanilla/savefile.py`; when
they disagree, the code wins and this doc is stale.

For the user-facing `start-state` flow see [`devtools.md`](devtools.md); for
project status see [`STATE.md`](STATE.md). This doc is the engine-level *why*.

---

## The job, and why four bytes isn't it

A dev wants to preview a map: teleport the player to `(group, number, y, x)` and
boot. The naive patch writes the four position bytes —
`wMapGroup`/`wMapNumber`/`wYCoord`/`wXCoord` — fixes the save checksum, and boots.
It renders **garbage**.

The reason is the save-load path the game runs, `MAPSETUP_CONTINUE`
(`engine/map_setup.asm`). On a normal warp the game rebuilds the whole overworld
from the destination map. On a *continue* (loading a save) it deliberately does
**less**: it reloads map graphics and the sprite-GFX VRAM allocator
(`LoadGraphics` → `RefreshSprites`) but **trusts the saved state** for the tiles
around the player (`wScreenSave`) and the live objects (`wObjectStructs` /
`wMapObjects`). It never re-runs `LoadMapObjects` or `InitializeVisibleSprites`.

So when you overwrite the *coordinates* but leave everything else describing the
*previous* map, `MAPSETUP_CONTINUE` faithfully renders the previous map's tiles
and NPCs at the new position. Two visible symptoms:

- **Wrong tiles** around the player — `wScreenSave` still holds the old map's
  30-byte window.
- **Wrong / ghost NPCs** — `wObjectStructs` and `wMapObjects` still describe the
  old map's objects (and the player renders off-screen).

A patch that stands you on a map must therefore **reconstruct what
`MAPSETUP_CONTINUE` skips**. That is the map rebuild.

---

## The two halves of a patch

`Save.stand_on` (`hacks/vanilla/savefile.py`) does the whole job:

1. **Position** — write the four bytes into their saved SRAM mirror.
2. **Map rebuild** — call the shared `rebuild_map` (needs the ROM to read the
   destination map from). Without a ROM path, only step 1 runs; that path exists
   only to exercise the position arithmetic in tests.
3. **Framing** — recompute the checksums the game verifies (below).

Everything hack-neutral in step 2 lives in `shared/overworld/` and is driven by
**both** vanilla and prism. Only steps 1 and 3 are per-adapter, because that is
where the save *format* actually differs.

---

## Save framing — the one real format divergence

A stock Gen-2 save (`ram/sram.asm`, `engine/menus/save.asm`) is:

- **Game data** spanning three WRAM blocks — player, current-map, pokemon — each
  mirrored byte-for-byte into an SRAM copy (`sPlayerData` / `sCurMapData` /
  `sPokemonData`). Every field a patch writes lives in one of these; the vanilla
  locator `_saved_offset` finds which block contains a WRAM symbol and maps it to
  its save-copy byte.
- **Two validity bytes** `SAVE_CHECK_VALUE_1` (99) / `_2` (127) that a real save
  has written. Their absence is how a fresh/empty SRAM dump gives itself away —
  we refuse to patch a file that lacks them (it would boot to a black screen).
- **A primary checksum** — a plain 16-bit running sum over `sGameData`
  (`sum(data) & 0xFFFF`), which `TryLoadSaveData` verifies before it will load.
- **A full backup copy** in a different SRAM bank
  (`sBackupGameData`/`sBackupChecksum`), read **only if the primary fails**.

**This is where stock diverges from prism, and it is the divergence that stays in
the adapter.** Prism has a *co-verified* extra block (`sExtraData` /
`sExtraChecksum`) checked alongside the primary. Stock's backup is a **fallback**,
not co-verified — the boot never needs it, because a valid primary loads and the
backup is ignored. So porting prism's "recompute both checksums" verbatim would
calibrate to the outlier.

Vanilla instead does what an *in-game save* does: recompute the primary, then
**mirror** the backup — copy the patched primary game-data over
`sBackupGameData`, stamp its two validity bytes, and sum its own checksum. The
boot doesn't require this, but a stale pre-teleport backup would mean a later
corruption of the primary silently reverts the player to the old map, so both
copies are kept consistent exactly as the game leaves them
(`Save._recompute_backup`).

> The port is calibrated to prism, which is the outlier. The save-framing split
> was re-derived against stock pokecrystal, not assumed from prism. See the
> `port-calibrated-to-prism-outlier` memory.

---

## The map rebuild — write-once, shared by both trees

`shared/overworld/rebuild.py::rebuild_map` is the single entry both prism's
`dev_server/apply.py` and vanilla's `savefile.py` call. It is engine-general
Gen-2: it touches only `sav.data` (a bytearray both trees' save objects expose),
takes the `.sav` offsets it writes into as declared data (`SaveOffsets`), and
reads formats through the caller's own `.sym`. It does **not** know which tree it
serves, and it does **not** recompute checksums — that is the one thing the trees
spell differently, so it stays in each adapter.

The steps:

1. **`wScreenSave`** — `blockdata.load` walks `MapGroupPointers` → primary header
   → secondary header to the map's block grid, `compute_screen_save` cuts the
   30-byte window around `(x, y)`, and connected **neighbours** are overlaid so an
   edge position renders the real border blocks instead of void. Written to
   `offsets.screen_save`.
2. **Player + NPC reset** (`people.reset_player_and_clear_npcs`) — the player
   struct is reset to `(x+4, y+4)` (the game's screen-edge `+4`), and unless
   `keep_people` the old NPC slots are cleared.
3. **Load the destination map's NPCs** (`people.load_map_npcs`) from the map's
   `object_events` into `wMapObjects`.
4. **Instantiate the on-screen NPCs** (`people.instantiate_visible_sprites`) —
   for each loaded NPC whose coords fall in the player's window, fill the next
   `wObjectStructs` slot the way `InitializeVisibleSprites` +
   `CopyMapObjectToObjectStruct` would, and bind the map object to it. The
   non-obvious field is **`SPRITE_TILE`**, which must name the VRAM tile the
   rebuilt allocator gave that sprite — see below.

`keep_people` (wired through from the boot) skips steps 3–4: the tiles and player
are refreshed but the save's existing objects are preserved. It exists for
debugging the difference.

---

## Sprite VRAM allocation — the involved part (`spritevram.py`)

`MAPSETUP_CONTINUE` *does* rebuild the sprite-GFX VRAM allocator, so the
`SPRITE_TILE` we write into each instantiated struct has to agree with what that
allocator produces, or the NPC renders from a stale offset (typically as the
player's graphic). `sprite_tiles` reproduces `GetSpriteVTile` by replaying the
whole `RefreshSprites` pipeline (`engine/overworld.asm`):

```
zero wUsedSprites
GetPlayerSprite     -> wUsedSprites[0]              (player always slot 0)
AddMapSprites       -> append the map's sprite pool, deduped from slot 1
LoadSpriteGFX       -> tag each entry with its sprite *type*
SortUsedSprites     -> order by type ascending      (NOT a stable sort — see below)
ArrangeUsedSprites  -> assign cumulative tile offsets across two VRAM tables
```

Tile length comes from the sprite **type** via `GetSpriteLength`: a
`STILL_SPRITE` is 4 tiles, everything else 12. VRAM is `$100` tiles in two tables;
once the first would pass `$80`, allocation spills into the second.

### Sprite id bands — and variable sprites

Every object carries a **sprite id**. `GetSprite` splits ids on two cutoffs the
game defines with `const_next` *jumps* in `constants/sprite_constants.asm`
(`SPRITE_POKEMON` at `$80`, `SPRITE_VARS` at `$f0` in stock — honouring
`const_next` is load-bearing; counting `const` lines reads them far too low):

| id range | kind | type source |
|---|---|---|
| `1 .. SPRITE_POKEMON` | **fixed graphic** (`SPRITE_YOUNGSTER`, `SPRITE_ROCK`) | header byte in the sprite table |
| `SPRITE_POKEMON .. SPRITE_VARS` | **monster icon** (overworld Pokémon) | always walking (`GetMonSprite`) |
| `>= SPRITE_VARS` | **variable sprite** (`SPRITE_WEIRD_TREE`, …) | resolved at runtime — see below |

A **variable sprite** id does not name a graphic. It is an index into a 16-byte
runtime table `wVariableSprites` (`$100 - SPRITE_VARS` = 16 slots, in the player
data block): `wVariableSprites[id - SPRITE_VARS]` holds the *real* sprite id to
use, which is itself usually a fixed sprite — so resolving it is a small recursive
lookup (`type_of`, depth-bounded).

This is how the game lets one map object show different graphics without editing
the map. Route 36's Sudowoodo places `SPRITE_WEIRD_TREE`; script code writes
`wVariableSprites` to reuse that one id for different graphics as the story moves
on. Route 40 and Route 41 place their SWIMMER♂ trainers as
`SPRITE_OLIVINE_RIVAL`, which resolves to a swimmer or to the rival — see below.

**Why it matters to the patcher:** the real sprite's *type* decides its VRAM
*length* (still = 4, walking = 12), and the allocator sorts by type and assigns
cumulative offsets — so getting one length wrong shifts the VRAM tile of every
sprite placed after it. A variable sprite's real type is knowable **only from the
save**, which is why the save's `wVariableSprites` array has to travel into the
shared core (`rebuild_map(..., variable_sprites=...)`, read in vanilla from the
16-byte `wVariableSprites` field).

### Variable sprites carry story state — a stale graphic is not a bug

`wVariableSprites` is **saved game state**, not a property of the map. Scripts
write it as the player progresses, so what a variable sprite *looks like* depends
on how far the save has got. A teleport jumps the player past that progress
without running any of it, so a map can legitimately come up drawing a graphic
the player would never see at that point in a real playthrough.

The clearest case, found on the first live boot: Route 40's two SWIMMER♂ trainers
are placed as `SPRITE_OLIVINE_RIVAL`, and they render as **the rival, standing in
the sea**. Nothing is wrong. `InitializeEventsScript`
(`engine/events/std_scripts.asm`) runs at new game and sets
`variablesprite SPRITE_OLIVINE_RIVAL, SPRITE_RIVAL`; the only thing that flips it
to a swimmer is `maps/OlivineCity.asm`
(`variablesprite SPRITE_OLIVINE_RIVAL, SPRITE_SWIMMER_GUY`), which you reach by
walking into Olivine City. Boot a save that has never been to Olivine onto Route
40 and the rival is exactly what the engine draws. Route 41 places five more of
the same object.

**The game resolves the graphic; we only resolve the length.** The runtime reads
`wVariableSprites` itself when it draws the object — the patcher's use of the same
array is confined to picking the sprite's VRAM *length* so the allocator's
cumulative offsets come out right. So a story-stale graphic is the engine faithfully
obeying the save, and it is a **different failure mode** from the one this whole
mechanism exists to prevent:

| symptom | cause | ours? |
|---|---|---|
| object draws as a plausible *other* character | `wVariableSprites` reflects unreached story state | no — engine is correct |
| object draws as the **player**, or as garbage | `SPRITE_TILE` names the wrong VRAM tile | yes — that's the bug class above |

The quick test that separates them: look up both candidate resolutions in the
sprite table. If they share a type and length — `RivalSpriteGFX` and
`SwimmerGuySpriteGFX` are both `12, WALKING_SPRITE` — then **no** VRAM shift is
possible either way, and a wrong-looking graphic cannot be an allocation error.

**Both halves of that test are load-bearing; equal length alone is not enough.**
Route 37's twin trainers are also placed as `SPRITE_WEIRD_TREE`, so from a save
that hasn't beaten the Sudowoodo they draw as **Sudowoodo** — the same story-state
effect. But here the two resolutions are `SudowoodoSpriteGFX` at
`12, STANDING_SPRITE` and `TwinSpriteGFX` at `12, WALKING_SPRITE`: same length,
**different type**. Since `SortUsedSprites` orders by type, which one the save
names can move the sprite's position in the sort and therefore its tile — so a
story-stale graphic there can coexist with a genuine allocation error, and the two
have to be told apart some other way. `SPRITE_WEIRD_TREE` flips to `SPRITE_TWIN`
in `maps/Route36.asm`, at the end of the Sudowoodo encounter.

A save whose array still matches `InitializeEventsScript` byte for byte is one
nothing has touched, which makes it easy to confirm the patcher left it alone (it
never writes the array — it only reads it). The debug save is in exactly that
state, and that has a consequence worth knowing before trusting a boot from it:
**every set slot resolves to a walking sprite** (`SPRITE_SUDOWOODO`, `SPRITE_RIVAL`,
`SPRITE_ROCKET`, `SPRITE_JANINE`, `SPRITE_LASS` — all 12 tiles). Since the old
buggy `type_of` also assumed walking, **no map booted from this save exercises the
still-vs-walking half of bug 2 below.** What it does still exercise is the
`const_next` parse that puts `SPRITE_VARS` at `$f0`: read that cutoff too low and
fixed ids get misclassified as variable and resolved through the array into
nonsense. Catching the length half live needs a save whose array points a slot at
a *still* sprite.

Standing on a map deliberately **does not invent story state** — the patcher
reconstructs what `MAPSETUP_CONTINUE` skips, and nothing else. Making a map render
as though the player had progressed to it (writing `wVariableSprites`, setting
events) is a separate feature, not a fix, and it is not implemented.

---

## The two bugs this session surfaced (and fixed)

Both lived in `sprite_tiles` and both are the *same class*: the VRAM allocation
placed an on-screen NPC on the wrong tile, so it rendered as another sprite
(often the player). Route 32's genuine debug save (`pokecrystal11_debug.sav`,
player at Route 32 y=4 x=19) exercised both; MtEmberWest — the one map prism was
ever verified on — exercised neither.

1. **Stable sort instead of selection-from-end.** `SortUsedSprites` is **not
   stable**: it selects each position's minimum by scanning from the *end* of the
   list toward the front and swapping on a strict decrease, so a run of
   equal-typed sprites comes out **reversed** relative to input order. A
   convenient Python `sorted()` is stable and produces a different order, which
   moves which sprites land where — and, near the `$80` table boundary, which
   overflow. Fixed by replaying the real selection sort (`spritevram.py`
   ~L233–240).

2. **Variable sprites assumed walking length.** The old `type_of` returned
   `WALKING_SPRITE` for any id `>= SPRITE_VARS`. A variable sprite resolving to a
   *still* rock (4 tiles) was sized as walking (12), over-allocating by 8 and
   shoving every later sprite forward. Fixed by resolving through
   `wVariableSprites` before choosing the length, plus the `const_next` parsing
   needed to find `SPRITE_VARS` correctly.

A third, related bug fixed just before these: **`outdoor_sprite_ids` overran the
pool.** Stock's per-group outdoor sprite lists are a *fixed* 23 entries
(`MAX_OUTDOOR_SPRITES`), not zero-terminated like prism's. Reading until a 0 ran
straight into the next group's list — 170+ ids — which shouldered the map's real
sprites out of VRAM so they fell back to the player's tile. Fixed with the
`count` parameter (23 fixed for stock, `None`/terminated for prism).

That one surfaced on **Route 40**, whose three smashable rocks (`SPRITE_ROCK`, a
*fixed* still sprite — nothing variable about it) all rendered as the player.
Worth keeping the two repros apart, because they are different bugs on different
maps: Route 40's rocks were the pool overrun, Route 32's cooltrainer at (8, 19)
was the sort and the variable-sprite sizing.

### Why prism "worked fine" the whole time

Prism drives the same `spritevram`, so it carried **the same latent bugs** — they
were never surfaced because prism's patcher was only ever spot-checked on **one
save**, MtEmberWest, which happens not to exercise either:

- Its sprite pool has **no variable sprites** (none `>= SPRITE_VARS`), so bug 2
  can't fire.
- Only one NPC is on-screen (`SPRITE_ROCK` → tile 200), and it lands on the same
  tile under **both** the stable and selection sorts, so bug 1 doesn't move it.

So "prism has been working fine" meant "prism was verified once, narrowly, and
never stress-tested across maps with multiple NPCs." The vanilla cross-map
playtest is what finally exercised the bugs. **The fixes improve prism too** (for
prism maps where ties matter it was also wrong; the verified case is unchanged at
200). Prism's variable-sprite handling is still unfixed — `apply.py` passes an
empty `wVariableSprites`, so a prism map with a weird-tree/boulder in its pool
would show the same class of bug. Wiring prism's own `wVariableSprites` through
`apply.py` is the follow-up; it was left out because there is only one prism save
to verify against.

---

## ROM-dialect divergences — `blockdata.MapFormat`

The readers are engine-general, but the *dialect* they read differs per tree and
crosses the seam as declared data (`MapFormat`). Stock's values are the core's
**defaults** (the base engine, the right calibration for the next family tree);
prism overrides them in `hacks/prism/mapformat.py::PRISM_FORMAT`:

| field | stock (default) | prism |
|---|---|---|
| `compressed` | raw `.blk` block bytes | LZ-compressed |
| `coord_event` | 8 bytes | 7 bytes |
| `overworld_map` | `wOverworldMapBlocks` | `wOverworldMap` |
| `sprite_headers` | `OverworldSprites` | `SpriteHeaders` |
| `connection_source` | neighbour-blocks-relative | scratch-relative |
| `outdoor_sprites` | 23 (fixed count) | `None` (zero-terminated) |

Each of these was a real bug found while making stock work: prism's LZ
decompressor returned garbage on stock's raw `.blk`; `coord_event=7` read zero
objects on stock; the symbol names and connection pointer differed; and the
outdoor overrun above. Getting these from a declared format (not a fork in the
reader) is what keeps [[no-hack-branching-outside-mount]] intact.

---

## How to verify a patch (the debug method)

The writer is proven **offline** so the final live SameBoy boot is just a human
confirming a clean map. Two idioms:

- **A genuine game save is the only valid ground truth.** A save the game itself
  wrote while standing on a map holds the *correct* `SPRITE_TILE` per struct.
  Patch a **copy** of a different save to the same map/position and **diff** —
  our tiles must match the game's. A save produced by our own patcher is **not**
  valid ground truth (it would just confirm our own arithmetic). This is how the
  Route 32 sprite bugs were pinned down: a genuine save standing on Route 32 had
  an NPC at (8, 19) with a known tile that our output got wrong.

  **Mind which file that is.** `Player.boot` patches `pokecrystal11_debug.sav`
  *in place*, so after the first boot that filename holds our own output and is
  worthless as ground truth — it only ever looks genuine, because a patched save
  is still a valid save. The real one is whatever `.devtools/sav-backups/` holds
  from *before* the first boot; every later backup is the previous patch's
  output. Anything to be used as ground truth should be copied out under a name
  the rotation won't age out.
- **Rule out story state before calling a live glitch a bug.** A boot lands the
  player somewhere the save never earned, so an object drawing "wrong" may be the
  engine correctly obeying `wVariableSprites` — check that first, with the
  same-length test above, before going near the allocator.
- **Falsify each check first.** Every assertion in `tests/test_vanilla_play.py`
  is shown *failing* before it passes, so a check that can't fail (the classic
  round-trip that only re-reads what the writer wrote) is caught. The original
  four-bytes-only boot round-tripped perfectly and was still wrong — a writer
  that writes too little still round-trips what it does write. See the
  `round-trip-to-verify-writer` memory.

Tests are scripts, run with `./.venv/bin/python tests/<name>.py`.

---

## Known remaining risks

- **`MAPCALLBACK_SPRITES` callbacks.** A map can add map-specific sprites to the
  pool *before* the sort via a `MAPCALLBACK_SPRITES` callback. Route 32 only had
  `MAPCALLBACK_OBJECTS`, so its pool was clean — but a map with a sprites callback
  could still mis-arrange VRAM. Not yet reproduced by the patcher.
- **Prism variable sprites.** As above, `apply.py` passes an empty
  `wVariableSprites`; prism maps that use variable sprites are unfixed.
- **Runtime-only paths ruled out.** We cannot force the game to run
  `InitializeVisibleSprites` (gated on `hMapEntryMethod` at runtime), nor leave
  objects unbound (per-step spawn only binds at the leading edge) — so
  reconstructing the structs ourselves is the only route.
