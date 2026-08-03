# Phase 1 — calibration: the six CLI packages

**The deliverable is two things, and the rules are the larger one.** Six packages
get split; four later phases inherit whatever "done to the standard" turns out to
mean. Nothing depends on Phase 1, which is why the answer is settled here.

Findings and their evidence: `refactor-phase-1-STATE.md`.

## What step 1 changed before any code moved

Three of this phase's premises were checked and two were wrong. Details in the
STATE; the consequences for the plan:

- **"All six are test-covered" is wrong, but not the way the filenames suggest.**
  `map_show` *is* covered — by `test_grid.py` and `test_mapsource.py`, neither
  named for it. `usage` is covered by nothing. Filenames measured the wrong thing.
- **Coverage is not a yes/no.** Measured by line, the six `__init__.py` files run
  **0–54%** of themselves; the two files already split out of `mapfit` run
  **93% and 95%**. Coverage tracks the split that already happened. So "has a
  test" was never the right question — see "The oracle" below.
- **The banner hypothesis holds for five of seven files, not all seven.**
  `usage/__init__.py`'s two `# ---` lines carry no title and do not mark a
  parse/analyse/render seam, because `usage` has no analysis of its own to seam
  off — `shared/mapfile.py` does that work.

## The rules — the actual deliverable

CLAUDE.md is the standard and is not restated here. These four resolve questions
CLAUDE.md leaves open for a package split.

### R1 · `__init__.py` re-exports, and defines nothing

A package's `__init__.py` holds its module docstring, imports from its own
submodules, and `__all__`. No `def`, no `class`, no constant, no logic. Under
CLAUDE.md a folder is an address — so a package's `__init__` answers *"what is
reachable here?"* and nothing else.

**A thin façade is not allowed.** The rejected alternative was letting `__init__`
keep small glue (a `main` that wires submodules together). It fails because glue
grows: every one of the six files under this phase's knife started as a CLI with
"a little" logic beside it.

**`main` is re-exported, not defined.** All six console entry points in
`pyproject.toml` are `pokeprism_devtools.<pkg>:main`, so `main` must remain a
package attribute. It is defined in the package's `cli.py`.

### R2 · Content must not change; the surface may only shrink

Today's `__init__` files re-export their own imports by accident: `map_show`
exposes `Path`, `argparse`, `os`, `re`, `sys`, `shutil`, `dataclass`, `MapFile`,
`MapSpec` and nine foreign modules, none of which is `map_show`'s public surface.
A re-exports-only `__init__` drops all of it.

So the check is over two different things, and `scripts/surface-snapshot.py`
prints them as two sections:

- **CONTENT** — every function, class and constant the package defines,
  *anywhere in it*, as a digest, with no mention of which file holds it. Moving
  a function between files does not touch this section; editing one does.
  **CONTENT must not change at all.**
- **SURFACE** — what `import <package>` exposes. **It may only lose names.** The
  one permitted addition is a submodule binding: importing `pkg.cli` makes
  Python bind `cli` on `pkg`, which no `__init__` controls.

*Corrected after `map_inspect`.* The first version of this rule asked that every
surviving name keep a byte-identical body and that every dropped name be
"imported, or a symbol the package does not define". It failed immediately: a
split moves package-*private* names (`_fmt_row`, `_SORT_KEYS`) out of `__init__`
into the submodule that owns them, and they are neither. Comparing only what
`__init__` exposes cannot tell that move from a deletion. Snapshotting the whole
package can, and it is a stronger claim besides — CONTENT covers code that was
never exposed at all.

R2's cost fell entirely on private names: `tests/` reached four of them across
three packages, each of which now imports from the submodule that owns it.
`mapfit.compressed_blk_size` — flagged when this plan was written as a name
`mapfit` re-exports without defining — needed no edit at all: the only mention
of it in `tests/` is inside a `print` label, and the test imports the real one
from `hacks/prism/blobsizes.py` already. A grep for `mapfit\.<name>` matched a
string; the leaked re-export simply disappeared with nothing depending on it.

### R3 · A name says what a file holds, never which layer it is

"Split parse / analyse / render / CLI" is a hypothesis about *seams*, not a set
of filenames. CLAUDE.md forbids an architectural noun where a domain one exists,
so `analysis.py` and `render.py` are not acceptable outputs of this phase:
`mapuse.py`, `tileset.py`, `report.py` are. `cli.py` is the one architectural
name kept deliberately — for a tool whose entire product is a command, the
command line *is* the domain, and `main` plus its argparse tree has no better
name.

### R4 · Imports may be rewritten in tests; assertions may not

Moving code changes where a test imports from. That is not a behaviour change.
Changing what a test asserts, during a move, destroys the only evidence that the
move was neutral. **`git diff` on `tests/` must touch import lines only** — this
is checkable per commit, and it is how each split's claim stays worth something.

The one exception is `tests/test_usage.py`, which does not exist yet and is
written before anything moves (below).

### R5 · A split is a move, and nothing else rides along

CONTENT not changing (R2) means a package's split commit cannot also shorten a
function, name a constant, or drop a dead branch — every one of those edits a
body. That is the same reasoning as the plan's "a move must never be the thing
that fixes a bug", one step weaker: not just defects, *any* edit.

So where a moved function still breaks CLAUDE.md after landing in its new file —
`main` and `collect` both clear 50 LOC in `map_inspect` — the fix is a **second
commit against the new layout**, whose snapshot diff shows exactly which bodies
changed and nothing else. Two small commits, each provable, instead of one that
proves nothing. **Phase 1's commits below are the moves.** What each package
still owes CLAUDE.md afterwards is recorded per package in the STATE, so the
follow-up is a list someone can work, not a memory.

## The oracle

Line coverage of 28–54% means the existing tests cannot certify these moves — the
uncovered majority is exactly the render and CLI halves a split relocates
wholesale. Writing characterization tests for all of it would cost more than the
phase and would still only sample the behaviour.

**A move is proved textually instead.** `scripts/surface-snapshot.py` (new, this
phase) imports a package and prints its CONTENT and SURFACE sections (R2). Run it
before a split and after; the diff must satisfy R2. This is a *stronger* claim
than a test for a pure move — it shows the bodies did not change at all, rather
than that a sampled subset still agrees — and it is what Phases 2–5 inherit. It
proves nothing about a *rewrite*, which is the point: anything that fails it was
not a move.

**Run it against a cleared `__pycache__`.** A same-length edit reverted within the
same second leaves mtime and size both matching, so Python keeps running the old
bytecode while `inspect.getsource` reads the new file — which happened here, and
made a reverted mutation look like a real failure. `PYTHONDONTWRITEBYTECODE=1`
also does it.

**`usage/` gets a real test first.** It is the one package at 0%, it is product
A's and therefore ships, and its eight `cmd_*` functions print rather than
return, so nothing about them is currently pinned. `MapFile` is constructible in
memory (`tests/test_mapfit.py` already builds one from `Bank`/`Section`), so a
golden-output characterization test over a synthetic map is cheap.
**`tests/test_usage.py` lands in its own commit, before `usage/` is touched.**

Descoping `usage` was the alternative. Rejected: this repo is product A's only
editable copy, and leaving A's one untested CLI untested is a worse outcome than
the test costs.

## Order of work

`map_inspect` goes first *because* it is the smallest and best-covered — the
rules above get their first contact with reality where a mistake is cheapest.
Anything they get wrong is corrected in this file before the second package.

| # | commit | what proves it | done |
|---|---|---|---|
| 1 | `scripts/surface-snapshot.py` | snapshots all six packages; no product code touched | ✓ |
| 2 | `tests/test_usage.py` | new test passes against unmodified `usage/` | ✓ |
| 3 | split `map_inspect` (287) | snapshot diff satisfies R2; suite at baseline | ✓ |
| 4 | **re-read the rules against step 3** | this file is corrected, or is confirmed | ✓ R2 rewritten, R5 added |
| 5 | split `map_show` (340) | as 3 | ✓ |
| 6 | split `map_new` (354) | as 3 | ✓ |
| 7 | split `usage` (445) | as 3, plus `test_usage.py` unchanged and green | ✓ unchanged |
| 8 | split `metatiles` (670) | as 3 | ✓ |
| 9 | split `mapfit` (602) | as 3 | ✓ |

One package per commit. `mapfit` is last: it is the only one whose split also has
to place logic beside two files that already exist (`mapwire.py`, `packing.py`).

Step 4 earned its place. The rules were wrong twice and the tool three times, all
of it found on the smallest package — see the STATE, "What the first split
corrected" and "Two ways the tool lied".

## The shape

Written as intent, kept as the record. **Measured sizes and the three places the
result deviated are in the STATE, "The six splits".** Where a cut was open when
this was written, it says so and says how it closed.

**`map_inspect` (287)** — **done**: `mapinfo.py` 135, `table.py` 76, `cli.py` 80,
`__init__.py` 11. The sort keys went to `mapinfo.py`, not `table.py` where the
banner filed them: `_SORT_KEYS` and `_NULLABLE_SORTS` say how to *order*
`MapInfo` records, which is a fact about the record, not about drawing it. First
evidence that the banners are a hypothesis and not a cut list.

**`map_show` (340)** — two halves that barely speak: `mapspec.py`-side report
(`build_spec`, `BlobRow`, `gather_blobs`, `_print_report`) and the terminal
drawing (`fit_zoom`, `print_grid`, `_cell`, `_paint`, `_ruler`, `ZOOMS`). Files:
`blobreport.py`, `grid.py`, `cli.py`.

**`map_new` (354)** — `template.py` (`TEMPLATE`, `write_template`, `place_blk`),
`repoquery.py` (`_consts`, `_existing_groups`, `_existing_labels_consts`),
`wizard.py` (`_ask`, `_gather_spec`, `_Aborted`), `cli.py`. `TEMPLATE` must stay
importable — `hacks/prism/newmap.py` reads it.

**`usage` (445)** — no analysis of its own, so the seam is not the standard four:
`bankselector.py` (the pure token parsing), `maploader.py` (`_load`,
`_fill_cartridge_banks` — the boundary), the `cmd_*` reports, `ansi.py`, `cli.py`.
Whether the eight commands wanted two files was **open**; they did — seven read
one link map, `diff` reads two and loads them itself, so `reports.py` and
`diffreport.py` split on a real difference rather than on a size target.

**`metatiles` (670)** — `mapuse.py` (`MapUse` and everything that finds them in
the tree), `tileset.py` (`TilesetAnalysis`, `BlobSize`, the pure per-tileset
analysis), `report.py` (heatmap buckets, `render_report`, `render_summary`,
`_as_dict`), `cli.py` (`main`, `_do_blank`, `_render_sheet`).

**`mapfit` (602, plus `mapwire.py` 357 and `packing.py` 196)** — `sizes.py`,
`freespace.py`, `blobs.py`, `commands.py`, `cli.py`, beside the two existing
files. Two things were **open**, and both closed against the file:

- `commands.py` did *not* stay under 250 — it came out at 274 with the
  spec-loading helpers in it, so `specload.py` took `_load_spec`,
  `_load_baseline`, `_apply_placement_flags` and `_check_dedicated_sections`.
- The spec-aware placement planning went to `freespace.py`, beside the free space
  it spends. **Not `mapfit/placement.py`** — Phase −1 recorded `Placement` in
  `mapfit/packing.py` colliding with `wiring/placement.py` in both name and job,
  and a phase premised on behaviour-neutral moves must not make that census entry
  worse.

`mapwire.py` and `packing.py` are not targets; they are at 93–95% coverage and
already hold one responsibility each.

## What must not break

- The six `pyproject.toml` console entry points still resolve to a `main`.
- `hacks/prism/newmap.py` imports `map_new.TEMPLATE` and `mapfit.mapwire`; they
  are the only imports of these six packages from anywhere else in `src/`.
- The suite stays at its baseline. `test_eventheader`, `test_maplint` (live-prism
  drift) and `test_lib` (needs cwd inside a game repo) are red for reasons that
  predate this branch. **A fourth red means the move was not neutral.**
