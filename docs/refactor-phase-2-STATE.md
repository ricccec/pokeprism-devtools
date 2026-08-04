# Phase 2 — the contract package · findings

**Plan:** `refactor-phase-2-PLAN.md` (rewritten 2026-08-04 from these
measurements) · **Index:** `refactor-STATE.md` → Phase 2

The one line this phase carries into the index, and where it is proved:

> **`panels.py` was half the cycle and half of it is not contract** —
> `studio/actions.py` is imported by 20 adapter modules to `panels`'s 11, and 22
> of `panels.py`'s 44 names are the IDE's table builders, which no adapter has
> ever touched. → "The carve, measured".

## Where the phase started · 2026-08-04

Baseline **34/37**, the three known reds unchanged (`test_eventheader`,
`test_maplint` — live-prism drift; `test_lib` — needs cwd inside a game repo).
Run with `__pycache__` cleared and `PYTHONDONTWRITEBYTECODE=1`.

## What step 1 re-verified, and what it found instead

The PLAN rested on three claims. All three were measured; the file sizes held
and the *shape* did not.

- **`studio/panels.py` is 678 LOC, `hacks/seam.py` 266, `studio/app.py` 523** —
  all three exactly as the PLAN said.
- **The six protocols are still six** — `Reads`, `Measures`, `Sketches`, `Plays`,
  `Lints`, `Writes`, plus `Hack`, `Refused`, `PlayError`.
- **`panels.py` holds 20 classes** — as claimed. But class count was the wrong
  measure, and it hid the split below.
- **"its only import is `shared.coords`" is true and was the wrong file to
  measure.** The question the PLAN meant to ask is what the *contract* imports,
  and that is `shared.coords.Tile`, `shared.swatches.Rgb`/`Swatch` (via the
  duplicate below) and `shared.edits.Edit` — three `shared/` modules, not one.
  **So B depends on A, narrowly and deliberately**: each of the four names is a
  Gen-2 fact that already lives in A, A cannot import B without inverting the
  arrow, and every adapter installs A anyway.

## The carve, measured

**`panels.py` splits almost exactly in half, and the half that stays is the half
the file is named for.** Every name in it was grepped for a constructor or a
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
  contract must not carry it. The PLAN's "the twenty classes in `panels.py`" would
  have moved the IDE's own vocabulary into the package both sides import.
- **`ADD` and `add_ref` travel with `Ref` even though only `studio/` names them** —
  `Ref.adds` and `Ref.deletable` are *defined in terms of* `ADD`. Splitting them
  would leave the contract importing the IDE for a string constant, which is the
  cycle in miniature.
- **`UNDECLARED` stays.** Adapters set the `undeclared: bool` flag; the ⚠ glyph
  that renders it is read by `_num` and nothing else.

## `studio/actions.py` is the larger half of the cycle, and was not in the spec

**Measured over `hacks/`: 20 modules import `studio.actions`, 11 import
`studio.panels`, 28 between them.** The PLAN named only `panels`, so a phase run
to the PLAN as written would have moved 11 modules' worth of the cycle and
declared the keystone laid.

`actions.py` is contract by every test the PLAN sets: it imports `shared.edits`
and `.panels` and nothing else, it parses no source, opens no file and draws
nothing, and its own module docstring already states the contract rule —
*"adapters import this module; this module imports no adapter."* It holds
`Action`, `Field`, `Result`, `ActionError` and the 22 choice-kind constants.

**And it is what makes the runtime check askable.** `test_vanilla.py`'s
`test_the_base_imports_no_adapter` says in its own docstring that the question
can only be asked statically, because importing `studio.actions` runs
`studio/__init__` → `session` → `maplint`, which is written against prism. That
chain is a property of `actions.py` *living in `studio/`*. Moving it dissolves it,
which is why the phase's oracle can now assert the runtime version.

## What the phase does not fix, and hands on

- **`studio/mapadd.py` and `studio/resize.py` are not the IDE and are not the
  contract.** They are neutral `Action` subclasses over `wiring/`, imported by four
  adapter modules (`prism/write`, `prism/offers`, `vanilla/write`, `vanilla/newmap`)
  — three of the four through a function-local import, which is how the dependency
  stayed invisible to a top-of-file grep. They fail B's bar (they read the
  filesystem and call `wiring.mapnew`/`wiring.mapresize`), so they cannot come
  here; they are a **shared adapter library**, and where that lands is Phase 3's.
  **They are the whole of the `hacks → studio` edge this phase leaves standing**,
  and `tests/test_contract.py` names them so the day they move is not silent.
- **`Rgb` and `Swatch` are defined twice** — `studio/panels.py` and
  `shared/swatches.py`, the same alias in both, with `hacks/prism/swatches.py`
  importing one and `hacks/vanilla,polished/swatches.py` the other. Not fixed
  inside a move (R5); its own commit.
- **`studio/panels.py`'s residual is ~320 LOC** across two responsibilities —
  what a table is, and how each of the twelve tabs is built. Over CLAUDE.md's 250
  smell, inside its "one or two responsibilities" rule. Looked at, and left.
- **`studio/app.py` (523) and `studio/session.py` (596) are untouched.** Extracting
  the entities is not the same job as splitting those files; they are Phase 4's
  god objects and this phase does not open them.
