# Where the adapter seam stands — the current-state map

This is the doc to read to know *what is true now* and *what is left*. The three
plans it replaces as a status source are journey logs and stay as history:

- `adapter-plan.md` — the argument for one frontend / many hacks, and why the
  split is deferred. Its one scheduled piece (the pluggable mount) shipped.
- `polished-crystal-feasibility.md` — the measured experiment. Phases 0–4.
- `family-write-plan.md` — the family write story. Phases 5–10.

Read those for *why* a thing is shaped the way it is. Read this for *what shape
it is in*. When a phase closes or an engineering item is paid, update this file
first.

## The seam, as it exists

`hacks/seam.py` is the contract, provably free of hack names. `hacks/mount.py`
(146 lines) does discovery and the claim loop and nothing else. Each hack ships
a `claim.py` that recognises its own tree and builds its adapter — the same
entry-point path a third-party adapter would use.

Four `runtime_checkable` protocols, each gating a capability rather than a name:

| Protocol | What it covers | Gated on |
|---|---|---|
| `Reads` | the nine read methods every adapter owes | always present |
| `Writes` | the nine write methods (actions, forms, deletion, undo) | `Hack.writes is not None` |
| `Measures` | `measure` — text in tiles against the engine's VWF | `Hack.measures` |
| `Sketches` | `sketch` — draw the map while you type | reachable only from an action that sets `sketches` |

`Hack` declares `name`, `reads`, `ctx` (lint context, or `None`), `writes` (or
`None` → read-only), `plays`, `measures`. Everything above the seam gates on
these; a missing capability degrades to a visible absence, never a crash.

## Capability matrix — what each mounted tree can do

| | reads | writes | lint (`ctx`) | plays | measures |
|---|---|---|---|---|---|
| **prism** | ✓ | ✓ | ✓ | ✓ | ✓ |
| **vanilla** | ✓ | ✓ | — | — | — |
| **polished** | ✓ | ✓ (head anchor, own warps/choices/adders/resize/newmap) | — | — | — |

The family trees (vanilla, polished) read and write — delete, edit, add,
resize, new-map, and the block scaffolding those ride — and the writes
round-trip to the byte on all real maps. Their blanks in the matrix are the
**absences by design** below — one permanent, the rest deferred — not gaps. One
of the deferred, family dialogue-overflow linting, is wanted next.

## The last engineering item — paid (2026-07-25)

**Phase 9c, category 4 — relocate the prism-bound `wiring/` modules home. Done.**
`wiring/` no longer imports `hacks.prism` at all: the last wrong-direction edge
in the tree is gone.

**Step 1 — the vocabulary split.** The dialect-free editing vocabulary —
`EditError`, `Change`, `same`, `spliced`, `palette_of`, `repainted` — moved into
`wiring/editvocab.py`, a module with no `hacks.prism` import (`same` takes
`as_int` from `shared/constants`; `spliced` types its entry with a structural
`Spliceable` Protocol, naming no hack's `Entry`). Every prism-free consumer —
`mapnew`, `mapresize`, `placement`, `mapedit`, `vanilla/resize` — was repointed
at `editvocab`, severing the `vanilla/newmap → wiring.mapnew → objedit`
import-load leak.

**Step 2 — the move itself.** Eight modules that lived in `wiring/` while being
consumed only by `hacks/prism/` and each other — `objedit`, `scaffold`, `props`,
`removal`, `warps`, `connections`, `mapedit`, `text` — relocated into
`hacks/prism/`, beside the write-adapter files that moved home in category 3.
Their coupling was never the import lines, it was prism's logic: the field
indices *are* prism's twelve-slot `person_event` (`PALETTE=8`, `PERSONTYPE=9`),
which polished does not have; `objedit`'s trainer parser is anchored on prism's
five-arg `trainer` and would skip every family `generictrainer`. A family caller
that reached for `S_X`/`W_Y` next door would have got a wrong answer, not a
crash — which is why they moved rather than stayed.

It was a **move, not a parameterize** (see `family-write-plan.md`, "How category
4 gets paid"): no family caller wants these modules' logic, so an injection seam
would have served a second consumer that does not exist. The import graph did
not change — only the spelling of the paths — so no cycle appeared, and
CLI-extractability survives: a `prism-objedit` CLI wraps `hacks/prism/objedit` as
readily as it would have `wiring/`. `editvocab` stays in `wiring/` (the family
still reaches it for `EditError`); the movers now reach it as `...wiring.editvocab`.

**Verified:** `mapnew`/`mapresize`/`placement` load zero prism modules; the seam
trio, `test_wiring`, `test_scaffold`, `test_events_write`, `test_placement`,
`test_mapnew`, `test_studio`, and `test_regions`/`test_flagalloc` all pass. What
remains of prism showing up when a *family* tree mounts is the mount discovering
every hack through `studio → session → mount` — the mount's job by design, not a
wiring-layer leak. With this paid, the seam has no known structural debt left.

## Wanted next — family dialogue-overflow linting (scoped: `family-write-plan.md`, Phase 11)

Distinct from a debt (there is none left): this is a wanted capability, the next
thing worth building rather than a resting blank. **Now scoped as Phase 11** in
`family-write-plan.md`; that section holds the argument, the architecture, and
the moves. In brief:

**The want:** flag a dialogue line that crosses the screen boundary and
overflows the box — for vanilla and polished, not only prism.

**Why it needs no VWF — measured, and the old flat claim corrected.** Overflow
is a *fit* question, and map dialogue is fixed-width in **both** trees: every
glyph is one tile, the box interior is a fixed 18 tiles (`TEXTBOX_INNERW`), and
the script's own break macros (`text`/`line`/`cont`/`para`) end each visual
line. Count printable tiles between breaks, compare to the box width — exact, not
a guess. (Polished *does* ship a VWF, but only for menus; overworld dialogue
runs through the fixed-width `PlaceString` path. So the fit is exact for
dialogue even though a menu elsewhere is proportional.) This is why it does
**not** sit under `Measures.measure`, which rightly refuses the unknowable VWF
*pixel* width — a different question.

**What it reads.** `Reads.texts(label)` already crosses every string in source
order. What is missing is small and family-local: the box width, the break
vocabulary, and a family charmap reader for control-code expansions.

**Where it lands.** As a family **`ctx`** — the first thing that makes
`Hack.ctx` non-`None` for vanilla/polished, surfacing through prism's existing
finding channel. Phase 11's step A first turns `Hack.ctx` into a lint capability
(`ctx.lint()`) so a family ctx can run only its own rules without the session
knowing rule sets. Does not touch `Measures`, `Writes`, or the read methods.

## Absences by design — none permanent but one, all otherwise deferred

Each is a capability a family tree does not have *yet*. None is debt: none is the
residue of a shortcut, none blocks anything, and each renders as a visible
absence rather than a plausible stand-in. But — the correction that prompted this
rewrite — only one is settled "never." The rest are future work consciously
scoped out, each pick-up-able as its own phase.

**The one permanent absence — and it is a font fact, not a capability:**

- **Family VWF pixel metrics for dialogue** — map dialogue in both trees renders
  through the fixed-width `PlaceString` path, so the per-glyph pixel widths
  prism's `measure` sums do not exist for it. (Polished ships a menu VWF, but it
  is off the dialogue path.) This is about the dialogue font, forever. It does
  **not** mean the family cannot be checked for overflow — that is fixed-width
  tile counting, scoped just above as Phase 11.

**Deferred — implementable, deliberately out of the seam's current scope. The
full roadmap, grouped, is in `family-write-plan.md` ("The roadmap past the
seam"); the standing items:**

- **Family `plays`** — build-and-replay is engine wiring, a separate project.
- **Family rewording** — `wiring/text` is still prism-parser-based (one of the
  cat-4 movers); rewording against a fixed-width charmap is a text-wiring project.
- **Connection *adding*** — `wiring/connections` is two-sided; deserves its own
  look. Deletion already refuses on the neighbour's side, with teeth.
- **`EditMap` (attributes tab)** for family trees — not claimed.
- **Family map *sketch*** — the new-map form does not draw the grid while you
  type; that needs a family block renderer to point at, and returning something
  that does not draw would be the exact wrong-absence Phase 4's `absent()` exists
  to prevent.

The prism-only CLIs (`dev_server`, `gfx_view`, `map_inspect`, …, 12 files) are
prism-written by design, gated by `plays`. The current linter (`maplint/`, 7
files) is prism-only *today* via `ctx is None` — but that is a present fact, not
a permanent one: the family overflow pass above is exactly how a family `ctx`
begins.

## Doc hygiene — the accretion to watch

`docs/` is accreting. Besides the three journey docs and this one:
`devtools-plan.md` (historical), `bank-usage-plan.md` (spec, no code),
`blockdata-plan.md` (shipped), `map-inspect-plan.md`, `devtools.md` (user
reference). Separately, a `feat/map-studio` docs restructure sits **stashed**
(`git stash@{0}`), unlanded. None of this is on the critical path; it is the
entropy to prune when convenient, not now.

## Tests

Run as scripts with `./.venv/bin/python tests/<name>.py`, not pytest. The
seam-critical trio — `test_seam.py`, `test_vanilla.py`, `test_polished.py` —
passes clean. `test_seam.py::test_falsified` is the one that earns its keep: it
catches the adapter that passes every name check while answering `None` to
everything — the one that mounts, draws an empty studio, and blames the repo.
