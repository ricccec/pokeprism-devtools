# Phase 2 — the contract package · plan

The keystone phase's own plan. `refactor-plan.md` carries the sketch and the running
order; this file carries what the package *is*, which is the part an implementer
needs and the plan has no room for. Findings go to `refactor-phase-2-STATE.md`, one
line each also in `refactor-STATE.md`.

**Status: not started.** This is the spec as argued, not as built. Before starting,
run the three steps in `refactor-plan.md` → "Starting a session, or starting a
phase", and rewrite what follows from what you verify.

## What this package actually is

**One sentence:** it is the *noun list and the question list* that an IDE and an
adapter must agree on before either can be written — and nothing else.

**What is inside.** Two kinds of thing, both pure data:

1. **The entities a Gen-2 map is made of** — `Npc`, `Trainer`, `Prop`,
   `Signpost`, `Warp`, `Trigger`, `Link`, `WildMon`, `Roof`, `Attributes`,
   `Blocks`, `Sketch`, and the table/row/reference types that carry them. Today
   these are the twenty classes in `studio/panels.py`.
2. **`Hack` and its six capability protocols** — `Reads`, `Writes`, `Lints`,
   `Plays`, `Measures`, `Sketches`. The questions an adapter may be asked. Today
   this is `hacks/seam.py`.

**What is *not* inside:** any parsing, any file I/O, any ROM knowledge, any
widgets. It reads no bytes and draws no pixels. Measured, the current
`panels.py` already meets that bar — its only import is `shared.coords`.

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

**Naming.** By the folder rule an architecture-adjacent name qualifies:
`contract/`, `adapter/`, `api/`. Leaning `contract/` — it answers "where do I look
to find what I owe?" Still open.
