# Phase 1 findings — the six CLI packages

Plan: `refactor-phase-1-PLAN.md`. Index entry: `refactor-STATE.md` → Phase 1.

The same one line per finding is in the index; each links to the section below
that proves it.

- The filename test for coverage was wrong both ways — `map_show` is covered by
  two tests not named for it, `usage` by nothing. → *Coverage, measured*
- Coverage tracks the split that already happened: the six `__init__.py` run
  28–54% of themselves (`usage` 0%), the two files already carved out of
  `mapfit` run 93–95%. → *Coverage, measured*
- An `__init__.py` re-exports its own imports by accident — `map_show` exposes 9
  foreign modules and 7 stdlib names. So a split *shrinks* the surface, and the
  post-move check cannot be "surface identical". → *The surface is mostly leakage*
- Tests reach package-private names (`metatiles._blob_sizes`,
  `mapfit._lift_free_space`, `map_new._gather_spec`), and one name its package
  does not define (`mapfit.compressed_blk_size`). → *Tests reach through*
- `tests/test_mapnew.py` does not test `map_new` — it covers `wiring/mapnew.py`
  and `hacks/vanilla/newmap.py`. → *Tests reach through*
- `usage/` has no parse/analyse seam to split on: its analysis is
  `shared/mapfile.py`'s. Its two `# ---` lines are untitled and mark neither.
  → *The banner hypothesis*
- Checking a split against what `__init__` *exposes* cannot tell a moved private
  from a deleted one. The check has to be over what the package *defines*.
  → *What the first split corrected*
- The verification tool reported a false diff on every run before it worked, and
  silently dropped every `_FOO_RE` constant. Both were found by running it twice
  and reading the output, not by it failing. → *Two ways the tool lied*
- **A stale `.pyc` faked a passing mutation test.** Same-length edit, same
  second: mtime and size both matched, so Python ran the mutated bytecode while
  `inspect.getsource` read the restored file. → *Stale bytecode*
- `map_inspect`'s sort keys belong with the record they order, not the table
  the banner filed them under. → *What the first split corrected*
- The splits leave 2 functions over CLAUDE.md's 50-LOC limit in `map_inspect`
  alone; a move may not fix them (PLAN → R5). → *What the moves still owe*

---

## Coverage, measured

Measured 2026-08-03 by running the seven tests that reference these packages
under `sys.settrace`, counting executable lines from the compiled code objects.
`coverage` is not installed in `.venv`; the harness is in the session scratchpad,
not the repo — it measures, it does not verify anything later phases need.

| file | exec lines | hit | % |
|---|---|---|---|
| `mapfit/mapwire.py` | 194 | 185 | **95%** |
| `mapfit/packing.py` | 107 | 100 | **93%** |
| `map_inspect/__init__.py` | 189 | 102 | 54% |
| `map_show/__init__.py` | 230 | 106 | 46% |
| `metatiles/__init__.py` | 446 | 151 | 34% |
| `mapfit/__init__.py` | 404 | 132 | 33% |
| `map_new/__init__.py` | 218 | 61 | 28% |
| `usage/__init__.py` | 345 | 0 | **0%** |

Two readings, and the second is the one that changed the plan.

**The filename test was wrong both ways.** `tests/` holds `test_metatiles`,
`test_mapfit`, `test_map_new`, `test_map_inspect` and no `test_usage` or
`test_map_show`, which reads as two uncovered packages. `map_show` is in fact
covered — `test_grid.py` exercises `fit_zoom`/`ZOOMS`, `test_mapsource.py`
exercises `build_spec`/`gather_blobs`/`MapNotFound`. Only `usage` is genuinely
untested: no test file imports it at all. The hits for the word "usage" in
`test_metatiles.py` are `metatile_usage`, a different thing.

**Coverage tracks the split, not the package.** The two files already carved out
of `mapfit` sit at 93–95%. Every file still fused into an `__init__` sits at
28–54%. The uncovered majority is in each file's render and CLI half — the exact
code a split relocates wholesale. So "is it test-covered?" was never a question
these tests could answer for this phase: none of them certifies the code being
moved. The plan's oracle is textual instead.

## The surface is mostly leakage

`import pokeprism_devtools.map_show` today exposes, besides its own eight names:
`Path`, `argparse`, `os`, `re`, `shutil`, `sys`, `dataclass`, `MapFile`,
`MapSpec`, `PRIMARY_HEADER_GROWTH`, `compressed_blk_size`, `secondary_size`, and
the modules `blocksrc`, `coords`, `eventheader`, `maps_mod`, `mapsource`,
`paths`, `render`, `swatches`. None of it is `map_show`'s public surface; all of
it is reachable because `__init__.py` is where the imports happen to sit.

This is why the phase's post-move check is asymmetric (PLAN → R2): surviving
names must be byte-identical, disappearing names must be leakage. A symmetric
"the surface did not change" check would forbid the cleanup the phase is for.

## Tests reach through

The existing tests do not confine themselves to public API:

- `test_metatiles.py` imports `_blob_sizes`, `_COLLISION_PER_METATILE`,
  `_TILES_PER_METATILE` from the package.
- `test_mapfit.py` reads `mapfit._lift_free_space`.
- `test_map_new.py` reads `map_new._consts`, `_existing_groups` and
  `_existing_labels_consts`.

Under a re-exports-only `__init__` these move to the submodule that owns them,
which is an import-line edit (PLAN → R4), not a behaviour change. Four names
across three packages; every other test needed nothing.

**One reported case was not real.** `mapfit.compressed_blk_size` was recorded
here as a name `mapfit` re-exports without defining and a test depends on. The
test does not: the only mention in `tests/` is inside a `print` label, and the
test imports the real symbol from `hacks/prism/blobsizes.py`. A grep for
`mapfit\.<name>` matched a string, and reading the match rather than counting it
is what caught it. The accidental re-export was real and is now gone; nothing
depended on it.

Separately: **`tests/test_mapnew.py` is not `map_new`'s test.** It imports
`wiring/mapnew.py` and `hacks/vanilla/newmap.py`; `map_new`'s test is
`test_map_new.py`. The two names differ by one underscore and cover unrelated
code.

## The banner hypothesis

Five of the seven files carry titled `# ---` banners that do mark the seams:
`metatiles` (7 sections), `mapfit` (5), `map_inspect` (5), `map_new` (3),
`map_show` (1, over the grid half). `mapfit/mapwire.py` and `mapfit/packing.py`
are already split and need none.

`usage/__init__.py` is the exception. Its two `# ---` lines carry no title, and
they separate helpers from commands and commands from `main` — not
parse/analyse/render. That is not sloppiness: `usage` has no analysis of its
own. `shared/mapfile.py` parses the link map and `MapFile`'s methods answer the
questions; `usage` is eight report printers and an argparse tree. Its split
follows what it holds, not the four-way template.

## What the first split corrected

`map_inspect` went first because it is the smallest and best-covered, so that
the rules would meet reality where a mistake is cheap. Two of them were wrong.

**The check was aimed at the wrong thing.** R2 originally asked that every name
surviving in `__init__` keep its body, and that every dropped name be an import
or a foreign symbol. The `map_inspect` split dropped fifteen names that were
neither: `_fmt_row`, `_SORT_KEYS`, `_blk_sizes`, `_NPC_RE` and the rest are the
package's own privates, and moving them into the submodule that owns them is the
whole point. Comparing `__init__`'s namespace cannot distinguish that move from a
deletion — the two look identical from outside.

So the snapshot now covers the package's **content**: every function, class and
constant it defines anywhere, digested, with the owning file deliberately left
out. A move does not change it; an edit does. That is both the correct check and
a stronger one, since it also covers code `__init__` never exposed. The
`map_inspect` split passes it exactly — content byte-identical, surface down from
30 names to 7, and the only additions are the three submodule bindings Python
creates on import and no `__init__` controls.

**The banners are a hypothesis, confirmed on the first file.** `_SORT_KEYS` and
`_NULLABLE_SORTS` sit under `map_inspect`'s `# Rendering` banner. They do not
render anything: they say how to *order* `MapInfo` records, and `main` uses them
to sort and to build argparse's `choices`. They went to `mapinfo.py`, with the
record whose fields they name. Following the banner would have filed ordering
under drawing and coupled `cli.py` to `table.py` for a reason that is not real.

## Two ways the tool lied

`scripts/surface-snapshot.py` produced confident, wrong output twice before it
was right. Both were caught by running it and reading the result, which is the
only reason to write the tool before trusting it.

**It reported a diff on every run.** `repr` is not stable across processes: a
`frozenset`'s iteration order follows the interpreter's hash seed, and a
function's repr carries its address. `map_inspect` has both — `_AGGREGATE_SCRIPTS`
and `_SORT_KEYS`, whose values are lambdas. Three consecutive runs gave three
different answers. A verification tool that cries wolf on every run is worse than
none: it trains the reader to skip its output.

**It silently dropped every compiled regex.** Crediting an object to the module
in `obj.__module__` is right for a function or a class and wrong for everything
else — a compiled pattern reports `re`, so `_NPC_RE` was filed as foreign and
left out of CONTENT entirely. These packages are full of module-level
`_FOO_RE` constants; an edit to any of them would have passed the check unseen.
`__module__` is now consulted only for functions and classes.

## Stale bytecode

While falsifying `tests/test_usage.py`, a mutation was reverted and the test kept
failing against a tree `git` reported as clean. The mutation had replaced `16`
with `10` — the same number of bytes — and the revert landed in the same second,
so the `.pyc` header's mtime and size both still matched and Python loaded the
mutated bytecode. `inspect.getsource` reads the `.py`, so the source printed
correct while the code that ran was not.

This is worth more than the ten minutes it cost, because it is aimed straight at
this refactor's method: every phase moves files and re-runs a suite to claim
nothing changed. Clear `__pycache__` before a verification run, or set
`PYTHONDONTWRITEBYTECODE=1`, and never trust a green suite that follows a revert.

## What the moves still owe

Per R5 a split may not edit a body, so functions that break CLAUDE.md arrive in
their new file still breaking it. Recorded here rather than fixed, so the
follow-up is a list rather than a memory — **it is Phase 1b**
(`refactor-phase-1b-PLAN.md`), which exists because this list is too long to
carry as a memory and too test-poor to work without an oracle.

**Every file Phase 1 wrote is under 250 LOC**, the largest being
`mapfit/commands.py` at 243; eight are over 150. One file in these packages is
still over 250 — `mapfit/mapwire.py` at 357 — which Phase 1 did not touch because
its criterion was "what is fused into `__init__`", and `mapwire.py` was already
its own file. 250 LOC is a different criterion, and it is Phase 1b's.

| package | functions over 50 LOC after the split |
|---|---|
| `map_inspect` | `cli.main` (65), `mapinfo.collect` (61) |
| `map_show` | none |
| `map_new` | `cli.main` (68), `wizard._gather_spec` (132) |
| `usage` | `cli.main` (66), `diffreport.cmd_diff` (77) |
| `metatiles` | `cli.main` (69), `report.render_report` (65) |
| `mapfit` | `cli.main` (57), `commands.cmd_add` (76), `commands.cmd_consolidate` (75) |

**Five of the eleven are `main`,** and they are one shape: an argparse tree of
20-odd `add_argument` calls followed by a dispatch. Splitting the parser out of
the dispatch fixes all five the same way and is the obvious first follow-up.
`_gather_spec` at 132 is the outlier and a different problem — it is twenty
prompts in sequence, one per `MapSpec` field, and shortening it means deciding
what a group of prompts is.

## The six splits, and what proved each one

Every package: CONTENT byte-identical, SURFACE smaller, no addition but the
submodule bindings Python creates on import.

| package | before | after | surface |
|---|---|---|---|
| `map_inspect` | 287 | 11 / 135 / 80 / 76 | −25 |
| `map_show` | 340 | 31 / 138 / 109 / 59 / 49 | −32 |
| `map_new` | 354 | 20 / 166 / 81 / 65 / 44 | −20 |
| `usage` | 445 | 20 / 195 / 94 / 85 / 50 / 41 / 30 | −24 |
| `metatiles` | 670 | 31 / 187 / 170 / 161 / 149 | −38 |
| `mapfit` | 602 | 35 / 243 / 123 / 89 / 78 / 68 / 42 | −31 |

The suite ends at **32/35**, which is the baseline: 31 before the phase, plus the
new `tests/test_usage.py`. The three reds are the ones that were red before the
branch — `test_eventheader` and `test_maplint` (live-prism drift), `test_lib`
(needs cwd inside a game repo).

`usage` is the one whose oracle was written for the occasion, and
`tests/test_usage.py` passed **unchanged** across its split — the goldens were
recorded before the package moved and never touched after. That is the check R2
cannot make: R2 says the text did not change, the goldens say the program still
prints the same bytes.

Three deviations from the intended shape, all decided with the file open:

- **`usage` split its reports in two.** Seven commands read one link map; `diff`
  reads two and loads them itself. `reports.py` at 195 plus `diffreport.py` at 94
  beats one 260-line file, and the seam is a real difference rather than a size
  target.
- **`mapfit` needed a sixth file.** `commands.py` came out at 274 with the
  spec-loading helpers in it, so `_load_spec`, `_load_baseline`,
  `_apply_placement_flags` and `_check_dedicated_sections` became `specload.py`.
  That is the plan's open question answered: 243 and 68.
- **No `mapfit/placement.py`.** The spec-aware planning (`plan_placement`,
  `resolve_manual`, `map_items`) went into `freespace.py` beside the free space it
  spends. Phase −1 recorded `Placement` in `mapfit/packing.py` colliding with
  `wiring/placement.py` in both name and job; a third file of that name would have
  made the census worse from inside a phase premised on changing nothing.

## Only two imports of these packages exist in `src/`

`hacks/prism/newmap.py` imports `map_new.TEMPLATE` and `mapfit.mapwire`;
`map_new/__init__.py` imports `mapfit.mapwire`. Nothing else in `src/` reaches
any of the six. The external contract is therefore those two names plus the six
`pyproject.toml` console entry points — much smaller than the surface the
packages actually expose.
