# Phase 0 — split the git history · findings

**Plan: `refactor-phase-0-PLAN.md`.** This file is findings only, filled as the
phase runs. Findings dated 2026-08-03 unless stated.

## Findings — the same list as the index, each linked to its evidence

- A naive carve loses A's first month — [the rename ledger](#the-ledger--a-naive-carve-loses-15-commits).
- D's ledger needs eight `wiring/*` files, and A over-collected seven commits — [the folder-vs-file call](#folder-or-file--the-two-ways-a-ledger-is-wrong).
- Build the ledger from recorded renames; `--follow` invents ancestry for empty files — [the recipe](#build-the-ledger-from-recorded-renames-not---follow).
- Carve first, rename `wiring/` after — [the measurement behind it](#renaming-first-is-a-31-file-commit-in-the-phase-that-touches-nothing).
- The carve is proven walkable, not just present — [the checks](#what-was-proved).
- `--no-local` + `filter-repo` carves **every** branch — [the surprise](#the-carve-brought-four-branches-nobody-asked-for).
- The carved repo is a dated snapshot, not the product — and A still has no packaging
  or tests, both outside its four folders — [what the snapshot is for, and what Phase 3
  owes A](#the-carved-repo-is-a-snapshot-not-product-a).
- Re-verified: A imports nothing from `studio`, `hacks` or `maplint` — [still true](#re-verification-step-1).

## Re-verification (step 1)

**A's zero-dependency claim still holds** (last measured 2026-08-02, re-measured
today). A grep for `studio|hacks|maplint` across `shared`, `wiring`, `usage`,
`sym_lookup` returns 25 hits — **every one of them in a docstring or comment**. The
same grep restricted to `^\s*(from|import)` returns nothing. A's only outward imports
are `..shared.*` from `wiring`, `usage` and `sym_lookup`, and `..symfile` / `..lz`
from `shared/overworld/`.

That distinction is the finding, not the result: the prose in those files talks about
the studio and the hacks constantly, so a grep for the *word* says A is entangled and
a grep for the *import* says A is free. Phase −1 already learned that import greps
mislead; this is the same lesson from the other side.

## The ledger — a naive carve loses 15 commits

The plan's "record every path rename so the later filter can name both" reads
forward, as a thing to do when files move next. **A's paths already have a past.**

Three layouts, one round trip:

| era | shape | boundary commit |
|---|---|---|
| `_lib/` | `_lib/lz.py`, `_lib/paths.py`, … | until `f5e752b` 2026-05-29 |
| flat | `src/pokeprism_devtools/lz.py`, … | until `c8a3e9a` 2026-06-11 |
| subfolders | `src/pokeprism_devtools/shared/lz.py`, … | today |

plus a round trip: 25 files left `shared/` for `hacks/prism/` in `b0298cc`
(2026-07-19), and three of them — `blockdata.py`, `people.py`, `spritevram.py` — came
back as `shared/overworld/` in `3a1fae6` (2026-07-27).

**Measured:** `--path` on today's four folders alone reaches **73** of 234 commits.
Adding every historical spelling reaches **88**. The 15 lost commits are A's entire
first month, 2026-05-29 → 2026-06-07, and they are not incidental — they are the
birth of the primitives A exists to provide:

```
aeae7d9 tools: add _lib/ shared parsers (sym, constants, savefile)
76cbfc3 tools: add _lib/lz.py LZ decompressor
0b6e283 tools: add _lib/blockdata.py — map blockdata reader + wScreenSave computer
8d944cf tools: add sym-lookup for querying the .sym file
dcf56cd feat: add the new tool prism-usage
5d4186e feat(prism-usage) reports the cartridge's true size by reading the ROM header
f5e752b restructure: src/ layout + pyproject.toml for pipx install
… and 8 more
```

A carve that drops these gives the carved repo an LZ decompressor whose first
commit is a subfolder reshuffle. **The "why" Phase 0 exists to preserve is exactly
the part a naive carve throws away** — because the oldest reasoning is the most
renamed.

### Build the ledger from recorded renames, not `--follow`

**The recipe, for Phase 3:**

```sh
git log --diff-filter=R --name-status -M --format='' \
  | awk '$1 ~ /^R/ {print $2" -> "$3}' | sort -u
```

Then walk the chains backward from today's paths. It recovers every era of A —
`sym-lookup/sym-lookup.py` → `sym_lookup.py` → `sym_lookup/__init__.py`, and all nine
`_lib/*` moves — because it reads the rename **git actually recorded in a commit**,
one row per event.

**The first ledger was built the other way, from `git log --follow` per file, and that
output cannot be used raw.** It reports `_lib/__init__.py` as the ancestor of **both**
`shared/__init__.py` and `wiring/__init__.py`. All three are **zero bytes**, so the
similarity heuristic is scoring nothing against nothing and matching whatever it meets
first. The three `__init__.py` files were left out of the ledger by hand. The query
above names `_lib/__init__.py` exactly once, which is the truth.

Generalising: **`--follow` asks the heuristic to invent a chain and it obliges wherever
a file is trivial; `--diff-filter=R` reads a chain that was already written down.** The
check on the first is content, not the tool's confidence — there is no check to run on
the second.

`--follow` is still the right tool for the *other* job, verifying a finished carve
(see [what was proved](#what-was-proved)). Deriving history and confirming it survived
are different questions.

## Renaming first is a 31-file commit in the phase that touches nothing

Phase −1 scheduled `wiring/` for renaming "on the way into A" and left the order open.
**Decided: carve first, rename later.** (Later means *after Phase 3's re-carve* — see
[the snapshot](#the-carved-repo-is-a-snapshot-not-product-a), which corrected this
section's original answer of "inside A's own repo".) The measurement:

- **31 files** outside A import `wiring`, over **50 import lines** — 2 in `studio/`,
  9 in `hacks/prism/`, 11 in `hacks/vanilla/`, 9 in `tests/`.
- **237 further textual mentions** across `src`, `tests`, `docs` and `pyproject.toml`.

Renaming first lands that churn in the monorepo during the one phase whose premise is
that the tree is untouched, and B, C and D then carry a commit they have no stake in.

**And it buys nothing**, which is the part that settles it: the rename commit would
itself be inside the history being carved, so the filter must name both spellings
either way. The order changes who does the work, not whether the ledger needs the row.

**Cost, recorded so Phase 3 does not trip on it:** the B/C/D filter must name
`wiring/`, not A's new name, because at the moment that filter runs the monorepo still
spells it `wiring/`.

## Folder or file — the two ways a ledger is wrong

Measured while checking whether "the B/C/D filter must name `wiring/`" was even
stated correctly. It was not.

`--path` matches the path a commit touched **in the history being filtered**. This
repo's history spells the folder `wiring/` permanently — renaming it inside
the carved repo cannot reach back into commits already made here. So D's ledger
carries a `wiring/` row regardless of what A calls the folder afterwards.

**But it is eight files, not the folder.** `033fbe4` (2026-07-25) moved eight modules
out of `wiring/` into `hacks/prism/`, where they are today: `connections`, `mapedit`,
`objedit`, `props`, `removal`, `scaffold`, `text`, `warps`. D must name those eight
paths, or it loses their history before that date — the same defect the ledger exists
to prevent, one product over.

**A already made the opposite error, and it is recorded rather than fixed.** A's carve
named the `wiring/` folder, so it swept those eight up for the period they lived there:
**17 commits reach them, 7 touch nothing still in A.** They are correctly absent from
A's tip — they appear and are deleted, which is what happened — so this is history
being accurate, not a leak.

The two failures are not symmetric, and that is the rule to carry forward:

| error | how it happens | what it costs |
|---|---|---|
| over-collect | name a folder | a dead file in an old commit, absent from the tip |
| under-collect | name a file, miss a rename | the reasoning behind a **live** file, silently |

**When the ledger is ambiguous, over-collect.** Only one of these is recoverable by
reading the result.

**None of this concerns imports.** Carving history never rewrites an import line.
After the split, B/C/D import A as an installed dependency under its package name;
that edit is code, happens once, and is where A's `wiring/` rename becomes visible
outside A.

## What was proved

The carve ran in a throwaway clone under the session scratchpad. The exact command is
committed as **`scripts/carve-product-a.sh`** — Phase 3 re-runs it rather than
re-deriving it. Checks, each written so that a failure is visible:

| check | result |
|---|---|
| commits carried | **88** — and 73 is the falsification, i.e. the ledger silently not taking |
| tree is exactly A | 34 files, `git ls-files` matches this repo's A exactly, nothing outside the four folders |
| content unchanged | `diff -r` against this repo's A: no differences |
| **history is walkable** | `--follow` on `shared/lz.py` reaches `_lib/lz.py`'s birth; on `sym_lookup/__init__.py` reaches `8d944cf`; on `shared/overworld/blockdata.py` reaches `_lib/blockdata.py` |
| renames survived as renames | 24 rename records in the carved history |
| cited SHAs still resolve | filter-repo rewrote every in-message SHA. One dangling reference (`9ea8675`, cited by `a368191`) — **it was already dangling in this repo before the carve**, so the carve introduced none |

The fourth row is the one that matters. Commits *being present* proves the `--path`
list; `--follow` *crossing the rename* proves they were kept as one story rather than
as an unrelated delete and add. A carve can pass the count and fail this.

**SHAs are rewritten** — `76cbfc3` in this repo is `6f8d237` in A. Any SHA quoted in
`docs/` refers to *this* repo and does not resolve in the carved one. The reverse also
holds, so the two repos' commit identifiers are permanently unrelatable.

## The carve brought four branches nobody asked for

`git clone --no-local` fetches every branch, and `filter-repo` rewrites all of them.
The carved repo arrived with `main`, `feat/adapter-seam`, `feat/map-studio` and
`refactor/four-product-split` — branch names that describe *this* repo's history and
mean nothing to a standalone library.

Checked before touching them: all three are **strict ancestors** of the tip
(`git merge-base --is-ancestor`), so nothing was lost. They were deleted and the tip
renamed `main`, re-verifying afterwards that `--follow` still reaches the `_lib` era.

**For Phase 3:** the carve's default output is not a clean repo. Prune branches, and
check ancestry before pruning rather than after.

## The carved repo is a snapshot, not product A

`~/code/ricccec/pokecrystal-asm-lib-history-2026-08-03` — `main`, 88 commits, 34 files,
no remote. **The folder name is the finding.** It was `pokecrystal-asm-lib` for an
afternoon, and that name claimed something untrue.

`filter-repo` **copies** history; it never deletes from the source. So A's files are in
two places — here, where everything imports them, and there, where nothing does. The
snapshot froze at 34; A is **40** here today, because Phase 1 split `usage/` into seven.
**This repo is A's only editable copy. The snapshot takes no commits at all**, not even
a rename, because Phase 3 re-runs the carve and a carve builds a **fresh** history:
anything committed in the snapshot meanwhile is discarded, not merged.

**Its one job is to be a dated backup** of A's 88 commits against a rewrite of *this*
repo's history. That is the only scenario where it is not reproducible on demand — and
it is why it was kept rather than deleted.

**Phase 0's real deliverable is the rehearsal and the ledger**, both of which live in
this repo (`scripts/carve-product-a.sh` and the sections above). The snapshot is a
by-product. Read "Phase 0 carved A" as *"the carve is known to work and the path list
is known to be right"*, never as *"product A exists"*.

**It is not a library and could not be one.** `pyproject.toml`, the entry points and all
38 test files live outside A's four folders, so they were not carved; the snapshot does
not even contain `src/pokeprism_devtools/__init__.py`, which is shared with every
product and would have dragged in the whole repo's history. **Phase 3 owes A a packaging
and test story.** `usage` and `sym_lookup` are CLI packages whose `console_scripts`
entries stayed behind in this repo's `pyproject.toml`.

**One question Phase 0 got backwards.** The carve-first decision was argued as if A's
repo would take its own first commit — the `wiring/` rename — "against A's own imports".
It cannot: the re-carve would throw that commit away. The rename belongs to Phase 3,
after the final carve. Corrected in the PLAN rather than annotated.

**And freezing A *here* was never the alternative**, which is what forces the direction:
`usage/` is both one of A's four folders and one of **Phase 1's** six CLI packages, and
CLAUDE.md compliance is scoped to every file in this repo. A's code is *supposed* to
change here. The snapshot is what holds still.
