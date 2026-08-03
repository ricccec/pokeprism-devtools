# Phase 1b findings — paying what Phase 1 could not

Plan: `refactor-phase-1b-PLAN.md`. Index entry: `refactor-STATE.md` → Phase 1b.

The same one line per finding is in the index; each links to the section below
that proves it.

- The debt re-measured on the day it was planned: **all eleven, unchanged**, and
  the executed column reproduces to the line. → *The debt, re-measured*
- **`> 50` is this phase's working number**, recorded as a reading of CLAUDE.md's
  `~50` rather than a restatement of it. → *What "~50" is read as*
- The eight uncovered functions execute **exactly one line — their `def`**; Phase
  1 counted the same fact as 0. → *Two spellings of the same zero*
- **A characterization test goes where the fixture already is** — four of the five
  packages own a test that builds one. → *One new file, not five*
- `map_inspect`: `main` went **1 → 52 executed lines**, and the goldens caught
  **7 of 7** seeded mutations. → *Step 1 · map_inspect*
- **The goldens carry invisible trailing spaces** and a guard now says so before
  they all fail at once. → *What the table pads*
- **A guessed golden was wrong three ways; a recorded one was right.** `mapgroup`
  is `(H, W)`, not `(W, H)`. → *Why goldens are recorded, not written*
- **A mutation run and a suite run cannot share a working tree.** → *The baseline
  that had to be taken twice*
- **A fixture is only as good as what it can falsify.** Ten mutations survived a
  first-draft fixture across three packages, every one because the fixture's
  *shape* made correct and wrong output identical. → *What the fixtures had to
  be able to tell apart*
- **All eleven targets now have an oracle**: the eight that executed nothing now
  execute 44–101 lines each. → *Where the eleven stand now*
- Two mutations survive honestly, and neither is a gap: one is provably
  equivalent, the other reaches **unreachable code in `map_new.cli.main`**. →
  *The two that survive, and why*
- **`map_show` owed this phase nothing** — its test is insurance for the phases
  that move it, not an oracle for a shortening here. → *Step 4 · map_show*
- **R6's stated signature for a rename was wrong**, and the PLAN and the tool
  both said so. A rename always changes the digest. → *What R6 is worth on a
  rename*
- **Step 6's "five argparse trees" was four.** `map_new`'s `main` is a wizard
  and was long for a different reason. → *Steps 6–8 · the shortenings*
- A word-boundary rename **missed a real importer and hit four pieces of
  prose**. → *Step 10 · the four bare verbs*
- **The phase is done: 0 functions over 50 LOC, 0 files over 250, 0 bodies
  nested four deep** in the six CLI packages. → *Where the debt stands*

---

## The debt, re-measured

Measured 2026-08-03, the same day the PLAN measured it, by walking every
`FunctionDef` in the six packages with `ast` and tracing the ten tests that
reference them under `sys.settrace`.

**Every row reproduces.** Same eleven functions, same LOC, same executed counts —
`cmd_diff` 62, `usage.cli.main` 49, `collect` 46, and eight at zero.
`mapfit/mapwire.py` is still 357 lines and still the only file over 250 in the
six packages. Nothing was re-scoped, and the PLAN's table stands as written.

### What "~50" is read as

`CLAUDE.md` gained a tilde after the PLAN was written — "No function should be >
**~50** LOC" — which makes the rule looser but no longer computable, and the
eleven targets were produced by `if loc > 50`.

**This phase reads `~50` as `> 50`.** That is a working number chosen so the next
session measures the same thing rather than re-judging eleven cases; it is not a
restatement of the standard, which stays deliberately soft.

It changes nothing here. The targets are 132, 77, 76, 75, 69, 68, 66, 65, 65, 61
and 57: only `mapfit.cli.main` at 57 is anywhere near the line, and the same
bullet's untouched **~30 LOC** smell threshold condemns all eleven at 1.9× or
worse. The softening is not permission to drop a target, and none was dropped.

### Two spellings of the same zero

Phase 1 reported eight functions as executing **0** lines; this phase's harness
reports **1**. Both are right and neither is a change: Phase 1 counted executable
lines off the compiled code objects, which excludes the `def` line, and the `def`
line is exactly what runs at import time. The body of all eight is untouched by
the suite.

`mapwire.py` is likewise 91% here against 95% in Phase 1 — statement lines versus
code-object lines. The conclusion both support is the one the PLAN leans on: it
has the best oracle in the six packages.

## One new file, not five

The PLAN's table reads "characterization test for `<pkg>` CLI" per step, and its
"what must not break" expects the suite to gain one test per step 1–5. **Four of
the five packages already own a test file, and `test_map_inspect.py` already
builds the fixture tree the CLI needs.**

CLAUDE.md is authoritative and says to prefer editing an existing file, so the
characterization cases are added to the package's own test where one exists, and
only `map_show` — which has no test file of its own — gets a new one. The repo's
own pattern already mixes the two kinds: `test_usage.py` holds
`parse_bank_selectors` unit checks beside its golden CLI cases.

The tripwire survives the change. A regression in the new cases turns an existing
test file red, which the 32/35 count still reports.

## Step 1 · map_inspect

`tests/test_map_inspect.py` gained 13 golden cases covering every flag
`prism-maps` offers — sorts, the nullable re-partition in both directions, all
four filters, `--json`, the empty result — plus the one path that writes to
stderr, running outside a game repo.

`main` is driven through `sys.argv` and `SystemExit` rather than a passed argv
list, because that is how the console entry point calls it. It also means step 6
can give `main` a parameter without touching a single assertion.

**The oracle now exists**: `map_inspect/cli.py::main` went from 1 executed line
to 52 of its 65. `collect` is unchanged at 46 — it was already the best-covered
of the three.

**Falsified: 7 seeded mutations, 7 caught.** Reversing the sort, exiting 0 instead
of 1 on an empty result, making `--min-blocks` strict, dropping the None-at-end
re-partition, exiting 3 instead of 2 outside a repo, changing the JSON indent, and
swapping `--used` for `--unused`.

### What the table pads

`render_table` pads every cell to its column width **including the last**, so
every data row ends in spaces while the header does not. The goldens record that
faithfully, which makes them the first casualty of any "strip trailing whitespace"
an editor might apply — and all thirteen would fail at once, looking like a defect
in the code.

`test_goldens_kept_their_padding` fails first and says what happened.

### Why goldens are recorded, not written

The first draft of the case table was written by hand from reading the code. It
was wrong three ways at once: the script byte counts, the trailing padding, and
**W/H transposed** — `mapgroup NAME, H, W` takes height first, so the fixture's
`mapgroup CAPER_RIDGE, 10, 9` is a 9-wide, 10-tall map and the CLI printing `9 10`
is correct.

Every one of those would have been "fixed" in the code by anyone who trusted the
hand-written golden. The recorded table is the behaviour; the phase's job is to
keep it, not to have opinions about it.

## Step 2 · metatiles

`tests/test_metatiles.py` gained six golden cases plus a dry-run/write pair for
`--blank-unused`. `main` went 1 → 47 executed lines, `render_report` 1 → 50.
**12 seeded mutations, 12 caught.**

## Step 3 · mapfit

Nine golden cases over `plan`/`add`/`consolidate`, plus five tests for the paths
that write. `cmd_add` 1 → 44, `cmd_consolidate` 1 → 42, `main` 1 → 47.
**12 seeded mutations, 12 caught.**

Two external programs are stubbed, both at a real process boundary, so the code
under test runs unchanged — subprocess and all:

- **`utils/lzcomp`**, so compressed block-data sizes are fixed rather than
  whatever the real compressor does today.
- **`make`**, which is what reaches `cmd_add`'s two build branches. Those are
  half the function and the half worth fearing: the measurement build only works
  because the map's sections are **unpinned first**, so a map that outgrew its
  bank does not overflow on a stale pin. Without the stub that branch has no
  test, and step 7 would be rewriting it blind.

## Step 4 · map_show

The one package with no test file of its own, so it gets the phase's one new
file: `tests/test_map_show.py`, four golden cases plus two error paths.
**7 seeded mutations, 7 caught.**

**It owed this phase nothing.** None of the eleven over-long functions is in
`map_show` — `main` is 44 lines and `_print_report` 44 — so nothing here is
shortened and these goldens prove no edit in Phase 1b. They are insurance for
Phase 3, which moves this code. The PLAN ordered the test; re-deriving the debt
is what showed it is not load-bearing, and it was written anyway rather than
dropped.

`--grid` is left uncovered deliberately: drawing a map needs tileset graphics, a
palette table and decompressed block data — a fixture an order of magnitude
larger than the rest of the file, for a path that is one call into
`grid.print_grid`, whose arithmetic `test_grid.py` already covers.

## Step 5 · map_new's wizard

`tests/test_map_new_cli.py` (new — `tests/test_map_new.py` is about
`wiring/mapnew.py` and `hacks/vanilla/newmap.py`, one underscore away and
unrelated). A fake `questionary` answers the prompts and is installed into
`sys.modules` so `main`'s own `import questionary` picks it up.

`_gather_spec` went 1 → 101 executed lines, `main` 1 → 44. **15 seeded
mutations, 13 caught** — the two survivors are below.

**The order of the questions is part of the golden.** A wizard *is* its
sequence; reordering it changes what the user is asked and when, so all
eighteen prompts are asserted as a list rather than sampled.

**The fake runs each prompt's own `validate`** against the answer it is about to
return. A scripted run therefore also proves the script is answers the wizard
would have accepted — without that, a canned answer can drift into something no
human could have typed and the test still passes.

## Where the eleven stand now

Measured after step 5, same harness as the opening measurement:

| function | LOC | was | now |
|---|---|---|---|
| `map_new.wizard._gather_spec` | 132 | 0 | **101** |
| `usage.diffreport.cmd_diff` | 77 | 62 | 62 |
| `mapfit.commands.cmd_add` | 76 | 0 | **44** |
| `mapfit.commands.cmd_consolidate` | 75 | 0 | **42** |
| `metatiles.cli.main` | 69 | 0 | **47** |
| `map_new.cli.main` | 68 | 0 | **44** |
| `usage.cli.main` | 66 | 49 | 49 |
| `map_inspect.cli.main` | 65 | 0 | **52** |
| `metatiles.report.render_report` | 65 | 0 | **50** |
| `map_inspect.mapinfo.collect` | 61 | 46 | 46 |
| `mapfit.cli.main` | 57 | 0 | **47** |

Steps 6–11 may now start: **no function is shortened before something executes
it**, and none is left that nothing executes.

## What the fixtures had to be able to tell apart

Ten seeded mutations survived a first-draft fixture, across three packages, and
not one was a gap in the *assertions* — every one was a fixture whose shape made
correct and incorrect output identical. A test can execute every line of a
function and still be unable to fail.

- **metatiles**, 4 metatiles: one heatmap row, three ranked entries, one unused
  id. Changing the row width from 16, slicing top-k off by one, and dropping the
  dash from range compaction all produced byte-identical output. Twenty
  metatiles over two runs of unused ones tells all three apart.
- **mapfit**, a fresh map: `cmd_add` never unpins, because there is no pin. An
  already-pinned map is needed to reach the branch the module's own header
  comment is about.
- **mapfit**, own sections only: the measured-size path never subtracts the
  pre-wiring baseline, because that only matters for a blob appended *into* an
  existing section.
- **mapfit**, a consolidation where everything moves: cannot tell "count the
  sections that moved" from "count them all", nor "banks freed" from "banks
  touched". One section that stays put separates both.
- **mapfit**, `--blockdata-bank 0x03`: parses identically whether or not `$` is
  translated to `0x`. Only a `$03` distinguishes the two.

The rule this leaves: **choose the fixture's shape from the mutations it must be
able to fail on**, not from what looks like a representative input.

## The two that survive, and why

Neither is a hole, and both are recorded rather than papered over.

**Sorting the group list is provably a no-op.** `map_new.wizard` sorts
`_existing_groups(root).items()` before offering them. Group numbers come from a
counter in `hacks/prism/maps.py` that only ever increments, so the dict is built
in ascending order and `sorted` cannot change it. An equivalent mutation, like
the one survivor `tests/test_usage.py` reported in Phase 1.

**`map_new.cli.main`'s `spec.validate` block is unreachable from the wizard.**
Every field it checks was already validated at its prompt — label, const, group,
both dimensions — and the two files it requires on disk were written by
`write_template` and `place_blk` four lines above it. So `problems` is empty
whenever the wizard succeeded, and deleting the branch changes nothing.

It is **not** removed here. This phase shortens functions; dropping a defensive
branch is a behaviour change and belongs to whoever can also say what calls
`main` besides the wizard. Recorded so the next reader does not have to
re-derive it — and noted for step 6, which restructures this `main`.

## Steps 6–8 · the shortenings

Cheap, exactly as the PLAN predicted, and each one checked with
`scripts/surface-snapshot.py` against a snapshot taken immediately before it.
In every case the digests that changed were the functions the commit named,
plus the extracted names arriving, and nothing else.

**Step 6's premise was slightly wrong, and it cost nothing.** The PLAN says
"split the argparse tree out of five `main`s". Only **four** of the five have an
argparse tree: `map_new`'s `main` is a wizard driver with no parser at all, and
was 68 lines because it ran eight phases of a script in one body. It was split
by phase instead. The other four each gained a `_build_parser`.

`usage` also lost a seven-armed `if` chain to a `_COMMANDS` table. `diff` stays
out of that table on purpose — it reads two `.map` files and loads them itself,
so it must run before the single-file load the other seven share.

Step 7 split the five long command bodies; step 8 split `_gather_spec`, the
132-line wizard, into seven functions named for what they ask about. Its
recorded prompt list is unchanged, which is what proves the eighteen questions
and their wording survived.

## Step 9 · mapwire.py, the one move

357 lines holding three responsibilities → `mapwire.py` (189), `asmblocks.py`
(115), `linkscript.py` (81).

**Checked the Phase 1 way, and it passed exactly**: CONTENT byte-identical,
SURFACE gaining only the two submodule bindings Python creates on import, which
R2 permits because no code controls them.

Keeping it a pure move cost one thing worth recording: `"contents/romx.link"`
appears twice in `linkscript.py` and was **left unnamed**. Naming it is an edit,
and an edit cannot be proved the way a move can. A move commit that also tidies
is neither provable as a move nor reviewable as an edit.

## Step 10 · the four bare verbs

`collect` → `collect_map_info`, `collect` → `group_maps_by_tileset`, `analyze` →
`analyze_tileset`, `pack` → `pack_into_banks`.

**Two `collect`s in one codebase returned different things** — a list of map
records, and a dict of maps keyed by tileset. That is the cost the rule is
about, and it is only visible once both names are read together.

**A word-boundary rename is not a rename.** Doing all four mechanically got two
things wrong:

- It **missed `mapfit/commands.py`**, which imports `pack`. The file list came
  from grepping the obvious places, and the obvious places were not all of them.
  Two test files went red on import, which is the only reason it was caught.
- It **rewrote four pieces of prose**, turning "tight re-pack" into "tight
  re-pack_into_banks" in a docstring, a comment, a `print` label and a module
  header.

Phase 1 hit the same trap from the other side: a grep for `mapfit.<name>`
matched a `print` label and reported a call that did not exist. **The word is
not the call, in either direction.**

### What R6 is worth on a rename

The PLAN and this phase's edit to `scripts/surface-snapshot.py` both claimed a
correct rename shows "one name leaving and one arriving with an **unchanged**
digest". **Measured false, and it cannot be true**: the digest is of the
function's source and the source contains the `def` line, so a rename always
changes it — and so does every caller that names the function.

Both files are corrected. What the check is actually worth on a rename is the
rest of the list: `pack` → `pack_into_banks` moved exactly three digests, the
function and its two callers. A fourth would have meant the rename reached
something it should not have.

## Step 11 · the threshold and the two deep loops

**95.0 was written four times**, not twice: two argparse defaults and two
`getattr` fallbacks behind them. The fallbacks are unreachable, which is how the
duplication survived — changing one copy could not fail a test, which is exactly
how the PLAN found it while falsifying `test_usage.py`.

All four now read `DEFAULT_MAX_BANK_USAGE`. The `getattr` stays: a caller
building its own Namespace may still omit the flag. What it no longer does is
decide the number a second time.

`cmd_banks` and `cmd_bank` were the two bodies nested four deep, and in both the
inner two levels were a separate job with no name — rendering the occupancy bar,
and finding a bank by a number that ROM, WRAM and SRAM can all claim. The bar's
own constants (16 cells, red at 95%, yellow at 80%) were named on the way past.

## Where the debt stands

Re-measured after step 11, with the same script that opened the phase:

| | at the start | now |
|---|---|---|
| functions over 50 LOC | 11 | **0** |
| files over 250 LOC | 1 (`mapwire.py`, 357) | **0** |
| bare-verb names | 4 | **0** |
| bodies nested four deep | 2 | **0** |
| thresholds spelled twice | 1 | **0** |

**The phase's debt is paid in full.** The six CLI packages carry nothing further
that CLAUDE.md rejects.

Two things are recorded rather than fixed, both above: the unreachable
`spec.validate` block in `map_new.cli.main`, and the unnamed `contents/romx.link`
literal that step 9 could not name without spoiling its proof.

## The baseline that had to be taken twice

The first full-suite run was started in the background, and step 1's mutation runs
began while it was still going — editing `src/` and clearing `__pycache__` under a
suite that was reading both. It happened to report the expected 32/35 with exactly
the three known reds, and was re-run rather than believed.

Same family as Phase 1's stale `.pyc`: **the suite's answer is only about the tree
it actually read.** A background suite makes the working tree read-only until it
exits.
