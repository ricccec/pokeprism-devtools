# Where the four-product split stands

**The index.** One entry per phase: its files, its status, and one line per finding.
Nothing is argued here — follow the link when a line matters to you.

- `refactor-plan.md` — the argument: why four products, the phases, the order.
- `refactor-phase-<n>-PLAN.md` — a phase's own working plan, written when it opens.
- `refactor-phase-<n>-STATE.md` — that phase's findings, written as it runs.

**Read this file, then exactly one phase's STATE.** Findings carry the date they
were taken; re-verify the ones your phase leans on, not all of them (plan →
"Starting a session", step 1).

## Phase −1 · the product survey — **done 2026-08-01**

**Findings:** `refactor-phase--1-STATE.md` · no PLAN (it predates the convention)

- Import greps were wrong three ways; a path literal measures hack-specificity better.
- `maps.py` is a Gen-2 fact — its catalog walk reads all three trees unchanged.
- `blobsizes.PRIMARY_HEADER_GROWTH` was 8; prism's macro emits 9 bytes — **fixed
  2026-08-01**, and the test counts the macro's bytes rather than restating them.
- The macro-line reader was hand-rolled 15 times, with three different answers — the
  label-anchored ones **lifted into `wiring/macroline.py` 2026-08-01**; the rest ask
  an unanchored question a label-keyed reader cannot serve.
- Prism's header read path and its own write path disagreed about arguments — **fixed
  2026-08-01**, they share the writer's anchor.
- **Both defects had a green test pinning the wrong answer.** A test that restates a
  constant instead of naming it defends nothing; when a check spells a value out, ask
  what would ever tell it the value is wrong.
- **B ships separately** — no CLI needs it; every adapter does, and must not reach C.
- Every CLI got an (a)/(b)/(c) call; `mapview` is the strongest candidate for (b).
- `dev_server`'s service half *is* prism's `Plays`, wearing a CLI's name.
- `maplint/diagnostics.py` is contract vocabulary — two family adapters import it.
- `dev_server/emulator.py` is already neutral: both family adapters import it.
- The LZ codec fork is legitimate; one duplicated helper, deliberately not scheduled.
- `rules_geometry.py` was deferred to Phase 5 rather than answered without evidence.

## Phase 0 · split the git history — **tooling proven; A snapshotted 2026-08-03**

**Plan:** `refactor-phase-0-PLAN.md` · **Findings:** `refactor-phase-0-STATE.md`

**No product exists yet.** What Phase 0 delivered is a proven carve and a correct path
list: `scripts/carve-product-a.sh` — re-run it, do not re-derive it. Its output sits at
`~/code/ricccec/pokecrystal-asm-lib-history-2026-08-03` (`main`, 88 commits, 34 files,
no remote) as a **dated backup only**; **3b** re-carves and supersedes it. Phases 2
and 3 removed what blocked B, C and D, so nothing gates the real carve but its
position — last, after 4 and 5.

- **A naive carve loses A's first month** — 73 commits by folder, 88 with every
  historical spelling; the 15 lost are the birth of the LZ decompressor, the sym
  reader and both CLIs. **The oldest reasoning is the most renamed.**
- Three layouts (`_lib/` → flat → subfolders) plus a round trip through `hacks/prism/`:
  "record every rename" reads forward, but the past needed it first.
- **Build the ledger from recorded renames** — `git log --diff-filter=R --name-status -M`
  walked backward from today's paths, not `git log --follow`, which invents ancestry
  for empty files. One reads a chain git wrote down; the other asks a heuristic to
  guess one. `--follow` is still right for *verifying* a finished carve.
- **Carve first, rename `wiring/` after** — renaming first is a 31-file, 50-import
  commit in the phase premised on an untouched tree, and buys nothing since the rename
  lands inside the carved history anyway.
- **D's ledger must name eight `wiring/*` files, not the folder** — `connections`,
  `mapedit`, `objedit`, `props`, `removal`, `scaffold`, `text`, `warps` lived there
  until `033fbe4`. A history filter reads the *old* spelling forever; renaming inside
  A cannot reach back. Nothing here concerns imports.
- **A holds 7 commits that are purely prism's** — the cost of naming the `wiring/`
  folder. Harmless (absent from A's tip), and the lesson is the asymmetry:
  over-collecting leaves a dead file, under-collecting loses live reasoning.
- **Counting commits does not prove a carve** — `--follow` crossing the renames is
  what says they survived as one story rather than a delete plus an add.
- `--no-local` + `filter-repo` rewrites **every branch**; the carve arrived with four,
  all strict ancestors, checked before pruning.
- SHAs are rewritten, so any SHA quoted in `docs/` never resolves in A.
- **A is history plus source and nothing else** — packaging, entry points and all 39
  tests are outside its four folders. Phase 3 paid that with a decision table.
- **Carving early bought the rehearsal, not the repo** — the plan's own "not
  now-or-never" holds: this repo's past is immutable and A's four folders are stable
  paths, so 3b re-carves the same history. The snapshot takes **no commits**, and A's
  code keeps changing **here** through Phase 5. This finding is now load-bearing
  twice — it is one of the three reasons the carve was scheduled last.
- Re-verified: A imports nothing from `studio`, `hacks` or `maplint` — 25 grep hits,
  **every one in a docstring**. The word says entangled; the import says free.

## Phase 1 · calibration, the six CLI packages — **all six split 2026-08-03**

**Plan:** `refactor-phase-1-PLAN.md` · **Findings:** `refactor-phase-1-STATE.md`

**The rules are the deliverable, and they are in the PLAN as R1–R5** — Phases 2–5
inherit them. In short: an `__init__.py` re-exports and defines nothing; a split
may not edit a body, so a CLAUDE.md violation that survives the move gets its own
commit afterwards; `scripts/surface-snapshot.py` proves a move textually, because
the tests cannot. Every file is now under 250 LOC, all but four under 150.

- The filename test for coverage was wrong both ways — `map_show` is covered by two
  tests not named for it, `usage` by nothing.
- **Coverage tracks the split that already happened** — the six `__init__.py` ran
  28–54% of themselves (`usage` 0%), the two files already carved out of `mapfit`
  ran 93–95%. "Is it test-covered?" was never a question these tests could answer
  for this phase: the uncovered majority is the render/CLI half a split relocates.
  **So a move is proved textually, not by test** — content digested and compared,
  which is a stronger claim than a sampled behaviour still agreeing.
- An `__init__.py` re-exports its own imports by accident — `map_show` exposed 9
  foreign modules and 7 stdlib names. Splitting shrank the six surfaces by 20–38
  names each, so the post-move check **cannot** be "surface identical".
- **Comparing what `__init__` exposes cannot tell a moved private from a deleted
  one** — the check has to be over what the package *defines*. Found on the first
  package, which is why the first package was the smallest.
- The verification tool was confidently wrong twice before it worked: unstable
  `repr` (hash seed, addresses) made it cry wolf every run, and trusting
  `__module__` on non-callables silently dropped every `_FOO_RE` constant.
- **A stale `.pyc` faked a passing mutation test** — same-length edit, same second,
  so mtime and size both matched. Aimed straight at this refactor's method: clear
  `__pycache__` before believing a suite that follows a revert.
- Tests reach package-private names (`metatiles._blob_sizes`,
  `mapfit._lift_free_space`, `map_new._consts`) — 4 names across 3 packages, each
  now imported from the submodule that owns it. A fifth, `mapfit.compressed_blk_size`,
  was a false alarm: the grep matched a `print` label, not a call.
- `tests/test_mapnew.py` does not test `map_new` — it covers `wiring/mapnew.py` and
  `hacks/vanilla/newmap.py`. One underscore apart, unrelated code.
- `usage/` has no parse/analyse seam: its analysis is `shared/mapfile.py`'s. The
  four-way template is a hypothesis about seams, not a filing system — `map_inspect`
  filed sort keys under "Rendering", and they belong with the record they order.
- **`usage/` now has the test it never had** — golden output for all eight
  subcommands, written before the split and **unchanged** across it.
- 11 functions still break CLAUDE.md's 50-LOC limit, 5 of them the same `main`
  shape; `mapfit/mapwire.py` (357, untouched here) still breaks the 250-LOC one.
  Not fixed here, because a move may not — **this list is Phase 1b**.

Sizes to work from are in `refactor-phase--1-STATE.md` → "Phase 1's six CLI packages".

## Phase 1b · pay what Phase 1 could not — **done 2026-08-03**

**Plan:** `refactor-phase-1b-PLAN.md` · **Findings:** `refactor-phase-1b-STATE.md`

The second commit R5 promised: every CLAUDE.md violation Phase 1 moved without
fixing, because a move may not edit a body. **Numbered 1b so Phases 2–5 keep their
numbers** — they are cross-referenced from four documents.

- **Eight of the eleven over-long functions are executed by nothing**, so the phase
  is test-first: no function is shortened before something runs it. Steps 1–5 are
  characterization tests; 6–11 are cheap once they exist and impossible before.
- Two of the three that *are* covered are covered only because Phase 1 wrote
  `tests/test_usage.py` — which is also the pattern the five new tests copy.
- **The snapshot tool changes job (R6).** In Phase 1 it proved CONTENT identical;
  here every commit edits by intent, so it proves the change is *confined* to the
  functions named in the commit. Same question, different expected answer.
- Also owed: `mapfit/mapwire.py` (357 LOC, but 95% covered — the cheapest item),
  4 bare-verb names CLAUDE.md rejects, 2 bodies nested four deep, and one
  threshold spelled twice with the second copy unreachable.
- The debt re-measured on the day it was planned: **all eleven, unchanged**, and
  the executed column reproduces to the line.
- **`> 50` is this phase's working number**, recorded as a reading of CLAUDE.md's
  `~50` rather than a restatement of it — the rule stays soft, the list stays
  re-runnable.
- The eight uncovered functions execute **exactly one line — their `def`**; Phase
  1 counted the same fact as 0. Both harnesses are right.
- **A characterization test goes where the fixture already is** — four of the five
  packages own a test that builds one, so this phase adds one file, not five.
- `map_inspect`: `main` went **1 → 52 executed lines**, and the goldens caught
  **7 of 7** seeded mutations.
- **The goldens carry invisible trailing spaces** — the table pads its last column
  — and a guard now says so before all thirteen fail at once.
- **A guessed golden was wrong three ways; a recorded one was right.** `mapgroup`
  is `(H, W)`, not `(W, H)`, so the CLI was right and the guess was wrong.
- **A mutation run and a suite run cannot share a working tree** — same family as
  Phase 1's stale `.pyc`.
- **A fixture is only as good as what it can falsify.** Ten mutations survived a
  first-draft fixture across three packages, every one because the fixture's
  *shape* made right and wrong output identical — not because an assertion was
  missing. Choose a fixture from the mutations it must fail on.
- **All eleven targets now have an oracle** — the eight that executed nothing now
  execute 44–101 lines each, so steps 6–11 may start.
- Two mutations survive honestly: sorting the wizard's group list is provably a
  no-op, and **`map_new.cli.main`'s `spec.validate` block is unreachable from the
  wizard**. Recorded, not removed — this phase shortens, it does not drop
  behaviour.
- **`map_show` owed this phase nothing** (no over-long function), so its new test
  is insurance for Phase 3 rather than an oracle for any edit here.
- **R6's stated signature for a rename was wrong** — a rename always changes the
  digest, because the digest is of source that contains the `def` line. The PLAN
  and `scripts/surface-snapshot.py` are corrected; what the check is worth on a
  rename is that *nothing else* moved.
- **Step 6's "five argparse trees" was four** — `map_new`'s `main` is a wizard
  driver with no parser, long for a different reason, and split by phase instead.
- **A word-boundary rename is not a rename**: it missed a real importer
  (`mapfit/commands.py` imports `pack`) and rewrote four pieces of prose. Phase 1
  hit the same trap from the other side. The word is not the call, either way.
- **Step 9 stayed a pure move by leaving a magic value unnamed** — a commit that
  both moves and tidies is neither provable as a move nor reviewable as an edit.
- **The debt is paid in full**: 11 → 0 over-long functions, 1 → 0 oversized files,
  4 → 0 bare verbs, 2 → 0 depth-4 bodies, 1 → 0 duplicated thresholds. Two items
  are recorded rather than fixed, both named in the STATE.

## Phase 2 · the keystone, `Hack` and its vocabulary — **done 2026-08-04**

**Plan:** `refactor-phase-2-PLAN.md` · **Findings:** `refactor-phase-2-STATE.md`

The cycle is broken: 28 adapter modules imported the IDE, 4 still do. The folder is
**`contract/`** — decided, not still open — 15 files, 1122 LOC, importing stdlib and
three `shared/` modules and nothing else. **B ships separately** (Phase −1) is now
*possible*; the distribution is Phase 3's. Suite 34/37 → **35/38**.

- **`panels.py` was half the cycle and half of it is not contract** —
  `studio/actions.py` is imported by 20 adapter modules to `panels`'s 11, and 22
  of `panels.py`'s 44 names are the IDE's table builders, which no adapter has
  ever touched.
- **The PLAN's load-bearing measurement was of the wrong file.** "`panels.py`'s
  only import is `shared.coords`" is true and answers nothing; what matters is
  what the *contract* imports. **B depends on A** — `Tile`, `Rgb`/`Swatch`, `Edit`
  — narrowly, and A cannot import B back without inverting the arrow.
- **`Diagnostic` had to move, and that was forced.** `Lints` answers
  `list[Diagnostic]`, so the contract could not state its own linting question
  without importing a CLI. Phase −1 called it contract vocabulary; this is the
  phase that could act. The suppression half stayed, as `maplint/suppressions.py`.
- **R7 — across packages, CONTENT is a union.** One package's list shrinks and
  another's grows, so the invariant is the sorted concatenation. Held at every
  step: 146 → 146, 247 → 247, 336 → 336.
- **The move and the rename are separate commits**: the vocabulary landed under a
  re-export shim first, so no importer changed; the shim came down next, so no
  body changed. Phase 1b's step 9, learned again.
- **A word-boundary rename is still not a rename** — `panels` → `tables` collided
  with a local variable holding a `MapTables`, and **CONTENT could not tell**: the
  digest it reported as changed was expected and correct, and wrong. Third phase
  running to pay for this.
- **A `TYPE_CHECKING`-only import passes a runtime check and fails a static one**,
  measured on a seeded mutation — which is why `tests/test_contract.py` has both.
  A plain top-level one no longer *runs*: the cycle is unbuildable now.
- **CONTENT cannot see a duplicate alias appear or leave** — collapsing the two
  spellings of `Rgb`/`Swatch` moved no digest at all.
- **Two `hacks → studio` edges survive**, both neutral forms over `wiring/`
  (`mapadd`, `resize`), three of the four call sites function-local imports. Not
  the IDE, not the contract; Phase 3's to home. The test asserts the list in both
  directions so a shorter one cannot pass silently.

## Phase 3 · make the products separable — **done 2026-08-04**

**Plan:** `refactor-phase-3-PLAN.md` · **Findings:** `refactor-phase-3-STATE.md`

**"Mechanical once Phase 2 lands" is false — the products are not folders yet.**
Five cross-product import edges survived Phase 2, so a carve run then produced four
repos that import each other. The phase split: **3** makes the folders equal the
products, **3b** carves them.

**All five edges are now closed and a test says so.** `wiring/` is `asmedit/`, the
mount is `contract/mount.py`, and `tests/test_products.py` asserts the membership
map and every cross-product arrow. Suite **35/38 → 36/39**. 3b is unblocked.

- **`studio → hacks` is a cycle direction nobody ever named** — `studio/app.py:63`
  and `studio/session.py:42` import `hacks.mount`, and always have. The goal, the
  plan and Phase 2's acceptance test all read the arrow one way only. The fix is to
  move the target, not break the edge: the mount is contract machinery.
- Three of the five edges are the same shape — **a family adapter reaching into a
  prism CLI** (`dev_server.emulator`, `maplint.textfit`, `maplint.suppressions`) for
  a module Phase −1 assigned elsewhere on 2026-08-01 and nothing could act on until
  the cycle broke.
- **A relative-only import scan reports `dev_server` as a leaf.** It is the one
  package written with absolute imports and it reaches `hacks.prism` five times.
  Both spellings, always — third measurement error of this family in this refactor.
- **The family adapters ship with C** — `mount()` is called from two studio modules
  and tests, nowhere else; no CLI mounts an adapter. `refactor-plan.md`'s table had
  four rows and no home for either.
- **Nothing in `studio/` imports the two survivors, and that is the seam working** —
  the adapter imports the form and hands the class back up. Not dead code, and it is
  why these two outlived the cycle.
- **A owns 3 test files of 38** (`test_flagalloc`, `test_regions`, `test_usage`).
  A's test story is authorship, not a carve — 3b's largest unpriced item.
- Re-verified and holding: `contract/` imports only `shared`, the four `hacks →
  studio` edges, the carve path list, the `wiring/` rename cost (31 files / 50
  imports), 35/38. Drifted and corrected in place: A is 40 files, the suite is 38.
- **The survivors are two names, not two modules.** Only `grids` (→ A) and
  `resize_for` (one copy per adapter) are reached from prism; `studio/mapadd.py` is
  a **C→C edge already** and this phase does not touch it. **The name is the unit of
  measurement, not the module** — Phase −1's import-grep lesson one level down.
- **`AddMap` is the generic new-map form and two of three hacks already mount it**
  as dialects; prism is the one never written. So the plan's first draft, which
  called it family-only and moved it into `hacks/vanilla/`, would have buried the
  generic form inside one hack. Caught by the user reading the plan.
- **The third dialect, costed and deliberately not scheduled** — of prism's ~235
  code lines, **~118 duplicate what the family already has generically** (`_collisions`
  is written twice with the same three messages) and **~68 are one thing, bank
  placement**. A redesign, not a move; recorded so nobody answers it by reflex.
- **A substring check passes for the wrong reason** — commit 0 went green with the
  form's edge guard deleted, because the mechanism underneath refuses an empty edge
  in words that also contain "edge". **A check has to name the layer it tests.**
  5 of 6 seeded mutations caught; the survivor is provably equivalent.
- **An edge map is not an importer list, and it is wrong in both directions** — the
  mount's repoint touched 5 src lines not 2 (three `claim.py` files reach it
  intra-package, so no cross-product scan could see them), the emulator's touched 3
  not 4 (prism *uses* `Emulator` through a re-export, never imports it). Re-measure
  before each commit.
- **B's bar covers an arrival without being told** — `contract_modules()` globs, so
  `mount.py` was inside it the day it landed; proved by seeding a violation into the
  moved file. The mount is reached as `contract.mount` and re-exported nowhere, so
  SURFACE gains only the one addition R2 permits.
- Moved without fixing, per R5: `shared/launcher.py` is an architectural name where
  `sameboy` is the domain one, and `tests/test_studio.py` reaches D for a mock —
  3b's test split, priced here rather than discovered there.
- **A comment's stated reason can die while the code it defends stays right** —
  `maplint.all_rules`'s lazy import lost its argument when the finding channel left,
  and is still worth 32 modules (23 vs 55). Measured before rewriting the sentence;
  deleting it on the expired reason would have been a regression.
- **A commit that duplicates a body needs an oracle per copy.** Commit 8 retyped the
  resize form into two adapters and only prism's had one — the family's closest test
  proved a form was *offered*, never ran it. Added as commit 7b, 5 of 6 mutations
  caught. The plan counted the duplication as one thing because it was one commit.
- **The `wiring/` rename paid for being read hit by hit, three times over** — 13
  docstrings named files that left for `hacks/prism/` a year ago (a rename would
  have made them *more* wrong), ~40 hits are the English word, and **3 were live
  guards spelled as strings** (`FORBIDDEN`, `READERS`, and a `"wiring" in d`) that
  would have passed forever while guarding nothing. Phase 1b and 2 were bitten by a
  rename *reaching* too far; this one would have *missed*. Same lesson, both ways.
- **A falsification needs falsifying.** The first attempt at re-checking those three
  guards seeded an import above `from __future__`, so three "catches" were
  `SyntaxError`s, not guards firing.
- **A imports no third-party module at all** — the packaging draft said "stdlib +
  Pillow"; Pillow and questionary are D's. Also: `textual` is an optional extra that
  must become C's hard dependency, `rich` is undeclared anywhere, and the
  `pokeprism_devtools.hacks` entry-point group spans three distributions, which
  makes it a published ABI. Tests divide A 3 · B 3 · C 13 · D 19.

## Phase 4 · the god objects — not started

**Plan:** not written · **Findings:** none yet

Sizes and the `DevServer` breakdown are in `refactor-phase--1-STATE.md` → "Phase 4's
god objects". Its characterization test is a mandatory prerequisite, not a step.

## Phase 5 · the maplint survey, then the family port — not started

**Plan:** not written · **Findings:** none yet

Inherits one unanswered question from Phase −1: whether `rules_geometry.py`'s rules
are Gen-2 facts or prism facts. The seven prism-importing rule modules are listed in
`refactor-phase--1-STATE.md`.

## Phase 3b · carve the remaining products — **last, after 4 and 5**

**Plan:** not written · **Findings:** none yet

Four ledgers, four repos, the import rewrite, the test split, and the packaging
files. **Unblocked 2026-08-04** by Phase 3, then **scheduled last 2026-08-05** by
the user. The name stays `3b` because four documents cross-reference it.

- **The carve goes after Phases 4 and 5, not before** — "after 3, never before" was
  a floor being read as a position. Three findings move it: Phase 3's
  `tests/test_products.py` is a **monorepo-only instrument** and fails its first
  check in all four carved repos, so every phase it should watch must precede it;
  Phase 5's family port is a **D→C migration**, one refactor here and a two-repo
  coordination problem after; and Phase 0 measured that an early carve buys the
  rehearsal, not the repo, leaving a copy free to drift. Phase 4 is neutral — its
  three targets each sit inside one product. **An external consumer of A or B would
  overturn this**; there is none. → `refactor-phase-3-STATE.md`, "Why the carve
  goes last".
- **This repo stays every product's only editable copy through Phases 4 and 5** —
  which answers the question deferred on 2026-08-04. Where the four repos finally
  go is still 3b's to ask.

What Phase 3 leaves on 3b's desk, all of it written down rather than waiting to be
discovered: the packaging decision table (Phase 3's PLAN), three files that moved
into A from outside it and still owe ledger rows (named in
`scripts/carve-product-a.sh`, which now carries **both** the `wiring` and `asmedit`
spellings because a history filter reads the old one forever), and the test split —
A owns 3 of 39, and `test_studio.py`/`test_studio_tui.py` import all four products.
