# Phase 2 — the contract package · plan

The keystone phase's own plan. `refactor-plan.md` carries the sketch and the running
order; this file carries what the package *is*, which is the part an implementer
needs and the plan has no room for. Findings go to `refactor-phase-2-STATE.md`, one
line each also in `refactor-STATE.md`.

**Rewritten 2026-08-04 from measurement**, per this plan's own step 1. Three of the
claims below replace claims that were wrong; they are marked, and the wrong versions
are gone rather than annotated. What changed most: **`panels.py` is not the whole
job and is not all contract.** See "What step 1 changed" at the end.

## What this package actually is

**One sentence:** it is the *noun list and the question list* that an IDE and an
adapter must agree on before either can be written — and nothing else.

**What is inside.** Three kinds of thing:

1. **The entities a Gen-2 map is made of** — `Npc`, `Trainer`, `Prop`, `Signpost`,
   `Warp`, `Trigger`, `MapTables`, `Link`, `WildMon`, `Roof`, `Attributes`,
   `Blocks`, `Sketch`, `TextRef`, `Measured`, `TextPreview`, `Ref`, `Unreadable`.
   Today: **22 of the 44 names in `studio/panels.py`.** The other 22 are the
   twelve table builders and what they build, and they are the IDE's.
2. **`Hack` and its six capability protocols** — `Reads`, `Writes`, `Lints`,
   `Plays`, `Measures`, `Sketches`, plus the seam's two words `Refused` and
   `PlayError`. Today: `hacks/seam.py`, unchanged at six protocols.
3. **`Action` and the field vocabulary** — `Action`, `Field`, `Result`,
   `ActionError` and the 22 choice-kind constants. Today: `studio/actions.py`.
   **Not in the original spec, and the reason the phase would have failed without
   it:** 20 adapter modules import it, against 11 for `panels` — 28 between them.
   Moving `panels` alone leaves two thirds of the cycle standing.

**What is *not* inside:** any parsing, any file I/O, any ROM knowledge, any
widgets. It reads no bytes and draws no pixels.

**Its one responsibility:** to be the thing both sides depend on so that neither
depends on the other. It exists to be *pointed at*, not executed.

**Why you need it.** Without it the vocabulary lives in the IDE, so every adapter
imports the IDE to describe a warp — which is exactly today's cycle, and exactly
why the seam does not hold. With it, the dependency arrows go
`adapter → contract ← IDE`, and neither end can reach the other.

**How a hack developer uses it.** Install it, read `hack.py` to see the six
protocols, implement the ones your tree can answer, and return the entities above.
Capabilities you do not implement degrade to *absence* in the IDE — no lint panel,
no boot key — never a crash and never an `if <hack name>`. That is the whole
contract, and it is meant to be readable in one sitting.

**Naming — decided, not open.** `contract/`. By CLAUDE.md's folder rule an
architecture-adjacent name qualifies, and this one answers the question a folder
is supposed to answer: *"where do I look to find what I owe?"* `adapter/` names
one of the two sides and would read as *the* adapter; `api/` says nothing.

**B depends on A, narrowly and on purpose.** `contract` imports four names from
three `shared/` modules — `coords.Tile`, `swatches.Rgb`/`Swatch`, `edits.Edit` —
and nothing else outside stdlib. Each is a Gen-2 fact that already lives in A, and
A cannot import B without inverting the arrow. Every adapter installs A anyway to
read `.asm`. The rule the tests enforce is not "no dependencies" but **`contract`
imports stdlib and `shared` only**.

## The rules

R1–R5 from `refactor-phase-1-PLAN.md` and R6 from `refactor-phase-1b-PLAN.md`
carry over unchanged. One addition, forced by this being the first phase to move
code *between* packages:

### R7 · Across packages, CONTENT is a union

`scripts/surface-snapshot.py` snapshots one package. A move out of `studio` into
`contract` necessarily shrinks one CONTENT list and grows the other, so R2's
"CONTENT must not change at all" is checked against the **concatenation of both
packages' CONTENT, sorted**. That set is what must not change. A name that
vanished from one side and did not arrive on the other is a deletion; a digest
that changed is an edit; both show up in the union diff and nowhere else.

The tool's `is_defined_here` credits a class to the module its `__module__` names,
and its digest is of dedented source — so a class whose text is unchanged carries
the same digest into its new file, which is what makes the union check work at all.

### The move/rename split, which is a step and not a rule

Phase 1b: *a commit that both moves and tidies is neither provable as a move nor
reviewable as an edit.* Here the same trap wears a new hat — moving `Npc` out of
`panels.py` and repointing 25 importers at it in one commit produces a diff in
which the move and the rename cannot be told apart. So the vocabulary lands in
**two** commits: the code moves under a re-export shim first (no importer changes
at all, suite untouched), then the shim comes down and the token `panels.`
becomes `contract.` everywhere (no body changes at all).

## Order of work

| # | commit | what proves it |
|---|---|---|
| 1 | the map vocabulary into `contract/`, `panels.py` re-exports it | R7 union unchanged; 34/37 |
| 2 | every importer points at `contract`, shim removed | word-diff is the token only; 34/37 |
| 3 | `hacks/seam.py` into `contract/` | R7 union across three packages; R6 confinement on `Reads`/`Measures`/`Sketches`, whose annotations name `panels` |
| 4 | `studio/actions.py` into `contract/` | R7 union; word-diff on importers |
| 5 | the residual `studio/panels.py` → `studio/tables.py` | R7 union; the file now holds no noun |
| 6 | `tests/test_contract.py` | the phase's own oracle — see below |
| 7 | the prose: every docstring and doc that says `panels.` or `hacks/seam.py` | R6 — only docstrings move |

Steps 1–5 are moves and renames; nothing is shortened, named or deduplicated on the
way past. What the phase finds and does not fix goes to the STATE as a list, the
way Phase 1 handed its eleven functions to Phase 1b.

## The oracle

The phase's deliverable is a *direction*, and a direction is not something the
existing tests can fail on: every one of them passes today, with the cycle in
place. So Phase 2 owes a test that fails when the arrow turns round.

`tests/test_contract.py`, four checks, each falsified before it is believed:

1. **Static** — no module in `contract/` imports `studio`, `hacks`, `wiring` or
   `maplint`. Over import lines, by AST, the way `test_vanilla.py`'s
   `test_the_base_imports_no_adapter` does.
2. **Runtime** — importing `pokeprism_devtools.contract` in a fresh interpreter
   leaves `studio`, `hacks`, `maplint` and `textual` absent from `sys.modules`.
   `test_vanilla.py` says in prose that this question could not be asked, because
   `studio.actions` dragged `studio/__init__` → `session` → `maplint` in behind
   it. Moving `actions` is what makes it askable, so asking it is the proof the
   phase landed.
3. **No adapter imports the IDE** — over every module under `hacks/`, with the
   two survivors (`studio.mapadd`, `studio.resize`) named in the test, so the day
   they move the test says so rather than silently passing.
4. **The six are six** — `Hack`'s five optional capabilities each default to
   absence, and every protocol is `runtime_checkable`.

**A fixture is only as good as what it can falsify** (Phase 1b). Each check is
seeded with the mutation it exists to catch — an import added to a `contract/`
module, an adapter pointed back at `studio`, a seventh protocol — and must fail
on it before the commit lands.

## What must not break

- **34/37.** `test_eventheader`, `test_maplint` (live-prism drift) and `test_lib`
  (needs cwd inside a game repo) are red for reasons that predate this branch.
  A fourth red means an edit was not what it claimed.
- **R4 holds**: `git diff` on `tests/` touches import lines only — plus, in step 4,
  one *path literal*: `test_vanilla.py` reads `src/pokeprism_devtools/studio/actions.py`
  off disk by name. A path to a moved file is an import in every sense that matters.
- The entry points in `pyproject.toml` are untouched: `contract` ships no command.
- **Packaging is Phase 3's.** This phase makes B a folder no other product reaches
  into; carving it into its own distribution is the re-carve Phase 0 deferred.

## What step 1 changed

Three claims in the previous draft did not survive measurement, and the phase is
a different shape for it. The evidence is in `refactor-phase-2-STATE.md`.

- "the twenty classes in `studio/panels.py`" → 20 classes is right, but **half of
  what the file holds is the IDE's** and must not move: `Row`, `Tab`, `Table`, the
  twelve table builders and their layout constants are constructed by `studio/`
  and by nothing else, ever.
- "Today this is `hacks/seam.py`" → true, and it is not enough. **`studio/actions.py`
  is the larger half of the cycle** and was not in the spec.
- "its only import is `shared.coords`" → still true of `panels.py`, and it was
  the wrong file to measure: the question is what the *contract* imports, and the
  answer is three `shared/` modules, not one.
