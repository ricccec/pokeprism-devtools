# The rest of the write story — what Phase 4 refused, planned

`polished-crystal-feasibility.md` ran Phases 0–4 and closed. What it left is not
an unfinished phase but a recorded residue: the three writes a family tree still
refuses in sentences. This doc is the plan for those sentences — for turning
each refusal into either a write that crosses the seam or an absence the tree
genuinely has. It inherits the two rules the branch was built on: hack
differences live in adapters and cross the seam as **declared data** — only
`hacks/mount.py` knows a hack's name — and mechanics that a CLI could someday
wrap live in `wiring/` (primitives in, `Change` out), decoupled from the studio.

Where we stand: `Hack.writes` is the write adapter or `None`; deletion crosses
for all three trees; the family writer (`hacks/vanilla/write.py`) already has
`add_entry` / `replace_entry` with named identity, round-tripped to the byte on
all 388 + 607 real maps — the *mechanics* of adding and editing exist and are
tested, and what refuses today is the layer above them. The refusals, and their
phases:

| Refusal today | Why it refuses | Phase |
|---|---|---|
| ~~deleting a family warp~~ | **done** — crosses via a declared warp grammar | ~~5~~ |
| family `a` / `e` (adders, editors) | form machinery is still prism's | **6** |
| family `a` on the map list (new map) | scaffold + bank placement unmodelled | **7** |

Ordered smallest-risk-first, as before: 5 is a port of machinery that already
exists for prism, 6 is the big lift, 7 stands on 6.

**Phase 5 is done, and the survey it opened with is why it was worth doing that
way.** Three of the assumptions the plan below inherited from
`wiring/warpdel`'s docstring turned out to be false, and each one would have
been a silent corruption:

* **"Two macros are the whole surface."** They are prism's whole surface, not
  the family's. The family also counts warps in `elevfloor FLOOR, n, MAP` (14
  rows in vanilla, 17 in polished), and polished adds `digmod n, MAP`. Missing
  `elevfloor` would have left every elevator in both trees quietly off by one.
* **"`data/` does not mention warps."** True of prism and vanilla. Polished
  keeps hidden-grotto return warps in `data/events/hidden_grottoes/grottoes.asm`
  as bare numbers whose map is named nowhere on the line — only inferable from
  the naming convention on a constant in another file. That is not a reference
  a scan can follow, so it is declared as a `BlindTable` and every polished
  deletion warns, naming it. A guess would have been worse than a warning.
* **"`dummy_warp` means group 0, map 0, *nowhere*."** It does not, in either
  dialect. `CopyWarpData` (pokecrystal `home/map.asm:331`, prism
  `home/map.asm:172` — the same code) sees `warp_to == -1` and takes the warp
  number, the group **and** the map from `wBackupWarpNumber`; prism's trailing
  `0, 0` is never read. A dead door lands on stale state, not nowhere, and
  neither dialect has an encoding for nowhere at all. Prism's spelling is kept
  because it is what ships, and its docstring now says what it actually does.

The family's dead door therefore had to be *found*, exactly as this plan
insisted — and it exists: both trees `DEF GROUP_NONE` and `DEF MAP_NONE` to 0,
so `warp_event x, y, NONE, -1` assembles to the very bytes `dummy_warp` does.
Verified with `rgbasm` rather than by reading macros: `07 04 ff 00 00`. Had we
concluded "no `dummy_warp` macro, therefore no dead door", family warp deletion
would have refused on **all 8** of AzaleaTown's warps — gen-2 warps are paired,
so every town warp is some building's exit destination — and the phase would
have shipped a capability nobody could use.

What crossed: `wiring/warpdel` keeps the rule and the repo scan and knows no
hack's name; the grammar (macros, seats, dead-door spelling, blind tables) is a
`WarpGrammar` record each adapter declares, with prism's now the first record
rather than the hard-coded case. `as_int` moved to `shared/` — reading an
rgbasm number is rgbasm's business, not prism's — which was the last thing
`wiring/` imported a hack for. Tested on fixtures for the renumber / dead-door /
refuse triad, and on both real trees: delete a warp, and every line the deletion
did not claim is byte-identical, across 2,463 and 2,790 `.asm` files.

- **Phase 5 — family warp deletion. Done**, in the three moves it planned —
  survey, generalization, writer — with the survey's findings recorded above,
  because it found more than it expected to. The renumber rule was
  dialect-free as predicted (`n > k → n−1`; `n == k` → the door goes nowhere,
  told by name; `n < k` untouched; unreadable → refuse, naming the line); the
  grammar was not, and is now data. What did *not* generalize is the
  refusal for a macro with no dead form: `warpmod`, `elevfloor` and `digmod`
  aimed at the deleted warp still refuse, naming the lines, because there is
  no dummy form of any of them. Connection deletion was not this phase and is
  not: the neighbour's-side refusal stands.

- **Phase 6 — family adders and editors.** The mechanics are done
  (`EventBlock.add_entry` / `replace_entry`); what is missing is everything
  between a keypress and them: fields, choices, prefill. Four moves.

  **The carve is done.** `studio/actions.py` now imports no adapter and no
  `wiring/`: `Connect` and `AddWarp` moved to `hacks/prism/actions.py` (both
  ride prism-only wiring), and `Action.obj()` moved down to
  `content._Placed`, since a `scaffold.Object` *is* prism's `person_event`
  and every caller already descended from that class. The base keeps the
  field vocabulary, `Field`/`Action`/`Result`/`ActionError`, and nothing
  else. The rule, stated once: **adapters import the base; the base imports
  no adapter** — now guarded by a static test over the module's own import
  lines rather than by intent.

  One correction to what this plan assumed: the six names it called "prism
  constant caches" (`CLASSES`, `FACINGS`, …) are not caches and are not
  prism's. They are field *kind* tags — `choices=ITEMS` says what sort of
  thing a box wants — and the answers were always the write adapter's
  `choices()` to give. So they stayed in the base, which is what let the
  family declare its own sets against the same vocabulary. Naming a kind
  commits nobody to having one: a tree that cannot enumerate it answers `[]`
  and the field degrades to free text.

  Deferred, and named rather than quietly left: the *package* chain
  `studio/__init__` → `session` → `maplint` → prism still loads prism for
  any family tree. It predates this phase, it is a startup cost rather than
  a correctness bug (nothing branches on a hack name), and unpicking it
  means making `maplint`'s module-level `ALL_RULES` lazy — a change to the
  linter's shape, not to the seam.

  **Family choices are done, and the survey earned its keep a fourth time.**
  `Writer.choices` now answers six kinds off the tree's own
  `constants/*.asm`, declared as a `ConstSet` record per kind exactly the way
  `WarpGrammar` is declared — `read_set` in `shared/` knows the rgbasm
  spellings, the adapter knows which file and which prefix, and polished
  overrides the one entry it forks. `names`/`with_prefix` moved from
  `hacks/prism/consts.py` to `shared/constants.py` for the reason `as_int`
  did in Phase 5: binding a name at file scope is rgbasm's business.

  Three things a plausible reading would have got wrong, each caught by
  comparing the offered set against what 995 real map files actually write:

  * **The prefix was wrong for both trees.** Both define a `PAL_OW_*` set and
    neither ever puts one on an `object_event` — all 1,466 vanilla and 2,161
    polished object lines name a `PAL_NPC_*`. The palette field would have
    offered a complete, plausible list of constants the maps never use.
  * **Polished writes its palettes through a macro.** `ow_npc_pal_const RED`
    pastes both `PAL_OW_RED` and `PAL_NPC_RED` on at assembly time, so
    neither name is in the source; scanning for `const PAL_NPC_` finds only
    `PAL_NPC_DEFAULT`. A near-empty list is indistinguishable from "this
    field is free text", so the box would have gone quiet on one tree of
    three. Hence `ConstSet.macro`, and hence the union with the longhand
    members rather than a replacement of them.
  * **`PURGE` un-defines two of them.** Polished's file ends
    `PURGE PAL_OW_YELLOW, PAL_OW_WHITE`, so those symbols do not survive the
    file that appears to define them — and offering a constant the assembler
    will reject is the one failure `studio/offers.py` calls worse than
    offering no list at all.

  Also: `names()` was missing modern `DEF NAME EQU 0` entirely, which is how
  polished spells file-scope bindings. `follows` and `sprite_hint` stay empty
  and the emptiness is argued, not stubbed — prism's answers are *counted*
  off trainer tables and measured by `maplint`, and the family has neither, so
  half an answer that reads as authoritative is worse than none.

  **Then the actions**: one Add and one Edit per kind, riding the existing
  splice methods, declaring their own `Field`s. Named identity is the part
  that thinks: on a fully-named list the form asks for the `const` name
  (validated unique before preview); on a partially-named list it appends
  unnamed — the writer already refuses to do otherwise, so the form offers
  what the writer will accept. Kind shapes follow the read side's
  classification (trainer / itemball / fruittree / hiddenitem write the line
  shapes `hacks/vanilla/read.py` walks to recognize); polished's 12-arg
  `object_event` with type-shifted trailing args is the polished writer's
  override, stated as the fork it is, exactly like the head anchor.

  **Then prefill for `e`**: parsed `Entry` back into form values, with the
  (x, y) ↔ `Tile(y, x)` turn happening at the seam and nowhere else.

  Not claimed by this phase, on purpose: `EditMap` (the attributes tab),
  rewording (family `text` vs prism's VWF `ctxt` is a text-wiring project of
  its own), and connection *adding* (`wiring/connections` is two-sided and
  deserves its own look). Each keeps its sentence.

- **Phase 7 — a new map, and where it may be put.** The last capability, and
  the reason it is last: `NewMap` is a scaffold across many files *plus* the
  one question the three trees answer three ways — **where does map data
  go?** Prism answers with explicit banks (`romx.link`; the existing form
  already lets you pin `$7C` or leave it floating — see `studio/newmap.py`'s
  argued refusal to guess). The multi-hack finding on record says vanilla is
  a bucket choice and polished floats — but polished ships a `layout.link`
  too, so the survey re-measures rather than trusts. The model: placement is
  a **declared answer from the write adapter** — the choices it offers
  (banks / buckets / nothing) become a form field exactly when they exist,
  a capability read, never a hack name. The scaffold itself is the family
  new-map checklist (`data/maps/maps.asm`, `blocks.asm`'s INCBIN, the
  constants, the attributes — surveyed per tree, the way vanilla's read
  adapter was), and `resize` follows it (`wiring/mapresize`
  generalized the way Phase 5 generalizes `warpdel`). This phase may split
  once surveyed; it is the outer edge of the plan, not its foundation.

What this plan still does not claim, and calls absences rather than debts:
`plays` for family trees (build-and-replay is engine wiring, a different
project), and `measures` — the family has no VWF; that gutter's absence *is*
the correct rendering, forever. The Diagnostics distinction ("not applicable"
is not "clean") already says this on screen.

The sentence to keep, again: nothing in these phases teaches the studio a hack
name. Each phase moves a refusal downward — from a sentence the writer says,
to data the writer declares, to a write that crosses.
