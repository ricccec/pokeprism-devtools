# Phase 1b — pay what Phase 1 could not

Phase 1 moved code and proved it moved nothing else (R5). Every CLAUDE.md
violation that rode along inside a moved body is therefore still there, by
design, and this phase is the second commit R5 promised.

**Numbered 1b, not 2.** `refactor-phase-2-PLAN.md` already exists and Phases 2–5
are cross-referenced from four documents; renumbering would invalidate all of it
to save a letter. The name also says the truth — this is the back half of
calibration, not a new idea.

Findings: `refactor-phase-1b-STATE.md`. The rules R1–R5 are in
`refactor-phase-1-PLAN.md` and are not restated; this phase adds one.

## The debt, measured 2026-08-03

**Eleven functions over CLAUDE.md's 50 LOC**, and the column that decides the
phase is the third one — lines the whole suite actually executes:

| function | LOC | executed |
|---|---|---|
| `map_new.wizard._gather_spec` | 132 | **0** |
| `usage.diffreport.cmd_diff` | 77 | 62 |
| `mapfit.commands.cmd_add` | 76 | **0** |
| `mapfit.commands.cmd_consolidate` | 75 | **0** |
| `metatiles.cli.main` | 69 | **0** |
| `map_new.cli.main` | 68 | **0** |
| `usage.cli.main` | 66 | 49 |
| `map_inspect.cli.main` | 65 | **0** |
| `metatiles.report.render_report` | 65 | **0** |
| `map_inspect.mapinfo.collect` | 61 | 46 |
| `mapfit.cli.main` | 57 | **0** |

**Eight of eleven are executed by nothing.** Two of the three that are covered
are covered only because Phase 1 wrote `tests/test_usage.py`; before that they
were zero too. Shortening an unexecuted 76-line function is a rewrite with no
oracle — the same objection `refactor-plan.md` already raises against `DevServer`
in Phase 4, and it is why this phase is test-first rather than edit-first.

**One file over 250 LOC**: `mapfit/mapwire.py`, 357. Phase 1 did not touch it
because Phase 1's criterion was "what is fused into `__init__`" and `mapwire.py`
was already its own file. It has the best oracle in the six packages — 95% line
coverage — so it is the cheapest item here, not the dearest.

**Four bare-verb names**, which CLAUDE.md rejects by name: `map_inspect.collect`,
`metatiles.collect`, `metatiles.analyze`, `mapfit.packing.pack`. Reading the name
alone, none answers *what does this return or change?*

**Two functions nested four deep**: `usage.reports.cmd_banks`, `cmd_bank`.

**One magic value duplicated**, found while falsifying `test_usage.py`:
`getattr(args, "max_bank_usage", 95.0)` in `cmd_check` and `cmd_diff` restates
argparse's own `default=95.0`. The fallback is unreachable — mutating it changes
nothing, which is how it surfaced. Two spellings of one threshold, one dead.

## R6 · The snapshot tool changes job

In Phase 1 `scripts/surface-snapshot.py` proved a negative: CONTENT identical, so
nothing was edited. Here every commit edits something by intent, so that check
would fail on purpose and tell nobody anything.

**It proves confinement instead.** Before each edit, snapshot; after, diff; the
CONTENT lines that changed must be **exactly** the functions the commit set out
to change, and no others. A shrink that silently altered a neighbour shows up as
an extra changed digest.

*Corrected while running step 10.* This section first claimed that renaming a
function "appears as one name leaving and one arriving with an unchanged digest".
**It does not, and cannot.** The digest is of the function's source and the
source contains the `def` line, so a rename always changes it — as does every
caller that names the function. The check is still worth running on a rename,
but for the other side of the list: renaming `pack` to `pack_into_banks` moved
exactly three digests, the function and its two callers, and a fourth would have
meant the rename reached something it should not.

So the tool answers "did anything else move?" in both phases. Only the expected
answer differs.

## Order of work

**No function is shortened before something executes it.** That is the whole
shape of the phase; everything else is bookkeeping.

| # | commit | what proves it |
|---|---|---|
| 1 | characterization test for `map_inspect` CLI | new test green against unmodified code |
| 2 | characterization test for `metatiles` CLI | as 1 |
| 3 | characterization test for `mapfit` CLI | as 1 |
| 4 | characterization test for `map_show` CLI | as 1 |
| 5 | characterization test for `map_new`'s wizard | as 1; a fake `q` answers the prompts |
| 6 | split the argparse tree out of five `main`s | tests 1–5 + `test_usage` unchanged and green; R6 confines the diff |
| 7 | shorten `cmd_add`, `cmd_consolidate`, `cmd_diff`, `render_report`, `collect` | as 6 |
| 8 | shorten `_gather_spec` | as 6, on test 5 |
| 9 | split `mapfit/mapwire.py` (357) | a pure move — R2 applies, not R6 |
| 10 | name the four bare verbs | R6: digests unchanged, names replaced |
| 11 | flatten the two depth-4 bodies; name the duplicated threshold | as 6 |

Steps 1–5 are the phase. Steps 6–11 are cheap once they exist, and impossible
before. Commit 9 is the one commit here that is a *move*, so it is checked the
Phase 1 way.

**`tests/test_usage.py` is the pattern for 1–5** — build the input in memory, run
`main(argv)` under `redirect_stdout`, assert the exact bytes. It caught 5 of 6
seeded mutations, and the survivor was an equivalent mutation, not a gap. Two
adaptations: `map_show` and `metatiles` need a fixture tree rather than a
fixture file (`tests/test_map_inspect.py` already builds one), and `map_new`'s
wizard needs a fake `q` whose `text`/`select`/`path`/`autocomplete`/`confirm`
return canned answers.

## What must not break

- The six console entry points still resolve to a `main`.
- `hacks/prism/newmap.py` imports `map_new.TEMPLATE` and `mapfit.mapwire`.
- The suite stays at or above 32/35 and gains one test per step 1–5.
  `test_eventheader`, `test_maplint` and `test_lib` are red for reasons that
  predate this branch; a fourth red means an edit was not what it claimed.
- **Renames in step 10 reach `hacks/`, `studio/` and `maplint/` too.** Phase 1's
  packages have only two importers inside `src/`, but a bare-verb rename is a
  grep across the whole tree, not across six folders.
