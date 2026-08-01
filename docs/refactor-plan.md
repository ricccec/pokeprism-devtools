# The refactoring plan — from one repo to four products

**This file is the argument**: what we are doing, in what order, and why. It is not
a status source. Three kinds of file, and each phase owns two of them:

- `refactor-STATE.md` — the index. Every phase, its files, one line per finding.
- `refactor-phase-<n>-PLAN.md` — a phase's working plan, written when it opens.
- `refactor-phase-<n>-STATE.md` — that phase's findings, written as it runs.

## The goal

Four things in this repo deserve their own place: a library for reading and editing
pret-family ROM-hack assembly; the CLI tools built on it; the studio (a TUI that,
despite its name, suits any hack in the family); and the per-hack adapters that teach
both about one tree — today `Pokemon Prism`, `Crystal` and `Polished Crystal`.

The studio and some of the CLIs are meant to be *extended with hack adapters*.
Everything below serves one measurable outcome:

> A developer with their own ROM hack can answer **"what do I need to do to make an
> adapter?"** by reading one small package — and nothing they write ever imports
> anything from above the seam.

A rule about **direction, not quantity**. An adapter is *expected* to lean on the
shared library and the domain entities; extracting those is why they exist. What it
must never import is the far side of the seam — the IDE, its widgets, its screens,
its edit cycle. Imports point down, never up.

That is not true today: all three in-tree adapters import the IDE at runtime
(`hacks/prism/read.py:33`, `hacks/polished/read.py:20`,
`hacks/vanilla/eventblock.py:54`, and six more), so the seam this branch was built to
create does not hold at the only place it matters.

## Maintaining this file

> A multi-session, long-horizon refactoring carried by a multitude of agents. This
> document and `refactor-STATE.md` are the primary means of information sharing, so
> keeping them current and easy to digest is essential.

- **Write it down.** Anything contradicting the plan, any fact about the refactoring
  (a bug, a duplicate, a convention violated), anything that might help another agent
  later even if not you now. Doing it now beats re-discovering it every session.
- **Replace, never append.** A correction *removes* the passage it corrects. Never
  leave the wrong version standing with a note beneath it: the next agent reads both
  and believes the first.
- **Keep this file under ~250 lines, no duplicates.** Written for agents, not humans.

**Which file — not a choice.** A finding, a count, a measurement, a verdict: your
phase's `-STATE.md`, plus **the same one line in two places** — the phase entry in
`refactor-STATE.md`, and a linked copy at the top of your `-STATE.md` pointing at
the section that proves it. That pair is what lets an agent arrive from the index
and land on the evidence without reading the file. How you intend to do the phase:
its `-PLAN.md`. **This file** changes only when *intent* does. If you cannot tell
which it is, it is a finding.

## Starting a session, or starting a phase

**Fresh session, or an existing one opening a new phase — the same three steps.** Do
them before writing any code or any plan.

A phase is planned before its evidence exists; that is what planning is. The phases
below were drawn from an import grep, and Phase −1 found three of its rows wrong and
a fourth short by eight modules. Going straight from plan to work would have mis-filed
three tools and never learned why. **So the first job of every phase is to find out
what changed since it was written.**

**1 · Re-verify what this phase leans on.** Read `refactor-STATE.md` — the index,
one line per finding — then open only the phase STATE files whose lines matter to
you. Check the claims *this* phase rests on: the tree moves, the live hack repos
move, and a finding is only as current as its last measurement. The load-bearing
ones only; a finding this phase never touches does not become a task.

**2 · Correct the drift in place.** A claim that no longer holds is fixed in the file
that made it, replacing the wrong version rather than annotating it. Never leave a
correction only in a commit message or a reply — the next session reads the docs, not
the transcript. If it invalidates an earlier decision, say so and say what that costs.

**3 · Open the phase's two files.** The sections below are sketches; **do not grow
them.** Write the real plan in `refactor-phase-<n>-PLAN.md` — what changes, in what
order, what proves each step, what it must not break — and start
`refactor-phase-<n>-STATE.md` empty, filling it as you go. Add both to the phase's
entry in `refactor-STATE.md`. When the phase closes, its two files stay as the
journey log, which is what the other landed plans in `docs/` are; the section here
never grows past a sketch and a link, and that is how the cap survives six phases.

Only then does the phase start. If step 1 or 2 changes what the phase should even be,
that is a result — record it and re-plan.

## Before anything

Three items. **The last two are not refactoring** — they are defects that exist today,
found by Phase −1 while reading for something else. They are here rather than in a
phase because a move must never be the thing that fixes a bug: you could never again
say whether the move was behaviour-neutral. Fix them on the current tree, each with
its own test, and the phases keep their "nothing changed" claim honest. Evidence for
all three is in `refactor-STATE.md`.

- **Push the branch.** A five-phase refactor on an unpushed branch means one bad day
  loses both, and Phase 0 clones the repo — which carries only what was pushed.
- **One macro-line reader.** Prism's header read path and its own write path disagree
  about what a line's arguments are, because the reader is hand-rolled once per site.
  Latent today, and pinned by
  `tests/test_macroline.py::test_readers_disagree_about_comments`, which flips to "all
  three agree" when this is done. Before Phase 0: `wiring/` is A's code, and A carves
  cleaner with one reader in it than three.
- **`blobsizes.PRIMARY_HEADER_GROWTH` is 8; the macro emits 9.** `mapfit`
  under-reserves the shared header section by a byte per map added. One line, one test.

## Ground rules

**`CLAUDE.md` is the standard**, and it is authoritative. Read it carefully and apply
the rules during this refactoring. **The job is done only once every single file in 
this repo comply with all the rules.**

Two rules carry more weight in this refactor than anywhere else, and are worth
re-reading before each phase rather than re-typing: **naming files and folders**
(the whole exercise is deciding what a file is for and calling it that) and
**comments** (Phase 2 deletes three comment walls, and the narrow exception —
never delete a measurement, route it somewhere — is what `refactor-STATE.md` is).

## The four products

The dependency graph already permits this split — measured, not assumed:

| product | contents | today's blocker |
|---|---|---|
| **A · pret/RGBDS library** | `shared` + `wiring` + `usage` + `sym_lookup` | none — zero dependency on any hack or the IDE |
| **B · adapter contract** | `Hack`, its capability protocols, the domain vocabulary | does not exist; split across `hacks/seam.py` and `studio/` |
| **C · the IDE** | `studio` | depends on B, which is inside it |
| **D · prism** | `hacks/prism` + the CLI packages Phase −1 assigned it | fused to C |

**Phase −1 assigned every CLI; the calls are in `refactor-STATE.md`** — as is the
lesson behind them: an import grep proves an edge exists, not that it is load-bearing,
and a path literal measures hack-specificity better. **B ships separately**, decided
there too — adapters need B and must never reach C to get it.

### Every prism-specific CLI faces the same three-way choice

"This CLI is prism-specific" does not say where it goes. Each lands in exactly one:
**(a) part of the prism adapter**, only if the tool *is* adapter work — rare, since
libraries that ship CLIs are usually two things wearing one name; **(b) refactored to
cross the seam**, when every hack has the question and only the *data* is prism's —
the option that grows the product, and real work; **(c) its own repo depending on the
prism adapter**, when the question is Prism's alone (bank placement, Prism's catalog)
and making it generic would only weigh down A or C.

**"Product D" is therefore not one bucket** — it is (a) + (c), with (b) draining into
A over time.

## The naming census

**The inventory is in `refactor-STATE.md`** — which file wears which wrong name, the
duplicate-class counts, what is already clean. The argument belongs here:

**A bad name costs twice.** `studio/panels.py` is the headline: twenty of the map's
nouns (`Npc`, `Warp`, `Trainer`, …) filed under a UI location — and that same name is
why every adapter imports the IDE. Phase 2 fixes both at once, which is what makes it
the keystone rather than a tidy-up. Two more files are named for an architecture
instead of their contents (`seam.py` defines `Hack`; `model.py` holds the edit cycle's
records and belongs with `flow.py`, which runs it), and `content.py` is generic enough
to have hidden a bug: `Connect` sits in `actions.py` while `Disconnect` sits in
`content.py`, though the split is meant to be map-to-map versus in-map.

**`wiring/` is not exempt**, though earlier drafts said so — neither a GBC/pret term
nor an architecture noun, and the cost shows: `WiringError` is defined three times in
three unrelated files, because a meaningless folder name attaches to anything. Its
contents are one thing, **editing pret assembly source**. Rename on the way into A.

**Enforce it in two layers, and neither is by name.** A "no duplicate class names"
rule cannot tell the three duplicate kinds apart — one-per-adapter implementations,
genuine collisions, view-versus-parse pairs — so it fires on the design working and
gets switched off in a week. What works is a hook matching on what code *does*:
Phase −1 found two the same day (`Placement` in `mapfit/packing.py` versus
`wiring/placement.py` share a name *and* a job; `_bit_reverse` and `_flip_bits` share
a body and nothing else). Two constraints keep it alive — **never compare across
adapters**, since the three `Reader`s are near-identical on purpose and would rank
first, and **advisory, never blocking**, since a gate on a fuzzy signal gets disabled
while a report gets read. The import-direction rule from the goal is the one true
gate: mechanical, no false positives.

## Phases

### Phase −1 — The product survey · **done, answers in `refactor-STATE.md`**
Per module: **is this a prism fact or a Gen-2/pret fact?** It produced a product
assignment for every surveyed module, a three-way call per CLI, the B-vs-C
decision, three measurements that each moved an answer, two defects now listed
under "Before anything", and one question handed to Phase 5.

### Phase 0 — Split the git history, while the tree is still untouched
Before any file moves. Clone once per product and `git filter-repo --path <dir>` to
carve history by folder, so each product keeps the "why" behind its code instead of
starting at one squashed commit. Two corrections to the naive version:

**Not now-or-never:** `filter-repo` takes multiple `--path` arguments, so a folder
renamed later still carves with full history by naming both paths — losing history
takes forgetting, not moving. **Only A can split now:** B, C and D are fused by the
`hacks → studio` cycle, and splitting today produces two repos that import each other.

So carve A now — zero dependencies, and the carve doubles as proof the tooling works
— then B/C/D after **Phase 2**, whose acceptance test *is* the cycle being gone.
Record every path rename so the later filter can name both.

### Phase 1 — Calibration: the six CLI packages
`metatiles`, `mapfit`, `usage`, `map_new`, `map_show`, `map_inspect`. Split
parse / analyse / render / CLI out of each `__init__.py`, leaving the package's
public surface *as* its `__init__`; `metatiles` and `mapfit` already carry `# ---`
banners on the seams.

**Why first:** it depends on nothing, all six are test-covered, and it is where we
settle what "done to the standard" means where a mistake costs nothing. **Not
targets:** `mapview`, `gfx_view`, `sym_lookup` are already at ~150 lines.

### Phase 2 — The keystone: give `Hack` and its vocabulary one home
**Plan: `refactor-phase-2-PLAN.md`** — what the package is, and what is not.

The phase that makes the goal true: the census's tier 1 and the `hacks → studio`
cycle in one move. `hacks/seam.py` becomes `hack.py` in a package neither the IDE nor
the adapters own; the entities in `studio/panels.py` and `studio/model.py` and the
`Action`/`Field` vocabulary in `studio/actions.py` move there, split by domain into
files named for what they define. The comment walls die here — same three files.

**Acceptance test, falsifiable:** grep `hacks/` for any import of the IDE package;
empty passes. The check `seam.py`'s docstring already invites, pointed at the file
where it would have caught something.

### Phase 3 — Split the remaining products
Mechanical once Phase 2 lands: B is its package, C and D fall out, Phase 0's carve runs again.

### Phase 4 — The god objects
Deliberately *after* the keystone, because `Session`'s seams move once the
vocabulary leaves `studio/`. Three targets, sized in `refactor-STATE.md`.

- **`Session`** — its methods group onto the seam's own six capabilities, a parallel
  that becomes structural rather than coincidental once the contract package exists.
- **`DevServer`** — ten editors welded onto a server, ~3/4 of the file. CLAUDE.md's
  "cluster of related responsibilities → a folder that names the domain", almost
  verbatim. **Mandatory prerequisite:** a characterization test driving the editors
  through scripted stdin, priced as its own step — without it this is a rewrite with
  no oracle.
- **`Studio`** — mostly not a target; Textual concentrates handlers by design. Only
  the `action_*` mixin, and only if Phase 1 leaves it obviously wanting.

### Phase 5 — The maplint survey, then the family port
Seven rule modules import `hacks.prism`, and decoupling them *is* the family-rule
port. Gated on a survey — for each rule, Gen-2 fact or prism fact? Same question as
Phase −1, one layer up. Phase −1 confirmed the seven, carved two neutral modules out
ahead of the port, and left one module it declined to answer without evidence.
