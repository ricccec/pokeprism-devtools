# Phase 3 — make the products separable · the plan

**Findings as it runs: `refactor-phase-3-STATE.md`.** This file is intent only.

**No repo is created here.** Phase 3 is entirely inside this tree; the carve, the
four ledgers, the import rewrite and the test split are **Phase 3b**.

## What step 1 found, and why the phase was re-shaped

`refactor-plan.md` called Phase 3 *"mechanical once Phase 2 lands: B is its
package, C and D fall out"*. Measured 2026-08-04, that is false, and the reason is
one sentence: **the products are not folders yet.** Five cross-product import
edges survive Phase 2, and a carve run today produces four repos that import each
other. Evidence in the STATE; the edges themselves are the work below.

So the phase splits, the way Phase 1 split into 1 and 1b and for the same reason —
**Phase 3** makes the folders equal the products, **Phase 3b** carves them. A carve
cannot be proved correct before the thing it carves is correct.

## The criterion — what is in this phase, and what is not

**Move exactly what one product imports out of another it must not depend on.**
Mechanical, measurable, and it terminates: five edges, listed below, and nothing
else. It is *not* "finish Phase −1's product assignment" — `hacks/prism/render.py`
and `mapsource.py` are still half A's by Phase −1's verdict, but **no non-prism
product imports either one** (measured), so splitting them buys separability
nothing. They are the (b) drain, and they wait.

## Decisions taken, with what settles each

- **The family adapters ship with C.** `mount()` is called from
  `studio/session.py`, `studio/app.py` and tests, and nowhere else — no CLI mounts
  an adapter — so `hacks/vanilla` and `hacks/polished` are reached only through the
  studio. Recorded in `refactor-plan.md`'s product table, which had four rows and
  no home for either.
- **`hacks/mount.py` goes to B**, as `contract/mount.py`. It imports
  `contract.Hack` and otherwise only stdlib, so B's bar — *stdlib and three
  `shared/` modules and nothing else* — survives the move intact. It also leaves
  `hacks/` holding only adapters, which is what the folder name claims.
- **`maplint/suppressions.py` goes to B, by elimination rather than by taste.**
  It reads `; maplint: ignore[code]` out of the source a finding points at, and
  every other home is closed: `apply_suppressions` takes `list[Diagnostic]`
  (`suppressions.py:44`) and `Diagnostic` is B, so **A would invert the arrow**;
  `hacks/vanilla/lint/context.py:24` imports it, so **staying in `maplint/` is
  edge 4 itself**; and `maplint/__init__.py:39` imports it too, so **`hacks/vanilla/`
  would point prism's linter at a family adapter**. Two linters in two products
  use it and it depends on B. That leaves one place.

  The consequence, stated because it is a real change and not a filing detail:
  **the `; maplint: ignore[…]` syntax becomes contract vocabulary** — the channel
  any linter reads in any tree. Phase 2 called it "one linter's mechanism", which
  held while only prism's linter read it and stopped holding when vanilla's did.
- **`maplint/textfit.py` and `dev_server/{emulator,launcher}.py` go to A**, into
  `shared/`, as Phase −1 assigned them. All three are stdlib-only. `shared/` rather
  than a new folder so A's carve stays at four paths and 3b's ledger gains no row.
- **Only the two names prism reaches leave `studio/`.** Measured per *name* rather
  than per module, which is what an earlier draft of this plan got wrong:

  | name | prism reaches it | family reaches it | lands |
  |---|---|---|---|
  | `grids` | `prism/offers.py:69` | `vanilla/newmap.py:302` | **A** — it names no contract type |
  | `resize_for` | `prism/write.py:124` | `vanilla/write.py:220` | **one copy per adapter** |
  | `AddMap`, `newmap_for`, `section_choices`, `_BASE`, `_PLACES` | — | yes | **stay put** |

  `studio/mapadd.py` is a **C→C edge already**: nothing in prism imports `AddMap`,
  `newmap_for` or `section_choices`, and vanilla ships with C. It is separable
  where it stands, so **this phase does not relocate it**. Its home is a *naming*
  problem — it is not the IDE — and naming is not what Phase 3 is for.

  *Corrected while running commit 7.* An earlier version of this line said the
  file "must appear in no diff", which contradicts this plan's own commit 7:
  `grids` is **defined in `studio/mapadd.py`**, so moving it necessarily edits
  that file. The rule meant is the one above — the module is not relocated into
  an adapter, and `AddMap`, `newmap_for`, `section_choices`, `_BASE` and
  `_PLACES` all stay exactly where they are. Two commits touch the file and
  neither moves it: commit 7 takes `grids` out, and commit 8 corrects the two
  places it points at `studio/resize.py`, a file that commit deletes.

  **And moving it into `hacks/vanilla/` would have been actively wrong.** `AddMap`
  is the generic form: it never branches, holds no hack name, reads
  `dialect.header_args` and passes the dialect down (`mapadd.py:130`, `:135`), and
  **two of the three hacks already mount it** — `newmap.VANILLA` and
  `newmap.POLISHED` are its dialects (`vanilla/write.py:223-226`,
  `polished/claim.py:57`). Burying the generic thing inside one hack inverts the
  relationship whether or not prism is ever ported. See the STATE for the third
  dialect that was never written, and what it would cost.

  `ResizeMap` is the one genuinely shared `Action` that prism *does* reach, and
  duplicating it per adapter is the pattern `refactor-plan.md` already blesses —
  *"never compare across adapters, since the three `Reader`s are near-identical on
  purpose"*. ~40 LOC, twice.
- **`wiring/` is renamed to `asmedit/`** — deferred here from Phases 0 and 2 on
  purpose, and the last chance before the rename would have to happen in four
  repos at once. Its contents are one thing, editing pret assembly source, and the
  cost of the meaningless name is that `WiringError` is defined three times in
  three unrelated files. Spelling confirmed by the user 2026-08-04 over the
  runner-up `asmsource/`.

## The rules

R1–R5 (`refactor-phase-1-PLAN.md`), R6 (`refactor-phase-1b-PLAN.md`, and read its
correction) and R7 (`refactor-phase-2-PLAN.md`) carry over unchanged. One addition,
forced by this being the first phase that deletes something on purpose:

### R8 · A deliberate deletion is named before it happens

R7 says the CONTENT union across affected packages must not change. Commit 8
deletes two names and grows a per-adapter replacement for each, so the union *does*
change — and an unnamed change to it is exactly what R7 exists to catch. So the
names leaving are written into this file before the commit, and **the union diff
must equal that list, name for name**. Anything else in it is a defect, not a
consequence.

`scripts/surface-snapshot.py` walks a package's top-level modules only, so the
*arrivals* under `hacks/prism/` and `hacks/vanilla/` are invisible to it. Those are
proved Phase 2's way instead: normalise the intended change out of `git diff` and
assert the leftovers are empty.

**Moving to A at commit 7:** `grids` — a move, so the union is unchanged and R7
applies unaltered. **Genuinely deleted, at commit 8:** `ResizeMap` and
`resize_for`, replaced by one copy inside each of `hacks/prism/` and
`hacks/vanilla/`, and `studio/resize.py` goes with them. That pair is R8's whole
list. `studio/mapadd.py` is not touched by this phase and must appear in no diff.

## Order of work

Every move lands under a re-export shim first and the shim comes down next — one
diff changes no caller, the next changes no body. Phase 1b's step 9 and Phase 2's
whole method; a commit that does both is reviewable as neither.

| # | commit | what proves it |
|---|---|---|
| 0 | a characterization test for prism's `s` form, through the seam | new test green against unmodified code — see below |
| 1 | `hacks/mount.py` → `contract/mount.py`, shim in `hacks/` | R7 union over `contract`+`hacks`; 35/38 |
| 2 | importers point at `contract`, shim down | word-diff is the token only; 35/38 |
| 3 | `dev_server/{emulator,launcher}.py` → `shared/`, shims | R7 union over `dev_server`+`shared` |
| 4 | importers repointed, shims down | word-diff |
| 5 | `maplint/textfit.py` → `shared/`, `maplint/suppressions.py` → `contract/`, shims | R7 union over three packages |
| 6 | importers repointed, shims down | word-diff |
| 7 | `grids` → `wiring/mapnew.py` | R7 union; `test_studio`'s newest-first test unchanged |
| 8 | `ResizeMap` copied into prism and vanilla; `studio/resize.py` deleted | R8's list is exactly two names; test 0 and `test_vanilla`/`test_polished` green |
| 9 | rename `wiring/` → `asmedit/` | a whole-tree grep read hit by hit, **not** a word-boundary sed; R6 confinement |
| 10 | `tests/test_products.py` — the phase's oracle | four checks, each falsified first |
| 11 | each product's packaging metadata | recorded as a decision table; 3b writes the files |

**Commit 0 is not optional and it is first.** Commit 8 is the phase's only one that
writes a body rather than moving one, and Phase 1b's lesson is that a body is not
edited before something executes it. `test_studio.py`'s newest-first test already
covers `grids` through `hacks/prism/offers.blocks`, so commit 7 has its oracle.
**Prism's resize form has none.** `test_wiring.py::test_resize` covers
`wiring/mapresize.resize`, the mechanism underneath, and nothing covers the fifteen
lines of `ResizeMap.run` that turn four form strings into that call — which is
precisely the code commit 8 retypes. It goes in **`tests/test_wiring.py`**, which
already owns `_resize_fixture`, the prism dialect and `hacks.prism.write` (Phase
1b: a characterization test goes where the fixture is).

**Commit 9 is the trap this refactor has paid for three phases running.** A
word-boundary rename is not a rename: Phase 1b's `pack` missed a real importer and
rewrote four pieces of prose, and Phase 2's `panels` → `tables` collided with a
local variable holding a `MapTables` — which CONTENT reported as an expected,
correct, *wrong* changed digest. 31 files import `wiring`, over 50 import lines,
and 305 further textual mentions across `src`, `tests`, `docs` and
`pyproject.toml`. Every hit is read.

## The oracle — `tests/test_products.py`

Phase 2's `tests/test_contract.py` asserts one arrow, B's. This phase owes the
other three, and it is the test that makes 3b safe: if the products are separable,
a machine can say so, and if a later commit re-fuses them it fails here rather than
in a carved repo.

1. **A declared membership map** — every module under `src/pokeprism_devtools/`
   belongs to exactly one of A, B, C, D, written down in the test. A module in none
   of them fails, so a new file cannot join silently.
2. **Every cross-product import points down** — D→A,B · C→A,B · B→A · A→nothing.
   By AST, over both spellings: relative *and* absolute `pokeprism_devtools.…`.
   The absolute form is not hypothetical — `dev_server` uses it exclusively, and a
   relative-only scan reports it as importing nothing at all.
3. **No adapter outside C imports the IDE.** `test_contract.py`'s survivor list
   goes from five rows to **two**, not to zero, and the two that remain are
   `vanilla/write.py` and `vanilla/newmap.py` reaching `studio.mapadd` — a C→C
   edge, legal because vanilla ships with C. Asserting emptiness here would be
   asserting something false; what the check owes is that no *prism* row survives,
   still named in both directions so a re-introduced edge cannot pass quietly.
4. **The runtime check, per product** — importing B leaves C and D absent from
   `sys.modules`; importing C leaves D absent. Phase 2 measured that a
   `TYPE_CHECKING`-only import passes a runtime check and fails a static one, which
   is why both are kept.

Each check is seeded with the mutation it exists to catch, on disk, and watched
going red before it is believed.

## What must not break

- **35/38.** `test_eventheader`, `test_maplint` (live-prism drift) and `test_lib`
  (needs cwd inside a game repo) are red for reasons predating this branch. A
  fourth red means an edit was not what it claimed. `PYTHONDONTWRITEBYTECODE=1`
  and `__pycache__` cleared first — a stale `.pyc` faked a result in Phase 1.
- **The studio's `a` and `s` keys still open working forms on all three trees.**
  This is commit 8's whole risk and commit 0 is what lets it be checked.
- **`tests/test_contract.py`'s survivor list is edited deliberately, twice** — five
  → four at commit 7, four → two at commit 8, leaving the two `studio.mapadd` rows
  that are C→C and stay. Never to zero, and each edit is the point of its commit
  rather than collateral.

  *Corrected while running commit 7.* This said "two rows at commit 7 and two more
  at commit 8", which does not arrive at two from five. **One** row goes at commit
  7: `hacks/vanilla/newmap.py` imports `studio.mapadd` on two lines — `grids` at
  :302 and `section_choices` at :293 — and the survivor set is keyed by
  *(file, module)*, so moving `grids` retires only `hacks/prism/offers.py`'s row.
  A count of import lines is not a count of edges; the endpoint was right and the
  arithmetic was not.
- **The three console entry points that name a moved module** still resolve.
- B's bar: `contract/` imports stdlib and `shared.coords` / `shared.edits` /
  `shared.swatches`, and nothing else. Commits 1 and 5 add to `contract/` and must
  not widen it.

## Packaging — the decisions, for 3b to write

Phase 0 recorded A as "history plus source and nothing else". The story owed is a
distribution per product, and the part Phase 3 can settle is what each one *is*:

| product | dist depends on | entry points | tests it owns today |
|---|---|---|---|
| **A** | stdlib + Pillow | `prism-sym`, `prism-usage` | 3 of 38 |
| **B** | A | none | `test_contract`, `test_products` |
| **C** | A, B, `textual` | `prism-studio` | the family and studio tests |
| **D** | A, B | the nine remaining `prism-*` | the prism tests |

**A owns three test files of thirty-eight** — `test_flagalloc`, `test_regions`,
`test_usage`. Everything else that exercises A does so through a prism or family
fixture. So A's test story is **authorship, not a carve**, and it is 3b's largest
unpriced item. Recorded here rather than discovered there.

## Handed on, but not to 3b — the third new-map dialect

**Not a Phase 3 item and not a blocker for any carve**, recorded because it was
measured here and because the measurement is what stops the next agent from
answering it by reflex, in either direction.

`AddMap` is the generic new-map form and two of three hacks mount it as dialects.
Prism does not: `hacks/prism/newmap.NewMap` is 279 lines that re-implement it.
Classified against what the dialect mechanism already provides, of ~235 code lines
**~118 duplicate something the family has generically** — `_collisions`
(`newmap.py:235-260`) and `wiring/mapnew.py:237-254` are the same three checks
producing the same three messages, `_unknown_names` is `ConstSet`/`HEADER_SETS`
rewritten, seven of its fields *are* `mapadd._BASE` — and **~68 are one thing,
bank placement** (`_bank`, `spec()` → `MapSpec`, `run()`'s `mapwire`/`pin_sections`
half). The remainder is a `sketch` that returns a coloured `BlockData` where the
family returns a neutral `contract.Sketch` for each reader to colour, which is
prism being *older* rather than different.

So the port is plausible on the evidence, and bank placement even sits on an axis
the design already has: `_PLACES`/`asks` is *"which blobs have a placement
question"*, polished mints, vanilla joins, prism would pin. **It is still a
redesign, not a move**, it reaches `MapSpec` and `mapfit.mapwire` — a (c) CLI —
and this refactor proves moves. Whoever takes it owes it a phase and an oracle.

Phase −1's **(c)** call covers the CLI `map_new`, *not* this form; that the two
share a name is why the question went unasked until 2026-08-04.

## Handed to Phase 3b

- Re-derive the ledger from recorded renames before re-running
  `scripts/carve-product-a.sh`; this phase adds rows to it (commits 1, 3, 5, 7, 9).
- **A's carve is 40 files now, not the snapshot's 34** — Phase 1 split `usage/`
  into seven. `88` commits and `73` as the falsification still stand as Phase 0
  measured them; both get re-measured, not assumed.
- **D's ledger names eight `wiring/*` files by their pre-`033fbe4` paths**, not the
  folder, and it names `wiring/` rather than `asmedit/` — a history filter reads
  the old spelling forever, and commit 9's rename lands *inside* the carved history.
- B's ledger needs `studio/actions.py`, `studio/panels.py`, `hacks/seam.py`,
  `maplint/diagnostics.py` and `hacks/mount.py` — B's files are younger than their
  history, and four of the five names no longer exist.
- Prune the carve's branches, and check ancestry before pruning rather than after.
- **Nothing here creates a repo.** Where the four go, and whether this repo stays
  the editable copy through Phases 4 and 5, is 3b's to ask — deferred by the user,
  2026-08-04.
