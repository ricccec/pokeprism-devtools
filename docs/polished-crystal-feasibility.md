# What a second and third hack do to the port — polished-crystal and vanilla

This extends `adapter-plan.md` from a sketch to a measured one. That doc argued
the split *in the abstract*, against one implementation, and proposed one
experiment: *"point `blocksrc` and `eventheader` at a pokecrystal checkout and
see what breaks."* This is that experiment, run against the map format, plus
polished-crystal (`../polishedcrystal`) as a heavily-diverged third point. Every
number here was read off the three trees; file:line citations are into this repo
unless a hack name prefixes them.

The finding is sharper than "the domain model is real." It is real — maps, NPCs,
warps, events, wild data, dialogue exist in all three — but the *port* we have
today (`studio/model.MapData`, `panels.Ref`, `entry.coords`, the `Session`
methods) is **calibrated to prism, and prism is the outlier of its own family.**
Vanilla is the common ancestor both prism and polished forked; on the assumptions
that masquerade as neutral vocabulary, vanilla agrees with polished and *disagrees
with prism*. The port faithfully followed the one hack that is least like the rest.

## The port is a lens, not a wall

The tempting model is that the adapter sits below the port and the GUI above it,
so a new hack is all below-the-line work. False wherever the port's own vocabulary
encodes an assumption. `MapData` is a set of nouns — an *index*, a *coordinate*, a
*count*, a *tail* — and the view was built to read exactly those. Change what a
noun means and every reader is in scope, GUI included. So each assumption below is
scored for *where it is encoded in the port* and *what it forces above the port* —
and now for *which hacks actually hold it*, which is what vanilla lets us see.

## Vanilla moves the diagnosis

Three-way, on the assumptions the port bakes in. "Outlier" is the hack that
stands alone; where it is prism, the port over-fit to prism.

| # | Port assumption | vanilla | polished | prism | Outlier |
|---|---|---|---|---|---|
| 1 | object identity is a positional **index** | named `const` | named `const` | positional | **prism** |
| 2 | events are a **tail** block | tail | **head** | tail | polished |
| 3 | the **count** is author-maintained (`db N`) | self-count | self-count | `db N` | **prism** |
| 4 | a coordinate is **(y, x)**, sprite-first macro | (x, y) | (x, y) | (y, x) | **prism** |
| 5 | a mon is a **scalar** species | scalar (251) | (species, form) | scalar | polished |
| 6 | a trainer is described **inline** on its object | type + data table | named block | inline `trainer` | **prism** |
| 7 | wild table resolved by **landmark** | yes (Johto/Kanto) | yes | yes | none |
| H | header is `map_header`(+`_2`) under `maps/` | `map`/`map_attributes`, `data/maps/` | same as vanilla | `map_header`/`_2`, `maps/` | **prism** |
| T | text is **VWF** (`ctxt`) | `text`, no VWF | `text`, no VWF | `ctxt`, VWF | **prism** |

The measured backing for the load-bearing rows:

- **#1** — `object_const_def` appears in **0 of 465** prism maps, **348** vanilla
  maps, **200** polished maps. Named object identity is how the entire lineage
  works *except* prism, which strips it to raw ordinals (`disappear 3`).
- **#2** — first events macro lands at line 235/255 in prism (tail), 362/382 in
  vanilla (tail), but 20/839 in polished (head, under one `_MapScriptHeader`).
- **#4** — prism: `person_event SPRITE_SUDOWOODO, 7, 7, …` (sprite first);
  vanilla and polished: `object_event 5, 7, SPRITE_BUGSY, …` (coords first, x
  before y).

Read the Outlier column. The assumptions disguised as neutral vocabulary — index
(#1), count (#3), coordinate (#4) — are all **prism divergences the port
inherited**, and vanilla proves it by siding with polished on every one. Only #2
(event location) and #5 (species form) are genuine polished costs where prism and
vanilla agree. #7 is the one true universal. So:

- **Prism-only divergences the port hardcoded** (fixing them helps the *whole*
  family, not just polished): #1, #3, #4, #6, headers, VWF.
- **Polished-only costs** (prism and vanilla agree, so these are new axes): #2, #5.
- **Survived intact:** #7 as a mechanism, the block-data grid, and warps/objects/
  signposts/connections as *categories*.

The adapter-plan's stated fear — *"you haven't designed a protocol, you've
serialized prism's data model and given it a grander name"* — is not a risk to
guard against. It already happened, and vanilla is the proof, because a neutral
gen-2 port would fit vanilla and it is prism it fits instead.

## The ledger — assumption, blast radius, and where vanilla falls

Ranked by how far the change reaches above the port.

### 1. Object identity is a positional index

- **In the port:** `panels.Ref` is `{what, kind, index}`, `index` = *"its position
  in that list"* (`panels.py:75`); `session.deletion` hands `content.Remove` an
  `{"index": N}` (`content.py:335,396`).
- **Vanilla & polished:** named `object_const_def` / `const AZALEAGYM_BUGSY`;
  scripts reference objects by name. **Prism alone** uses raw ordinals.
- **Blast radius above the port: small — the pleasant surprise.** Widgets treat
  `Ref` as *opaque* (`panels.py:60`); `tabs.py:225`'s `refs.index(ref)` is cursor
  positioning, not identity. A `Ref` carrying a *handle* (const name) instead of a
  bare ordinal is invisible to the view; the change is confined to `panels.Ref`,
  `session.deletion/entry`, and the `content` actions.
- **Reprioritise.** This is not a polished feature — it is how *everything except
  prism* addresses an object. It jumps to the top: the single place the port
  literally cannot express what the rest of the family writes down.

### 2. Events are a tail block, spliced without touching scripts

- **In the port:** `eventheader.py`'s round-trip contract — *"code above the header
  label … is never touched"* — rests on the block being at the file's end.
- **Vanilla & prism:** tail (`_MapEvents:` / `_MapEventHeader::` at the bottom).
  **Polished alone** puts events at the *top*, above every script.
- **Blast radius above the port: none, high risk.** No widget sees file layout,
  but the write path's splice model and its exactness guarantee (`Session.apply`)
  must be re-established against an inverted layout. This is the one place the
  polished divergence is genuinely new — prism's own habit happens to match vanilla.

### 3. The count is author-maintained (`db N`)

- **In the port:** `eventmodel` treats a list as `db N` + entries and works hard on
  the count being a *claim* (`declared_count`, the `db 6 ; FIXME` over seven).
- **Vanilla & polished:** `def_*` macros self-count — no count byte exists. **Prism
  alone** writes `db N`.
- **Blast radius above the port: none.** But an entire axis of the port (count-as-
  claim, and the lint that checks it) has no referent outside prism and should
  simply not be declared elsewhere.

### 4. A coordinate is (y, x)

- **In the port:** `entry.coords` returns `y, x`; `Row.coords` is documented as
  *"the source number"*, the reason `play.boot` hands the grid cursor straight to
  `wYCoord`.
- **Vanilla & polished:** `object_event x, y, …` (x first). **Prism alone** is
  (y, x), sprite-first.
- **Blast radius above the port: reaches the view and the ROM boot path.** The
  tuple is in view↔port calls (`app.py:285` `at((event.y, event.x))`, `:314`
  `tile_of`) and in `play.boot`. Both orders typecheck as two ints, so the failure
  is silent corruption unless the convention is centralised at the boundary. Cheap
  to fix, expensive to miss — and again, prism is the one that has to be *un-flipped*
  to match its family.

### 5. A mon is a scalar species

- **In the port:** `MapData` wild/party rows are `(level, species)` — one byte.
- **Vanilla & prism:** scalar (`NUM_POKEMON` 251 in vanilla, no form). **Polished
  alone** is `(species, form)`, 9th species bit in the form byte
  (`polishedcrystal/constants/pokemon_constants.asm:318`).
- **Blast radius above the port: absorbable by design.** `actions.Action.fields()`
  is dynamic, so a `form` field is *added* and the view renders it unschooled — the
  schema-driven promise paying out. Genuinely new work, but GUI-free.

### 6. A trainer is described inline on its object

- **In the port:** prism's `PERSONTYPE_TRAINER` + inline `trainer …` macro is
  treated as the object carrying its own trainer.
- **Vanilla:** `OBJECTTYPE_TRAINER` + a party in `data/trainers/`. **Polished:**
  `OBJECTTYPE_GENERICTRAINER` + a named `generictrainer` block. **Prism alone**
  inlines the declaration in the script file.
- **Blast radius above the port: absorbable, same mechanism as #5** — a lookup
  behind the port surfaced as fields.

### 7. Wild table resolved by landmark

- **In the port:** `wilddata.py` bakes prism's `RegionCheck` — *"picks the table
  from the landmark alone"* — and `table_for` resolves rather than accepting a name.
- **All three** split wild data by region (vanilla's Johto/Kanto is the origin).
  The *mechanism* is universal; only prism's specific landmark set and macros are
  its own. The one assumption that survived — but the port still encoded *prism's*
  resolution, not a neutral one.

### The already-honest leaks

`session.measure`/`TextPreview` (VWF) and the walking-sprite VRAM budget
(`maplint/rules_sprites.py`) are prism engine physics — and here prism is the
outlier again: neither vanilla nor polished has VWF or prism's emergent sprite
ceiling. `adapter-plan.md` anticipated these via capability negotiation. The one
place it reaches the GUI: the Diagnostics pane (`app.py:156`) and the text-measure
preview must **degrade to "not applicable"** when an adapter declares neither —
the template for how every omitted capability shows up above the port.

## What this does to the plan

The headline correction: **calibrate the port to vanilla, not prism.** Vanilla is
the family median — named identity, tail events, self-counting, (x, y), scalar
species, `data/maps/` headers, no VWF — and hacks fork *it*. A port that fits
vanilla fits most hacks by construction; every place the port disagrees with
vanilla is a place it over-fit to the outlier we happened to build it around.

- **Phase 0 — corrected experiment (½ day). Done.** The live parsers were
  pointed at both trees, and every one fails at the **path layer**, before any
  macro grammar is reached: both hacks keep map data under `data/maps/`
  (`maps.asm`, `attributes.asm`, `blocks.asm`) where prism has
  `maps/map_headers.asm` / `second_map_headers.asm` / `blockdata.asm`, and
  dimensions in `map_const W, H` where prism has a dedicated constants file.
  `eventheader` falls at its anchor — vanilla's block is `<L>_MapEvents:`
  (tail), polished's `<L>_MapScriptHeader:` (head) — before it would fall at
  the missing count bytes. The finding Phase 0 *added*: five of the eight
  parsers fail **silently** (`None`, `[]`, `{}`) rather than raising, so a
  studio opened on a vanilla checkout reported an empty repo with a straight
  face. That is now refused loudly — `shared/paths.assert_prism_layout`,
  checked by `Session` and by `prism-studio` at startup — which is the
  placeholder the adapter dispatch will one day stand in.

- **Phase 1 — extract the seam, and un-fit the port from prism.** Make `MapData` /
  `Session` the formal boundary and move prism macros into `hacks/prism/`. The
  concrete, checkable wins, now understood as *removing prism-specificity* rather
  than *adding polished-support*: `panels.Ref` becomes an opaque **handle** (#1),
  and coordinates are normalised at the boundary (#4). Both reach the view; both
  are bought back while prism is still the only hack to break.

  *Started.* The view's half of both is done: a `Ref`'s view-facing surface is
  now three declared affordances (existence, `adds`, `deletable`) plus equality,
  no view module reads a Ref field or mints one (`panels.add_ref` does), and the
  seam's tile is `coords.Tile` — named `(y, x)` fields, constructed by keyword,
  stated once as the place an (x, y) adapter normalises. Still open: the port's
  half of #1 (identity as a named handle where the hack has names) and the
  `hacks/prism/` move itself.

- **Phase 2 — add the two genuinely new axes.** Species `(id, form)` (#5) and a
  named-lookup trainer (#6), surfaced through `FIELDS`, GUI-free. Prism fills form
  with a constant and keeps its inline trainer.

- **Phase 3 — vanilla read adapter, then polished.** Vanilla first because it is
  the median and validates the boundary cheaply; polished second because its
  top-of-file layout (#2) and self-counting (#3) are the real stress test. Render
  read-only.

- **Phase 4 — write adapters + capability degradation.** `def_*` writers, named
  identity, the top-of-file splice for polished (#2); the Diagnostics/text panes
  learn to render an undeclared capability as an absence (VWF, sprite-vram).

## The single sentence to keep

We did not build a gen-2 port with a prism adapter under it; we built prism, and
gave the seam a grander name. Vanilla is the proof — it sides with polished
against prism on index, count, and coordinate — and the cheapest way to earn the
port back is to re-fit it to vanilla, the hack every other hack is a fork of.
