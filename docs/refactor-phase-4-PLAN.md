# Phase 4 — the god objects

Findings: `refactor-phase-4-STATE.md`. Index entry: `refactor-STATE.md` → Phase 4.
Rules inherited: **R1–R5** (`refactor-phase-1-PLAN.md`), **R6**
(`refactor-phase-1b-PLAN.md`), **R7** (`refactor-phase-2-PLAN.md`), **R8**
(`refactor-phase-3-PLAN.md`). `CLAUDE.md` is the standard and is not restated.

## What this phase is

`DevServer` in `dev_server/tui.py` — ten interactive editors welded onto a
server. Everything else the sketch names is a **question to answer with a
measurement**, and the answers are already taken: see the STATE. Neither
`studio/session.py` nor `studio/app.py` is split here, and the STATE says why in
numbers rather than in judgement.

Re-measured 2026-08-05, before any code:

| file | total | **code** | functions | over 50 LOC |
|---|---|---|---|---|
| `dev_server/tui.py` | 914 | **793** | 27 | **6** |
| `studio/session.py` | 597 | **204** | 45 | 0 |
| `studio/app.py` | 523 | **268** | 29 | 0 |

## The prerequisite, and the correction that made it one

`refactor-plan.md` said the characterization test drives the editors "through
scripted stdin". **It is corrected in place**: `DevServer` drives `questionary`
and reads no stdin at all — not one `input()`, not one `sys.stdin` read in the
file. A harness built on scripted stdin would have driven nothing.

The harness that works already exists and is proven: `tests/test_map_new_cli.py`,
written by Phase 1b for the same reason — a wizard no test could reach. This
phase copies its pattern, including the idea worth keeping: **the fake runs each
prompt's own `validate` against the canned answer**, so a scripted run also
proves the answers are ones the code would have accepted.

`DevServer.__init__` takes 11 keyword arguments, all paths and flags, and that is
the fixture surface. It is reachable hermetically: `inventory.load_or_build`
returns a cached `inventory.json` whose `schema` matches and whose mtime beats
the `.sym`, so a fixture that writes one never parses a real `.sym`, and
`apply.load_state` reads plain JSON.

**Two things are stubbed, both at a real process boundary** — Phase 1b's rule, so
the code under test runs unchanged: `playtest.patch_save` (it writes a real `.sav`
against a real ROM) and `self.emulator` (it spawns SameBoy). Nothing else is
replaced. `questionary` is not a stub of the code under test; it is the library
that reads a terminal, which no test can have.

## The fixture's shape is chosen from the mutations it must fail on

Phase 1b's most expensive finding — ten mutations survived a first-draft fixture
because the fixture's *shape* made right and wrong output identical. So the
fixture is specified by what it has to be able to tell apart, and each is seeded
on disk and watched go red before it is believed:

- **a map whose width ≠ height**, so `_coord_bound` transposing the axes fails.
  Phase 1b hit exactly this with `mapgroup`'s `(H, W)`; a square map cannot see it.
- **a bag cap small enough to reach**, so the `pocket full` disabled branch runs.
- **an item in a pocket the editor is not showing**, so the `want_pocket` filter
  is not equivalent to "every item".
- **TM/HMs whose `bit` order differs from their name order**, so sorting by
  `bit_of` is distinguishable from sorting by name — and one whose `kind`/`num`
  label differs from its state name, since the editor offers labels and stores
  names.
- **two party slots, not one**, so `party.pop(idx)` cannot be confused with
  `party.pop()`, and a nickname on exactly one of them.
- **flags already set**, so remove and clear are distinguishable from each other.
- **a `state.json` that omits some sections**, since `(template)` versus an
  explicit empty list is a real distinction this file is careful about: the
  `_edit_tmhms` comment says an empty `"tmhms": []` created by *browsing* would
  mean "own nothing" at the next launch.

## Order of work

**No editor is shortened before something executes it.** Steps 1–2 are the
oracle; nothing before them touches `src/`.

| # | commit | what proves it |
|---|---|---|
| 1 | `tests/test_dev_server.py` — the fake `questionary`, the fixture, the menu loop, the status block | new test green against unmodified code; executed lines in `tui.py` go 0 → N |
| 2 | characterization cases for the seven editors | as 1; every seeded mutation caught, and the survivors recorded with the argument that they are equivalent |
| 2b | **fix the abandoned-slot defect** the oracle found | the pinned check flips; the diff is one guard, and it is not inside a move |
| 3 | split the editors out of `DevServer` into `dev_server/state/` | **a pure move** — R7 union over `dev_server` unchanged; tests 1–2b unchanged (R4) and green |
| 4 | shorten the six over-50 editors | R6 confinement: the digests that changed are exactly the functions named |
| 5 | the two facts spelled twice — the bag's pocket table, and the rebuild check | R6; the union loses the names named here and no other body moves |
| 6 | the naming debt this phase's files owe | R6 on a rename: the function plus its callers, and nothing else |

**2b was not in the plan and is not optional.** The ground rule is that a move
must never be the thing that fixes a bug: found mid-phase, it is fixed on the
tree as it stands, with its own test, *before* the file moves — otherwise no one
can say afterwards whether the move was behaviour-neutral. It is numbered `2b`
so the steps below it keep the numbers this file already gave them.

Steps 3–6 are each their own commit for the reason Phase 1b's step 9 and Phase
2's whole method give: a commit that both moves and tidies is provable as neither.

## Step 3 · the split, and why it can be a pure move

CLAUDE.md's "a cluster of related responsibilities → give each file one or two
and put them in a folder whose name says what domain they share", almost verbatim.

The domain is already named by the tool itself: `state.json`, `load_state`,
`apply_state`. The folder is **`dev_server/state/`** and each file is named for
the section of the state it edits — `player.py`, `position.py`, `party.py`,
`bag.py`, `flags.py`, `tmhms.py`, `presets.py`. Not an architectural name among
them, and the grouping is not invented here: `apply.py` already splits the same
state the same way, into `_apply_player`, `_apply_map`, `_apply_party`,
`_apply_items`, `_apply_flags`, `_apply_tmhms`.

**Each file defines one mixin class and `DevServer` inherits them**, which is
what lets the split be a move rather than a rewrite: every body keeps `self.state`,
`self.inv` and `self._save_state()` unchanged, so the CONTENT union is unchanged
and R7 applies unaltered. The alternative — free functions taking the state — edits
every body in the same commit that moves it, and proves nothing.

The pattern is this repo's own: `studio/app.py`'s `class Studio(Flow, App)` splits
the shell across two classes exactly this way, and `studio/flow.py` is the half
that lives elsewhere.

What stays in `tui.py` is the server: the menu loop, the status block, the `.sym`
watcher, patch-and-launch, and saving the state.

## What must not break

- **`tests/test_products.py` is live.** `dev_server` is product D and `studio/` is
  product C; this phase straddles both and must create no edge between them. A new
  `dev_server/state/` package is inside D, and the test's membership map is by
  top-level folder, so it needs no edit — if it does, the edit is a finding.
- **The two `KNOWN_LEAKS` are Phase 5's** (`shared/paths.py`, `asmedit/regions.py`).
  They are asserted in both directions. Nothing here touches them; if one
  disappears, the list is shrunk deliberately in the same commit, because the test
  catches a stale row but cannot know it was this phase.
- **The suite baseline**, established in the STATE. A red beyond it means an edit
  was not what it claimed. Run with `PYTHONDONTWRITEBYTECODE=1`, `__pycache__`
  cleared first, and never against a tree a background suite is reading.
- **R4**: imports may be rewritten in tests, assertions may not.

## What the oracle proves, and what the phase claims

Written before the work, per the ground rule, because the gap is invisible from
inside the phase.

**The oracle proves** that `DevServer`'s seven editors ask the same questions in
the same order, accept and refuse the same answers, and leave the same
`state.json` on disk, before and after the split — and that the split moved no
body, by CONTENT union.

**The phase claims** that `dev_server/tui.py` was one file holding two
responsibilities and is now a server plus a folder of editors named for what they
edit.

**The gap:** behaviour preserved is not structure improved. A characterization
test would pass just as green over a split into `part1.py` and `part2.py`. Nothing
here measures whether the folder's name is right or whether the seven files are
the seven a reader would have drawn — that judgement is the phase's, made in the
open, and the STATE records the alternatives that were rejected.
