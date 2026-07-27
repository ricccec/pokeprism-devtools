# Where the adapter seam stands — the current-state map

This is the doc to read to know *what is true now* and *what is left*. The three
plans it replaces as a status source are journey logs and stay as history:

- `adapter-plan.md` — the argument for one frontend / many hacks, and why the
  split is deferred. Its one scheduled piece (the pluggable mount) shipped.
- `polished-crystal-feasibility.md` — the measured experiment. Phases 0–4.
- `family-write-plan.md` — the family write story. Phases 5–10 (history).
- `family-lint-plan.md` — the live plan: Phase 11 and the roadmap past the seam.

Read those for *why* a thing is shaped the way it is. Read this for *what shape
it is in*. When a phase closes or an engineering item is paid, update this file
first.

## The seam, as it exists

`hacks/seam.py` is the contract, provably free of hack names. `hacks/mount.py`
(146 lines) does discovery and the claim loop and nothing else. Each hack ships
a `claim.py` that recognises its own tree and builds its adapter — the same
entry-point path a third-party adapter would use.

Six `runtime_checkable` protocols, each gating a capability rather than a name:

| Protocol | What it covers | Gated on |
|---|---|---|
| `Reads` | the nine read methods every adapter owes | always present |
| `Writes` | the nine write methods (actions, forms, deletion, undo) | `Hack.writes is not None` |
| `Lints` | a tree's own linter, run through the seam | `Hack.ctx is not None` |
| `Plays` | build-and-boot: `make` a ROM, patch a save, open the game | `Hack.plays is not None` |
| `Measures` | `measure` — text in tiles against the engine's VWF | `Hack.measures` |
| `Sketches` | `sketch` — draw the map while you type | reachable only from an action that sets `sketches` |

`Hack` declares `name`, `reads`, `ctx` (a `Lints`, or `None`), `writes` (a
`Writes`, or `None` → read-only), `plays` (a `Plays`, or `None` → unplayable),
`measures`. Everything above the seam gates on these; a missing capability
degrades to a visible absence, never a crash. `plays` was a bare `bool` until the
build-and-boot section below turned it into the protocol it should always have
been.

## Capability matrix — what each mounted tree can do

| | reads | writes | lint (`ctx`) | plays | measures |
|---|---|---|---|---|---|
| **prism** | ✓ | ✓ | ✓ | ✓ | ✓ |
| **vanilla** | ✓ | ✓ | ✓ (dialogue overflow, name + buffer bounds) | ✓ (build ✓; boot rebuilds the map — tiles, objects, sprites, both checksums) | — |
| **polished** | ✓ | ✓ (head anchor, own warps/choices/adders/resize/newmap) | ✓ (dialogue overflow, name + buffer bounds, n-gram reader) | — | — |

The family trees (vanilla, polished) read and write — delete, edit, add,
resize, new-map, and the block scaffolding those ride — and the writes
round-trip to the byte on all real maps. **Both family trees lint too** (the
dialogue-overflow rules below), and **vanilla now builds and boots for real**: a
stock pokecrystal builds, and the studio patches its save to stand you on a map —
the *whole* map, not just the position. It writes the four position bytes and then
rebuilds what `MAPSETUP_CONTINUE` leaves stale: the tiles around you (`wScreenSave`),
the objects (`wObjectStructs`/`wMapObjects`), the on-screen sprites, and both the
primary and backup checksums. That rebuild runs on a shared Gen-2 core
(`shared/overworld/`) prism drives too — written once, not copied into each hack's
`play.py`. The family linters share everything but the width reader, which
polished's Huffman n-gram engine spells differently (see below). The two blanks
left — vanilla `measures`, polished `plays`/`measures` — are the **absences by
design** further down; `measures` is the one permanent one (a font fact), and
polished `plays` is the next family tree the build-and-boot seam is ready for.

## The last engineering item — paid (2026-07-25)

**Phase 9c, category 4 — relocate the prism-bound `wiring/` modules home. Done.**
`wiring/` no longer imports `hacks.prism` at all: the last wrong-direction edge
in the tree is gone.

**Step 1 — the vocabulary split.** The dialect-free editing vocabulary —
`EditError`, `Change`, `same`, `spliced`, `palette_of`, `repainted` — moved into
`wiring/editvocab.py`, a module with no `hacks.prism` import (`same` takes
`as_int` from `shared/constants`; `spliced` types its entry with a structural
`Spliceable` Protocol, naming no hack's `Entry`). Every prism-free consumer —
`mapnew`, `mapresize`, `placement`, `mapedit`, `vanilla/resize` — was repointed
at `editvocab`, severing the `vanilla/newmap → wiring.mapnew → objedit`
import-load leak.

**Step 2 — the move itself.** Eight modules that lived in `wiring/` while being
consumed only by `hacks/prism/` and each other — `objedit`, `scaffold`, `props`,
`removal`, `warps`, `connections`, `mapedit`, `text` — relocated into
`hacks/prism/`, beside the write-adapter files that moved home in category 3.
Their coupling was never the import lines, it was prism's logic: the field
indices *are* prism's twelve-slot `person_event` (`PALETTE=8`, `PERSONTYPE=9`),
which polished does not have; `objedit`'s trainer parser is anchored on prism's
five-arg `trainer` and would skip every family `generictrainer`. A family caller
that reached for `S_X`/`W_Y` next door would have got a wrong answer, not a
crash — which is why they moved rather than stayed.

It was a **move, not a parameterize** (see `family-write-plan.md`, "How category
4 gets paid"): no family caller wants these modules' logic, so an injection seam
would have served a second consumer that does not exist. The import graph did
not change — only the spelling of the paths — so no cycle appeared, and
CLI-extractability survives: a `prism-objedit` CLI wraps `hacks/prism/objedit` as
readily as it would have `wiring/`. `editvocab` stays in `wiring/` (the family
still reaches it for `EditError`); the movers now reach it as `...wiring.editvocab`.

**Verified:** `mapnew`/`mapresize`/`placement` load zero prism modules; the seam
trio, `test_wiring`, `test_scaffold`, `test_events_write`, `test_placement`,
`test_mapnew`, `test_studio`, and `test_regions`/`test_flagalloc` all pass. What
remains of prism showing up when a *family* tree mounts is the mount discovering
every hack through `studio → session → mount` — the mount's job by design, not a
wiring-layer leak. With this paid, the seam has no known structural debt left.

## Landing now — family dialogue-overflow linting (Phase 11; `family-lint-plan.md`)

**Move A — done.** `Hack.ctx` is a lint *capability* (`seam.Lints`): `lint()`,
`mentions()`, `source_lines()`, `invalidate()`. The session lints through it and
never learns which rules a tree runs — prism's `LintContext` runs all of them, a
family ctx runs four (the two overflow rules plus name and buffer bounds), and the session
cannot tell them apart. It branches only on `ctx is not None`, never on a name.

**Move B — done, both family trees.** `hacks/vanilla/lint/` is a
`FamilyLintContext` that flags a dialogue line wider than the 18-tile box
(`text-width`, counting the `#`→POKé kind of expansion the eye misses) or landing
past its last row (`text-rows`). It reads the box from `constants/text_constants.asm`,
tokenises with a family charmap, and counts widths from the engine — all
false-positive-free determinate arithmetic, the exact-fit case the plan argues is
*not* a `Measures.measure` question. Both real trees lint clean (polished across
606 maps and 27,701 visual lines, 2,753 of them packed to exactly 18 tiles and
none over — the metric agrees with the authors to the tile); the rules and their
falsification live in `tests/test_family_lint.py`.

**The one thing that forks — the width reader.** The map *event* format is
identical across the family (so the read mechanics are shared), but the *text
engines* are not: vanilla is classic `dict`+`print_name`→ROM `db`, polished is
`_dtxt`/Huffman `ctxtmap` with an n-gram string table (closer to prism). So the
box, the dialogue parse, the rules and the neutral arithmetic are shared; only
the `Metrics` reader is engine-specific. `hacks/polished/lint.py` is that fork and
nothing else: it resolves a byte through the n-gram table (`data/text/ngrams.asm`)
where an n-gram is one ROM byte but several screen tiles (`#`→`Poké`, `the `→four
tiles), counting each expansion in the un-compressed charmap so an apostrophe
ligature like `'s` is the one tile it draws and not two. It reuses vanilla's box,
parse, rules and `FamilyLintContext` unchanged — the same fork pattern as its
writer. Two shared touch-ups let it in without a branch: `FamilyLintContext` now
takes its `engine_files` as declared data (the guard cannot name one tree's
`home/text.asm`), and the width message names tokens that draw *wider than they
read* (`> len`, not `> 1`), so it calls out `#` without burying it under
polished's every n-gram.

**Move C — done, name bounds (`text-width-name`), both trees.** A line can fit in
testing and overflow the moment someone types a long name: `<PLAYER>` reads as
nothing and draws up to seven tiles (`PLAYER_NAME_LENGTH - 1`). The rule warns
where the *determinate* part still fits but the *worst case* does not — a
`Severity.WARNING`, since a short name is fine, not an error. It is the clean
half of Move C: the name tokens (`<PLAYER>`/`<RIVAL>`/`<MOM>`/`<RED>`/`<GREEN>` in
vanilla, `<PLAYER>`/`<RIVAL>` in polished) sit *inline* in strings, already
tokenised, so all that was added is a declared `bound` per tree and a `worst`
alongside `determinate`. Both shipping trees stay clean under it — and, exactly
like the determinate rule, the tightest real line packs to the tile
(`<PLAYER> obtained a`, 18 tiles at a seven-letter name, LakeOfRage): the metric
agrees with the authors again. The per-tree bound is declared data (`_NAME_BOUND`
maps each name buffer to `PLAYER_NAME_LENGTH`), read from source, seam-clean.

**Move C — done, buffers (`text-buffer`), both trees.** The other half needed the
parser rewrite the name half did not. The family splits a box across separate
`text`/`text_ram` *script commands*: `line "your @"` / `text_ram wStringBuffer3` /
`text "…"` is one visual line, `your <mon>…`, with a name spliced into the middle
of it. The old parse treated each break macro as its own line and `@` as the end
of the box, so the buffer and its suffix fell out as a stray second box and the
mon name measured as nothing on a line it is really the width of. The parser now
walks the cursor the way the engine does — `@` ends a *draw* and hands control
back to the command interpreter, so a `text_ram` and the `text` after it join the
line in progress; a line breaks only at `line`/`cont`/`para`/`next`, a box closes
only at `done`/`prompt`/`page`/`text_end` or the next label, and
`if DEF(FAITHFUL)`/`else`/`endc` branches are measured as siblings, not summed.
A name buffer reached by `text_ram` bounds like an inline `<PLAYER>` (declared
`ram_bound`, read from source); any other buffer is unbounded, since the text
cannot say how long it prints. On that, `text-buffer` warns the one certain
overflow — a line whose fixed text already fills the box has no room for the
spliced buffer, short or long — and stays silent on every buffer it cannot bound,
the same honesty as the determinate rules. Both shipping trees stay clean under
all four rules; the parse rewrite changed only the buffer lines (and correctly
joined a handful of `text_decimal` number-splices), verified line-for-line
against the old parse across both trees.

**The finding channel is now genuinely hack-neutral.** `maplint/__init__` defers
its rule/context imports (all of `hacks.prism`) into `run()`/`main()`, so
`maplint.diagnostics` and the new `maplint.textfit` (the shared fit/row
arithmetic) import without loading prism. That is what lets a family tree's
linter reach the channel without dragging in the tree it is not written against.

## Landing now — family build-and-boot (`plays` becomes a real capability)

`plays` was the last capability still carried as a bare `bool`, and because it was
only a flag the session reached *around* the seam: it imported `dev_server.playtest`,
built a prism `Emulator()` for every session — a read-only family tree included —
and delegated to a `studio/play.py` whose `make` targets, save patcher and ROM paths
were all prism's. Two moves fixed that.

**Move A — cut the seam.** `Plays` is now a protocol like the rest —
`targets()`, `keeps()` (which build lines a quiet build shows), `build()`, `boot()` —
and `Hack.plays` carries a `Plays | None`. Prism's play body moved into
`hacks/prism/play.py` behind a `Player` adapter that holds its own emulator and
resolves its own default target; the session routes through `hack.plays`, names no
`make` target, and instantiates no emulator. `PlayError` sits at the seam beside
`Refused` — the seam's word for a build-or-patch failure, caught by the session
without importing the adapter that raised it. Two neutral pieces came out along the
way: the `make` runner + quiet-grep (`shared/make.py`, every rgbds tree's, not any
hack's) and the SameBoy `Emulator` (`dev_server/emulator.py`, re-exported so
`devplay.Emulator` still reads the same to prism). Prism plays exactly as before
through the new adapter; the seam trio and `test_studio` stay green, and
`test_seam` now conformance-checks the `Plays` surface of every adapter that has one.

**Move B — vanilla builds and boots.** `hacks/vanilla/play.py` is the family
`Player`: it builds a stock pokecrystal and stands you on a map by patching its save.
The build targets are **read from the `Makefile`'s `roms :=` list** — all five ROMs
the tree builds, `pokecrystal.gbc` the default — whose target name *is* the ROM
filename, so no debug/nodebug guess. (This was a hardcoded pair until it bit us: it
omitted three real ROMs, one of them the debug build a boot save had been made for;
reading the list means the studio offers exactly what `make` accepts.) The save
patcher is `hacks/vanilla/savefile.py`, written from scratch — **not** prism's
`savefile.py`, whose RTC trailer and offsets are prism's. It reads the stock Gen-2
layout by symbol from the built `.sym`: the four position bytes
(`wMapGroup`/`wMapNumber`/`wYCoord`/`wXCoord`) mirrored into `sCurMapData`, the two
validity bytes (`SAVE_CHECK_VALUE_1`/`_2`) that say a save is real, and the 16-bit
checksum over `sGameData` the game verifies before it will load rather than fall
back to its backup. Which `(group, number)` a map name resolves to comes from the
same `map_constants.asm` parse the reader already draws the catalog with, so boot
and the map list can never disagree.

**And the boot rebuilds the whole map, on a shared core.** `stand_on` no longer
stops at the four position bytes — after writing them it reconstructs what
`MAPSETUP_CONTINUE` loads the coordinates *over*: the tiles (`wScreenSave`, from the
ROM block grid plus the connected neighbours), the objects (`wObjectStructs`/
`wMapObjects`: player reset, old NPCs cleared, the map's own loaded, the on-screen
ones instantiated with their sprite VRAM), and the checksums (the primary the game
verifies, and the backup copy mirrored to match). This was the boot's one real
*correction*, not a clean deferral — the old code claimed four bytes sufficed, and a
live playtest of `pokecrystal11_debug` found the glitch the round-trip test can't
(a writer that writes too little still round-trips what it does write).

The fix is **written once**: the Gen-2 arithmetic prism worked out in
`dev_server/apply.py` was lifted into `shared/overworld/` (block-data reading,
`wScreenSave` compute, the object engine, sprite VRAM, and a `rebuild_map`
orchestration), and **both** prism and vanilla now drive it — prism's `apply.py`
calls the shared core instead of its own inline copy, byte-identical (its whole
suite stays green). The core names no hack; each tree's ROM *dialect* crosses the
seam as declared data (`blockdata.MapFormat`) — where the calibration warning bit,
stock genuinely diverges from prism and the difference lives in the format, not the
reader: stock stores block data **raw** (`.blk` bytes, not prism's LZ), its coord
event is 8 bytes not 7, its overworld buffer is `wOverworldMapBlocks` not
`wOverworldMap`, its sprite table is `OverworldSprites` not `SpriteHeaders`, and a
connection's source pointer is neighbour-relative not scratch-relative. Prism
declares all of these in `hacks/prism/mapformat.py`; stock's are the core's defaults
(the base engine, the right calibration for the next family tree). The one real
save-framing divergence — stock's backup is a *fallback* copy, read only if the
primary fails, unlike prism's co-verified extra checksum — stays in vanilla's own
`savefile.py`, which mirrors it for consistency the way an in-game save does.

**The toolchain: a declared default, overridable from above.** A stock pokecrystal
wants `rgbds` v1.0.0+, and pins none itself — so `play.py` declares
`_BUILD_ENV = {"RGBDS": ""}`, meaning "use the `rgbds` on `PATH`" (portable to any
set-up pokecrystal machine, and a no-op except that it also drops the *older*
toolchain the launching shell exports for prism). But that is only the **default**:
`build` takes an `env` that, when given, wins entirely, so a user who knows the
machine's `rgbds` better than the adapter does can say so without touching hack code.
The env flows in from above — `Session(build_env=…)` → `Plays.build(env=…)` →
`shared.make.run_make(env=…)` — and each layer stays ignorant of what a toolchain is:
the session carries the user's word, the runner lays the mapping over `os.environ`,
and only the adapter knows which `rgbds` this tree assumes. This de-privileges prism,
which until now was the implicit default every sibling had to escape: prism pins
nothing in code either (`env=None` inherits, which is where its `rgbds` is already
chosen), so both trees now name their toolchain the same way — as data, from below,
overridable from above. What a build *target* is was already this shape (`targets()`
offers, the session passes the chosen one down); the toolchain now matches it.

**Verified — live build, patcher, and resolution.** The Crystal loop's build half is
closed for real, through the studio's own path: `Session.build` (with `build_env` at
its default, and the hostile `RGBDS=0.7.0` exported) relinked a 2 MB `pokecrystal.gbc`
+ `.sym` off the modern `PATH` toolchain — the whole above-the-seam chain
(`Session` → `Plays.build(env=None)` → the adapter's declared default →
`run_make`) proven live, not just the adapter in isolation. `tests/test_vanilla_play.py`
round-trips a save the way writers are checked, and falsifies each check first: a
transposed `y`/`x` reads back different from what was asked, a stale checksum fails
the game's own verification, a save missing its validity bytes is refused; it also
proves the toolchain env is a default a caller can override. Against the
**real** built `.sym` it confirms every symbol the patcher reads is present and that
the game-data block, checksum, and `wCurMapData` mirror all sit where the arithmetic
assumes. The `(group, number)` resolution is checked against the real tree
(`OLIVINE_POKECENTER_1F` → group 1 map 1, `NEW_BARK_TOWN` → group 24 map 4, matching
the source's own trailing comments). The **full rebuild** is now proven against the
real `pokecrystal11_debug` ROM+save next door, dry-run on a copy and falsified
first: on both an outdoor town (Cherrygrove, with N/E connections and NPCs) and an
indoor lab (Elm's), `wScreenSave` comes back byte-for-byte equal to the destination
map's tiles independently computed from the ROM (and *differs* from the stale bytes
a position-only boot would have left — the falsification); `wMapObjects` holds the
destination's own NPCs; the player struct sits on the new tile; the on-screen
sprites are instantiated; and both the primary and backup checksums verify with the
backup mirroring the primary (a corrupted game-data byte is shown failing the check
first). The writer is proven complete — the only step left is the human's: launch
SameBoy and see the clean map.

## Absences by design — none permanent but one, all otherwise deferred

Each is a capability a family tree does not have *yet*. None is debt: none is the
residue of a shortcut, none blocks anything, and each renders as a visible
absence rather than a plausible stand-in. Only one is settled "never." The rest are
future work consciously scoped out, each pick-up-able as its own phase. (The one
item here that *was* a correction rather than a clean absence — vanilla's boot
claiming a completeness it lacked — has been paid: the boot now rebuilds the whole
map, on the shared core, proven above.)

**The one permanent absence — and it is a font fact, not a capability:**

- **Family VWF pixel metrics for dialogue** — map dialogue in both trees renders
  through the fixed-width `PlaceString` path, so the per-glyph pixel widths
  prism's `measure` sums do not exist for it. (Polished ships a menu VWF, but it
  is off the dialogue path.) This is about the dialogue font, forever. It does
  **not** mean the family cannot be checked for overflow — that is fixed-width
  tile counting, scoped just above as Phase 11.

**Deferred — implementable, deliberately out of the seam's current scope. The
full roadmap, grouped, is in `family-lint-plan.md` ("The roadmap past the
seam"); the standing items:**

- **Polished `plays`** — vanilla now builds and boots on the shared `overworld`
  core; polished's save is its own layout (closer to prism's than to stock Gen-2),
  so a polished `Player` over its own patcher — declaring its own `MapFormat` where
  it diverges — is the next pick-up, on the same seam, neutral runner and rebuild core.
- **Prism variable sprites in the boot** — the shared sprite-VRAM allocator now
  resolves a *variable* sprite (id ≥ `SPRITE_VARS`) through the save's
  `wVariableSprites` before sizing it (a still boulder is 4 tiles, a walking NPC
  12, and guessing wrong shifts every sprite placed after it — the glitch that
  rendered Route 32's boulders as the player). Prism runs the same allocator, so
  the *sort* half of that fix already applies to it; the *resolution* half is
  **data-gated** and prism does not yet feed it. `dev_server/apply.py` calls
  `rebuild_map` without `variable_sprites`, so it takes the empty default and
  prism's variable sprites still fall back to walking — the old behaviour. This is
  **not** a seam breach: the fix lives on the neutral side and prism executes it;
  it is dormant only because prism has not handed it that one per-tree input, the
  same way each tree supplies its own `SaveOffsets`. `wVariableSprites` is save
  state, not ROM, so reading it out of *prism's* save layout is the adapter's job —
  one line, passing `off("wVariableSprites")`'s 16 bytes into the `rebuild_map`
  call (`apply.py`). Deferred, not done, because the only prism ground-truth save
  (MtEmberWest) has no variable sprites in its pool, so the fix cannot be verified
  against a real game-written save the way vanilla's was; wiring it blind would
  change prism output on an untestable path. Harmless until a prism map that
  teleports onto a weird-tree/boulder — the same class of glitch vanilla had. See
  `save-patch.md`.
- **Family rewording** — `wiring/text` is still prism-parser-based (one of the
  cat-4 movers); rewording against a fixed-width charmap is a text-wiring project.
- **Connection *adding*** — `wiring/connections` is two-sided; deserves its own
  look. Deletion already refuses on the neighbour's side, with teeth.
- **`EditMap` (attributes tab)** for family trees — not claimed.
- **Family map *sketch*** — the new-map form does not draw the grid while you
  type; that needs a family block renderer to point at, and returning something
  that does not draw would be the exact wrong-absence Phase 4's `absent()` exists
  to prevent.

The prism-only CLIs (`dev_server`, `gfx_view`, `map_inspect`, …, 12 files) are
prism-written by design, gated by `plays` — save-patch, inventory, RTC and the
rest are prism's. Three neutral pieces were lifted out of that corner so a family
`Player` can reach them without pulling prism in: `dev_server/emulator.py` (the
SameBoy process, re-exported through `playtest`), `shared/make.py` (the `make`
runner), and `shared/overworld/` (the Gen-2 map-rebuild core — block-data reading,
`wScreenSave`, the object engine, sprite VRAM, and the `rebuild_map` orchestration,
`blockdata`/`people`/`spritevram` moved out of `hacks/prism/` and parameterized by
a per-tree `MapFormat`). The finding channel (`maplint/`) is no
longer prism-only: its rules are, but the channel itself — `diagnostics` and the
neutral `textfit` — imports without prism, and both family trees now carry their
own overflow `ctx` on top of it. What each tree lints is its own; that the
session cannot tell them apart is the seam working.

## Doc hygiene — the accretion to watch

`docs/` is accreting. Besides the three journey docs, this one, and the live
`family-lint-plan.md` (Phase 11 + roadmap, split out of `family-write-plan.md`
to keep the completed history off the hot path):
`devtools-plan.md` (historical), `bank-usage-plan.md` (spec, no code),
`blockdata-plan.md` (shipped), `map-inspect-plan.md`, `devtools.md` (user
reference). Separately, a `feat/map-studio` docs restructure sits **stashed**
(`git stash@{0}`), unlanded. None of this is on the critical path; it is the
entropy to prune when convenient, not now.

## Tests

Run as scripts with `./.venv/bin/python tests/<name>.py`, not pytest. The
seam-critical trio — `test_seam.py`, `test_vanilla.py`, `test_polished.py` —
passes clean, as do `test_studio.py` and `test_vanilla_play.py` (the family save
patcher and the **full map rebuild**, round-tripped with each check falsified
first: on the real debug ROM+save it proves `wScreenSave`, the objects, the
sprites and both checksums against tiles/objects independently computed from the
ROM, on an outdoor town and an indoor lab). `test_grid.py` and `test_lib.py` now
exercise the lifted `shared/overworld` reader through prism's `MapFormat`, proving
the parameterization keeps prism byte-identical. `test_seam.py::test_falsified`
is the one that earns its keep: it catches the adapter that passes every name
check while answering `None` to everything — the one that mounts, draws an empty
studio, and blames the repo. The three reds on HEAD (`test_maplint`,
`test_eventheader`, `test_lib`) are pre-existing and unrelated — true reports
about the live prism tree, left alone.
