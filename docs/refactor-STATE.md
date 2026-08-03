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
no remote) as a **dated backup only**; Phase 3 re-carves and supersedes it. B, C and D
still wait on Phase 2, the phase that breaks the `hacks → studio` cycle.

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
- **A is history plus source and nothing else** — packaging, entry points and all 34
  tests are outside its four folders. Phase 3 owes A a packaging story.
- **Carving early bought the rehearsal, not the repo** — the plan's own "not
  now-or-never" holds: this repo's past is immutable and A's four folders are stable
  paths, so Phase 3 re-carves the same history. The snapshot takes **no commits**, the
  `wiring/` rename moves to Phase 3, and A's code keeps changing **here** — `usage/` is
  one of Phase 1's six packages.
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

- The filename test for coverage was wrong both ways — `map_show` is covered by two
  tests not named for it, `usage` by nothing.
- **Coverage tracks the split that already happened** — the six `__init__.py` run
  28–54% of themselves (`usage` 0%), the two files already carved out of `mapfit`
  run 93–95%. "Is it test-covered?" was never a question these tests could answer
  for this phase: the uncovered majority is the render/CLI half a split relocates.
- An `__init__.py` re-exports its own imports by accident — `map_show` exposes 9
  foreign modules and 7 stdlib names. A split therefore *shrinks* the surface, so
  the post-move check cannot be "surface identical".
- Tests reach package-private names (`metatiles._blob_sizes`,
  `mapfit._lift_free_space`, `map_new._consts`) — 4 names across 3 packages, each
  now imported from the submodule that owns it. A fifth, `mapfit.compressed_blk_size`,
  was a false alarm: the grep matched a `print` label, not a call.
- `tests/test_mapnew.py` does not test `map_new` — it covers `wiring/mapnew.py` and
  `hacks/vanilla/newmap.py`. One underscore apart, unrelated code.
- `usage/` has no parse/analyse seam: its analysis is `shared/mapfile.py`'s. The
  four-way template is a hypothesis about seams, not a filing system.

## Phase 1b · pay what Phase 1 could not — **planned 2026-08-03, not started**

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

## Phase 2 · the keystone, `Hack` and its vocabulary — not started

**Plan:** `refactor-phase-2-PLAN.md` · **Findings:** none yet

Carries one decision already made: **B ships separately** (Phase −1). The naming
census's Tier 1 is the file list it acts on.

## Phase 3 · split the remaining products — not started

**Plan:** not written · **Findings:** none yet

## Phase 4 · the god objects — not started

**Plan:** not written · **Findings:** none yet

Sizes and the `DevServer` breakdown are in `refactor-phase--1-STATE.md` → "Phase 4's
god objects". Its characterization test is a mandatory prerequisite, not a step.

## Phase 5 · the maplint survey, then the family port — not started

**Plan:** not written · **Findings:** none yet

Inherits one unanswered question from Phase −1: whether `rules_geometry.py`'s rules
are Gen-2 facts or prism facts. The seven prism-importing rule modules are listed in
`refactor-phase--1-STATE.md`.
