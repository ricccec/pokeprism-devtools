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

## Ground rules

**`CLAUDE.md` is the standard**, and it is authoritative. Read it carefully and apply
the rules during this refactoring. **The job is done only once every single file in 
this repo comply with all the rules.**

**A move must never be the thing that fixes a bug.** Find a defect mid-phase and it
is fixed on the tree as it stands, with its own test, before the file moves —
otherwise no one can ever say again whether the move was behaviour-neutral, and every
phase's "nothing changed" claim is worth less.

**Write down what your oracle proves *and* what your phase claims — as two
sentences.** Where they differ is the phase's real risk, and it is invisible from
inside the phase. Phase 3 built a test proving the *import graph* is layered and
reported it as *the products are separable*; a hardcoded `"pokeprism.gbc"` in
product A satisfies the first and destroys the second, and it survived the whole
phase until a human opened one file at random (2026-08-05). Two rules follow.
**A scan clears an axis, not a codebase** — say which axis. And when a finding
names a better instrument, use it: Phase −1 measured that *a path literal measures
hack-specificity better than an import grep*, and Phase 3 read that finding and
built the weaker check anyway.

Two rules carry more weight in this refactor than anywhere else, and are worth
re-reading before each phase rather than re-typing: **naming files and folders**
(the whole exercise is deciding what a file is for and calling it that) and
**comments** (Phase 2 deletes three comment walls, and the narrow exception —
never delete a measurement, route it somewhere — is what `refactor-STATE.md` is).

## The four products

The dependency graph already permits this split — measured, not assumed:

| product | contents | today's blocker |
|---|---|---|
| **A · pret/RGBDS library** | `shared` + `asmedit` + `usage` + `sym_lookup` | none — zero dependency on any hack or the IDE |
| **B · adapter contract** | `Hack`, its capability protocols, the domain vocabulary | does not exist; split across `hacks/seam.py` and `studio/` |
| **C · the IDE** | `studio` + `hacks/vanilla` + `hacks/polished` | depends on B, which is inside it |
| **D · prism** | `hacks/prism` + the CLI packages Phase −1 assigned it | fused to C |

**The family adapters ship with C** — decided 2026-08-04 on the measurement that
settles it: `mount()` is called from two studio modules and tests, nowhere else, so
vanilla and polished are reached only through it. Prism is D because prism's own
CLIs import it directly.

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

**A bad name costs twice.** `studio/panels.py` was the headline: the map's nouns
(`Npc`, `Warp`, `Trainer`, …) filed under a UI location — and that same name is why
every adapter imported the IDE. Phase 2 fixed both at once, which is what made it the
keystone rather than a tidy-up; what it found is that the nouns were only half the
file and `studio/actions.py` was the larger half of the cycle. `model.py` still holds
the edit cycle's records and belongs with `flow.py`, which runs it, and `content.py`
is generic enough
to have hidden a bug: `Connect` sits in `actions.py` while `Disconnect` sits in
`content.py`, though the split is meant to be map-to-map versus in-map.

**`wiring/` was not exempt**, though earlier drafts said so — neither a GBC/pret term
nor an architecture noun, and a meaningless folder name attaches to anything:
`WiringError` ended up defined three times in three unrelated files. Its contents are
one thing, **editing pret assembly source**, and it is `asmedit/` since Phase 3. The
three `WiringError`s stayed — two name a different sense of the word and one is
`mapfit`'s own, so their being three was the evidence, not the target.

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
decision, three measurements that each moved an answer, two defects since fixed on
the untouched tree, and one question handed to Phase 5.

### Phase 0 — Split the git history · **tooling proven; every carve is 3b's**
Clone once per product and `git filter-repo --path <dir>`, so each product keeps the
"why" behind its code instead of starting at one squashed commit. The correction to
the naive version: **not now-or-never** — `filter-repo` takes multiple `--path`
arguments, so a folder renamed later still carves whole by naming both spellings.
Losing history takes forgetting, not moving.

A was carved first, having zero dependencies, and that carve is a **rehearsal, not a
deliverable**: it takes no commits at all, and until 3b **this repo is every
product's only editable copy**. A carved repo is named `-history-<date>` so its
status is legible from the folder name alone. Phase 3 closed the last cross-product
edge, so nothing now blocks the real carve but the order it runs in.

### Phase 1 — Calibration: the six CLI packages · **done; rules in its PLAN**
`metatiles`, `mapfit`, `usage`, `map_new`, `map_show`, `map_inspect`. Split
parse / analyse / render / CLI out of each `__init__.py`, leaving the package's
public surface *as* its `__init__`.

**Why first:** it depends on nothing, and it settles what "done to the standard"
means where a mistake costs nothing. That settlement is **R1–R5** in
`refactor-phase-1-PLAN.md`, and Phases 2–5 inherit it. Two premises were wrong:
the six were *not* all test-covered, and no test could certify these moves at all
— so a move is proved *textually*, by digesting content. **Not targets:**
`mapview`, `gfx_view`, `sym_lookup`, already ~150 lines.

### Phase 1b — Pay what Phase 1 could not
R5 forbids an edit riding along with a move, so every CLAUDE.md violation inside a
moved body survived Phase 1 intact: eleven over-long functions, a 357-line file,
four bare-verb names. **Test-first — eight of the eleven are executed by nothing**,
and shortening those is a rewrite with no oracle, the same objection Phase 4 makes
below about `DevServer`.

### Phase 2 — The keystone: give `Hack` and its vocabulary one home · **done**
**Plan: `refactor-phase-2-PLAN.md`** — what the package is, and what is not.

The phase that makes the goal true: the census's tier 1 and the `hacks → studio`
cycle. `contract/` is a package neither the IDE nor the adapters own; the map
entities, `Hack` and its six protocols, and the `Action`/`Field` vocabulary all live
there, split by domain into files named for what they define. Its acceptance test,
`tests/test_contract.py`, asserts the arrow statically *and* at runtime.

### Phase 3 — Make the products separable · **done; `refactor-phase-3-PLAN.md`**
Not mechanical: five cross-product edges survived Phase 2, so the folders were not
the products yet. All five are closed and `tests/test_products.py` asserts it.

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

### Phase 3b — Carve them · **last, after 4 and 5** — moved 2026-08-05
Four ledgers, four repos, the import rewrite, the test split, the packaging files.
Name stays `3b` for the reason 1b keeps its number: four documents cross-reference
these. "After 3, never before" was a floor read as a position; the floor holds and
the position moved, because Phase 3's oracle cannot run in a carved repo, Phase 5's
family port is a D→C migration, and Phase 0 measured that an early carve buys a
rehearsal and a copy that drifts — `refactor-phase-3-STATE.md` → "Why the carve
goes last". **Only an external consumer of A or B outranks that**, and there is
none yet.
