# Phase −1 — the product survey · findings

**Closed 2026-08-01. No production code changed.** The phase's own record; the
one-line summary of each finding is in `refactor-STATE.md`, which indexes every
phase. `refactor-plan.md` carries the argument.

Every claim here is either something read in a file named here, or something
measured with the probe described beside it. Counts carry the date they were taken
— re-verify the ones your phase leans on (plan → "Starting a session", step 1).

## Findings — the same list as the index, each linked to its evidence

- Import greps were wrong three ways; a path literal measures hack-specificity
  better → [The grep was wrong in both directions](#the-grep-was-wrong-in-both-directions)
- `maps.py` is a Gen-2 fact — its catalog walk reads all three trees unchanged
  → [Measurement 1](#measurement-1--the-catalog-walk-is-the-familys)
- `blobsizes.PRIMARY_HEADER_GROWTH` was 8; prism's macro emits 9 bytes — **fixed
  2026-08-01** → [Measurement 2](#measurement-2--primary_header_growth-is-8-the-macro-emits-9)
- The macro-line reader was hand-rolled 15 times, with three different answers —
  the label-anchored ones **lifted 2026-08-01**; the rest ask a different question
  → [Measurement 3](#measurement-3--the-macro-line-reader-written-a-dozen-times)
- Prism's header read path and its own write path disagreed about arguments —
  **fixed**, they share one anchor
  → [Measurement 3](#measurement-3--the-macro-line-reader-written-a-dozen-times)
- **B ships separately** — no CLI needs it; every adapter does, and must not reach C
  → [Resolved: B ships separately](#resolved-b-ships-separately)
- Every CLI got an (a)/(b)/(c) call; `mapview` is the strongest candidate for (b)
  → [The three-way call, per CLI](#the-three-way-call-per-cli)
- `dev_server`'s service half *is* prism's `Plays`, wearing a CLI's name
  → [Per-module verdicts](#per-module-verdicts)
- `maplint/diagnostics.py` is contract vocabulary — two family adapters import it
  → [Per-module verdicts](#per-module-verdicts)
- `dev_server/emulator.py` is already neutral: both family adapters import it
  → [Per-module verdicts](#per-module-verdicts)
- The LZ codec fork is legitimate; one duplicated helper, deliberately not scheduled
  → [Incidental — the LZ codecs](#incidental--the-lz-codecs-asked-about-and-answered-no)
- `rules_geometry.py` was deferred to Phase 5 rather than answered without evidence
  → [Per-module verdicts](#per-module-verdicts)

Not findings, and further down: [reference measurements](#reference-measurements--not-this-phases-findings)
that pre-date this phase — the naming census, and the sizes Phases 1, 4 and 5 will
want.

## What was asked

Per module: **is this a prism fact or a Gen-2/pret fact?** An import edge proves a
dependency exists, not that it is load-bearing or correct. Output: a product
assignment per module, a three-way call per CLI, and the B-vs-C decision.

## The grep was wrong in both directions

**The grep was wrong in both directions, and worse than for `render.py`.** The
dependency table the plan carried was assembled from static imports; it has since
been deleted from `refactor-plan.md` because of what follows. Two of its rows did not
survive an import-time trace, and one CLI is four times more prism than its row said:

| CLI | the table said | actually reaches (import-time) |
|---|---|---|
| `metatiles` | `render` | **nothing** — the `render` import is inside two functions (Pillow is lazy) |
| `map_show` | `blobsizes`, `mapspec` | **ten**: `blobsizes blocksrc eventheader eventmodel mapformat maps mapsource mapspec render swatches` |
| `maplint` | (not listed) | **nothing** at import; every rule module is imported inside `run` |

And the reverse error: `gfx_view` and `metatiles` reach *less* prism through
imports than they contain. Both hardcode prism's tileset file naming in their own
bodies — `tilesets/NN_metatiles.bin`, `gfx/tilesets/NN.2bpp`, `tilesets/bg.pal`,
where the family names tilesets by name (`battle_factory.2bpp`) — and `metatiles`
additionally reads `maps/blockdata.asm`, `maps/map_headers.asm` and
`constants/tilemap_constants.asm` straight off disk. An import edge is not the
unit of hack-specificity; **a path literal is.**

### Per-module verdicts

| module | LOC | fact | product | why |
|---|---|---|---|---|
| `hacks/prism/render.py` | 338 | **both** | split: pipeline → **A**, tables → **D** | prism-specific as written (hardcoded `_TILESET_TUNOD`/`_ESPO_FOREST`/`_OLCAN_ISLE`, a `_COLOR_TABLES` block off prism's `engine/color.asm`, loads through `PRISM_FORMAT`) welded to a neutral Gen-2 pipeline (`_read_or_lz`, `_png_to_2bpp`, `parse_pal_file`, `decode_2bpp_tile`, `_composite_block`, `render_tileset_sheet`). The survey adds two more to the prism side: `load_tileset_files` (prism's numeric tileset naming) and `get_map_palettes` (transcribes `LoadMapPals`) |
| `hacks/prism/maps.py` | 92 | **Gen-2** | **A** | the catalog walk is the family's, unmodified; see the measurement below |
| `hacks/prism/mapsource.py` § `enclosing_section`, `section_banks` | ~40 | **pret/RGBDS** | **A** | `SECTION` membership and the linker-script format are RGBDS, not prism — pokecrystal's `layout.link` has the same syntax; only the path (`contents/romx.link` vs `layout.link`) is prism's. Belongs next to `shared/mapfile.py`, which already parses the *other* RGBDS artefact |
| `hacks/prism/mapsource.py` § header/path parsers | ~250 | **prism** | **D** | `map_header`/`map_header_2` is prism's old-pret two-header layout; the family split the same facts across `data/maps/maps.asm` + `data/maps/attributes.asm` years ago. The *field list* is prism's and stays. The *mechanic* is not, and is duplicated a dozen times — see "The macro-line reader", below |
| `hacks/prism/mapspec.py` | 259 | **prism** | **D** | bank placement. `AUTO`/`INTO`/`BANK`, the `"<Kind> <Label>"` section convention, `romx.link` pinning, and a field list that is prism's two header macros argument for argument. Nothing here is a question pokecrystal has — it is not 91% full and does not pin sections by hand |
| `hacks/prism/blobsizes.py` | 49 | **prism** | **D** | the byte sizes of prism's own macros, plus `utils/lzcomp` (the family builds `tools/lzcomp`). One of the three numbers is wrong — see below |
| `dev_server/emulator.py`, `launcher.py` | 216 | **Gen-2** | **A** | "launching a Game Boy ROM and killing the last window is the same whether the ROM is prism's or a stock pokecrystal's" — and that is no longer a claim: `hacks/vanilla/play.py:26` and `hacks/polished/play.py:27` both already import `dev_server.emulator`. Two family adapters depend on it today |
| `dev_server/apply.py`, `inventory.py`, `playtest.py` | 1,062 | **prism** | **D, and specifically (a)** | this *is* prism's `Plays` implementation. `hacks/prism/play.py` (146 LOC) is a wrapper over it — the adapter imports the CLI package, not the other way round. The neutral half was already extracted: `shared/overworld/rebuild.py` says so in its header |
| `dev_server/cli.py`, `tui.py`, `test_maps.py` | 1,295 | **prism** | **D, (c)** | two front ends and a sweep script over the service above. Phase 4's `DevServer` split is unaffected by which repo they land in |
| `maplint/diagnostics.py` | 103 | **Gen-2** | **B** | `Diagnostic`, `Severity`, `apply_suppressions` and the `; maplint: ignore[…]` channel. Three consumers today and only one is prism's: `hacks/vanilla/lint/context.py:23`, `hacks/seam.py:34` (the `Lints` protocol's return type) and `studio/session.py:41`. This is contract vocabulary filed inside a prism CLI |
| `maplint/textfit.py` | 33 | **Gen-2** | **A** | the width comparisons themselves; `hacks/vanilla/lint/rules.py:25` already imports it |
| `maplint/context.py` + the seven prism rule modules | 1,546 | **prism** | **D** | Phase 5's subject, unchanged. Listed here only so the package's split is on one page |
| `maplint/rules_geometry.py`, `__init__.py` | 435 | **untested** | defer to Phase 5 | prism-free by import, but both reach prism through `.context`. Whether the geometry rules are Gen-2 facts is the Phase-5 question and evidence for it was not gathered here |
| `usage`, `sym_lookup` | 592 | **pret/RGBDS** | **A** | unchanged from the plan; confirmed — neither imports any `hacks/` module, at import time or lazily |

### Measurement 1 — the catalog walk is the family's

**Not prism's — run on all three trees.** The
plan's likeliest reading of `maps.py` was "prism's own dimension macro, therefore
prism's". It is not. Prism's `mapgroup NAME, H, W` and the family's
`map_const NAME, W, H` differ in exactly two things — the macro's name and whether
height comes first — and the group/enum counting (`newgroup` bumps the group,
resets the within-group enum to 1) is byte-identical across pokecrystal,
polishedcrystal and pokeprism. Prism's parser with those two values changed reads:

    pokeprism         452 maps, groups 1..96   first=(INTRO_OUTSIDE, 1, 1, 18, 11)
    pokecrystal       388 maps, groups 1..26   first=(OLIVINE_POKECENTER_1F, 1, 1, 4, 5)
    polishedcrystal   607 maps, groups 1..37   first=(OLIVINE_POKECENTER_1F, 1, 1, 4, 6)

and the dialect it needs is **already declared data on the neutral side**:
`wiring/mapresize.MapShape(path, macro, height_first)` carries all three values and
is already handed prism's and the family's. `MapShape` reads *one* map's dimensions
by const; the whole-file catalog walk is the piece missing from it. So `maps.py`
is not a port, it is a `MapShape` method that has not been written yet.

### Measurement 2 — `PRIMARY_HEADER_GROWTH` is 8, the macro emits 9

`macros/map.asm:94` emits `db`×3 + `dw` + `db`×2 + `dn` + `db` = 9, and
the built `.sym` agrees — consecutive headers are 9 apart
(`IntroOutside_MapHeader 25:40c0`, `IntroCave_MapHeader 25:40c9`). The constant is
charged as headroom when `mapfit` places a new map (`mapfit/__init__.py:130`), so
the packer under-reserves the shared `Map Headers` section by one byte per map
added. `SECONDARY_BASE = 12` was checked the same way and is correct.

**Fixed 2026-08-01**, before Phase 0, on the tree as it stood. The constant is 9,
and the three prose restatements of the wrong number went with it
(`blobsizes`'s own docstring, `mapfit/__init__.baseline_free_space`,
`packing.FreeSpace.reserve`, plus three lines of `docs/devtools.md`).

The test is `test_mapfit.py::test_header_sizes_match_the_macros`, and it does not
restate the number either — it **counts the bytes prism's macro body emits**
(`db`×1, `dw`×2, `dba`×3, `dn` two nibbles to a byte) and compares. Falsified
first: with the constant back at 8 it fails with `macro emits 9, constant says 8`.
An unknown directive raises rather than counting nothing, which is also why
`connection` is not covered — its `if`/`elif` on the direction argument means a
body's size is not a property of the body.

**Two tests were pinning the bug.** `test_mapfit.py::test_baseline_credit_back`
asserted the debit was `- 8` as a literal, and `test_mapsource.py`'s
`gather_blobs` asserted `primary is 8 B` — so the wrong constant had two green
tests under it, and fixing it turned one of them red. Both now read
`blobsizes.PRIMARY_HEADER_GROWTH`, leaving exactly one place that states the size
and one test that checks that place against the macro. **The general form is
worth carrying into every phase:** a test that restates a constant instead of
naming it defends nothing, and reads as coverage.

### Measurement 3 — the macro-line reader, written a dozen times

With three different answers. Reading one `macro Label, …` line's arguments is the most-duplicated mechanic in
the repo. The anchor `^\s*<macro>\s+<label>\s*,` appears at **15 sites**, and they
do not agree about a trailing `; comment`:

| site | the comment |
|---|---|
| `wiring/macroline.py:45` — the writer | captured and **preserved** |
| `hacks/vanilla/mapedit.py:_find_args` | `split(";")[0]` — **dropped** |
| `hacks/prism/mapsource.py:111,138` (`_split_fields`) | **not handled** — it lands inside the last argument |
| `maplint/context.py:68`, `hacks/prism/spritesets.py:62` | `(?:;.*)?$` — dropped, a third spelling |
| `hacks/prism/eventmodel.py:24` (`_MACRO_RE`) | the general `(macro, args, comment)` — **the primitive already exists**, inside prism's adapter |

Plus a straight copy-paste: `_TRAINER_RE` is byte-identical in three files
(`maplint/rules_content.py:15`, `hacks/prism/removal.py:49`,
`hacks/prism/eventmodel.py:341`) with two near-variants in `flagrefs.py` and
`trainerstats.py`.

**The consequence is a live inconsistency, not just repetition.**
`hacks/prism/mapedit.py` reads through `mapsource.primary_header` and writes
through `splice_macro_args`, so **prism's read path and prism's own write path
disagree about what the arguments of one line are.** Measured on one
`map_header` line carrying `; a note`:

    prism  reader: last arg = 'FISHGROUP_SHORE ; a note'
    family reader: last arg = 'FISHGROUP_SHORE'
    writer split : last arg = 'FISHGROUP_SHORE'   comment kept = ' ; a note'

**It is latent, and the latency is measured too:** 0 of prism's 452 `map_header`
lines and 0 of its 454 `map_header_2` lines carry a comment today. So nothing is
broken *now*; it breaks the first time somebody annotates a header, and then a
fishgroup is called `FISHGROUP_SHORE ; a note` and is validated against the
constants file under that name.

**Lifted 2026-08-01**, before Phase 0, so `wiring/` carves into product A with
one reader in it. `wiring/macroline.py` now holds both halves:

- `read_macro_line(line) -> MacroLine(macro, args, comment) | None` — the general
  one, moved out of `hacks/prism/eventmodel.py:24` where it was mis-filed. The
  label, where there is one, is `args[0]`.
- `find_macro_args(text, macro, label) -> list[str] | None` — the anchored one,
  indexed **the way `splice_macro_args` writes**, which is the property the
  hand-rolled copies lacked.

Both go through one `_anchored(macro, label)`, and the writer was repointed at it
too — that shared function *is* the fix. Three call sites moved:
`hacks/prism/mapsource.py` (`_split_fields` gone, and the connection-block scan
split out as `_connections_under`), `hacks/vanilla/mapedit.py` (`_find_args` and
its two module-level regexes gone), and `hacks/prism/eventheader.py`
(`eventmodel._MACRO_RE` gone).

**The name is `read_macro_line`, not `macro_line` as scheduled** — CLAUDE.md's
verb-and-object rule is authoritative and a bare noun does not say what the
function does.

`test_macroline.py::test_readers_agree_about_comments` is the flipped test: it
asserts all three agree, on a line that carries a comment, **through the
adapters' real read paths** (`mapsource.primary_header`, the family's `_args_of`)
rather than against copies of their old regexes — so a site that re-rolls its own
reader fails here. The census check is gone with the premise it guarded.
Falsified: widening `_anchored` to fold the comment back into the last argument
fails all three checks.

**The lift stopped where the shapes stop matching, and that was the instruction.**
The remaining sites ask different questions, and the one they share is *not* the
one lifted: `maplint/context.py`, `hacks/prism/spritesets.py` and
`hacks/polished/read.py:203` each scan **every** line of a macro, with no label to
anchor on, and pick typed fields out positionally. A label-anchored reader cannot
serve them. If a second primitive is ever wanted it is "every line of macro X",
not a flag on this one.

### Incidental — the LZ codecs, asked about and answered *no*

Not part of the survey; raised because `blobsizes` shells out to `utils/lzcomp`
where the family builds `tools/lzcomp`. Recorded so the question is not asked a
third time, with the answer it actually got.

**`utils/lzcomp` is not a duplicate.** There is exactly one site that runs a
compressor — `blobsizes.compressed_blk_size` — so nothing is written twice. It is
an *undeclared path*, which is a smaller and different thing, and it is inert: the
only caller that needs a compressed blob size is bank placement, which is prism's
alone. It becomes declared data if a family tool ever asks the question. Today
none does. **No action.**

**The Python codecs are a legitimate fork — do not merge them.** `shared/lz.py`
and `hacks/polished/lzp.py` implement *different formats*: polished's is a
documented superset with per-command length minimums and three extended opcodes
(`$fc`/`$fd`/`$fe`), so the shared decompressor genuinely cannot read a polished
stream. This is the same category as `Reader`×3 in the naming census — one
protocol, one implementation per tree, the design working.

**But two smaller things inside it are real**, and neither is urgent:

- `shared/lz._bit_reverse` and `hacks/polished/lzp._flip_bits` have **byte-identical
  4-line bodies** and different names. The names are what hid it — precisely the
  case the census argues a name-based rule cannot catch and a functionality
  matcher can.
- The *stock half* of the codec — the 3-bit/5-bit command byte, LZ_LONG's 10-bit
  length, and the COPY offset encoding — is written twice. `lzp._copy`'s own
  docstring says "exactly `shared.lz`'s encoding", so the duplication was seen and
  never acted on.

**Not scheduled, on purpose.** Nothing disagrees with anything here — unlike the
macro-line reader, both codecs are correct and each is proven byte-exact against
its own tree. Parameterising `shared.lz` on a minimums table and an extended-opcode
hook, with polished declaring its three differences as data, is the branch's usual
idiom and would work; it is also a rewrite of a proven decoder to remove ~30
duplicated lines. Do it if `shared/lz.py` is being opened anyway in Phase 0's
carve of A. Do not open it for this.

### The three-way call, per CLI

| CLI | call | reason |
|---|---|---|
| `prism-usage` (`usage`) | — | product **A** outright; asks an RGBDS question, names no hack |
| `prism-sym` (`sym_lookup`) | — | product **A** outright; same |
| `prism-mapview` (`mapview`) | **(b)** | the strongest candidate in the repo, ahead of the two the plan nominated: its catalog dependency is now proven neutral, `MapFormat` already crosses the seam as declared data, and `shared/overworld/blockdata.py` already reads all three trees. Only `render`'s palette tables stand between it and a family tool |
| `prism-gfx` (`gfx_view`) | **(b)** | the plan's call stands, at a higher price than the import graph implied: the palette tables *and* the tileset file-naming scheme have to cross, and the naming is hardcoded in `gfx_view` itself, not only in `render` |
| `prism-metatiles` (`metatiles`) | **(b)** | same question every hack has (which metatiles does this tileset actually use), same price plus two more prism paths of its own (`maps/blockdata.asm`, `maps/map_headers.asm`). The largest of the (b)s and the one to do last |
| `prism-maps` (`map_inspect`) | **(c)** | a table of prism's map catalog. Half its dependency is now neutral (`maps.py`), but the other half is `mapsource`'s two-header dialect and the four asm files it names |
| `prism-map` (`map_show`) | **(c)** | reaches ten prism modules including the event-header parser and the block-data renderer; it is prism's map inspector and nothing smaller |
| `prism-newmap` (`map_new`) | **(c)** | authors a map into prism's five asm files and emits a `MapSpec` for the packer. The family's equivalent already exists on the other side of the seam as `hacks/vanilla/newmap.py` — the studio's new-map form, not a CLI |
| `prism-mapfit` (`mapfit`) | **(c)** | bank placement in a 91%-full ROM. The purest (c) in the repo |
| `prism-maplint` (`maplint`) | **(c)**, after (b) is carved out | ships as prism's linter; `diagnostics.py` leaves for **B** and `textfit.py` for **A** first, because the family adapters already import both |
| `prism-dev` (`dev_server`) | **(a)** for `apply`/`inventory`/`playtest`, **(c)** for `cli`/`tui`/`test_maps`, **A** for `emulator`/`launcher` | the one CLI that is genuinely adapter work wearing a CLI's name — exactly the "two things wearing one name" the (a) bullet warns about, and the warning is right: it should stop being a CLI package that an adapter imports |

Nothing lands in **(a)** except the dev-server's service half, which is what the
plan predicted for (a) — rare, and a sign of misfiling rather than a design.

### Resolved: B ships separately

**The plan's criterion returns empty, so it does not decide.** The question was
"who needs the vocabulary besides the IDE", and the answer for the CLIs is
*nobody*: not one of the eleven CLI packages imports `studio/` or `hacks/seam.py`,
at import time or lazily — traced, not grepped, by importing each entry point with
a cold `sys.modules` and counting what landed. They consume prism's *parsers*
(`maps`, `mapsource`, `mapspec`, `render`, `savefile`), never its contract. The
worry that folding B into C would drag the IDE into every CLI was unfounded in
both directions: the CLIs need neither B nor C.

**So the decision falls to the remaining constituency, and there it is one-sided.**
Three in-tree adapters need B, plus every third-party adapter the goal exists to
serve. B inside C makes `adapter → IDE` a real dependency edge — the exact edge
Phase 2's acceptance test greps for, which cannot both be the gate and be where
the vocabulary lives. And the "it costs nothing" half does not hold on measurement:
**12 of `studio/`'s 19 modules import `textual` at module scope.** The package is
importable without a widget library only because `__init__` imports `session` and
defers `app`, an invariant protected by nothing but one lazy import and a
docstring. One `import textual` at the top of any studio module would break every
adapter in the world.

`maplint/diagnostics.py` settles the last of it: it is contract vocabulary
(`seam.Lints` returns it) that **two family adapters already import without the
IDE in sight**. B has a live constituency outside C today, in a package neither of
them belongs to. It ships separately.

# Reference measurements — *not* this phase's findings

Repo-wide data that pre-dates Phase −1, moved out of `refactor-plan.md` when the
plan was capped. Kept here because Phase −1 is the only closed phase and something
must hold it; a later phase that needs one of these should re-measure first. All as
of 2026-07-31.

## The naming census — the inventory

### Tier 1 — entity files wearing an architecture name

| file | what it actually defines |
|---|---|
| `hacks/seam.py` | `Hack` + its six capability protocols |
| `studio/panels.py` | 20 classes: `Npc` `Trainer` `Prop` `Signpost` `Warp` `Trigger` `Link` `Blocks` `Sketch` `Attributes` `Roof` `WildMon` `TextRef` `MapTables` `Ref` `Row` `Tab` … |
| `studio/model.py` | `MapRef` `MapGeometry` `Draft` `MapData` `Preview` `Applied` `Finding` `Mutation` |
| `hacks/prism/eventmodel.py` | `Entry` `EventList` `Trainer` `Prop` `Handle` `ListKind` |
| `hacks/prism/content.py` | `AddNpc` `AddTrainer` `AddProp` `AddSignpost` `EditText` `Remove` `Disconnect` |
| `wiring/editvocab.py` | `Change` — the central entity of the asm-editing layer |

`studio/panels.py` is the headline: twenty of the map's actual nouns filed under a
UI location. It is also the file that forces every adapter to import the IDE. One
bad name, two problems.

**`model` is a bad fit** — it holds `MapData`, `Preview`, `Applied`, `Mutation`,
`Finding`. Those are not a model of anything; they are the *records of the edit
cycle*, which is what `flow.py` runs. They should sit with it under a name that
says so.

**Why `Trainer` is in `eventmodel` and not `model`: there are three `Trainer`s.**
`prism/eventmodel.Trainer` is what prism's parser produces, `vanilla/trainer.Trainer`
is the action that adds one, `studio/panels.Trainer` is what the IDE displays.
Legitimately distinct things, illegibly named — and Phase 2 fixes it by moving the
view entity out into the contract, leaving the parse entity alone in the adapter.

**`content` is too generic, and it hides a real bug:** `Connect` lives in
`hacks/prism/actions.py` while `Disconnect` lives in `content.py`. The intended
split is map-to-map actions versus in-map ones, so `Disconnect` is on the wrong
side of it.

### Tier 2 — minor, fix in passing
**`dev_server/` mixes a service with its consumers.** The service is `apply` (478),
`inventory` (460), `playtest` (124), `launcher` (114), `emulator` (102); `tui.py`
(914) and `cli.py` (226) are two front ends onto it. They should not share a
folder, let alone the naming.

`hacks/prism/objedit.py` defines `MapEdit`. `studio/flow.py` defines `Flow`, which
is self-consistent but the *class* is the architecture word — it is the write
cycle (preview → agree → re-read), and `model.py`'s records belong with it.

`studio/status.py` — not a status bar, and worse than "too generic": the docstring
says "three read-only panels" and the file defines five classes (`Banner`, `Where`,
`Legend`, `Diagnostics`, `Centre`). It has already drifted past its own
description, which is the responsibility-count smell showing up as prose rot.

### Corroborating symptom — measured
**38 duplicated class names across 85 definitions.** They are three different
phenomena and only two are problems:

- **Legitimate — do not touch.** `Reader`×3, `Player`×3, `Writer`×2, `Save`×2,
  and the `Add*`/`Edit*` action families. One implementation per adapter of one
  protocol. This is the design working.
- **Genuine collisions.** `WiringError`×3, `Connection`×3, `Layout`×2, `MapInfo`×2,
  `Section`×2, `Placement`×2, `NewMap`×2, `EventFlags`×2, and `Dialect`×2 — the
  last two *both inside `wiring/`*.
- **View-versus-parse.** `Block`×4, `Trainer`×3, `Line`×3, `Entry`×3, and
  `Prop`/`Roof`/`Warp`/`Box`/`Cursor`/`Metrics`×2. Phase 2 disambiguates these.

**Enforcement, in two layers.**

*Not by name.* A "no duplicate class names" rule cannot separate the three
categories above, so it would fire on `Reader`×3 — the design working — and be
switched off within a week.

*By functionality, advisory, scoped.* A hook that checks whether newly written
code re-implements something that already exists — matched on what it *does*, not
what it is called — is the right instrument, and it catches the thing names miss:
`Placement` in `mapfit/packing.py` versus `Placement` in `wiring/placement.py`
share a name *and* a job, and nobody noticed.

Two constraints make it survivable:

- **Never compare across adapters.** The three `Reader`s are functionally near
  identical *on purpose* — that is what implementing one protocol three times
  looks like. A functionality matcher will rank them as the strongest duplicate in
  the repo. Scope it within a product/layer, never across the seam.
- **Advisory, not blocking.** It reports a candidate and the file it resembles.
  A gate on a fuzzy signal gets disabled; a report gets read.

*Mechanically, with no false positives:* the import-direction rule from the goal.
That one is a gate.

### `wiring/` is not exempt after all
Earlier drafts marked it clean. It is not: `wiring` is neither a GBC/pret term nor
a recognised architecture noun, and the cost is visible — **`WiringError` is
defined three times, in three unrelated files.** That is what a meaningless folder
name does; it attaches to anything. Its contents (`warpdel`, `mapnew`, `blocks`,
`mapresize`, `regions`, `flagalloc`, `editvocab`, `placement`, `macroline`) are all
one thing: **editing pret assembly source.** Rename on the way into product A.

### Genuinely clean — do not touch
`shared/` as a folder, `shared/constants.py`, `maplint/context.py` (defines
`LintContext`), and all of `hacks/prism/*` that names its entity (`warps.py`,
`roofs.py`, `species.py`, `savefile.py`).

## The repo overall

183 files, 38,909 LOC. Eight files over 500, fifty-seven in 250–500. 1,236 `#:`
doc-comment lines, 2,726 comment lines total. `hacks/prism` is 10,577 LOC across
47 files — big because prism is big, averaging 225/file, and not a target.

## Phase 4's god objects — sizes

| class | file | lines | tests |
|---|---|---|---|
| `Session` | `studio/session.py:81-596` | 515 | 3 files |
| `DevServer` | `dev_server/tui.py:67-905` | 838 | **none** |
| `Studio` | `studio/app.py:82-502` | 420 | 1 file |

`Session` is 45 methods. `DevServer`'s ten editors run `_edit_player` through
`_edit_tmhms`, lines 243–813 — ~620 of the 838, so `tui.py` drops to ~250 once they
move to `dev_server/editors/`.

## Phase 1's six CLI packages — sizes

`metatiles` 670 LOC, `mapfit` 602, `usage` 445, `map_new` 354, `map_show` 340,
`map_inspect` 287. Not targets, already at ~150: `mapview` 167, `gfx_view` 164,
`sym_lookup` 147.

## Phase 5's seven prism-importing rule modules

`context`, `rules_content`, `rules_objects`, `rules_trainers`, `rules_sprites`,
`rules_flags`, `rules_text` — confirmed by Phase −1. `rules_geometry` and
`__init__` are prism-free by import but reach it through `.context`.

