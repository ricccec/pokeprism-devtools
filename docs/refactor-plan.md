# The refactoring plan — from one repo to four products

**Status: draft, under discussion.** Nothing here has been executed.

## The goal

This codebase contains 4 things that deserve their own place:
1. A set of utilities for reading and manipulating assembly files belonging to the
pret-disassembly family of pokemon ROM-hacks;
1-bis. Utilities specifically designed for `Pokemon Prism`, a ROM-hack of Pokemon
Crystal;
2. CLI tools for working on these hacks;
2-bis. Prism-specifica CLI tools;
3. `Prism-Studio`, a TUI tool for these hacks that, despite its name, could be used
(or extended to use) any hack in the family;
4. `Prism-studio` and CLI tools adapters meant for specific ROM hacks in the family
(currently `Pokemon Prism`, `Crystal` and `Polished Crystal`)


The studio and some of the CLI tools is meant to be *extended with hack adapters*. Everything below
serves one measurable outcome:

> A developer with their own ROM hack can answer **"what do I need to do to make
> an adapter?"** by reading one small package — and nothing they write ever
> imports anything from above the seam.

This is a rule about **direction, not quantity**. An adapter is *expected* to lean
on the shared library and the domain entities; extracting those is why they exist.
What an adapter must never import is anything on the far side of the seam — the
IDE, its widgets, its screens, its edit cycle. Imports point down, never up.

That is not true today. All three in-tree adapters import the IDE at runtime
(`hacks/prism/read.py:33`, `hacks/polished/read.py:20`,
`hacks/vanilla/eventblock.py:54`, and six more), so the seam the branch was built
to create does not hold at the only place it matters.

## Ground rules

These apply to every line any phase touches. They are the standard, not a phase.

### Abstraction levels
Keep each function at one abstraction level. Smells: more than 2–3 levels of
nested blocks, or a body longer than ~40 LOC. The test: every line in a function
should answer the same kind of question.

### File size
One file holds at most one or two responsibilities; LOC is a proxy for responsibility
count. ~150 LOC is one responsibility. Over 250 is a smell — a prompt to look,
not a failure. Tests are exempt.
When a file grows, give each responsibility its own file and consider
collecting them in a folder whose name says what domain they share. The folder name
is the explanation; if it can't be named, the grouping is wrong. 

### Magic values
Every magic number or string that encodes a protocol decision must be named.

### Naming functions
Verb **and its object** — say what the function does *to what*. A bare verb
(`handle`, `process`, `run`, `discover`) tells the reader nothing. The test:
reading the name alone, could someone answer *what does this return or change?*

### Naming files and folders
A **folder is an address** — its job is to answer *"What kind of things are here?"*.
Use GBC rom-hacking terms like `save` or `VRAM`, or pret domain names like 
`overworld` or `pokemon-stats`. Architecture-adjacent names (`shared/`, `core/`,
`services/`) are also fine and often helpful.

A **file that defines a domain entity must carry that entity's name** — its job
is to answer *"what is this?"*. 

Don't use an architectural noun if a domain one is available: `seam.py` defines
`Hack`; the domain noun was right there.

### Comments
A code file should explain itself. Nobody reads 100 lines of prose and then 100
lines of code saying the same thing — if the code needs the prose, it needs
better function names, some responsibility dropped and single-abstration level
functions. Refactoring beats comments. The header comment states intent plus
anything genuinely non-obvious or contestable. Delete the rest.

One exception, and it is narrow: prose recording a **measurement or a
falsification** ("reading polished with vanilla's record returns exactly one
palette, so the box silently stops suggesting") is a fact that cost work to find.
Route it to a test, a commit body or record it somewhere in `docs`. Do not simply
delete it.

### Validate at system boundaries
Validate at system boundaries (user input, external APIs, file formats). Trust
internal code and framework guarantees — no defensive validation inside private
functions or between layers we control.

### Commit style
Imperative mood; subject under 50 characters; the body explains **why** — what
was wrong before and how this fixes it. Scope is a module, package, feature or
component, never a phase number or plan name. **Never** a `Co-Authored-By`
trailer unless `.claude/settings.json` sets `attribution.commit`.

## The four products

The dependency graph already permits this split — measured, not assumed:

| product | contents | today's blocker |
|---|---|---|
| **A · pret/RGBDS library** | `shared` + `wiring` + `usage` + `sym_lookup`, ~6,300 LOC | none — zero dependency on any hack or the IDE |
| **B · adapter contract** | `Hack`, its capability protocols, and the domain vocabulary | does not exist; split across `hacks/seam.py` and `studio/` |
| **C · the IDE** | `studio` | depends on B, which is inside it |
| **D · prism** | `hacks/prism` + the nine CLIs that import it | fused to C |

`usage` (RGBDS link-map analysis) and `sym_lookup` are pret-general, not prism —
they belong to A. **Which product owns each remaining CLI is not yet decided**;
an import grep proves an edge exists, not that it is load-bearing. Phase −1
settles it. The early evidence already shows the naive answer is wrong:

```
gfx_view    -> hacks.prism.render   (only)
metatiles   -> hacks.prism.render   (only)
mapview     -> maps, PRISM_FORMAT, render
map_inspect -> maps, mapsource
map_new     -> maps, mapsource, mapspec
map_show    -> blobsizes, mapspec
```

`gfx_view` and `metatiles` touch nothing but `render.py` — and that file has now
been read. **It is prism-specific**, despite a docstring that opens "Shared map
rendering library": it hardcodes `_TILESET_TUNOD`, `_TILESET_ESPO_FOREST` and
`_TILESET_OLCAN_ISLE` (Prism's own regions, absent from Crystal), a
`_COLOR_TABLES` block transcribed from Prism's `engine/color.asm`, and
`render_map` loads through `PRISM_FORMAT`.

But it splits along the seam this branch already knows how to cut — **neutral
mechanics welded to declared data.** Pure Gen-2 pipeline: `_read_or_lz`,
`_png_to_2bpp`, `parse_pal_file`, `decode_2bpp_tile`, `_composite_block`,
`render_tileset_sheet`, and the `TILE_PX`/`BLOCK_PX` geometry. Prism facts:
`_SPECIAL_TILESET_PALS`, `_PERM_TO_TABLE`, `_COLOR_TABLES`, `PALETTE_TABLES`, and
the format argument.

**So `gfx_view` and `metatiles` are prism tools today.** They become hack-generic
only once the palette and tileset tables cross the seam as declared data, the way
`MapFormat` and `SaveOffsets` already do. That is a piece of work, not a filing
decision, and it is exactly what the survey is for.

### Open: does B ship separately, or inside C?

Measured, the vocabulary is *already* dependency-clean — `panels.py` imports only
`shared.coords`; `model.py` and `actions.py` pull in no widget library; and
`studio/__init__.py:31` already documents the package as "importable, without a
widget library installed". So B is mis-sited, not entangled, and extracting it is
cheap either way.

The deciding question is **who needs the vocabulary besides the IDE**. Today the
nine CLIs consume adapters without the IDE, so folding B into C would make every
CLI — and every third-party adapter — depend on the IDE package to get twenty
dataclasses. But if Phase −1 shows those CLIs are all prism's, and prism ships
alongside the studio anyway, then B-inside-C is the simpler answer and costs
nothing. **Decide after Phase −1, not before.**

### Every prism-specific CLI faces the same three-way choice

"This CLI is prism-specific" does not by itself say where it goes. Each one
lands in exactly one of:

- **(a) Part of the prism adapter.** Only if the tool *is* adapter work. Rare —
  an adapter is a library, and libraries that ship CLIs tend to be two things
  wearing one name.
- **(b) Refactored to cross the seam.** The tool asks a question every hack in the
  family has, and only its *data* is prism's. `gfx_view` and `metatiles` are the
  clear candidates: the rendering pipeline is Gen-2, the palette tables are
  Prism's. This is the option that grows the product, and it is real work.
- **(c) Its own repo, depending on the prism adapter.** The tool asks a question
  only Prism has — bank placement, Prism's map catalog. Nothing is gained by
  making it generic, and it should not weigh down A or C.

Phase −1 assigns one of these per CLI with a one-line reason. **"Product D" is
therefore not a single bucket** — it is (a) + (c), with (b) draining into A over
time.

## The naming census

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
Legitimately distinct things, illegibly named — and Phase 1 fixes it by moving the
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
  `Prop`/`Roof`/`Warp`/`Box`/`Cursor`/`Metrics`×2. Phase 1 disambiguates these.

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

## Phases

### Phase −1 — The product survey
An import edge proves a dependency exists, not that it is load-bearing or that it
is *correct*. Before any boundary is drawn, answer per module: **is this a prism
fact or a Gen-2/pret fact?**

`hacks/prism/render.py` (338 LOC) has been checked — see "The four products"
above. Verdict: prism-specific as written, but it splits into a Gen-2 pipeline and
a table of Prism facts. It is the worked example of what this phase produces, and
of why the grep answer was wrong in both directions: the file is *more* prism than
its docstring claims, and *less* prism than its location implies.

Still open, same question: `hacks/prism/maps.py` (the map catalog) and
`mapsource.py` (header parsing), which `map_inspect` and `map_new` depend on; and
`blobsizes.py`/`mapspec.py`, which `map_show` and `mapfit` depend on — bank
placement smells genuinely Prism-only, so those are likely (c).

**Output:** for every module in the survey, a product assignment plus, for each
CLI, one of the three choices above and a one-line reason. This also resolves
whether B ships separately or inside C.

### Phase 0 — Split the git history, while the tree is still untouched
Do this before any file moves. Clone the repo once per product and use
`git filter-repo --path <dir>` to carve history by folder, so each product keeps
the "why" behind its code rather than starting at one squashed commit.

Two corrections to the naive version of this plan:

- **It is not now-or-never.** `git filter-repo` accepts multiple `--path`
  arguments, so a folder that gets renamed later can still be carved with full
  history by naming both its old and new paths. Losing history requires
  forgetting to, not moving files.
- **Only product A can split now.** B, C and D are fused by the `hacks → studio`
  cycle; splitting them today produces two repos that import each other. They stay
  in this repo until Phase 1 breaks the cycle, then split.

So: carve A now — it has zero dependencies and the carve doubles as proof the
tooling works — and carve B/C/D immediately after Phase 1. Keep a record of every
path rename so the later filter can name both.

### Phase 1 — Calibration: the six CLI packages
`metatiles` (670 LOC), `mapfit` (602), `usage` (445), `map_new` (354), `map_show`
(340), `map_inspect` (287). Split parse / analyse / render / CLI out of each
`__init__.py`, leaving the package's public surface *as* its `__init__`.
`metatiles` and `mapfit` already carry `# ---` banners drawn on the seams.

**Why first:** it depends on nothing, all six are test-covered, and it is where we
settle what "done to the standard" means on code where a mistake costs nothing.

**Not targets:** `mapview` (167), `gfx_view` (164), `sym_lookup` (147) are already
at the ~150 target. Splitting them would be chasing the number.

### Phase 2 — The keystone: give `Hack` and its vocabulary one home
The phase that makes the goal true. Tier-1 of the census and the `hacks → studio`
cycle in one move.

- `hacks/seam.py` → `hack.py`, in a package neither the IDE nor the adapters own.
- The 20 entities from `studio/panels.py`, the 8 from `studio/model.py`, and the
  `Action`/`Field`/constant vocabulary adapters import from `studio/actions.py` —
  into that package, split by domain into files named for what they define.
- The comment walls die here: `panels.py` (74 `#:` lines), `hacks/vanilla/write.py`
  (73), `studio/actions.py` (56) are the same files this phase rewrites.

**Acceptance test, falsifiable:** grep `hacks/` for any import of the IDE package.
Empty result passes. This is the check `seam.py`'s docstring already invites,
pointed at the file where it would have caught something.

#### What this package actually is

**One sentence:** it is the *noun list and the question list* that an IDE and an
adapter must agree on before either can be written — and nothing else.

**What is inside.** Two kinds of thing, both pure data:

1. **The entities a Gen-2 map is made of** — `Npc`, `Trainer`, `Prop`,
   `Signpost`, `Warp`, `Trigger`, `Link`, `WildMon`, `Roof`, `Attributes`,
   `Blocks`, `Sketch`, and the table/row/reference types that carry them. Today
   these are the twenty classes in `studio/panels.py`.
2. **`Hack` and its six capability protocols** — `Reads`, `Writes`, `Lints`,
   `Plays`, `Measures`, `Sketches`. The questions an adapter may be asked. Today
   this is `hacks/seam.py`.

**What is *not* inside:** any parsing, any file I/O, any ROM knowledge, any
widgets. It reads no bytes and draws no pixels. Measured, the current
`panels.py` already meets that bar — its only import is `shared.coords`.

**Its one responsibility:** to be the thing both sides depend on so that neither
depends on the other. It exists to be *pointed at*, not executed.

**Why you need it.** Without it the vocabulary lives in the IDE, so every adapter
imports the IDE to describe a warp — which is exactly today's cycle, and exactly
why the seam does not hold. With it, the dependency arrows go
`adapter → contract ← IDE`, and neither end can reach the other.

**How a hack developer uses it.** Install it, read `hack.py` to see the six
protocols, implement the ones your tree can answer, and return the entities above.
Capabilities you do not implement degrade to *absence* in the IDE — no lint panel,
no boot key — never a crash and never an `if <hack name>`. That is the whole
contract, and it is meant to be readable in one sitting.

**Naming.** By the folder rule an architecture-adjacent name qualifies:
`contract/`, `adapter/`, `api/`. Leaning `contract/` — it answers "where do I look
to find what I owe?" Still open.

### Phase 3 — Split the remaining products
Mechanical once Phase 2 lands: B is Phase 2's package, C and D fall out, and the
`git filter-repo` carve from Phase 0 runs again for each.

### Phase 4 — The god objects
Deliberately *after* the keystone, because `Session`'s seams move once the
vocabulary leaves `studio/`.

| class | file | lines | tests |
|---|---|---|---|
| `Session` | `studio/session.py:81-596` | 515 | 3 files |
| `DevServer` | `dev_server/tui.py:67-905` | 838 | **none** |
| `Studio` | `studio/app.py:82-502` | 420 | 1 file |

- **`Session`** — 45 methods that group onto the seam's own six capabilities.
  Once the contract package exists, that parallel is structural rather than
  coincidental.
- **`DevServer`** — ten editors welded onto a server (`_edit_player` through
  `_edit_tmhms`, lines 243–813, ~620 of the 838). CLAUDE.md's "cluster of related
  responsibilities → a folder that names the domain" almost verbatim:
  `dev_server/editors/`, and `tui.py` drops to ~250. **Mandatory prerequisite:** a
  characterization test driving the editors through scripted stdin, priced as its
  own step. Without it this is a rewrite with no oracle.
- **`Studio`** — mostly not a target; Textual concentrates handlers by design.
  Only the `action_*` mixin, and only if Phase 1 leaves it obviously wanting.

### Phase 5 — The maplint survey, then the family port
Seven rule modules import `hacks.prism` (`context`, `rules_content`,
`rules_objects`, `rules_trainers`, `rules_sprites`, `rules_flags`, `rules_text`).
Decoupling them *is* the family-rule port, gated on the survey the live plan still
carries: for each rule, does it describe a Gen-2 fact or a prism fact? Same
question as Phase −1, one layer up — and worth asking together if the answers
turn out to share evidence.

## Before anything

- **Push the 14 commits.** A five-phase refactor on top of an unpushed branch
  means one bad day loses both. This matters more now that Phase 0 clones the
  repo: a clone carries only what was pushed or committed.

## Measurements as of 2026-07-31

183 files, 38,909 LOC. Eight files over 500, fifty-seven in 250–500. 1,236 `#:`
doc-comment lines, 2,726 comment lines total. `hacks/prism` is 10,577 LOC across
47 files — big because prism is big, averaging 225/file, and not a target.
