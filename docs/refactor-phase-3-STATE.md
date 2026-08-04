# Phase 3 — make the products separable · findings

**Plan:** `refactor-phase-3-PLAN.md` · **Index:** `refactor-STATE.md` → Phase 3

The one line this phase carries into the index, and where it is proved:

> **"Mechanical once Phase 2 lands" is false — the products are not folders yet.**
> Five cross-product import edges survive Phase 2, so a carve run today produces
> four repos that import each other. → "The five edges".

**Status: planning done 2026-08-04, no code moved yet.** Baseline re-measured at
**35/38**, the three known reds unchanged.

## Findings — the same list as the index, each linked to its evidence

- Phase 3 is not mechanical; five edges survive — [the five edges](#the-five-edges).
- **`studio → hacks` is a cycle direction nobody ever named** — [the edge Phase 2 could not see](#studio--hacks-was-never-in-anyones-scope).
- **A relative-only import scan is blind to a whole package** — [the measurement that was wrong once](#the-scan-that-missed-dev_server).
- The family adapters are reached only through the studio — [what settled C's row](#the-family-adapters-belong-to-c).
- **The two survivors are not dead code; nothing importing them is the seam working** — [the trace](#nothing-in-studio-imports-the-survivors-and-that-is-the-design).
- **The survivors' "redesign" is 40 lines; the rest is a move** — [name by name](#one-shared-action-not-four).
- A owns 3 test files of 38 — [A's test story is authorship](#as-tests-are-3-of-38).
- Re-verified: `contract/` still imports only `shared`; the carve path list still matches — [step 1](#re-verification-step-1).

## Re-verification (step 1)

Everything Phase 3 leans on, re-measured 2026-08-04 against Phase 2's one-day-old
numbers.

| claim | source | today |
|---|---|---|
| `contract/` imports stdlib + three `shared` modules | Phase 2 | **holds** — by AST over relative *and* absolute imports: `shared.coords`, `shared.edits`, `shared.swatches` |
| four surviving `hacks → studio` edges | Phase 2 | **holds** — 4 modules, 6 import lines, 3 of them function-local |
| `scripts/carve-product-a.sh`'s path list matches the tree | Phase 0 | **holds** — the ledger recipe re-run recovers no new row for A |
| suite baseline | Phase 2 | **holds** — 35/38, same three reds |
| `wiring/` rename costs 31 files / 50 import lines | Phase 0 | **holds** — exactly, a year of moves later |
| A is 34 files | Phase 0 | **drifted → 40**; Phase 1 split `usage/` 1 → 7. Corrected in `refactor-phase-0-STATE.md` |
| "all 34 tests are outside A's four folders" | Phase 0 | **drifted → 38**, location claim intact. Corrected in `refactor-STATE.md` and Phase 0's STATE |

## The five edges

The carve's premise is that a product is a set of folders. Measured, five import
edges cross a boundary the wrong way:

| # | edge | direction | fix |
|---|---|---|---|
| 1 | `studio/{app,session}.py` → `hacks.mount` | C → adapters | `hacks/mount.py` → `contract/mount.py` |
| 2 | `hacks/{vanilla,polished}/play.py` → `dev_server.emulator` | C → D | `emulator.py`, `launcher.py` → `shared/` |
| 3 | `hacks/vanilla/lint/rules.py` → `maplint.textfit` | C → D | `textfit.py` → `shared/` |
| 4 | `hacks/vanilla/lint/context.py` → `maplint.suppressions` | C → D | `suppressions.py` → `contract/` |
| 5 | `hacks/prism/{write,offers}.py` → `studio.{resize,mapadd}` | D → C | the forms become each adapter's own |

Edges 2–4 all wear the same shape: **a family adapter reaching into a prism CLI**
for a module Phase −1 had already assigned elsewhere. Phase −1 called those
assignments in 2026-08-01 and nothing acted on them, because until Phase 2 broke
the cycle nothing could tell the difference between this and the general fusion.

Edge 5 is Phase 2's declared hand-forward. Edge 1 is the one nobody saw.

## `studio → hacks` was never in anyone's scope

`refactor-plan.md` states the goal as a rule about direction, and names the
violation it was built to fix: *"all three in-tree adapters import the IDE at
runtime"*. Phase 2's acceptance test greps `hacks/` for imports of `studio`. Both
read the arrow in one direction only.

**`studio/app.py:63` and `studio/session.py:42` import `hacks.mount`**, and always
have. It is not a defect in the mount — the studio has to find an adapter somehow —
but it means C cannot be carved from D by folder, and no document said so. The fix
is not to break the edge but to move its target: the mount is contract machinery,
not an adapter, and `contract/mount.py` keeps B's import bar intact because
`mount.py` imports `contract.Hack` and stdlib and nothing else.

**The lesson is about the check, not the file.** A one-directional test over one
folder pair cannot certify a four-product split. That is why the phase's oracle is
a declared membership map over *every* module and an assertion over *every*
cross-product edge, rather than another named-pair grep.

## The scan that missed `dev_server`

The first edge map was built by AST over `ast.ImportFrom` nodes with `n.level` set
— relative imports. It reported `dev_server` as importing **nothing**, and
`dev_server` in fact reaches `hacks.prism` five times and `shared` nine.

`dev_server` is the one package in the tree written with absolute imports
(`from pokeprism_devtools.shared import paths`). A relative-only scan does not
under-report it by a little; it reports it as a leaf.

**Both spellings, always** — recorded because the oracle depends on it and because
this is the third measurement error in this refactor of the same family: Phase −1's
import grep was wrong in both directions, Phase 1's `.pyc` faked a result, and this
one would have carved `dev_server` as a dependency-free package.

## The family adapters belong to C

`refactor-plan.md`'s product table had four rows and no home for `hacks/vanilla`
(35 files) or `hacks/polished` (14). What settles it: **`mount()` is called from
`studio/session.py`, `studio/app.py` and tests, and nowhere else.** No CLI mounts
an adapter. So vanilla and polished are reached only through the studio and ship
with it as its reference adapters, while prism is D because prism's own CLIs
(`mapfit`, `map_show`, `maplint`, `dev_server`, …) import `hacks/prism` directly.

The two are also one unit whether or not anyone wants them to be: `hacks/polished`
imports `hacks/vanilla` on 13 lines, and `vanilla/resize.py:161` imports polished
back.

## Nothing in `studio/` imports the survivors, and that is the design

The measurement reads like dead code and is not. `grep` for any studio-internal
import of `mapadd` or `resize` — `from .resize`, `from . import resize`, both
`mapadd` forms — returns **no hits at all** across `studio/`, including `screens/`.
Yet the studio has both features.

```
studio/app.py  (the `s` key)
  → session.form("resize")          studio/session.py:311 is `self.hack.writes.…`
    → hack.writes.form("resize")    the seam
      → hacks/prism/write.py:124      from ...studio.resize import resize_for
        → resize_for(DIALECT, "Prism")  → a class
  ← the studio instantiates whatever class it was handed
```

The studio holds the key binding and the form runner; the **adapter** decides that
this tree offers a resize and which dialect it runs against, and the adapter is
what imports the module. So "nothing imports it" is not evidence the feature is
dead — it is why these two were the last survivors of the cycle: the module sits in
`studio/`, and every arrow into it points up from below.

## One shared `Action`, not four

Phase 2 handed the survivors on as one item — *"neutral `Action` subclasses over
`wiring/`, reached from four adapter methods"* — and it was priced as a redesign of
both files. Grepping each **name** rather than each module says otherwise:

| name | prism | family | what it is |
|---|---|---|---|
| `AddMap`, `newmap_for`, `_BASE`, `_PLACES`, `section_choices` | — | yes | **family-only** — a move into `hacks/vanilla/`, no edit at all |
| `grids` | yes | yes | names no contract type — **A** |
| `ResizeMap`, `resize_for` | yes | yes | the one genuinely shared `Action` in the tree |

**Prism's new-map form is already its own** (`hacks/prism/newmap.NewMap`, chosen in
`write.py:126`); prism reaches `mapadd.py` for `grids` and nothing else. So of the
267 LOC in the two files, the part that has to be *written* rather than moved is
`ResizeMap` — about 40 lines, duplicated once into prism and once into vanilla.

And that duplication is sanctioned rather than tolerated: `refactor-plan.md` already
says of the duplicate-name hook *"never compare across adapters, since the three
`Reader`s are near-identical on purpose and would rank first."* A dialect-free form
per adapter is that same shape.

**The lesson is the unit of measurement.** Phase −1 found an import grep wrong in
both directions and concluded a *path literal* measures hack-specificity better.
This is the same error one level down: a module-level grep said "four adapter
methods reach two modules", which is true and priced the work at four times its
size. The name is the unit, not the module.

## A's tests are 3 of 38

Phase 0 handed forward "A has no test file" as part of its packaging debt, which
reads as a carve that was not run. Measured over what each test file imports, A can
claim **three**: `test_flagalloc`, `test_regions`, `test_usage`. Two more are
mostly A's and reach prism or vanilla for a fixture (`test_macroline`,
`test_placement`).

Everything else that exercises A does so through a hack's tree. **A's test story is
authorship, not a carve** — the largest unpriced item in Phase 3b, and it is priced
here instead of discovered there.
