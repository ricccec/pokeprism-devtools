# Where the adapter seam stands — the current-state map

This is the doc to read to know *what is true now* and *what is left*. The three
plans it replaces as a status source are journey logs and stay as history:

- `adapter-plan.md` — the argument for one frontend / many hacks, and why the
  split is deferred. Its one scheduled piece (the pluggable mount) shipped.
- `polished-crystal-feasibility.md` — the measured experiment. Phases 0–4.
- `family-write-plan.md` — the family write story. Phases 5–10 (history).
- `family-lint-plan.md` — the live plan: Phase 11 and the roadmap past the seam.

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
| **vanilla** | ✓ | ✓ | ✓ (dialogue overflow + name bounds) | — | — |
| **polished** | ✓ | ✓ (head anchor, own warps/choices/adders/resize/newmap) | ✓ (dialogue overflow + name bounds, n-gram reader) | — | — |

The family trees (vanilla, polished) read and write — delete, edit, add,
resize, new-map, and the block scaffolding those ride — and the writes
round-trip to the byte on all real maps. **Both family trees now lint too**: the
dialogue-overflow rules below make them the first family trees with a non-`None`
`ctx`. They share everything but the width reader, which polished's Huffman
n-gram engine spells differently (see below). Their remaining blanks in the
matrix are the **absences by design** further down — one permanent, the rest
deferred — not gaps.

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

## Landing now — family dialogue-overflow linting (Phase 11; `family-lint-plan.md`)

**Move A — done.** `Hack.ctx` is a lint *capability* (`seam.Lints`): `lint()`,
`mentions()`, `source_lines()`, `invalidate()`. The session lints through it and
never learns which rules a tree runs — prism's `LintContext` runs all of them, a
family ctx runs three (the two overflow rules plus name bounds), and the session
cannot tell them apart. It branches only on `ctx is not None`, never on a name.

**Move B — done, both family trees.** `hacks/vanilla/lint/` is a
`FamilyLintContext` that flags a dialogue line wider than the 18-tile box
(`text-width`, counting the `#`→POKé kind of expansion the eye misses) or landing
past its last row (`text-rows`). It reads the box from `constants/text_constants.asm`,
tokenises with a family charmap, and counts widths from the engine — all
false-positive-free determinate arithmetic, the exact-fit case the plan argues is
*not* a `Measures.measure` question. Both real trees lint clean (polished across
606 maps and 27,701 visual lines, 2,753 of them packed to exactly 18 tiles and
none over — the metric agrees with the authors to the tile); the rules and their
falsification live in `tests/test_family_lint.py`.

**The one thing that forks — the width reader.** The map *event* format is
identical across the family (so the read mechanics are shared), but the *text
engines* are not: vanilla is classic `dict`+`print_name`→ROM `db`, polished is
`_dtxt`/Huffman `ctxtmap` with an n-gram string table (closer to prism). So the
box, the dialogue parse, the rules and the neutral arithmetic are shared; only
the `Metrics` reader is engine-specific. `hacks/polished/lint.py` is that fork and
nothing else: it resolves a byte through the n-gram table (`data/text/ngrams.asm`)
where an n-gram is one ROM byte but several screen tiles (`#`→`Poké`, `the `→four
tiles), counting each expansion in the un-compressed charmap so an apostrophe
ligature like `'s` is the one tile it draws and not two. It reuses vanilla's box,
parse, rules and `FamilyLintContext` unchanged — the same fork pattern as its
writer. Two shared touch-ups let it in without a branch: `FamilyLintContext` now
takes its `engine_files` as declared data (the guard cannot name one tree's
`home/text.asm`), and the width message names tokens that draw *wider than they
read* (`> len`, not `> 1`), so it calls out `#` without burying it under
polished's every n-gram.

**Move C — done, name bounds (`text-width-name`), both trees.** A line can fit in
testing and overflow the moment someone types a long name: `<PLAYER>` reads as
nothing and draws up to seven tiles (`PLAYER_NAME_LENGTH - 1`). The rule warns
where the *determinate* part still fits but the *worst case* does not — a
`Severity.WARNING`, since a short name is fine, not an error. It is the clean
half of Move C: the name tokens (`<PLAYER>`/`<RIVAL>`/`<MOM>`/`<RED>`/`<GREEN>` in
vanilla, `<PLAYER>`/`<RIVAL>` in polished) sit *inline* in strings, already
tokenised, so all that was added is a declared `bound` per tree and a `worst`
alongside `determinate`. Both shipping trees stay clean under it — and, exactly
like the determinate rule, the tightest real line packs to the tile
(`<PLAYER> obtained a`, 18 tiles at a seven-letter name, LakeOfRage): the metric
agrees with the authors again. The per-tree bound is declared data (`_NAME_BOUND`
maps each name buffer to `PLAYER_NAME_LENGTH`), read from source, seam-clean.

`text-buffer` — the *other* half of Move C, the unbounded `<STRBF*>` headroom —
is **not** the clean port the plan assumed and is left for a deliberate pick-up
(see the roadmap). Prism's dialogue is one string with inline codes, so
`text_from_ram` is a mid-line token; the family splits a box across separate
`text`/`text_ram` *script commands*, and the parser deliberately treats each
`text` as its own box and `@` as a terminator — a conservative simplification
that undercounts rather than false-positives. Modelling `text_ram` correctly
(joining consecutive commands into one visual line, past the `@`-terminator) is a
parser change with false-positive risk, distinct from Move C's inline-token work.

**The finding channel is now genuinely hack-neutral.** `maplint/__init__` defers
its rule/context imports (all of `hacks.prism`) into `run()`/`main()`, so
`maplint.diagnostics` and the new `maplint.textfit` (the shared fit/row
arithmetic) import without loading prism. That is what lets a family tree's
linter reach the channel without dragging in the tree it is not written against.

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
full roadmap, grouped, is in `family-lint-plan.md` ("The roadmap past the
seam"); the standing items:**

- **Family `text-buffer`** — the unbounded `<STRBF*>` headroom rule, Move C's
  second half. It needs the dialogue parser to model the `text_ram` script macro
  and join consecutive `text` commands into one visual line past the `@`
  terminator — a parser change with false-positive risk, not the inline-token
  port `text-width-name` was. See the Move C note above.
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
prism-written by design, gated by `plays`. The finding channel (`maplint/`) is no
longer prism-only: its rules are, but the channel itself — `diagnostics` and the
neutral `textfit` — imports without prism, and both family trees now carry their
own overflow `ctx` on top of it. What each tree lints is its own; that the
session cannot tell them apart is the seam working.

## Doc hygiene — the accretion to watch

`docs/` is accreting. Besides the three journey docs, this one, and the live
`family-lint-plan.md` (Phase 11 + roadmap, split out of `family-write-plan.md`
to keep the completed history off the hot path):
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
