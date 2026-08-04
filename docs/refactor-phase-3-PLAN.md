# Phase 3 — make the products separable · the plan

**Findings as it runs: `refactor-phase-3-STATE.md`.** This file is intent only.

**No repo is created here.** Phase 3 is entirely inside this tree; the carve, the
four ledgers, the import rewrite and the test split are **Phase 3b**.

## What step 1 found, and why the phase was re-shaped

`refactor-plan.md` called Phase 3 *"mechanical once Phase 2 lands: B is its
package, C and D fall out"*. Measured 2026-08-04, that is false, and the reason is
one sentence: **the products are not folders yet.** Four cross-product import
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
- **`maplint/suppressions.py` goes to B.** It imports `contract.Diagnostic`, so it
  cannot go lower; a family adapter imports it today out of a prism CLI. Phase 2
  left it in `maplint/` as "one linter's mechanism" — that reading is wrong now
  that two linters and two products use it. The `; maplint: ignore[…]` channel
  becomes contract vocabulary, which is what it has been behaving as.
- **`maplint/textfit.py` and `dev_server/{emulator,launcher}.py` go to A**, into
  `shared/`, as Phase −1 assigned them. All three are stdlib-only. `shared/` rather
  than a new folder so A's carve stays at four paths and 3b's ledger gains no row.
- **`studio/mapadd.py` and `studio/resize.py` cease to exist** — the user's call,
  2026-08-04, over shipping them as a shared adapter library. Measured name by name,
  this is **almost entirely a move**, not the redesign it was priced as:

  | name | prism | family | lands |
  |---|---|---|---|
  | `AddMap`, `newmap_for`, `_BASE`, `_PLACES`, `section_choices` | — | yes | `hacks/vanilla/`, a pure move |
  | `grids` | yes | yes | A — it names no contract type |
  | `ResizeMap`, `resize_for` | yes | yes | one copy per adapter |

  **Prism's new-map form is already its own** (`hacks/prism/newmap.NewMap`); it
  reaches `mapadd.py` for `grids` alone. So `ResizeMap` is the only genuinely
  shared `Action` in the tree, and duplicating it per adapter is not a lapse but
  the pattern `refactor-plan.md` already blesses — *"never compare across adapters,
  since the three `Reader`s are near-identical on purpose"*. ~40 LOC, twice.
- **`wiring/` is renamed to `asmedit/`** — deferred here from Phases 0 and 2 on
  purpose, and the last chance before the rename would have to happen in four
  repos at once. Its contents are one thing, editing pret assembly source, and the
  cost of the meaningless name is that `WiringError` is defined three times in
  three unrelated files. **Confirm the spelling before commit 9** — `asmedit/` is a
  proposal, `asmsource/` the runner-up; every other decision above is settled.

## The rules

R1–R5 (`refactor-phase-1-PLAN.md`), R6 (`refactor-phase-1b-PLAN.md`, and read its
correction) and R7 (`refactor-phase-2-PLAN.md`) carry over unchanged. One addition,
forced by this being the first phase that deletes something on purpose:

### R8 · A deliberate deletion is named before it happens

R7 says the CONTENT union across affected packages must not change. Commit 8
removes `AddMap`, `ResizeMap`, `newmap_for` and `resize_for` and grows per-adapter
replacements, so the union *does* change — and an unnamed change to it is exactly
what R7 exists to catch. So the list of names leaving is written into this file
before the commit, and **the union diff must equal that list, name for name**.
Anything else in it is a defect, not a consequence.

`scripts/surface-snapshot.py` walks a package's top-level modules only, so the
*arrivals* under `hacks/prism/` and `hacks/vanilla/` are invisible to it. Those are
proved Phase 2's way instead: normalise the intended change out of `git diff` and
assert the leftovers are empty.

**Leaving `studio/` for A at commit 7:** `grids`. **Leaving for `hacks/vanilla/` at
commit 8:** `AddMap`, `newmap_for`, `_BASE`, `_PLACES`, `section_choices` — a move,
so the union is unchanged and R7 applies unaltered. **Genuinely deleted, at commit
8b:** `ResizeMap` and `resize_for`, replaced by one copy inside each of
`hacks/prism/` and `hacks/vanilla/`. That pair is R8's whole list; anything else in
the union diff is a defect.

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
| 8 | the rest of `mapadd.py` → `hacks/vanilla/`; `studio/mapadd.py` deleted | a move — R7 union unchanged; `test_family_sketch` unchanged and green |
| 8b | `ResizeMap` copied into prism and vanilla; `studio/resize.py` deleted | R8's list is exactly two names; test 0 and `test_vanilla`/`test_polished` green |
| 9 | rename `wiring/` → `asmedit/` | a whole-tree grep read hit by hit, **not** a word-boundary sed; R6 confinement |
| 10 | `tests/test_products.py` — the phase's oracle | four checks, each falsified first |
| 11 | each product's packaging metadata | recorded as a decision table; 3b writes the files |

**Commit 0 is not optional and it is first.** 8b is the phase's only commit that
writes a body rather than moving one, and Phase 1b's lesson is that a body is not
edited before something executes it. The family side has oracles already —
`test_family_sketch.py` covers `AddMap.sketch`, `test_vanilla.py` and
`test_polished.py` mount and drive `writes`, and `test_studio.py`'s newest-first
test already covers `grids` through `hacks/prism/offers.blocks`. **Prism's resize
form has none.** `test_wiring.py::test_resize` covers `wiring/mapresize.resize`, the
mechanism underneath, and nothing covers the fifteen lines of `ResizeMap.run` that
turn four form strings into that call — which is precisely the code 8b retypes.
It goes in `tests/test_studio.py`, where the prism fixture and a live `Session`
already are (Phase 1b: a characterization test goes where the fixture is).

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
3. **The survivor list is empty**, replacing `test_contract.py`'s named pair. It
   asserts emptiness in both directions, so a re-introduced edge cannot pass.
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
- **`tests/test_contract.py`'s survivor assertion is updated deliberately**, at
  commit 8, and its removal is the point of the commit rather than collateral.
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
