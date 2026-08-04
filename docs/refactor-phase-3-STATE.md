# Phase 3 — make the products separable · findings

**Plan:** `refactor-phase-3-PLAN.md` · **Index:** `refactor-STATE.md` → Phase 3

The one line this phase carries into the index, and where it is proved:

> **"Mechanical once Phase 2 lands" is false — the products are not folders yet.**
> Five cross-product import edges survive Phase 2, so a carve run today produces
> four repos that import each other. → "The five edges".

**Status: the phase is complete — commits 0–11 landed 2026-08-04.** All five
cross-product edges are closed and `tests/test_products.py` says so. Suite
**35/38 → 36/39**, the three known reds unchanged throughout, re-run before and
after every commit.

**The order changed once, deliberately.** Commit 10 (the oracle) was pulled ahead
of commit 9 (the `wiring/` rename), so the phase's riskiest commit landed against
a live product check rather than a grep and a suite. It cannot run any earlier
than that — the five edges are exactly what it fails on. Its only cost was one
literal in the new test, which commit 9 renamed with everything else.

**One commit was added: 7b**, a characterization test for the *family* resize
form. Commit 8 retypes that body into two adapters and only prism's had an
oracle — see [the half that had no test](#the-copy-that-had-no-oracle).

## Findings — the same list as the index, each linked to its evidence

- Phase 3 is not mechanical; five edges survive — [the five edges](#the-five-edges).
- **`studio → hacks` is a cycle direction nobody ever named** — [the edge Phase 2 could not see](#studio--hacks-was-never-in-anyones-scope).
- **A relative-only import scan is blind to a whole package** — [the measurement that was wrong once](#the-scan-that-missed-dev_server).
- The family adapters are reached only through the studio — [what settled C's row](#the-family-adapters-belong-to-c).
- **The two survivors are not dead code; nothing importing them is the seam working** — [the trace](#nothing-in-studio-imports-the-survivors-and-that-is-the-design).
- **The survivors are two names, not two modules; `mapadd.py` is already legal where it is** — [name by name](#two-names-not-two-modules--and-the-module-was-never-the-problem).
- **`AddMap` is the generic new-map form with two of three dialects written** — [prism is the one never written](#addmap-is-the-generic-form-with-two-of-three-dialects-written).
- **`_collisions` is written twice, same three messages** — [the port's cost](#what-the-third-dialect-would-cost--measured-not-guessed).
- **A substring check passes for the wrong reason** — the layer underneath answers for it — [commit 0's falsification](#commit-0--what-falsifying-it-found).
- A owns 3 test files of 39 — [A's test story is authorship](#as-tests-are-3-of-39).
- **An edge map is not an importer list, and it is wrong in both directions** — [what the repoints actually touched](#an-edge-map-is-not-an-importer-list).
- **B's bar checks a file the day it arrives, without being told** — [`contract_modules()` globs](#bs-bar-covers-arrivals-by-construction).
- The mount is reached as `contract.mount`, not re-exported — [why the noun list stays a noun list](#the-mount-is-not-in-the-contracts-__init__).
- **`shared/launcher.py` carries an architectural name over an available domain one** — [the tidy-up a move may not do](#what-edges-1-and-2-moved-without-fixing).
- **A docstring's stated reason can die while the code it defends stays right** — [`all_rules` re-measured](#the-deferred-import-outlived-its-reason).
- **Commit 8's second copy had no oracle, and the plan did not notice** — [what the family form never ran](#the-copy-that-had-no-oracle).
- **The rename found thirteen docstrings already a year stale** — [reading every hit paid twice](#the-rename-found-what-a-rename-would-have-preserved).
- **Three of the rename's hits were live guards spelled as strings** — [they would have gone on passing](#three-string-literals-were-guarding-nothing).
- **A's dependency list was wrong: it has none** — [the packaging measurement](#packaging-measured-not-restated).
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

## Two names, not two modules — and the module was never the problem

Phase 2 handed the survivors on as one item: *"neutral `Action` subclasses over
`wiring/`, reached from four adapter methods"*. True, and it priced the work at
four times its size, because the adapter *method* is not the unit. The **name** is:

| name | prism reaches it | family reaches it | verdict |
|---|---|---|---|
| `grids` | `prism/offers.py:69` | `vanilla/newmap.py:302` | → **A**, names no contract type |
| `resize_for` | `prism/write.py:124` | `vanilla/write.py:220` | one copy per adapter |
| `AddMap`, `newmap_for`, `section_choices`, `_BASE`, `_PLACES` | — | yes | **stays** |

**`studio/mapadd.py` is a C→C edge already.** Nothing in prism imports `AddMap`,
`newmap_for` or `section_choices`, and vanilla ships with C — so the module is
separable where it stands and Phase 3 has no business moving it. Its home is a
*naming* problem, not a separability one.

Which matters, because the first draft of this phase's plan called it "family-only"
and scheduled a move into `hacks/vanilla/`. **That would have been a defect**, and
the reason is the section below.

This is Phase −1's lesson one level down. It found an import grep wrong in both
directions and concluded a path literal measures hack-specificity better; here a
module-level grep answered a question only a name-level one could answer.

## `AddMap` is the generic form, with two of three dialects written

It never branches. It holds no hack name. It reads `dialect.header_args`
(`mapadd.py:130`) and passes the dialect down to `wiring/mapnew.add_map`
(`:135`), and `newmap_for` builds `FIELDS` from what the dialect declares
(`:150-156`). The writer underneath is the same — `add_map` calls
`dialect.placements`, `.blk_name`, `.header_line`, `.attributes_line`,
`.blocks_entry`, `.script_entry`, `.template`, and the five mentions of a hack
name in `wiring/mapnew.py` are all prose in docstrings.

**Two of the three hacks already mount it**: `newmap.VANILLA` and
`newmap.POLISHED` are its dialects (`vanilla/write.py:223-226`,
`polished/claim.py:57`), pure declared data plus a placement callable. That is the
"hack differences cross the seam as declared data" rule working exactly as written.

So "prism's new-map form is already its own" — the phrasing this plan first used —
described the anomaly and called it the design. Prism is the dialect that was never
written, and burying the generic form inside one hack would have inverted the
relationship whether or not prism is ever ported.

### What the third dialect would cost — measured, not guessed

`hacks/prism/newmap.py` is 279 lines, ~235 of code. Classified against what the
dialect mechanism already provides:

| | lines | |
|---|---|---|
| duplicates something the family already has generically | **~118** | `_collisions`, `_unknown_names`, `blk_source`, `__init__`/`describe`/`selects`, 7 of its fields, the enum tables |
| prism only, and all of it one thing: **bank placement** | **~68** | `_bank`, `spec()` → `MapSpec`, `run()`'s `mapwire`/`pin_sections`/`.toml` half |
| older rather than different | ~16 | `sketch` returns a coloured `BlockData`; the family returns a neutral `contract.Sketch` each reader colours |

**The sharpest of these:** `hacks/prism/newmap.py:235-260` and
`wiring/mapnew.py:237-254` are the same three collision checks producing the same
three messages — *"X is already a map id"*, *"X is already a map"*, *"maps/X.asm
already exists — it belongs to something"* — and their docstrings make the same
argument about the half-collision and rgbds failing at link time minutes later.
Written twice, against different parsers.

And bank placement sits on an axis the design already has: `_PLACES`/`asks` is
*"which blobs have a placement question"* — polished mints, vanilla joins, prism
would pin.

**Not scheduled.** It is a redesign, it reaches `MapSpec` and `mapfit.mapwire`
(a (c) CLI), and this refactor proves moves. Phase −1's **(c)** call is about the
CLI `map_new`, not this form; the shared name is why nobody asked until now.

## Commit 0 — what falsifying it found

The characterization test for prism's resize form (`tests/test_wiring.py`,
`test_the_resize_form`) went green on the first run. Six mutations were then
seeded into `studio/resize.py` on disk, one at a time, and **two survived**.

- **A substring check passes for the wrong reason.** Deleting the form's
  `if not self.text("edge")` guard left the test green: `mapresize.resize` refuses
  the empty edge itself with *"edge must be one of …"*, the form wraps that in an
  `ActionError` exactly as it should, and a check for `"edge" in str(exc)` cannot
  tell the form's refusal from the mechanism's. Now matched exactly against the
  form's own words, `"pick an edge"`, and the mutation goes red. **The check has
  to name the layer it is testing**, or the layer underneath answers for it.
- **The other survivor is honest.** Passing `""` where the form passes `None` is
  invisible because `wiring/mapresize.py:278` opens with `raw = (fill or "").strip()`
  — the two are identical by construction, so no fixture can separate them.
  Recorded, not chased (Phase 1b: two mutations survived honestly there too).
- **And it found dead code.** That equivalence means `self.text("fill") or None`
  at `resize.py:55` converts a value the callee already converts. **Not fixed** —
  R5 forbids a tidy-up riding along, and commit 8 copies this body, so the copy
  carries it and dropping it is a separate commit or a separate phase.

Final: **5 of 6 caught**, `src/` unmutated afterwards, suite 35/38.

## An edge map is not an importer list

The five-edges table names the modules whose arrows point the wrong way. The
repoint commits need a different list — **every line that names the moved
module** — and taking the first for the second was wrong twice, once each way.

| move | edge map says | measured on the day |
|---|---|---|
| `mount` | `studio/{app,session}.py` | **5 src lines**: those two, plus `hacks/{prism,polished,vanilla}/claim.py` reaching `..mount` for `NearMiss` |
| `emulator` | `hacks/{vanilla,polished,prism}/play.py` | **3 src lines**: prism reaches `Emulator` through `playtest`'s re-export, never directly |

The three `claim.py` imports were **intra-package**, so no scan looking for
cross-product edges could ever have reported them; they are adapter→contract
now, which is the direction the split wants anyway. The prism `play.py` entry
was the opposite mistake — a module that *uses* `Emulator` counted as a module
that *imports* it.

This is Phase −1's grep lesson and Phase 3's own "the name is the unit of
measurement" arriving together: **the edge map answers "which arrows are
illegal", the repoint asks "which lines name this module", and they are not the
same question.** Re-measure immediately before each commit; the answer is cheap
and the assumption is not.

`dev_server/launcher.py` had exactly one importer, `emulator.py`, which moved
with it — so that shim came down repointing nothing at all.

## B's bar covers arrivals by construction

`tests/test_contract.py`'s static check builds its list with
`contract_modules()`, which globs `contract/*.py`. So `mount.py` was inside the
import bar the moment it landed, with no edit to the test.

**Checked rather than assumed**: `from ..studio import resize` was seeded into
`contract/mount.py` on disk and two checks went red — the static one and the
one that says the contract reaches no in-repo package but `shared/`. Removed,
green again. The bar is 15 files wide now and did not widen.

## The mount is not in the contract's `__init__`

`contract/__init__.py` is the noun list and the question list — that is what its
own docstring promises and what makes it readable in one sitting. The mount is
machinery: it is *called*, not *implemented*, and no adapter answers it. So it
is reached as `contract.mount` and appears in no `__all__`.

The practical consequence is that R2 stays satisfiable. `import contract`
gained exactly one name, the submodule binding `mount`, which is the single
addition R2 permits; had the `__init__` re-exported `mount`, `UnknownTree` and
`NearMiss`, SURFACE would have gained three names it must not.

## What edges 1 and 2 moved without fixing

R5 forbids a tidy-up riding along a move, so both are recorded here rather than
done. Neither is a defect.

- **`shared/launcher.py` is an architectural name with a domain one available.**
  It defines `build_cmd`, `focus_after_launch` and `_resolve_bin`, and every one
  of them is about *SameBoy* — where the binary is, how to start it so `Popen`
  tracks a real PID. CLAUDE.md says never use an architectural noun where a
  domain one exists, and `shared/sameboy.py` is that noun. Its docstring also
  still opens "SameBoy launch helpers for prism-dev", which stopped being true
  the moment two family adapters started booting through it.
- **`tests/test_studio.py` imports `dev_server.playtest`** (lines 545, 691) to
  patch `Emulator.launch`. That is a C test reaching D, and moving the emulator
  did not touch it, because patching a class attribute reaches the same object
  whichever module names it. Not a src edge and not this phase's; it is priced
  here so **3b's test split finds it written down** rather than discovering it.

## The deferred import outlived its reason

`maplint/__init__.all_rules` imports the seven rule modules inside the function,
and said why: reaching this package *for the finding channel alone* —
`maplint.suppressions`, `maplint.textfit` — should not drag in the rules and
through them all of `hacks.prism`.

Commit 5 moved both halves of that channel out, so the reason was gone. **The
deferral was re-measured before the docstring was rewritten**, and it is still
worth keeping for a different reason: `import maplint` leaves **23** modules in
`sys.modules` with it and **55** without, 18 of them prism's map parsers.

Also checked and **false**: that the deferral prevents a circular import.
Hoisting the rules to module top imports cleanly both ways, because
`hacks/prism/claim.py` reaches `maplint.context` inside a function.

The general shape is worth having: **a comment's *claim* can stop being true
while the code it defends stays right.** Deleting the deferral because its stated
reason had expired would have been a 32-module regression, and keeping the
sentence would have been a lie. Measuring separated them.

Afterwards, **no module outside `maplint/` imports `maplint` at all.**

## The copy that had no oracle

Commit 0 built a characterization test for prism's `ResizeMap.run` — the fifteen
lines between the `s` key and `mapresize.resize` — because commit 8 retypes them.
Commit 8 retypes them **twice**, and the plan's acceptance line for the family
half was "`test_vanilla`/`test_polished` green".

Measured: the closest thing the family had was
`s.form("resize").dialect.shape.height_first is False`, which proves a form is
*offered* carrying the right dialect and never runs it. Every other family resize
test calls `mapresize.resize` directly. **Those fifteen lines executed nowhere on
the family side**, and they are exactly the lines a copy gets wrong quietly —
each carries a default or a conversion whose failure is invisible.

So commit **7b** mirrors commit 0 in `tests/test_vanilla.py`, on the TOWN_A
fixture already there, reached through `Session` the way the studio reaches it.
Six mutations seeded into `studio/resize.py`, **5 caught**; the survivor is the
same provably-equivalent one prism's twin found (`mapresize` opens with
`raw = (fill or "").strip()`, so `""` and `None` cannot be told apart).

**The lesson is about the plan, not the test.** A commit that duplicates a body
needs an oracle *per copy*, and "the existing suite is green" counted the
duplication as one thing because the plan named it as one commit.

Commit 8 then proved the copies the way R8 requires. The CONTENT union over
`studio` and `hacks` lost exactly `ResizeMap` and `resize_for` and nothing else;
the arrivals, invisible to that tool, were diffed against the deleted original,
where `FIELDS`, `__init__`, `describe` and `run` are **byte-identical in both
copies** and the only differences are the `dialect` stamp and each copy's own
comment. Prism stamps `dialect = DIALECT` and needs no factory; the family keeps
`resize_for` because one class serves both its trees.

## The rename found what a rename would have preserved

Commit 9 was read hit by hit rather than done as a word-boundary rename, and the
reading is what paid. Three separate finds, none of which a `sed` reaches:

**Thirteen docstrings named files that left `wiring/` a year ago.**
`wiring/objedit.py`, `wiring/props.py`, `wiring/removal.py`, `wiring/warps.py`,
`wiring/text.py`, `wiring/mapedit.py`, `wiring/connections.py` — all eight moved
to `hacks/prism/` at `033fbe4` (2026-07-25), and eleven files still pointed at
the old home. **A rename would have rewritten them to `asmedit/objedit.py` and
made them more wrong**, in a commit whose whole claim is that references are now
correct. They name `hacks/prism/` now.

**About forty hits are the English word and must not change.**
"build-and-boot wiring", "Wiring two maps together", "the wiring is a provable
no-op", "wiring a map", `_resolve_wiring`. A word-boundary rename destroys every
one.

**The three `WiringError`s are not renamed.** The phase plan cites them as the
evidence that a meaningless folder name attaches to anything, which is true and
is not the same as saying they are the debt: two of them name a *different sense*
of the word — wiring two maps together — and the third is `mapfit`'s own. The
evidence for a rename is not automatically its target.

## Three string literals were guarding nothing

The sharpest of commit 9's hits. Three places name the package **as a string**,
and each is a live guard:

| where | what it guards |
|---|---|
| `test_contract.py` `FORBIDDEN` | no contract module reaches the asm editors |
| `test_vanilla.py:695` | `contract/action.py` imports no adapter and no editor |
| `test_studio_tui.py` `READERS` | no studio *view* module reads the repo itself |

Left spelled `"wiring"`, all three keep passing forever while guarding a package
that no longer exists. This is the mirror image of Phase 1b's `pack` and Phase
2's `panels`: those renames **reached** something they should not have, and this
one would have **missed** three things it must. The word is not the call, in
either direction.

All three re-falsified after renaming, with an import seeded into a real module,
and all three caught it. The first attempt at that falsification was itself
wrong — the seed was prepended *above* `from __future__ import annotations`, so
three "catches" were `SyntaxError`s rather than guards firing. **A falsification
needs falsifying too**; the second attempt inserted after the `__future__` line
and produced three real failures naming `asmedit`.

## Packaging, measured not restated

The draft table said **A depends on "stdlib + Pillow"**. Measured by AST over
every module, **A imports no third-party module at all** — `Pillow` belongs to
`gfx_view`/`mapview` and `questionary` to `map_new`'s wizard, both D. A is stdlib
only, which is what "a pret/RGBDS library" ought to mean and is a stronger
selling point than the draft claimed.

Three more, in the PLAN's table: `textual` is an *optional* extra today and must
become a hard dependency of C once C is its own distribution; `rich` is imported
eleven times by C and declared in no `pyproject.toml` at all; and the
`pokeprism_devtools.hacks` entry-point group **spans three distributions** — C
registers two adapters, D registers one, B's mount reads the group — which makes
that string a published ABI four `pyproject.toml` files must agree on.

## A's tests are 3 of 39

Phase 0 handed forward "A has no test file" as part of its packaging debt, which
reads as a carve that was not run. Measured over what each test file imports, A can
claim **three**: `test_flagalloc`, `test_regions`, `test_usage`. Two more are
mostly A's and reach prism or vanilla for a fixture (`test_macroline`,
`test_placement`).

Re-measured across all 39 at the end of the phase, assigning each test to the
highest product it reaches: **A 3, B 3, C 13, D 19**, plus `test_products` which
imports nothing at all — it reads the tree by path.

Everything else that exercises A does so through a hack's tree. **A's test story is
authorship, not a carve** — the largest unpriced item in Phase 3b, and it is priced
here instead of discovered there.
