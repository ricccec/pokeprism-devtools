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
| ~~family `a` / `e` (adders, editors)~~ | **done** — four editors, three adders | ~~6~~ |
| ~~family `s` (resize)~~ | **done** — crosses via a declared `MapShape` | ~~7a~~ |
| family `a` on the map list (new map) | scaffold + placement unmodelled | **7b** |

Ordered smallest-risk-first, as before: 5 is a port of machinery that already
exists for prism, 6 is the big lift, 7 stands on 6 — and 7 split in two once
surveyed, because resize turned out **not** to stand on newmap the way this
plan assumed. See Phase 7 below.

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

  **The actions and the prefill are done**, and they landed as one move
  rather than two because an editor *is* its prefill — a form that opens on
  nothing is not an editor. They are in `hacks/vanilla/actions.py`, with the
  records they are built from in `hacks/vanilla/shapes.py`.

  One correction to the plan's own carve, and it is the shape of the whole
  move: **not one form per kind — one per list.** This plan said "per kind"
  because the tables show six (npc, trainer, prop, signpost, warp, trigger),
  but those six are a *reading* of the block each entry points at, and what
  an editor rewrites is a **line**. An NPC and a fruit tree are one
  `object_event` with identical slots; what makes one a tree is the
  `fruittree` macro in another block, which this line does not own. So there
  are four editors, one per `def_*` list, and resolving the handle is what
  picks the form. `Ref.what` never comes into it.

  The fork is a fourth declared record, `ObjectShape`, beside the anchor, the
  warp grammar and the constant sets — and the survey that produced it found
  the sharpest thing in the phase:

  * **The movement radius is swapped between the two trees.** Vanilla's macro
    emits `dn \6, \5` and polished's `dn \5, \6`, so arguments 5 and 6 are the
    radius in both dialects and mean opposite axes. 153 vanilla lines and 250
    polished lines write an asymmetric one, and a writer that copied the other
    tree's order would have reflected every one of those pacing boxes across
    the diagonal — the identical failure the (x, y) ↔ `Tile(y, x)` turn exists
    to prevent, one column further along, and invisible in the ~90% of lines
    that write `0, 0`.

  **Round-tripping every real entry is what earned the phase.** Prefill each
  of the 9,257 entries in the two trees, hand it straight back unchanged, and
  demand the file come back byte-identical. It is the only check that can
  catch a wrong slot order, because a wrong order is not a crash — it is a
  plausible line with two arguments transposed. It caught two live bugs:

  * **`replace_entry` was dropping every comment.** Its docstring said
    "keeping its comment" and its regex `(?:;.*)?` *consumed* the comment
    before `m.end()` measured where the arguments stopped, so the slice was
    always empty. Twenty lines in vanilla and eighty-three in polished,
    including the `; hole` that is the only thing distinguishing a Blackthorn
    Gym floor hole from a door. Pre-existing since Phase 4 and invisible until
    something called `replace_entry` on real data.
  * **Polished's `bg_event` takes an optional fifth argument.** `if _NARG == 5`
    spends it on a `BGEVENT_JUMPSTD`'s argument — 35 lines, every one a hidden
    grotto — and the four-argument form writes a zero in its place. A form
    with four boxes would have turned each grotto into grotto 0 on first edit.

  A third was caught by the fixture rather than the trees: `ObjectShape.args`
  fell back to `"0"` for a slot with no declared default, and `0` is a
  perfectly good `SPRITEMOVEDATA_*`. It now refuses instead, because a line
  that assembles into the wrong pose is the failure mode this whole phase is
  organised against.

  Result: vanilla 3,684/3,684 byte-identical, polished 5,560/5,573 with the
  13 differing only by `format_entry`'s own two-column padding — house style
  on the edited line, the same cosmetic already on record for prism's
  `dummy_warp`. 22 polished object lines *refuse*: the 13-argument
  `object_event` spends its trailing three on item, quantity and flag where
  the ordinary twelve spend two on a pointer and a flag, so rewriting one with
  the 12-slot shape would slide the flag into the quantity. It says which line
  instead.

  **Adding crosses for three lists, not four, and the fourth is an absence
  rather than a gap.** Warps, triggers and signposts append cleanly; NPCs
  append with an optional `const`. Trainers and props have no adder, because
  their entry line is the small half — the content is a `trainer` /
  `itemball` / `fruittree` / `hiddenitem` block written beside it, and
  `add_entry` splices lines. A line pointing at a block nobody wrote does not
  assemble, so the tab's Add row says nothing rather than producing a map that
  will not build. Family scaffolding is the project rewording is.

  Named identity landed slightly differently from the sketch above: the const
  box is always offered, and `add_entry`'s own refusal explains the ordinal
  when the list names only its leading objects. Hiding the box would need
  `adders()` to be told which map you are on, and it is told a tab's name and
  nothing else — and the refusal arrives at *preview*, with everything you
  typed still on screen and not one byte written, which is the moment the form
  exists to reach.

  Not claimed by this phase, on purpose: `EditMap` (the attributes tab),
  rewording (family `text` vs prism's VWF `ctxt` is a text-wiring project of
  its own), and connection *adding* (`wiring/connections` is two-sided and
  deserves its own look). Each keeps its sentence. Joining them, named by
  this phase rather than assumed away: **family scaffolding** — the block
  writer that trainer and prop adders would ride, and the thing rewording
  needs too. It is one project, not three, and it is the natural Phase 8.

  Left as a debt by this phase and **paid before 7b**: `hacks/vanilla/write.py`
  was 771 lines against this repo's 500, and 787 after 7a added a fifth
  mount-declared fork — compounding rather than static. It carved at the seam
  the debt note named: `.eventblock` holds the parser and the splicer (338
  lines), `.write` the adapter, its records and its two delete actions (471).
  Nothing moved but whole definitions — the split's code lines are the
  original's, and the four differences are documentation the split made wrong.
  It also removed a cycle: `.actions` imported `.write` only for the parser, so
  the arrow the `Writer._forms` comment argued about does not exist any more.

- **Phase 7 — split once surveyed, exactly as this line reserved the right
  to.** The plan bundled `newmap` and `resize` and asserted resize "stands on"
  newmap. It does not: **a resized map keeps whatever section it was already
  in**, so resize never asks the placement question that makes newmap hard.
  They were two capabilities sharing a bullet, and the cheap one shipped
  first.

- **Phase 7a — family resize. Done.** `wiring/mapresize.py` keeps the geometry
  (it is the same in every tree) and asks the tree everything else through a
  `Dialect`; `hacks/prism/resize.py` and `hacks/vanilla/resize.py` hold the two
  sets of answers. `Writer.form("resize")` crosses, so the `s` key exists on a
  family tree.

  **The finding, and it is the swapped movement radius again.** The dimension
  macro takes its two numbers in the *opposite order* in each family:
  prism's `mapgroup NAME, H, W` against the family's `map_const NAME, W, H`.
  Measured rather than read off the macro comment — `PlayersHouse1F` is
  `map_const …, 5, 4` and its `.blk` is exactly 20 bytes. So `MapShape` owns
  the order and does *both* the read and the write of that line, because the
  only way to guarantee they agree is to give them no chance to disagree.

  **A byte count cannot catch that**, which is worth writing down: `h*w` is
  `w*h`, so the obvious check — does the grid match the declared size — passes
  under both readings and proves nothing. What discriminates is the things
  *standing* on the map, since a coordinate knows which axis it is on. Under
  the declared order 387/388 vanilla and 601/604 polished maps have every
  entry in bounds; under the transposed order, 192 and 290. Half of every map
  would have been mislocated, silently. The four maps that fit under neither
  are real: they park objects off the grid on purpose, one at `y = -5`, which
  is not a misparse.

  Two more forks the survey caught. Polished indexes blocks under
  `<Label>_BlockData:` where vanilla writes `<Label>_Blocks:` — so the dialect
  is handed its tree's own `_blk` rather than deriving one from the anchor,
  which does not imply it; before that fix polished resolved *zero* maps. And
  polished INCBINs the compressed `.ablk.lzp` while the file a human draws is
  the `.ablk` beside it, the same suffix-stripping prism does for `.lz`.

  **The refusal that turned out to be the common case.** Both trees stack
  several labels on one INCBIN, and vanilla does it constantly: 436 labels
  against 302 INCBINs, so 157 of its 388 maps share a grid with a twin
  (`NationalPark` and `NationalParkBugContest` are the same blocks). Resizing
  one corrupts the other, whose dimension constant does not move with it.
  Prism's resize already refused this; for the family it is not an edge guard
  but roughly 40% of the tree. Final: 231 vanilla and 415 polished maps
  resize, 157 and 191 refuse for sharing a grid, and **nothing refuses for any
  other reason**.

- **Phase 7b — a new map, and where it may be put.** The remaining half, and
  the survey has already moved its foundation. The plan recorded "vanilla is a
  bucket choice and polished floats"; both trees ship a `layout.link`, and the
  answer differs **per blob kind, not per tree**:

  | | scripts | blocks |
  |---|---|---|
  | vanilla | 25 `Map Scripts N` buckets, all 25 pinned | 3 `Map Blocks N` buckets, all 3 pinned |
  | polished | 119 thematic sections, 11 pinned | 436 sections, one per map, none pinned |

  So there are three placement *shapes*, not two: prism **pins a bank** (or
  floats for `prism-mapfit`), vanilla **chooses an existing bucket** — twice,
  and each bucket is already pinned, so the choice picks the bank implicitly —
  and polished chooses a bucket for the script but **mints a new section** for
  the blocks. The plan's model ("the choices it offers become a form field
  exactly when they exist") survives but is one shape short: a declared list of
  choices cannot express *mint a new one*. The record has to say what **kind**
  of answer placement is per blob, not just enumerate options.

  The scaffold is the easy half and nearly shared: `maps/<Label>.asm`,
  `data/maps/{maps,blocks,attributes,scripts}.asm` and
  `constants/map_constants.asm` in both trees, plus `scenes.asm` in vanilla
  only. Placement is the entire fork.

What this plan still does not claim, and calls absences rather than debts:
`plays` for family trees (build-and-replay is engine wiring, a different
project), and `measures` — the family has no VWF; that gutter's absence *is*
the correct rendering, forever. The Diagnostics distinction ("not applicable"
is not "clean") already says this on screen.

The sentence to keep, again: nothing in these phases teaches the studio a hack
name. Each phase moves a refusal downward — from a sentence the writer says,
to data the writer declares, to a write that crosses.
