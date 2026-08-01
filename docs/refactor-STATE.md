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

## Phase 0 · split the git history — not started

**Plan:** not written · **Findings:** none yet

Carve product A only; B, C and D wait on Phase 2, which is the phase that breaks the
`hacks → studio` cycle.

## Phase 1 · calibration, the six CLI packages — not started

**Plan:** not written · **Findings:** none yet

Sizes to work from are in `refactor-phase--1-STATE.md` → "Phase 1's six CLI packages".

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
