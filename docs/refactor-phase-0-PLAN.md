# Phase 0 — split the git history · the plan

**Findings as it runs: `refactor-phase-0-STATE.md`.** This file is intent only.

Carve **product A** — `shared` + `wiring` + `usage` + `sym_lookup` under
`src/pokeprism_devtools/` — out of this repo's history with `git filter-repo`, so A
keeps the reasoning behind its code instead of starting at one squashed commit.
B, C and D are fused by the `hacks → studio` cycle and wait on Phase 2, whose
acceptance test *is* that cycle being gone.

**This repo is not touched.** No file moves, no commit is rewritten here. The only
change inside this repo is documentation: this file, the phase STATE, and the index
entry. Everything else happens in the new repo.

## What A is called, and where it lives — decided

`~/code/ricccec/pokecrystal-asm-lib-history-2026-08-03`, local, no remote. The name is
the user's call, taken 2026-08-03; the `-history-<date>` suffix says what it is — a
dated snapshot of A's history, superseded by Phase 3's re-carve, not the product.

No remote yet because there is nothing to install or run: `pyproject.toml`, the
entry points and every test live **outside** A's four folders, so the carved repo is
history plus source and nothing else. That is not a defect of the carve — it is the
next thing Phase 3 owes A. Recorded as a hand-forward, not fixed here.

## Carve first, rename `wiring/` after — decided, with the reason

Phase −1 scheduled `wiring/` for renaming "on the way into A" and left the order
open. **Carve first.**

Renaming first would be a **31-file, 50-import** churn commit across `studio/`,
`hacks/` and `tests/` — measured, see STATE — landing in the monorepo, in the phase
whose premise is that the tree is still untouched, and then carried by B, C and D
which do not care. It also buys nothing: the rename commit would be *in the history
being carved*, so the filter still has to name both spellings either way.

Carving first means the rename is not this phase's business at all: it happens once,
after Phase 3's final carve, against A's own imports. It cannot happen in
the snapshot before then — see "the snapshot" below, and the STATE section it links.

**Cost, stated plainly — and this is about history, not imports.** `--path` selects
commits by the path they touched *in the history being filtered*, and that history
spells the folder `wiring/` permanently: renaming it inside A's repo cannot reach back
into this repo's commits. So D's ledger must name the old `wiring/` spelling.

**It must name eight files, not the folder.** Eight modules that are `hacks/prism/*`
today lived at `wiring/*` until `033fbe4` (2026-07-25) — `connections`, `mapedit`,
`objedit`, `props`, `removal`, `scaffold`, `text`, `warps`. D needs those eight paths
or it loses their history before that date, the same defect the ledger exists to
prevent. Naming the whole folder instead would drag all of A's `wiring/` history into
D.

## The rename ledger — the part the plan under-specified

The plan says "record every path rename so the later filter can name both". It reads
forward. **A's paths already have a past**: three layouts (`_lib/` → flat
`src/pokeprism_devtools/` → today's subfolders) and one round trip through
`hacks/prism/`. A carve naming only today's four folders drops **15 commits**,
including the birth of every primitive A is built on. Measured; see STATE.

So the filter names today's four folders **plus** every historical spelling of a file
now in A:

| era | paths |
|---|---|
| today | `shared/`, `wiring/`, `usage/`, `sym_lookup/` (under `src/pokeprism_devtools/`) |
| flat, from `f5e752b` | `blockdata.py`, `constants.py`, `lz.py`, `mapfile.py`, `paths.py`, `people.py`, `sym_lookup.py`, `symfile.py`, `usage.py`, `viewer.py` (under `src/pokeprism_devtools/`) |
| `_lib/`, before `f5e752b` | `_lib/blockdata.py`, `_lib/constants.py`, `_lib/lz.py`, `_lib/paths.py`, `_lib/people.py`, `_lib/symfile.py` |
| the prism round trip | `src/pokeprism_devtools/hacks/prism/{blockdata,people,spritevram}.py` |
| pre-`src/` | `sym-lookup/sym-lookup.py` |

**Rebuild it from the renames git recorded**, walking the chains backward from today's
paths — `git log --diff-filter=R --name-status -M`. Not from `git log --follow`, which
was used the first time and reports `_lib/__init__.py` as the ancestor of *both*
`shared/__init__.py` and `wiring/__init__.py`: all three are zero bytes, so the
similarity heuristic matches nothing against nothing. A ledger built from `--follow`
contains invented rows. Full recipe in STATE.

## Steps, and what proves each

Work in a throwaway clone under the session scratchpad. `filter-repo` rewrites
history irreversibly and refuses to run on a non-fresh clone, so it never sees this
working repo.

1. **Clone `--no-local` into scratchpad.** Proof: `git log --oneline | wc -l` is 234
   and `git status` is clean.
2. **Run the carve** with the ledger's paths. Proof: it exits 0 and reports a
   rewrite.
3. **Count what survived.** Proof: 88 commits, not 73 — the naive figure is the
   falsification. If it comes out 73, the ledger did not take.
4. **Prove the history is walkable, not just present.** `git log --follow` on
   `shared/lz.py` must reach `_lib/lz.py`'s birth commit `76cbfc3`, and on
   `sym_lookup/__init__.py` must reach `8d944cf`. This is the check that says the
   rename commits survived *as renames* rather than as an unrelated add and delete.
5. **Prove the tree is exactly A.** `git ls-files` in the carved repo lists A's 34
   files and nothing else — no `hacks/`, no `studio/`, no `pyproject.toml`.
6. **Prove nothing leaked in.** The carved repo's tip content is byte-identical to
   this repo's A, checked with `diff -r`.
7. **Move it to `~/code/ricccec/pokecrystal-asm-lib-history-2026-08-03`** only once
   3–6 pass, and confirm it has no remote.
8. **Record.** One line per finding in `refactor-STATE.md`, the evidence in
   `refactor-phase-0-STATE.md`, including the exact command so Phase 3 re-runs it
   rather than re-deriving it.

## What must not break

- This repo's history, working tree and branch are unchanged. `git status` clean and
  `git log` at 234 commits when the phase closes, plus the three doc commits.
- The three known-red tests stay red for the same reasons (`test_eventheader`,
  `test_maplint`, `test_lib`). Phase 0 runs no code, so a *new* failure would mean
  something happened that this phase does not believe it did.

## A holds seven commits that are prism's

A's carve named the `wiring/` **folder**, so it swept up the eight modules listed
above for the period they lived there: **17 commits reach them, 7 of which touch
nothing that is still in A.** Those files are correctly absent from A's tip — they
appear and are deleted, which is what actually happened — so this is history being
true rather than a leak. It is recorded because Phase 3 faces the mirror image and
must not answer it by reflex: naming a folder is the cheap way to over-collect, and
naming a file is the cheap way to under-collect.

**Neither error is symmetric.** Over-collecting leaves a dead file in an old commit;
under-collecting silently loses the reasoning behind a live one. When the ledger is
ambiguous, prefer over-collecting.

## The snapshot is a by-product, not the deliverable

The carve **copied** A; it deleted nothing. **This repo is A's only editable copy, and
the snapshot takes no commits at all** — not even the `wiring/` rename. Phase 3 re-runs
the carve and builds a fresh history: anything committed in the snapshot meanwhile is
discarded, not merged.

Freezing A *here* is not the alternative. `usage/` is one of Phase 1's six CLI packages,
and CLAUDE.md compliance covers every file in this repo, so A's code is meant to keep
changing here.

**What this phase actually delivers is the rehearsal and the ledger** — the script and
the measurements, both of which live in this repo. The snapshot's only unique value is
as a dated backup should *this* repo's history ever be rewritten; everything else about
it Phase 3 reproduces on demand. Evidence and the corrected consequences: STATE, "the
carved repo is a snapshot".

## Handed forward

- **To Phase 3, before it re-runs this:** re-derive the ledger from recorded renames,
  do not trust this table. Phases 1 and 2 move files, and every move adds a row — but
  the recipe recovers them, so the table needs no hand-maintenance in between.
- **To Phase 3, for D specifically:** name the eight `wiring/*` paths above, not the
  folder. This is the one row Phase 0's ordering decision put there.
- **To Phase 3, on imports — a separate job from any of this.** Carving history never
  changes an import line. After the split B, C and D import A as an installed
  dependency under its own package name, and every `from ..shared...` becomes an
  import of that package. That edit is code, it happens once, and it is what makes the
  `wiring/` rename visible outside A.
- **To Phase 3, as A's unfinished half:** packaging and tests. A has no
  `pyproject.toml`, no entry points, no test file. Until Phase 3 writes them, no repo
  anywhere holds an installable product A.
- **To Phase 3, once the final carve lands:** rename `wiring/`. Phase −1 named its
  contents — editing pret assembly source — and `WiringError` is defined three times
  because the folder name means nothing. Not before: a rename committed in the snapshot
  is discarded by the re-carve.
