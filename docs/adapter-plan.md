# One frontend, many romhacks — a sketch, not a commitment

Nothing here is scheduled. This is written down so that the decisions we take
while finishing `prism-studio` don't quietly foreclose it, and so that the
argument doesn't have to be reconstructed from memory the day it comes up.

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

   The Python UI then becomes hack-agnostic inside this repo, with no new process
   and no protocol, and the day the protocol is written it is a serialization of
   `Session` rather than an act of invention.
2. **Keep every action schema-driven.** No form in P3–P4 may hardcode a field
   that isn't declared in `FIELDS`. The moment one does, the frontend knows what
   an NPC is, and the boundary is gone.
3. **Make the studio an optional extra** (`pip install pokeprism-devtools[studio]`).
   Three lines, and it gets the whole benefit the repo split was going to buy:
   people who want the tools don't pay for the GUI.

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
