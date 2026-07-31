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
| `Measures` | `measure` — text in tiles against the engine's charmap and widths | `Hack.measures` |
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
| **vanilla** | ✓ | ✓ | ✓ (dialogue overflow, name + buffer bounds) | ✓ (build ✓; boot rebuilds the map — tiles, objects, sprites, both checksums — confirmed live in SameBoy) | ✓ (tiles) |
| **polished** | ✓ | ✓ (head anchor, own warps/choices/adders/resize/newmap) | ✓ (dialogue overflow, name + buffer bounds, n-gram reader) | ✓ (build ✓; boot rebuilds tiles + connected edges + loads the map's NPCs + their VRAM tiles, confirmed live in SameBoy) | ✓ (tiles, n-gram reader) |

The family trees (vanilla, polished) read and write — delete, edit, add,
resize, new-map, **reword**, **edit the map header**, **connect and disconnect
neighbours**, and the block scaffolding those ride — and the writes round-trip to
the byte on all real maps. **Both family trees lint too** (the
dialogue-overflow rules below), and **vanilla now builds and boots for real**: a
stock pokecrystal builds, and the studio patches its save to stand you on a map —
the *whole* map, not just the position. It writes the four position bytes and then
rebuilds what `MAPSETUP_CONTINUE` leaves stale: the tiles around you (`wScreenSave`),
the objects (`wObjectStructs`/`wMapObjects`), the on-screen sprites, and both the
primary and backup checksums. That rebuild runs on a shared Gen-2 core
(`shared/overworld/`) prism drives too — written once, not copied into each hack's
`play.py`. The family linters share everything but the width reader, which
polished's Huffman n-gram engine spells differently (see below), and **both now
measure**: the reword box carries a tile gutter, the same widths the linter reads,
asked while the line is still yours to shorten. **Polished now builds and boots
too, fully**: its blocks are a custom `.ablk.lzp` codec and its object structs
their own sizes, so — unlike prism, which shares the stock-family reader through a
`MapFormat` — polished reads its own ROM dialect on its own side of the seam
(`hacks/polished/lzp.py`, `mapread.py`, `objects.py`), reusing only the genuinely
neutral arithmetic (`compute_screen_save`, and the object-engine writers
parameterised by struct sizes and two strategies crossing as data). The boot
rebuilds the tiles, loads the destination map's own NPCs into `wMapObjects`, and
instantiates the on-screen ones into `wObjectStructs` with the right VRAM tiles and
palettes (Stage 2, landed 2026-07-28; **NPC spawning confirmed live in SameBoy
2026-07-29**). And the edges are filled now too: a spawn against a map border reads
the connected neighbour's real tiles instead of void — polished's `<Label>_MapAttributes`
holds the same 12-byte connection structs stock does (scratch-relative source,
overworld-relative dest), so its own header reader feeds them through the *neutral*
`connection_geometry`/`compute_screen_save`, and the neighbour's grid is loaded by
label just like the current map. Verified byte-for-byte against the genuine save,
which stands at New Bark Town's east edge (Route 27 fills the border column). The
whole capability matrix is now filled in.

The Stage-2 work turned out far smaller than the deferral feared, for one reason:
**polished's VRAM is positional, not a pool.** `GetSpriteVTile` derives a sprite's
tile straight from its object-struct slot (`12 * (slot % 8)`, banked), so there is
no used-sprites allocator to reproduce — the hard, engine-intricate half that gates
prism's variable sprites simply does not exist here. A genuine game-written save
(`polishedcrystal-3.2.3_vanilla_outside.sav`, standing in New Bark Town with all
five NPCs loaded) is the ground truth: it pins the tile formula (player → `$80`,
NPC slot 1 → `$8c`) and the event-walk order (`[10, 9, 125, 105, 135]`, byte-equal
to its `wMapObjects`), and the patcher reproduces the same struct the game did.

`measures` was always two questions wearing one name, and only one of them was
ever absent: *pixel* widths for a proportional dialogue font do not exist (a font
fact, permanent), while the *tile* count is exact in every tree and was merely
unwired. It is wired now, and the flag is no longer a constant — each family mount
asks its own tree whether the charmap and the widths are on disk, because those
*are* the measurement, and answers accordingly. A checkout mid-edit gets no gutter
rather than a wrong one.

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
the `Metrics` reader is engine-specific. `hacks/polished/metrics.py` is that fork and
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
first).

**Confirmed live (2026-07-27) — the loop is closed.** The human step is done: a boot
to Route 32 (4, 19) through `Player.boot` opened SameBoy on a clean map — the player
on the right tile, the destination's own tiles with the north connection to Violet
City filled, and the one on-screen object (map-object slot 8, `SPRITE_COOLTRAINER_M`
at (8, 19), VRAM tile 36) rendering as itself rather than as the player. That is the
last thing `save-patch.md` listed as unproven; **build-and-boot for vanilla is now
verified end to end, offline and on screen.**

The same session turned up one thing that *looks* like a bug and is not, now written
up in `save-patch.md` under "Variable sprites carry story state": Route 40 draws its
two SWIMMER♂ trainers as **the rival**, because they are placed as the variable id
`SPRITE_OLIVINE_RIVAL` and the save has never run the Olivine City script that flips
`wVariableSprites[5]` from its new-game `SPRITE_RIVAL` to `SPRITE_SWIMMER_GUY`. The
engine resolves the graphic from save state; the patcher only resolves the *length*.
A teleport lands the player somewhere the save never earned, so a story-stale graphic
is the engine being right — a different failure mode from a wrong `SPRITE_TILE`, and
one to rule out before touching the allocator.

## Landed — the family new-map form draws (2026-07-27)

The family's `newmap` form now sketches, the way prism's has since Phase 7b: the
grid you pointed at, at the height and width you typed, on the studio's grid
while the form is still open. The mistake it turns into a picture is the one that
otherwise *builds* — a grid that is not `height × width` leaves the engine reading
whatever follows it in the bank as terrain, which shows up in-game as a band of
garbage along the bottom rather than as an error.

**The blocker was stale.** `studio/mapadd.py` said this needed "a family block
renderer to point at". It did not: each family reader has drawn *existing* maps
since Phase 3, through its own `swatches.for_tileset` — vanilla averaging palette
classes, polished reading metatile attributes. All that was missing was the path
from a half-filled form to that renderer.

**What crosses, and why it is a new record.** Prism's action and reader are the
same adapter, so `Action.sketch` is deliberately untyped — "one adapter handing
itself its own record". The family's form is *neutral studio code* and its readers
are not, so the same trick would have meant the studio inventing a per-tree value.
Instead the form answers a declared `panels.Sketch` — grid, size, and the tileset
name as typed — and each family reader turns it into `panels.Blocks` with its own
swatches. The shape is shared because a grid file is bytes in any tree; the colour
forks because a tileset constant means something only to the tree that defines it.
Same split as the lint's width reader.

**One rule for the picture and the write.** `wiring/mapnew._read_grid` became the
public `read_grid`, and the form both draws and writes through it — so a grid the
picture refused cannot then be written, and the grid that drew is the grid that
lands. Two copies of that arithmetic would eventually disagree and both sides
would still assemble. `tests/test_family_sketch.py` asserts the two refuse in the
*same words*, not merely that both refuse.

**Where it deliberately does not refuse:** a tileset that is empty or half-typed
draws the shape uncoloured, because a form is unfinished for as long as you are
typing into it and the shape is the half that catches a wrong height. A tileset
that is *finished and wrong* is refused by name — falling back to tileset 0 would
draw a forest in a cave's colours, which looks perfectly fine and is perfectly
wrong. Verified on both real trees, every check falsified first.

## Landed — the build screen remembers its target (2026-07-27)

`b` offers the play adapter's targets in the order the `Makefile` declares them,
which is not the order anyone wants: on vanilla the first is `pokecrystal.gbc`
and the answer is always `pokecrystal11_debug.gbc`, so every build opened by
correcting a field that had been corrected the same way the build before. The
target that *built* is now kept in the tree it is about — `.devtools/studio.json`,
beside the lint baseline and the save backups (`studio/prefs.py`) — and prefilled
next time.

In the tree because that is what it is a fact about: which ROM you build is a
property of the checkout, and a per-user file would key it by path and be wrong
the moment the checkout moved. Written only **after a build succeeds**, because a
prefilled field is read as an answer rather than a question. Reading is forgiving
(a corrupt `studio.json` costs a prefill, never a build) and writing is not (a
tree that refuses the file says so in the log). The box stays free text and the
offer list is untouched — a `make` target the `Makefile` never enumerates is one
you can type, and having typed it once is the reason to keep it.

The box was also 14 columns, which was never a decision: prism's targets are
`prism` and `nodebug`, vanilla's are 23-character file names. It is now
`width: 1fr; max-width: 30` — 30 is what the longest name needs, as a ceiling
rather than a width, because a flat 30 pushes the Quiet checkbox off the right
edge below 103 columns.

`prefs` joins the seam guard's reader list, so a screen that reaches for it
directly instead of through the session fails `test_the_view_does_not_import_a_parser`.

## Landed — the reword box counts tiles (2026-07-28)

The reword form had no gutter on a family tree: you typed the words and found out
from the linter, later, that `#mon Center near` is sixteen characters and nineteen
tiles against an eighteen-column box. Now the count is on the line, on every
keystroke, in both family trees — the same gutter prism has had.

**The absence was a real refusal answering the wrong question.** `hacks/vanilla/
read.py` said `measure` was "honestly absent … this tree's dialogue is
fixed-width, so the per-glyph pixel widths it would sum do not exist," and that
sentence is true and irrelevant: `panels.Measured` is denominated in *tiles*, and
fixed width is what makes a tile count **exact** rather than a guess. The
permanent absence is the *pixel* width of a proportional font, which nothing on
the dialogue path asks for. This is Phase 11's lesson a second time — a
principled-sounding refusal that had never been measured against the question
actually being asked.

**What it is made of.** Almost nothing new, which was the point: the widths
(`hacks/vanilla/metrics.py`) and the box (`hacks/vanilla/box.py`) are the
linter's, unchanged. `measures.py` walks prose the way `lint/dialogue.py` walks a
parsed file, and both go through one `Metrics.tiles` — a gutter that said sixteen
where the linter said nineteen would be worse than no gutter at all. Polished
forks the one thing it forks everywhere else, the n-gram width reader, and shares
the rest.

**Two things moved to make that true.** The widths and the charmap left `lint/`
for `hacks/vanilla/`, exactly as the box and the parse did when the reword form
needed them — `lint/` holds what only a linter wants, and the widths stopped
being that the moment a second reader appeared. And polished's `lint.py` split:
the n-gram reader is now `hacks/polished/metrics.py`, mirroring vanilla, leaving
`lint.py` as the ten lines of wiring it always was.

**The flag is read off the tree, not written down.** The charmap and the widths
*are* the measurement, so a checkout that has neither cannot measure, and each
family mount now asks (`metrics.engine_is_readable`) and picks a reader
accordingly: `MeasuringReader` when the engine is there, plain `Reader` when it is
not. Two classes rather than one method that sometimes refuses, because the seam
test checks `isinstance(reads, Measures) == hack.measures` **both ways** — a flag
and a method that could disagree are a crash on a keystroke in one direction and a
gutter nobody ever sees in the other. The fixture trees in `test_vanilla.py` and
`test_polished.py` ship no text engine, so they are the degraded direction, tested.

**`Measured`'s two list fields got family answers**, both real rather than empty:
`unknown` is a token the tokenizer fell through on — a typo'd `<PLAYR>` is named
instead of being counted as seven tiles of literal text — and `unbounded` is a
token that prints WRAM nothing can bound. Vanilla has none of the latter (every
buffer its engine splices inline is a name the naming screen caps); polished has
`<TRENDY>`, the phrase the player types at the Goldenrod sign, which is now named
rather than quietly counted as zero.

**Verification.** `test_family_lint.py` grew a third section, and the check that
matters is the last one: the linter's own sample, measured both ways, required to
agree line for line. It is not decoration — it failed the first time it ran,
because the test was measuring a polished tree with vanilla's `dict` widths, and
an n-gram read through the wrong charmap counts as one tile. Every other number
it asserts has a twin in the rule tests above it (`#mon Center near` = 19,
`<PLAYER> obtained a` = 11 + 7 at exactly the box, one tile wider = 3 over at
worst), and each has its falsification beside it.

## Landed — family rewording, on one parse (2026-07-27)

`t` on a vanilla or polished map listed a block's words and then said rewording
was not wired for this tree. It is now, and **both dialects mount the same
class**: they write the same text macros into the same box, and the only thing
that ever forked — how wide a glyph draws — is not something a splice has to
know. `hacks/vanilla/text.py` is the splice and the form; `hacks/vanilla/box.py`
is the window it writes into, moved up out of `lint/` because a writer needs to
know where a `line` lands as much as a linter needs to know where one landed.

**The first move was collapsing the two parses**, which was named here as the
blocker and turned out to be the whole of the risk. `events.prose` walked the
source a macro at a time for the Texts browser; `lint/dialogue` walked it as a
cursor for the overflow rules; they disagreed, and every disagreement was the
naive one being wrong (a buffer splice read as three lines, two boxes under one
label run together, two mail templates listed as dialogue). Harmless while both
only read — fatal the moment something writes, because the block the browser
shows and the block the writer splices have to be the same block. There is one
parse now, `hacks/vanilla/dialogue.py`, and the split it makes instead is by what
an answer costs: structure needs only the file, so the browser still works on a
tree whose engine files are mid-edit; widths and rows need the charmap and
`home/text.asm`, so they stay in the linter. Verified by dumping all **42,976**
rendered lines the linter sees across both shipping trees before and after —
byte-identical.

**A block is identified by the line it opens on, not by its label.** 10 labels in
vanilla and 100 in polished hold two boxes; matching on the label would have
quietly rewritten the first one every time. `TextRef` already carried `lineno`,
so the view passes the record's whole identity through the form rather than the
two fields that happen to be boxes.

**~1.3% of blocks are refused by name rather than written wrong** (46 of 3,277 in
vanilla, 78 of 6,056 in polished): a line spliced out of three commands has no
one line of source to put back; an `if`/`else` block shows two versions of one
line; a jump target inside the box would be moved; and a command sitting between
the macros — polished has four, an `assert` and three `text_decimal`s — would be
*deleted* by a span rewrite that never mentioned it. That last one is checked the
other way round, by asking whether every line in the span is one this writer
emits, so a command nobody has thought of yet is refused rather than eaten.
Re-deriving the split for the spliced ones is possible and is not attempted: it
means deciding where in your new sentence the buffer goes, which is a question
only the author can answer and the form has no way to ask.

The proof is two halves, because either alone is worthless. All **9,209**
acceptable blocks in both trees were reworded with the words they already had and
the file required back byte for byte — and then, because a `rewrite` that returned
its input would pass that perfectly, a word was changed in every one of them and
exactly the line that changed was required to move. Falsifying the round trip
found that dropping the verbatim copy-back is invisible on vanilla and shows up
59 times on polished: the second tree is not redundancy.

## What's left — the pick-up list

The seam has **no known structural debt**; everything below is elective. Ordered
by what it costs versus what it buys, with the detail in the sections that follow.

| | Size | Where |
|---|---|---|
| **1. Prism variable sprites in the boot** | one line, unverifiable alone | Absences — pair it with sprite work |

**Polished `plays` Stage 2 landed 2026-07-28** — the boot now loads the map's own
NPCs and their VRAM tiles, so a family teleport shows the NPCs, not an empty map;
see "Landed", below. That was the last large item; what remains is elective and
small. Four items came off this list in as many days. The decayed VRAM test that
used to
head it is **restored** (2026-07-28) — see Tests, below; it was the one the repo
could not afford to leave, because it guards the sprite-VRAM allocator that (1)
and (2) both go on to change, and it now proves it bites on every run. **Family
`measures` is done** the same day — see "Landed", below. And the `.devtools/`
housekeeping item is **done** (2026-07-28): every `mkdir` that creates the
directory now goes through one `shared/devtools.py` helper that seeds a
self-ignoring `.gitignore` (`*`) as it makes the dir, so `pokecrystal` and
`polishedcrystal` — which track upstream and cannot take a line in a `.gitignore`
we do not own — no longer report `?? .devtools/`. See "Landed", below.

**Not on this list, on purpose:** family VWF *pixel* metrics, which is permanent
and a font fact rather than a gap — not to be confused with the *tile* count, which
is now wired into the reword form; doc accretion and the stashed
map-studio restructure, which are housekeeping; and the three pre-existing test
reds, which are true reports about the live prism tree and are left alone.

## Landed — the family header editor, on a shared splicer (2026-07-30)

`e` on the Attributes tab of a vanilla or polished map used to say editing the
header "is not wired for this dialect yet." It is now, for **both** family trees
off one module — the same way rewording mounts one class on both — because what
forks is data the mount already hands over.

**The header is split across two files**, unlike prism's one `map_header` pair:
`data/maps/maps.asm` holds `map Label, <the tree's own arguments>` and
`data/maps/attributes.asm` holds `map_attributes Label, CONST, border`. An edit
rewrites one line in each, argument by argument, under the rule prism's editor
works by — *an argument you did not change comes back exactly as it was written*.

**The `map` arguments fork between the trees, and that fork already existed.**
Vanilla ends in a fishing group; polished carries a location `sign` and no fishing
group. That is the very `header_fields`/`header_args` the new-map form declares
(`newmap.VANILLA_FIELDS`/`POLISHED_FIELDS`), so `hacks/vanilla/mapedit.py` takes
the same `FamilyNewMap` dialect the mount hands `form("newmap")` and one module
serves both trees. The form is stamped per tree exactly as `newmap_for` stamps
its own — `editmap_for(dialect, set_of, tag)`.

**What is not editable is prism's list unchanged**, with one refusal that gets
*easier*: the label and the map id (`map_attributes`'s CONST, argument 0) are
read-only for prism's reasons (a rename touches every reference; a renumber drops
every `.sav`), the group/height/width are not in these two lines at all, and the
family needs **no conn_flags refusal** — `MAP_CONNECTIONS_*` is macro-computed
from the `connection` lines, never a typed argument, and the border splice leaves
those lines untouched. Validation mirrors prism's `_unknown`: only *changed*
constants are checked (the `MUSIC_NONE` lesson), driven by the field declarations
themselves, so polished's unprefixed-landmark fork is right without a branch.

**The splicer is now shared.** The argument-by-argument macro-line rewrite lived
inside `hacks/prism/mapedit.py`, which the family cannot import; it was genuinely
neutral rgbds syntax, so it moved to `wiring/macroline.py`
(`splice_macro_args`) — the same shape as `wiring/warpdel`'s rule — and **prism
was repointed at it**, byte-identical. `test_macroline.py` guards both the rule
(comment/spacing preservation, prefix-name safety, out-of-range refusal) and that
the extraction changed nothing prism writes. `test_family_mapedit.py` proves the
write on both real trees, falsified first: a single field moved changes exactly
one line, in exactly one file, at exactly one argument, with every other argument
byte-for-byte its old source text — and the border block lands in
`attributes.asm`, not `maps.asm`.

## Landed — family connections, both sides on one splice (2026-07-30)

The Connections tab of a vanilla or polished map used to have no "Add new…" row,
and `d` on a connection refused: "rewriting the neighbour's side is not wired for
this dialect yet." Both are wired now, for **both** trees off one shared module
(`hacks/vanilla/connections.py`) — because the family's `connection` macro is the
*easy half* of prism's.

**The family macro does the work prism does by hand.** The modern macro — which
pokecrystal and polishedcrystal share byte-for-byte — takes four things:
direction, the neighbour's label and id, and the offset along the shared edge.
From that one offset the assembler computes the strip's source and length, the
player's crossing shift, **and the connection-flag nibble** (`MAP_CONNECTIONS_*`).
So where prism's `hacks/prism/connections.py` derives all of that into a
seven-argument macro and rewrites a flag nibble on each side, the family writes
one line per side and lets rgbds expand it. No geometry, no nibble.

**Both sides, always, in one file.** The pair lives in `data/maps/attributes.asm`
under each map's `map_attributes` block, and the neighbour's offset is the
negative of this side's — B sits `k` along A's edge, so from B, A sits `-k`. A
connection the neighbour does not mirror is a wall you can walk through one way,
so `connect` writes both and `disconnect` removes both — and if the far side was
already absent, that is *said*, as a one-way note, not silently repaired. The
macro refuses to assemble unless connections are in north/south/west/east order,
so a new line is spliced into its slot, never appended.

**Crossing the seam.** `FamilyConnect`/`FamilyDisconnect` mirror prism's
`Connect`/`content.Disconnect`; they fork on nothing (both trees write the same
macro), so `fork` injects the adder unstamped rather than stamping an event
anchor onto it, and the write adapter's `deletion` hands back a disconnect for a
connection row. In-place *editing* stays a refusal that now points at delete +
re-add — the same place prism leaves it. `test_family_connections.py` proves it
on both real trees, falsified first: the reciprocal must be present *and* carry
`-k`, disconnect deletes exactly two lines and rewrites nothing else, and
disconnect-then-reconnect returns the file byte-for-byte.

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
  **not** mean the family cannot be measured: fixed width is precisely what makes
  the *tile* count exact, and that count now runs in both the linter and the
  reword gutter. What has no answer is a pixel width for a font the dialogue path
  never uses.

**Deferred — implementable, deliberately out of the seam's current scope. The
full roadmap, grouped, is in `family-lint-plan.md` ("The roadmap past the
seam"); the standing items:**

- **Prism variable sprites in the boot** — the shared sprite-VRAM allocator now
  resolves a *variable* sprite (id ≥ `SPRITE_VARS`) through the save's
  `wVariableSprites` before sizing it (a still sprite is 4 tiles, a walking NPC
  12, and guessing wrong shifts every sprite placed after it — the class of glitch
  that gave Route 32's cooltrainer another sprite's tile). Prism runs the same allocator, so
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

  **The vanilla side is less verified than that reads, and the gap is the same
  one** (found 2026-07-27, `save-patch.md` has the detail). The stock debug save's
  `wVariableSprites` is untouched new-game state, and **every set slot in it
  resolves to a *walking* sprite** (`SPRITE_SUDOWOODO`, `SPRITE_RIVAL`,
  `SPRITE_ROCKET`, `SPRITE_JANINE`, `SPRITE_LASS` — all 12 tiles). Since the old
  buggy `type_of` also assumed walking, **no map booted from that save exercises
  the still-vs-walking half of the fix**; what vanilla's Route 32 proof actually
  pins down is the sort and the `const_next` cutoff parse. So neither tree has a
  ground-truth save that discriminates the length half. Closing it needs a save
  whose array points a slot at a *still* sprite — or Route 37, whose twins are
  `SPRITE_WEIRD_TREE` and whose two resolutions (`SudowoodoSpriteGFX`
  `12, STANDING` vs `TwinSpriteGFX` `12, WALKING`) share a length but differ in
  *type*, which is enough to move the sort.
- ~~**Family `measures`**~~ — **done (2026-07-28)**, see "Landed", below. The
  stated reason for the absence turned out to be answering the wrong question, in
  the same way Phase 11's did.
- ~~**Family rewording**~~ — **done (2026-07-27)**, see above. The blocker
  recorded here — that the family's visual line is not its source line — was
  real, and the answer was to refuse the 1.3% of blocks where it bites rather
  than to re-derive them.
- ~~**Family connection *adding* (and delete)**~~ — **done (2026-07-30)**, see
  "Landed", below. The family macro turned out to be the easy half of prism's:
  four arguments the assembler expands, no flag nibble to write and no geometry
  to derive, so both sides are a one-line splice apiece.
- ~~**`EditMap` (attributes tab)** for family trees~~ — **done (2026-07-30)**, see
  "Landed", below. The blocker recorded here — that the header lives in files this
  adapter only read — was real; the answer was to write both of them, argument by
  argument, on the same neutral splicer prism now shares.
- ~~**Family map *sketch***~~ — **done (2026-07-27)**, see below. The blocker
  ("needs a family block renderer") turned out to be stale: each family reader
  had drawn existing maps through `swatches.for_tileset` since Phase 3.

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

## Landed — `.devtools/` hides itself from the tree that owns it (2026-07-28)

The tools write into `<hack>/.devtools/`: renders, the lint baseline, the new-map
specs, the save backups, `studio.json`. Only prism's `.gitignore` knew —
`pokecrystal` and `polishedcrystal` reported `?? .devtools/` forever, and they are
the two trees that **track upstream**, where a line added to a `.gitignore` we do
not own is a permanent local diff that conflicts on every rebase.

The fix was not to edit those files by hand but to stop needing them: write
`.devtools/.gitignore` containing `*` at the moment the directory is created. It
ignores its own contents *and itself* (`git check-ignore` names line 1 as the rule
that hides the file), so the whole directory leaves `git status` with nothing
tracked and nothing to commit. `.git/info/exclude` does the same job and was
rejected: it means reaching into git's private directory, and doing it correctly
means resolving `git rev-parse --git-dir` first, because `.git` is a *file* in a
worktree or a submodule.

The work is one `shared/` helper — `devtools.make_devtools_dir(root, *sub)` —
that mkdirs, seeds the ignore once if absent (never overwriting: it may have been
edited to un-ignore `presets/`), and returns the path. Every call site that
created the directory itself now routes through it: `studio/prefs.py`,
`maplint` (baseline), `gfx_view`, `mapview`, `metatiles`, `map_new` specs,
`vanilla/play.py`'s sav-backups, and the prism entrypoints `dev_server/cli.py`,
`dev_server/test_maps.py`, `hacks/prism/play.py`. One code path making both means
the ignore and the directory cannot drift. (Two `mkdir`s stay direct on purpose:
`dev_server/playtest.py`'s backup — a prism-only path whose `.devtools/` its
entrypoint has already seeded — and the generic `shared/edits.py`, which only ever
touches `.devtools/` on prism's own newmap path, where prism's `.gitignore`
already covers it.) A bare `*` also hides `.devtools/presets/`, which `devtools.md`
calls check-in-able — not a regression, since prism's own `.devtools/*` already
ignores them with no negation, and the negated variant puts `?? .devtools/` back
for the two trees that have no presets.

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
ROM, on an outdoor town and an indoor lab). **One trap about that save:**
`Player.boot` patches `pokecrystal11_debug.sav` *in place*, so after the first boot
that file holds our own output and is no longer ground truth — and it still passes
every validity check, because a patched save is a valid save. Game-written saves are
preserved in the pokecrystal tree under `.devtools/sav-backups/GENUINE-*.sav` —
`route-32`, `new-bark-town` (both outdoor, the VRAM fixtures),
`players-house-1f` and `players-house-2f` (indoor); every *timestamped* backup
after the first is a previous patch's output. Anything used as ground truth has to
be copied out under a name the rotation won't age out — it only ever writes
`pokecrystal11_debug-<timestamp>.sav`, so the `GENUINE-` prefix is what keeps these.

**Polished's Stage-1 boot has its own two (2026-07-28), both provable without a
game save.** `test_lzp.py` decompresses every one of the 452 built `.ablk.lzp`
block files and asserts it equals the plain `.ablk` sibling the build compressed —
ground truth that ships in the tree, so the custom codec is verified byte-exact
across every map, falsified against a wrong map's bytes. `test_polished_play.py`
proves the writer offline: the tiles half checks `mapread`'s ROM-decompressed
`wScreenSave` against the same window from the plain `.ablk` on 200 maps, and the
save half runs `stand_on` on a *synthetic* save sized to the real SRAM layout —
real offsets from the real `.sym`, polished's own 34/14/21 struct sizes — proving
the position, the player-struct `+4`, the cleared NPC slots and both checksums,
with a tampered-byte falsification. The genuine round-trip and the clean SameBoy
boot wait on a hand-made polished save (the one input Stage 1 cannot synthesize).

**That cost one test its teeth, and the teeth are back (2026-07-28).**
`test_visible_sprites_get_the_right_vram_tile` used to read the *working* debug
save's current map and compare our computed VRAM tiles against the `SPRITE_TILE`
in its `wObjectStructs` — sound only while those structs are the **game's**. They
stopped being: `instantiate_visible_sprites` writes that field from the same
`sprite_tiles` output the test then checked it against, so on a save any boot had
touched the check was **self-confirming and could not fail** — while still printing
`[OK]`, the worst version of the problem. Exactly the trap
[[round-trip-to-verify-writer]] names: a check that only re-reads what the writer
wrote.

It now runs on **declared fixtures** in `.devtools/sav-backups/`, saves the game
wrote and no boot has touched: `GENUINE-route-32.sav` and
`GENUINE-new-bark-town.sav`. Both were made by warping in, walking through a door
and back, then saving in-game — `MAPSETUP_WARP` runs `LoadMapGraphics` (rebuilding
the VRAM allocation) *and* `LoadMapObjects` (writing the structs), where the
patched-boot `MAPSETUP_CONTINUE` runs the first and literally calls
`LoadMapAttributes_SkipObjects` for the second. That asymmetry is both why the
patcher exists and why a door launders a patched arrival back into ground truth.
A map *edge* would not do: `MapSetupScript_Connection` omits `LoadMapGraphics`, so
it never rebuilds the allocation.

Two properties keep it from rotting the same way twice. **Provenance is checked,
not assumed** — `_engine_wrote_the_structs` re-runs our own patcher on a copy at
the fixture's own position and demands bytes the fixture has set where ours are
zero (the animated remainder the engine fills on its first frame). The fingerprint
is *derived from the writer*, so it cannot go stale when the writer grows a field,
and the guard is itself falsified: a deliberately patched fixture must be refused.
And the comparison is **falsified every run** — five wrong allocations (the
historical zero-terminated pool, unresolved variable sprites, the pool in sorted
rather than ROM order, a pool missing an id, the wrong player sprite) are fed to
the real `sprite_tiles` and each must be caught by at least one fixture, so a
suite that has stopped biting fails loudly. The two fixtures are complementary,
which is the argument for keeping both: only Route 32 catches unresolved variable
sprites (its group's pool carries id 244 → Sudowoodo, `STANDING` not walking — the
same 12-tile length, so it is the *sort order* that moves, 14 tiles' worth), and
only New Bark Town catches the pool arriving pre-sorted. The original observation
is back with it: sprite 35 → tile 36 on Route 32. **The one gap left:** no fixture
sizes a still sprite as a walking one, because neither map has a still sprite on
screen ahead of its NPCs — a busier outdoor save would close it.
`test_family_sketch.py` covers the new-map form's picture on both real family
trees — that it draws at the asked size in the tileset's colours, that each way
it can be wrong is refused *by name*, and that the picture and the write refuse a
bad grid in the same words (one `read_grid`, not two that drift).
The remembered build target is covered on both sides of the seam:
`test_studio.py::test_the_target_you_built_with_comes_back` for the store (per
tree, survives a new session, leaves other keys alone, and a corrupt file costs a
prefill and nothing else), and `test_studio_tui.py::TestBuildScreen` for the box
itself, on a temp copy of a real repo.
`test_family_lint.py` covers both readers of the family's widths — the rules, and
the reword gutter added on 2026-07-28. Its last check is the one that keeps them
one arithmetic: the linter's own sample measured through the rules *and* through
the gutter, required to agree line for line. That check is not decoration; it
failed the first time it ran, on a polished tree being measured with vanilla's
`dict` widths, which reads every n-gram as a single tile.
`test_family_text.py` is the rewording suite, and it is deliberately two checks
that fail in opposite directions: every acceptable block in a stock pokecrystal
*and* polishedcrystal reworded with its own words must come back byte-identical
(9,209 blocks), and every one of them with a word changed must move **exactly**
the line that changed — because a `rewrite` returning its input passes the first
one perfectly. Both were falsified before being believed, and the falsification
that matters is that dropping the verbatim copy-back is invisible on vanilla and
breaks 59 blocks on polished: the second tree is doing work, not repeating the
first. The synthetic half covers what the trees do not contain enough of — the
macro an *added* line gets when `line`'s row is taken, the refusals by name, and
the stray command a span rewrite would have eaten.
`test_grid.py` and `test_lib.py` now
exercise the lifted `shared/overworld` reader through prism's `MapFormat`, proving
the parameterization keeps prism byte-identical. `test_seam.py::test_falsified`
is the one that earns its keep: it catches the adapter that passes every name
check while answering `None` to everything — the one that mounts, draws an empty
studio, and blames the repo. The three reds on HEAD (`test_maplint`,
`test_eventheader`, `test_lib`) are pre-existing and unrelated — true reports
about the live prism tree, left alone.
