# One frontend, many romhacks — a sketch, not a commitment

Almost nothing here is scheduled. This is written down so that the decisions we
take while finishing `prism-studio` don't quietly foreclose it, and so that the
argument doesn't have to be reconstructed from memory the day it comes up.

**One piece is now being built** — see "The mount, made pluggable". Not because
the protocol argument was settled (it isn't; "Why not now" still holds), but
because `mount()` had accumulated enough hack-specific construction that
splitting it raised the registry question early, and the answer turned out to
cost about a day. The frontend split remains a sketch. The *registry* is real.

## The idea

Gen-2 romhacks — vanilla GSC, polished-crystal, coral, prism — share a domain
model. Whoever hacks any of them is building maps, placing NPCs and trainers,
wiring warps and connections, writing dialogue, defining wild encounters. What
they *don't* share is the syntax: the macros, their argument order, where the
headers live, how event flags are declared, how a trainer party is spelled.

So split the work in two:

- a **user-facing layer** that knows about maps and NPCs and dialogue, and knows
  nothing about `.asm` — it presents the game's content and accepts edits;
- a **codebase-facing layer**, one per hack, that translates edits into source
  mutations and translates source back into structures the frontend can render.

`pokeprism-devtools` then stops being "the tools" and becomes *prism's adapter*.
Another hack writes its own adapter — in any language — and plugs into the same
frontend. A new hack costs one adapter, not one editor.

This is LSP, for romhacks. That comparison is the best argument for the shape and
also the loudest warning attached to it; see "Why not now".

## What the boundary actually is

We have most of it already, by accident of having designed the studio properly.

**`studio/actions.py` is the write half.** Each action declares `FIELDS` and
implements `run(root) -> Result`; the TUI builds its forms and its autocomplete
out of the declaration and knows nothing about NPCs. That is exactly a plugin
contract. A hack whose NPCs carry a palette and a tracking flag declares two more
fields, and the frontend renders them without being taught what they mean.

**`studio/session.py` is the read half and the transaction half.** `maps`,
`lint`, `diagnostics`, `preview`, `apply`, `undo` — already headless, already in
plain data, already the thing the TUI is a view over.

Two consequences worth stating plainly:

- **The version handshake you'd otherwise need is a symptom, not a feature.** If
  the adapter *declares its capabilities* — here are the actions I support, here
  are their fields — then the frontend shows what exists and nothing else. A hack
  with no VWF simply doesn't declare the text-width rules, and the text preview
  doesn't appear. That is strictly better than pinning versions and refusing to
  launch, and it falls straight out of the schema-driven design.
- **The read path generalizes; the write path is thinner than it looks.** "Here
  is a map: dimensions, blocks, resolved swatches, objects with y/x/sprite/type,
  warps, signposts, connections, wild encounters, diagnostics" is genuinely
  hack-agnostic — it is essentially `MapView` plus `panels.Table` today. The write
  path is where hacks diverge, and worse, so do the *rules*: prism's VWF text lint
  and its emergent walking-sprite limit are not concepts vanilla GSC has.

## The protocol is a persistent process, not a CLI

The tempting version of this is "the tools are CLIs, anything can spawn a
process." It does not survive contact with the numbers.

A cold `LintContext` is **1.7 seconds**, and it dies with the process. The whole
of P0 is a long-lived cache with incremental invalidation, targeting a re-lint
under 100 ms so diagnostics land before you've let go of the key. Spawn-per-edit
throws that away and buys 1.7 s per keystroke.

The `prism-*` scripts are also not an API. They are argparse wrappers that print
for humans; a couple have a JSON mode, none was designed to be driven. The asset
is the *library*, not the command line.

So the adapter is a **long-lived process speaking JSON-RPC over stdio** — a
mechanical serialization of `Session`'s methods — and the frontend is the only
thing that gets written in TS.

## Why not now

The failure mode of a protocol designed against one implementation is that you
haven't designed a protocol, you've serialized prism's data model and given it a
grander name. Every place the abstraction would have to bend for
polished-crystal is a place we currently cannot see. LSP works because it was
extracted *after* several editors and several language servers existed — and it
is still famously leaky, with every server carrying extensions.

We have one adapter and zero other hacks in hand. The write path — the half that
doesn't obviously generalize — is exactly what P3 is about to exercise for the
first time. Freezing a protocol before P3 means guessing at the part we're about
to learn.

There is also, today, one user.

## What it would cost

To the direct question — *how much Python gets rewritten in TS?* — **none.** The
Python is the adapter; that is the entire point of the split. What gets written
is new:

| | |
|---|---|
| Frontend | `app.py` + `grid.py` + `panels.py` ≈ 530 lines of Python → perhaps 2–3k lines of TS, CSS, build config |
| Protocol | JSON-RPC schema + serializers on the Python side, client on the TS side, capability negotiation |
| Upkeep | a second repo, a second test suite, a second CI, and a wire format that must stay in step with two codebases |

Real, bounded, and not a rewrite. But it is a *project*, not a refactor, and it
buys nothing for prism that the TUI won't already do.

## What we do instead, now, so this stays open

Cheap, and worth doing on its own merits:

1. **Enforce the seam.** `studio/app.py` today imports `blocksrc`, `eventheader`
   and `wilddata` inside `_read()` — the view opens the repo and parses it. That
   is the coupling that would hurt. Push `_read()` down into
   `Session.load(label) -> MapData` and hold one rule, stated so it's checkable:
   *the view layer reads no files.*

   Note what the rule deliberately permits: the view may still call the pure
   drawing helpers — `coords.glyph_cells`, `coords.hex_color`,
   `swatches.tile_color` — which take plain data and return colours. Those are
   the *renderer*, and in a split world they'd move to the frontend alongside
   `grid.py`, not to the adapter. The line is not "which package"; it is who
   opens the source tree.

   The leak census in `family-write-plan.md` flags `studio/grid.py` importing
   `hacks.prism.swatches`, which is not a contradiction of this rule but of
   where the function is *filed*: `tile_color` takes blocks and swatches as
   plain data and opens nothing, so it is hack-agnostic renderer code living in
   a hack's package. It belongs in `shared/`. The rule above stands unchanged.

   The Python UI then becomes hack-agnostic inside this repo, with no new process
   and no protocol, and the day the protocol is written it is a serialization of
   `Session` rather than an act of invention.
2. **Keep every action schema-driven.** No form in P3–P4 may hardcode a field
   that isn't declared in `FIELDS`. The moment one does, the frontend knows what
   an NPC is, and the boundary is gone.
3. **Make the studio an optional extra** (`pip install pokeprism-devtools[studio]`).
   Three lines, and it gets the whole benefit the repo split was going to buy:
   people who want the tools don't pay for the GUI.

## The mount, made pluggable

This is item 1 continued, and the first thing above that is actually scheduled.

**What was wrong.** `hacks/mount.py` grew into two jobs and then a third. It
declares the contract (four protocols, `Hack`, `Refused`), it recognises which
tree it is looking at, *and* it constructs each adapter — the polished branch
alone imports six symbols from vanilla and hand-wires them into vanilla's
`Writer` under a twelve-line comment about how the fork differs. That comment is
polished's knowledge, sitting in the one file that is supposed to know only
names. The rule was "only the mount knows hack names"; the file had quietly
started knowing hack *behaviour*.

**The shape.**

- `hacks/seam.py` — the four protocols, `Hack`, `Refused`. The contract, and
  provably free of hack names: a `grep` for one returning nothing is the rule
  made checkable rather than merely stated. `tests/test_seam.py` already tests
  exactly this half and nothing else, which is the responsibility announcing
  itself a phase before the split.
- `hacks/mount.py` — discovery, the claim loop, `UnknownTree`. Nothing else.
- `hacks/<name>/claim.py` — one per hack: *do I recognise this tree, and if so,
  build me*.

**Every hack recognises itself.** There is no family concept and no shared
recogniser. An earlier draft of this section proposed a `hacks/family.py` owning
the pokecrystal anchor probe, on the grounds that vanilla and polished are
discriminated by the same read. That was wrong, and wrong in a way worth
recording: it invents a third category between "a hack" and "hack-agnostic",
and a third-party adapter shipped by someone else can never join it. Vanilla
asks whether map files here end with `_MapEvents`; polished asks whether they
open with `_MapScriptHeader`; neither needs to know the other exists to answer.

Where a hack genuinely builds on another — polished forks vanilla, and already
imports its parsers and its `Writer` — **the dependency is declared in the
dependent hack**, never hoisted into a shared middle. That relation is real and
the code should state it; what it must not do is become structure that only
in-tree hacks can use. What lands in `shared/` is the plumbing with no opinion:
*read the first map file listed in `data/maps/maps.asm`*. No anchor, no name.

**Partial recognition belongs to the hack that partially recognised.** A
`claims()` returns the built `Hack`, or nothing, or a near-miss with a reason.
The near-miss is what keeps `UnknownTree` actionable — "unknown" is not, and a
loop over silent `None`s can say nothing better. A pokecrystal checkout with an
unfamiliar anchor now yields both near-misses side by side rather than one
committee-authored sentence, which is more useful *and* needs no shared concept
to produce.

**Registration is entry points.** Not a hard-coded tuple, and not `iter_modules`
over `hacks/` either — the goal is that a hack developer packages an adapter and
a user `pip install`s it, and a directory scan can only ever find what already
ships in this repo. `pyproject.toml` already uses the mechanism for
`[project.scripts]`:

```toml
[project.entry-points."pokeprism_devtools.hacks"]
prism    = "pokeprism_devtools.hacks.prism.claim"
```

The three in-tree hacks register through the identical path a third party would.
That is the only way we learn whether the plugin seam works before somebody else
is depending on it. A `--hack-path` override covers the case entry points serve
badly: an adapter author iterating on their own tree who doesn't want to
reinstall between runs.

**Claim modules stay thin.** Discovery imports every registered hack to ask it,
where the old branchy `mount()` imported exactly one. With three hacks that is
noise; with thirty installed adapters it is the difference between importing
thirty parsers and importing thirty predicates. So `claim.py` imports no
`Reader`, no `Writer`, no linter at module level — the adapter is pulled in
inside the branch that actually claims. (The old worry that discovery costs a
bare `--version` was overstated: `iter_modules` and entry-point enumeration
don't import, and `--version` never calls `mount()`.)

**Ambiguity is an error, not a race.** Collect every claim rather than taking
the first. Two hacks claiming one tree is a bug in one of them, and "coral and
prism both claim this repo, here are both" beats whichever happened to sort
first winning silently. Sorting by name buys stable messages, not correctness.

**Third-party code now runs inside the mount.** `Refused` and `UnknownTree` stop
being the only failure modes the moment an adapter we didn't write can raise
anything at all. Each `claims()` is isolated so one broken adapter degrades to
"this adapter failed to answer, here's why" instead of taking discovery down
with it. This is new surface the current design doesn't have, and it belongs in
the change rather than after the first crash.

**Two costs, accepted.** Vanilla and polished each read `maps.asm` and the first
map file independently — two small reads where there was one, and no probe cache
until something measures slow. And a tree that no adapter claims now costs one
import per installed hack before it fails.

## The experiment that would actually settle it

Point `blocksrc` and `eventheader` at a **pokecrystal** checkout and see what
breaks. An afternoon's work, and it is the only thing that will tell us whether
the shared domain model is real or whether it's prism's model wearing a hat.
Everything above is a guess until someone runs it.

**Update — the map-format half was run** (`../pokecrystal`, `../polishedcrystal`;
see `polished-crystal-feasibility.md`). The domain model *is* real, but the second
question got the more interesting answer: it is prism's model wearing a hat, and
we can now measure the hat. On the assumptions disguised as neutral vocabulary —
object identity, event count, coordinate order — **vanilla agrees with
polished-crystal and disagrees with prism.** `object_const_def` (named object
identity) appears in 348 of vanilla's maps and 0 of prism's; both other hacks
self-count their event lists where prism writes `db N`; both order coordinates
`(x, y)` where prism is `(y, x)`. The port did not generalize a gen-2 model — it
followed the one hack least like the rest. The correction that falls out: calibrate
the seam to **vanilla**, the median every other hack forks, not to prism.

## The fork in the road, stated honestly

If the goal is *the authoring loop for prism* — author a `.blk`, add the map,
place an NPC, write its dialogue, boot into it — finish the TUI. It is three
phases away.

If the goal is *a general gen-2 map editor*, with mouse placement and a real tile
render, that is a different project with a different budget, and no amount of
seam-keeping in Python gets you there: a terminal cannot do it.

Finish the loop first either way. It is what teaches us what the protocol should
say.
