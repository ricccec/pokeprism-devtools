# Phase 4 findings — the god objects

Plan: `refactor-phase-4-PLAN.md`. Index entry: `refactor-STATE.md` → Phase 4.

The same one line per finding is in the index; each links to the section below
that proves it.

- **The plan's characterization harness was wrong and is corrected in place**:
  `DevServer` drives `questionary` and reads no stdin at all. → *What drives the
  editors*
- **`tui.py` executes zero lines under the suite — it is never even imported.**
  Phase 1b's eight functions executed one line each; this executes none. → *The
  oracle that does not exist yet*
- **`studio/session.py` does not need this phase, and the sketch's premise is
  half right**: its methods *do* group onto the capabilities (writes 9, reads 7,
  plays 6, lints 4, measures 1), but 597 lines are **204 of code** across 45
  methods, none over 50. → *Session, measured*
- **`studio/app.py` is not obviously wanting**: 523 lines are **268 of code**,
  29 methods, the longest 36. → *Studio, measured*
- **Total LOC over-reports responsibility count in this repo's seam files** —
  `session.py` is 42% docstring, `app.py` 24%, `tui.py` **2%**. The number that
  separated the three targets was code lines, not file size. → *What the size
  column was measuring*
- **7 names owed, of which 2 are renames and 5 are readings** — the survey's
  over-reporting, itemised rather than allowlisted. → *The naming debt, itemised*
- **The bag's pocket table is spelled twice** (`apply._POCKETS` and
  `tui.DevServer._BAG_POCKETS`), and the second says so in a comment. → *One fact,
  two homes*
- **`dev_server` carries 13 functions over 50 LOC, only 6 of them in `tui.py`** —
  the other 7 are Phase 1b's shape one product over, and are recorded rather than
  scheduled. → *What `dev_server` still owes CLAUDE.md*
- **The suite baseline is 36/39 and reproduces; `test_studio_tui` is
  intermittent**, and the run that failed is the one whose output was discarded,
  so the cause is a guess and is labelled one. → *The baseline, and the fourth red*
- **The oracle exists: `tui.py` goes 0 → 673 of 914 lines, and all 48 seeded
  mutations were caught.** Every editor was at 1 executed line and is now at
  48–87. → *Steps 1–2 · the characterization test*
- **Three mutations survived the first fixture, and none was an assertion gap** —
  all three were the fixture's *shape*, which is Phase 1b's finding reproduced
  exactly. → *What the fixture could not tell apart*
- **A defect, found by the test and fixed before anything moves**: abandoning a
  party slot past the end of the party leaves `{}` gaps in `state.json`, and
  `apply._apply_party` refuses them — so the *next launch* dies and the only way
  out is editing the file by hand. **`Remove slot` had it too**, which only
  driving both ways out of the editor found. → *The defect the oracle found*
- **The first fix was wrong and a test caught it** — "drop trailing empties" is
  not "drop the gaps this call created", and the difference is somebody's
  hand-written `{}`. → *Step 2b · the fix*
- **R6 cannot see inside a class**: `surface-snapshot.py` digests `DevServer` as
  one CONTENT entry, so it cannot tell a commit that touched one method from one
  that touched all 23. **Step 3 needs a per-method digest**, and that is this
  phase's one departure from the method of the four before it. → *What R6 cannot
  see inside a class*
- **A second thing recorded, not endorsed**: a failed save-patch still spawns the
  emulator, so the game comes up on the old save. → *The defect the oracle found*
- **`_watch` and `_refresh_inventory_if_stale` are the same logic written
  twice** — a third fact with two homes, alongside the pocket table. → *One fact,
  two homes*

---

## What drives the editors

`refactor-plan.md`'s Phase 4 sketch said the characterization test drives the
editors "through scripted stdin". **Measured false and corrected in place** (the
sketch did not grow): `dev_server/tui.py` contains no `input()` and no read of
`sys.stdin`. Every prompt in all seven editors is `questionary.select`, `.text`,
`.autocomplete` or `.confirm`, built with `questionary.Choice` and
`questionary.Separator`.

The one `sys.stdin` in the package is `cli.py`'s `isatty()` check, which decides
whether the TUI runs at all — it never reads a byte.

`tests/test_map_new_cli.py` already holds the harness this needs, written by
Phase 1b for the same reason. Its `_fake_questionary_module` installer needs one
addition here: `Separator`, which the wizard never used and four of these editors
do.

## The oracle that does not exist yet

Five test files name `dev_server`; **none of them reaches `tui.py`**. Traced
under `sys.settrace` (2026-08-05) across all five — `test_contract`, `test_lib`,
`test_studio`, `test_products`, `test_prism_variable_sprites`:

    lines of tui.py executed: 0
    tui in sys.modules: False

Not one line, and the module is never imported: `cli.py` imports it lazily inside
`main`, on the interactive branch only, so nothing but a TTY ever loads it.

This is a step past Phase 1b, where eight uncovered functions still executed
**one** line each — their `def`, at import time. Here even that does not happen,
which makes the prerequisite stronger rather than weaker: there is no import-time
check that the file is syntactically reachable, let alone that an editor works.

## Session, measured

The sketch says *"its methods group onto the seam's own six capabilities, a
parallel that becomes structural rather than coincidental once the contract
package exists."* **The grouping is real.** Every method of `Session`, by which
`hack.*` capability its body touches:

| capability | methods | |
|---|---:|---|
| `writes` | 9 | `_writable`, `choices`, `follows`, `form`, `sprite_hint`, `warm`, `adders`, `deletion`, `editor` |
| `reads` | 7 | `maps`, `const_of`, `parses`, `load`, `sketch`, `texts`, `_finding` |
| `plays` | 6 | `_playable`, `plays`, `build_targets`, `keeps_build_line`, `build`, `boot` |
| `ctx` (lints) | 4 | `lints`, `lint`, `diagnostics`, `reload` |
| `measures` | 1 | `measures` |
| *(none)* | 14 | `drifted`, `_fresh`, `preview`, `apply`, `act`, `undo`, `undo_at`, `can_undo`, `mutations`, `findings`, `findings_for`, `recall_build_target`, `remember_build_target`, `_map_consts` |
| two at once | 3 | `__init__` (ctx+reads), `_invalidate` (ctx+writes), `measure` (measures+reads) |

**And the split still does not follow.** The file is 597 lines of which **204 are
code** — 249 are docstrings, 54 comments, 90 blank. Forty-five methods share those
204 lines: a mean of 4.5 code lines each, the longest body 32 (`apply`), and
**none over 50**. Splitting six ways yields files of roughly 30 code lines whose
whole content is delegation, and each would still need the `Session` to delegate
*from* — so the object does not go away, it acquires six collaborators that only
it can construct.

The 14 methods that touch no capability are the largest group and they are the
class's actual job: the build → preview → apply → undo cycle. That is the one
responsibility this file has; the capability-shaped methods are the facade over
the seam that makes the cycle expressible, and a facade is one thing.

**Left alone, recorded as a result.** Phase 1b's precedent is `map_show`, which
owed that phase nothing and said so.

## Studio, measured

`refactor-plan.md`: *"mostly not a target; Textual concentrates handlers by
design. Only the `action_*` mixin, and only if Phase 1 leaves it obviously
wanting."*

**It is not obviously wanting.** 523 lines, **268 of code**, 29 methods, longest
36 (`__init__`, which is mostly annotated attribute comments). Seven `action_*`
methods: `action_edit`, `action_add_map`, `action_delete`, `action_build`,
`action_focus_filter`, `action_zoom`, `action_refresh`. The file already carries
nine named sections, and the `Studio(Flow, App)` split has already moved the
whole edit cycle out to `flow.py`.

Extracting seven handlers averaging under 15 lines into a mixin would move the
handlers away from the `check_action` that decides which of them are offered,
which is the one non-obvious thing in the file.

**Left alone.** The condition the plan attached to it was not met, and that is
the answer, not a deferral.

### What the size column was measuring

The sketch ranked the three targets 914 / 597 / 523 and read that as three god
objects of decreasing severity. Measured by **code** lines they are 793 / 204 /
268, and the ranking is not the same list:

| file | total | docstring | comment | blank | **code** | prose share |
|---|---:|---:|---:|---:|---:|---:|
| `dev_server/tui.py` | 914 | 20 | 18 | 83 | **793** | **2%** |
| `studio/session.py` | 597 | 249 | 54 | 90 | **204** | 42% |
| `studio/app.py` | 523 | 128 | 58 | 69 | **268** | 24% |

The seam files this refactor produced are documented in prose *on purpose* — the
architecture arguments live in their module docstrings, and Phase 2 and 3 both
lean on them. So in this repo total LOC over-reports responsibility for exactly
the files a refactor is most tempted to split.

**This clears one axis and no others.** It is a count of lines and of function
lengths. It says nothing about coupling, fan-out, or how many reasons a file has
to change — `session.py` could still be two things for a reason no line count
would show, and the capability table above is the closest this phase came to
asking.

## The naming debt, itemised

Baseline 2026-08-05, `scripts/naming-survey.py`: **542 tree-wide** (A 107 · B 3 ·
C 135 · D 297) — reproduces the number in `refactor-plan.md` exactly. The files
this phase opens owe **7**, also as recorded.

Itemised, because the survey over-reports on purpose and the reading belongs
here rather than in its word list:

| name | file | verdict |
|---|---|---|
| `_int_in` | `dev_server/tui.py:905` | **rename** — a noun phrase; it returns a validator |
| `_pretty_path` | `dev_server/cli.py:198` | **rename** — an adjective on a noun |
| `looks_like_real_save` | `dev_server/apply.py:39` | reading — verb + object; `looks` is not in the word list |
| `recompute_checksums` | `dev_server/apply.py:458` | reading — verb + object; `recompute` is not in the word list |
| `needs_rebuild` | `dev_server/inventory.py:88` | reading — a predicate, verb + object |
| `main` | `dev_server/cli.py:42` | reading — R3 keeps it deliberately |
| `main` | `studio/app.py:502` | reading — R3 |

**Five of seven are the survey working as designed**, and the two real ones are
the two the rule was written for: a name that reads as an attribute rather than
an action. The word list is not touched.

## One fact, two homes

**The bag's pockets.** `tui.DevServer._BAG_POCKETS` and `apply._POCKETS` both
spell out the three bag pockets and, for each, its state key, whether it carries
a quantity, and which `pocket` attribute an item must have to belong to it. The
TUI's copy carries the comment `# … — mirrors apply._POCKETS`, so the duplication
is known and was written down instead of removed.

**The rebuild check.** Found while measuring coverage, not while reading:
`_refresh_inventory_if_stale` (called from the menu loop) and the `_watch` closure
inside `_start_rebuild_watcher` (the background thread) are the same seven lines
— stat the `.sym`, tolerate its absence, take the lock, compare against
`self.sym_mtime`, rebuild, write `inventory.json`, restamp. They differ only in
what surrounds them: one prints, the other may re-launch.

It shows up in the coverage table as the one body the tests barely reach —
`_watch` runs 1 of its 14 lines, because a test that drives a menu never starts
the thread. The logic *is* covered, in the other copy. **That is the cost of the
duplication stated precisely: the covered copy is not the one that runs while
you are building.**

Both are Phase 1b's step 11 shape — a fact that decides behaviour, spelled twice,
where changing one copy cannot fail a test. Paid as their own commits, after the
split, because a split may not also tidy.

## Steps 1–2 · the characterization test

`tests/test_dev_server.py`, new — `dev_server` had no test file of its own, so
this is the one package where Phase 1b's *"a characterization test goes where the
fixture already is"* had nowhere to go.

**152 checks over the server and all seven editors.** `tui.py` under it:

| | before | after |
|---|---:|---:|
| lines of `tui.py` executed | **0** | **673** of 914 |
| `_edit_pocket` (109 LOC) | 1 | 87 |
| `_edit_tmhms` (88) | 1 | 69 |
| `_edit_party_slot` (78) | 1 | 65 |
| `run` (64) | 3 | 53 |
| `_edit_flag_group` (55) | 1 | 47 |
| `_edit_player` (51) | 1 | 48 |
| `_print_status_block` (50) | 0 | 42 |

All six over-50 functions now have an oracle, so step 3 may start. Suite
**36/39 → 37/40**, the three known reds unchanged.

**Steps 1 and 2 landed as one commit**, against the PLAN's table, which asked for
two. The file was written and mutation-proven in two passes — the server first,
12/12, then the editors, 36/36 — but splitting the finished file back into those
two states afterwards would produce a commit describing a moment that had already
passed. The PLAN's reason for wanting them apart was that a body may not be
edited before something runs it, and no body is edited by either.

**Falsified: 48 seeded mutations, 48 caught** — 12 against the server (the menu's
order, its dispatch table, every field of the status block, the error path that
keeps a long-lived server alive) and 36 against the editors (transposed coord
bounds, a pocket offering the wrong items, TM/HMs ordered by name instead of by
bit, autosave writing over a preset, a preset merged rather than replacing).

Two things are stubbed, both at a real process boundary and nothing else:
`playtest.patch_save` and the emulator. `questionary` is replaced by the fake,
which is the library that reads a terminal, not the code under test.

**The order of a menu is part of the golden**, for the reason Phase 1b gives
about a wizard: a menu *is* its list, and reordering it changes what is offered
and where. The dispatch is checked entry by entry *and* against the menu's own
values, so an entry that stops being reachable cannot pass.

### What the fixture could not tell apart

**Three mutations survived the first draft, and not one was a missing assertion.**
All three were the fixture's shape — Phase 1b's finding, reproduced without
having to be looked for:

- **key items given a quantity they must never carry.** The normaliser only
  touches state.json's bare-string shorthand, and the fixture's key-item entry
  was written in dict form. One bare string in that pocket separates them.
- **an unset pocket left behind as `"balls": []`.** Backing out of a pocket does
  not save, so the trace is in memory and reaches disk on the *next* unrelated
  edit. Asserting on the file alone could not see it; the test now edits the
  player afterwards and reads the file then.
- **setting a flag that is already set, twice.** The prompt accepts any flag the
  tree defines, set or not, so "set it again" is something a user can type — and
  the fixture never typed it.

A fourth thing came out of this and is behaviour rather than a mutation:
`_edit_pocket` normalises to dict form **per pocket, as that pocket is opened**,
so a pocket nobody edited keeps whatever shorthand was hand-written in
state.json. Recorded in the assertion that noticed it.

## The defect the oracle found

**Abandoning a party slot past the end of the party leaves gaps.** Open slot 5
with two mons in the party and back out without naming a species: the editor
appends three empty dicts to reach the slot (`while idx >= len(party)`), pops
only the one that was asked for, and autosaves the other two. `state.json` ends
up holding `{}` entries, and `apply._apply_party` raises *invalid party entry:
{}* — so the **next launch** fails and the only way out is editing the file by
hand.

The intent is not in doubt. The code's own comment says *"Drop the slot entirely
if species was never set."* It drops one slot; it created three.

**Pinned before it is fixed**, per the ground rule that a move must never be the
thing that fixes a bug: `test_abandoning_a_slot_past_the_end_leaves_gaps` records
today's behaviour, including asking the real `_apply_party` what it does with the
result, so the fix is a commit with a visible diff and an oracle rather than a
line changed inside a move.

### Step 2b · the fix, and what it had to be careful about

`_drop_slot_and_its_gaps(party, idx, existing)`, called from **both** ways out of
the slot editor — backing out without a species, and `Remove slot`. The second
was not in the report that started this: filling a slot past the end and then
removing it leaves the same gaps, and only driving both found it.

**The first draft of the fix was wrong and a test caught it.** It dropped
*trailing* empty slots, which is not the same claim as "the gaps this call
created": remove slot 3 from a hand-written `[mon, {}, mon]` and the `{}` becomes
trailing, so a draft aimed at our own mess would have silently deleted somebody
else's. Passing `existing` — how many slots there were before the editor opened —
is what makes the function's sentence true. `test_a_hand_written_gap_is_left_alone`
is the check that says so, and the rejected draft is one of the seeded mutations.

**5 of 5 mutations caught**, including reverting either call site alone.

### What R6 cannot see inside a class

The confinement check on this commit came back with exactly two changed digests —
`DevServer` and the arriving `_drop_slot_and_its_gaps` — which is the right
answer and a much weaker one than it looks.

**`scripts/surface-snapshot.py` digests a class as a single CONTENT entry.** For a
phase whose entire target is one 23-method class, that means R6 cannot tell *"this
commit touched only `_edit_party_slot`"* from *"it touched all 23 methods"*. Every
commit from here to step 6 moves the `DevServer` line and says nothing more.

Step 3 needs an instrument the tool does not have: a **per-method** digest, so a
split can be proved the way Phase 1 proved a move — every body byte-identical,
only its home changed. That is written here rather than discovered at the commit,
and it is the one place this phase's method departs from the four before it.

**Also recorded, and not endorsed:** `_patch_and_launch` spawns the emulator even
when `_patch_save` failed, so the game comes up on the *old* save with nothing on
screen to say the patch did not happen. Pinned rather than changed — this phase
moves code, and deciding what should happen after a failed patch is not a
question a refactor gets to answer quietly.

## What `dev_server` still owes CLAUDE.md

Measured while sizing `tui.py`, because the phase opens four of these files for
their names and the list should exist rather than be rediscovered:

| file | total | code | functions > 50 LOC |
|---|---:|---:|---|
| `tui.py` | 914 | 793 | `_edit_pocket` 109, `_edit_tmhms` 88, `_edit_party_slot` 78, `run` 64, `_edit_flag_group` 55, `_edit_player` 51 |
| `apply.py` | 478 | 353 | `apply_state` 118, `_apply_items` 86, `_apply_party` 79 |
| `inventory.py` | 460 | 352 | `build` 161 |
| `cli.py` | 226 | 157 | `main` 154 |
| `test_maps.py` | 155 | 113 | `main` 119 |
| `playtest.py` | 124 | 57 | `patch_save` 56 (44 without its docstring) |

**Thirteen over 50, and only six are this phase's.** The other seven are Phase
1b's shape one product over: function-level debt with no oracle, in files whose
size is not the complaint. `inventory.build` at 161 and `cli.main` at 154 are the
two longest functions in the tree. Recorded, not scheduled — scheduling is not
this phase's to do, and the index is where it can be seen.

`dev_server/test_maps.py` is a source module named like a test file, 155 lines
holding one 119-line `main`. Noted for whoever schedules the above; the name is
its own small hazard next to a `tests/` directory.

## The baseline, and the fourth red

`refactor-plan.md`'s recorded baseline is **36/39** with three known reds:
`test_eventheader` and `test_maplint` (live-prism drift) and `test_lib` (needs
cwd inside a game repo).

The first full run of this phase reported **35/39**, with `test_studio_tui` as a
fourth red — which by the phase's own tripwire rule would mean something was
wrong before a line was edited. Four runs later:

| run | result |
|---|---|
| full suite, first time | `test_studio_tui` **red** — output discarded, so the reason is unrecorded |
| `test_studio_tui` alone | 88 tests, **OK**, 167s |
| `test_studio` then `test_studio_tui` | both **OK**, 194s |
| full suite, second time, every log kept | **36/39**, and the three known reds |

**The baseline is 36/39** and it reproduces. `test_studio_tui` is **intermittent**
— it is the slowest test in the suite by an order of magnitude and drives
Textual's `Pilot` against real timeouts, which is a plausible cause and is *not*
what was measured, because the one run that failed is the one whose output was
thrown away. What is established is the baseline and the intermittency; the cause
is a guess and is labelled as one.

**The working rule for the rest of the phase:** a red in `test_studio_tui` is
re-run alone before it is believed. A red in anything else is an edit that was
not what it claimed.

Two habits paid for this and both are Phase 1b's: discarding a failing run's
output cost a whole re-run, and *"the suite's answer is about the conditions it
ran under, not only about the code"* — the same family as the stale `.pyc`.
