# Phase 2 — the contract package · findings

**Plan:** `refactor-phase-2-PLAN.md` (rewritten 2026-08-04 from these
measurements) · **Index:** `refactor-STATE.md` → Phase 2

The one line this phase carries into the index, and where it is proved:

> **`panels.py` was half the cycle and half of it is not contract** —
> `studio/actions.py` is imported by 20 adapter modules to `panels`'s 11, and 22
> of `panels.py`'s 44 names are the IDE's table builders, which no adapter has
> ever touched. → "The carve, measured".

**Status: done 2026-08-04.** Eight commits, `c119ca4`..`0589c64`. Suite
**35/38** — the three known reds, plus `tests/test_contract.py` new and green.

## Where the phase started

Baseline **34/37**, the three known reds unchanged (`test_eventheader`,
`test_maplint` — live-prism drift; `test_lib` — needs cwd inside a game repo).
Run with `__pycache__` cleared and `PYTHONDONTWRITEBYTECODE=1` throughout.

## What step 1 re-verified, and what it found instead

The PLAN rested on three claims. All three were measured; the file sizes held
and the *shape* did not.

- **`studio/panels.py` is 678 LOC, `hacks/seam.py` 266, `studio/app.py` 523** —
  all three exactly as the PLAN said, and the six protocols are still six.
- **`panels.py` holds 20 classes** — as claimed. But class count was the wrong
  measure, and it hid the split below.
- **"its only import is `shared.coords`" is true and was the wrong file to
  measure.** The question the PLAN meant to ask is what the *contract* imports.
  Measured on the finished package: `shared.coords.Tile`, `shared.swatches.Rgb`
  /`Swatch`, `shared.edits.Edit`, and nothing else outside stdlib.
  **So B depends on A, narrowly and deliberately**: each name is a Gen-2 fact
  that already lives in A, A cannot import B without inverting the arrow, and
  every adapter installs A anyway.

## The carve, measured

**`panels.py` split almost exactly in half, and the half that stayed is the half
the file was named for.** Every name in it was grepped for a constructor or a
raise outside `studio/`:

| crosses the seam (22) | never leaves `studio/` (22) |
|---|---|
| `Unreadable`, `Ref`, `ADD`, `add_ref` | `Row`, `Table`, `Tab`, `_NONE` |
| `Npc`, `Trainer`, `Prop`, `Signpost`, `Warp`, `Trigger`, `MapTables` | `npcs`, `trainers`, `objects`, `signposts`, `warps`, `triggers`, `connections`, `attributes`, `roof`, `wild` |
| `Link`, `Attributes`, `Roof`, `WildMon` | `_yx`, `_num`, `_tile` |
| `Rgb`, `Swatch`, `Blocks`, `Sketch` | `NUMERIC`, `prompt_column`, `UNDECLARED` |
| `TextRef`, `Measured`, `TextPreview` | `WILD_IS_READ_ONLY`, `ROOF_IS_READ_ONLY` |

- **No adapter has ever constructed a `Row` or a `Tab`.** The twelve table
  builders choose column headers, dashes and glyphs; that is rendering, and the
  contract must not carry it. The PLAN's "the twenty classes in `panels.py`"
  would have moved the IDE's own vocabulary into the package both sides import.
- **`ADD` and `add_ref` travel with `Ref` even though only `studio/` names them** —
  `Ref.adds` and `Ref.deletable` are *defined in terms of* `ADD`. Splitting them
  would leave the contract importing the IDE for a string constant, which is the
  cycle in miniature.
- **`UNDECLARED` stays.** Adapters set the `undeclared: bool` flag; the ⚠ glyph
  that renders it is read by `_num` and nothing else.

## `studio/actions.py` was the larger half of the cycle, and was not in the spec

**Measured over `hacks/`: 20 modules imported `studio.actions`, 11 imported
`studio.panels`, 28 between them.** The PLAN named only `panels`, so a phase run
to the PLAN as written would have moved 11 modules' worth of the cycle and
declared the keystone laid.

`actions.py` was contract by every test the PLAN sets: it imported `shared.edits`
and `.panels` and nothing else, parsed no source, opened no file, drew nothing,
and its own module docstring already stated the contract rule — *"adapters import
this module; this module imports no adapter."*

**And it is what made the runtime check askable.** `test_vanilla.py`'s
`test_the_base_imports_no_adapter` said in its own docstring that the question
could only be asked statically, because importing `studio.actions` ran
`studio/__init__` → `session` → `maplint`, which is written against prism. That
chain was a property of `actions.py` *living in `studio/`*. Moving it dissolved
it, which is why the phase's oracle now asserts the runtime version.

## `Diagnostic` had to move too, and that was forced rather than chosen

`Lints.lint()` answers `list[Diagnostic]`, and `Diagnostic` lived in
`maplint/diagnostics.py` — so **the contract could not describe its own linting
question without importing a CLI**, and `hacks/vanilla/lint/rules.py`, which
builds four findings of its own, had to reach into prism's linter to name them.
Phase −1 had already called this file contract vocabulary; Phase 2 is the phase
that could act on it.

`Diagnostic` and `Severity` moved; the suppression half did not. Reading
`; maplint: ignore[...]` out of the source a finding points at is one linter's
mechanism, not vocabulary two sides agree on, so the remainder is
`maplint/suppressions.py` — named for what it does now that it does only that.

## What proved each step

**R7 — across packages, CONTENT is a union.** `scripts/surface-snapshot.py`
snapshots one package, and a move out of `studio` into `contract` necessarily
shrinks one list and grows the other. The check is the **concatenation of every
affected package's CONTENT, sorted**; that set must not change. It held at every
step: 146 → 146, 247 → 247, 336 → 336. A name that vanished from one side and
did not arrive on the other would be a deletion, and shows up nowhere else.

**The move and the rename are separate commits.** The vocabulary landed under a
re-export shim first — no importer changed, the suite was untouched — and the
shim came down in the next commit, which changed no body. A single commit doing
both is reviewable as neither (Phase 1b's step 9, learned again).

**Where an edit was intended, R6 confinement.** Every step's CONTENT diff was
read name by name, and every changed digest was a function that named a moved
type in a signature or a docstring: 9 at step 2, 2 at step 3, 5 at step 4, 1 at
step 5, 3 at step 6. Nothing else moved.

**The line-level proof, for the files the snapshot cannot reach.**
`surface-snapshot.py` walks a package's top-level modules only, so nothing under
`hacks/prism/`, `hacks/vanilla/`, `hacks/polished/` or `studio/screens/` is in
any CONTENT list. Those were proved instead by normalising the intended rename
out of `git diff` and asserting the leftovers were empty: at step 2, 167 removed
lines and 168 added, and the single line not explained by the token swap was
`vanilla/write.py`'s combined import splitting in two.

## What the phase found the hard way

- **A word-boundary rename is still not a rename, and the snapshot cannot tell
  you.** Renaming `panels` to `tables` hit `reader.py`'s local variable `tables`,
  which held the `MapTables` it had just read — so every tab construction became
  an attribute lookup on a dataclass. CONTENT reported `read_map`'s digest as
  changed, which was expected and correct, and said nothing about it being
  *wrong*. The suite caught it. Phase 1b hit this trap from the other side; this
  is the third phase in a row to pay for it.
- **A top-level `from ..studio import x` inside `contract/` no longer runs.**
  It is a circular import now — `studio` imports the contract and `hacks/mount`
  imports it back — so a seeded mutation of that shape kills the test file on its
  own import line rather than reporting a failure. Red either way, and the
  strongest form of the check: the cycle is unbuildable, not merely disapproved.
- **A `TYPE_CHECKING`-only import passes the runtime check and fails the static
  one.** Measured, on a real seeded mutation, and it is the whole argument for
  `tests/test_contract.py` carrying both: an import that costs nothing at import
  time is invisible to anything that reads `sys.modules`.
- **CONTENT cannot see a duplicate alias appear or leave.** `Rgb`/`Swatch` were
  spelled twice — `panels.py` and `shared/swatches.py`, identical aliases either
  side of the seam — and collapsing them to one re-export moved no digest at all,
  because a re-exported alias describes the same as a redeclared one.

## The result

| | before | after |
|---|---|---|
| adapter modules importing the IDE | 28 | 4, through 2 modules |
| `studio/` | 5504 LOC | 4865 LOC |
| `contract/` | — | 15 files, 1122 LOC, largest 208 |
| suite | 34/37 | 35/38 |

Every `contract/` file is under 250 LOC and all but one under 150; no function in
it clears 50. `contract/action.py` at 208 is the one over 150 — the base class
plus the three records a form is built from, which is two responsibilities and
inside CLAUDE.md's rule. Looked at, and left.

## What the phase does not fix, and hands on

- **`studio/mapadd.py` and `studio/resize.py` are not the IDE and are not the
  contract.** Neutral `Action` subclasses over `wiring/`, reached from four
  adapter methods (`prism/write`, `prism/offers`, `vanilla/write`,
  `vanilla/newmap`) — three of the four through a *function-local* import, which
  is how the dependency stayed invisible to a top-of-file grep. They fail B's bar
  because they read the filesystem and call `wiring.mapnew`/`wiring.mapresize`.
  They are a **shared adapter library**, and where that lands is Phase 3's.
  **`tests/test_contract.py` asserts the survivor list in both directions**, so a
  shorter one is somebody's decision rather than a silent pass.
- **`studio/tables.py` is 316 LOC** across two responsibilities — what a table
  is, and how each of the twelve tabs is built. Over CLAUDE.md's 250 smell,
  inside its "one or two responsibilities" rule. Looked at, and left.
- **`studio/app.py` (523), `studio/session.py` (597) and `studio/screens/forms.py`
  (496) are untouched.** Extracting the entities is not the same job as splitting
  those files; they are Phase 4's god objects and this phase did not open them.
- **Packaging is Phase 3's.** `contract/` is now a folder no other product reaches
  into, which is what makes B *possible*; carving it into its own distribution is
  the re-carve Phase 0 deferred.
- **The finished journey logs were left alone on purpose** — `adapter-plan.md`,
  `family-write-plan.md` and the earlier phase STATEs still say `hacks/seam.py`
  and `studio/panels.py`. They record what was true when they were written, and
  rewriting them would destroy the only account of why the seam ended up inside
  `hacks/`. `docs/STATE.md` and `docs/refactor-plan.md` are live and were
  corrected in place.
