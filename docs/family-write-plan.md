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
| ~~family `a` on the map list (new map)~~ | **done** — placement declared in three shapes, scaffold crosses | ~~7b~~ |
| ~~family scaffolding (the block an entry line points at)~~ | **done** — four block writers (itemball, fruittree, hiddenitem; trainer in both trees), plus polished's line-only item adders and the splicer fix they needed | ~~8~~ |
| the seam is a docstring, so nothing enforces it | done — four Protocols and one battery across all three adapters (9a, 9b), and the `hacks.prism` leak counted (9c): 8 `wiring/` modules of real debt, the rest misfiled or declared | 9 |
| ~~the reader reads four macros, so polished's shorthand objects are invisible~~ | **done** — the parser expands ten convenience macros; 657 objects now surface, the writer counts them in step, and the census xfail flipped to a check | ~~10~~ |

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
  | polished | 119 thematic sections, 9 pinned | 436 sections, one per map, none pinned |

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

  **7b, first move — placement modelled and measured.** `wiring/placement.py`
  holds the three shapes as `PIN`/`JOIN`/`MINT` plus the two readers they stand
  on, and `hacks/vanilla/newmap.py` declares the family's answers. Re-measuring
  corrected this section twice. The **9** above was **11**: eleven section names
  in polished's `layout.link` contain the word "Scripts", and two of them
  (`Phone Scripts`, `Phone Scripts 2`) are not map script sections at all — the
  honest number intersects the link script with `data/maps/scripts.asm`. And
  "both trees ship a `layout.link`" understated it: the link script is the
  **only** place either tree records a bank. All 583 `SECTION` lines in the
  four map data files are a bare `ROMX` — as, in fact, are all 3,840 in both
  trees — so a reader that looked at the asm would conclude nothing is pinned
  anywhere, and would be wrong about all 28 of vanilla's buckets.

  The refusal this move adds: a `JOIN` tree will not mint. A fourth
  `Map Blocks 4` is spelled like the three sections it is named after and does
  not behave like them, because `layout.link` does not name it — so it is
  refused with the list of what may be joined instead, rather than created.
  What stays a *note* and not a check is bank headroom: joining a pinned bucket
  can overflow that bank, and knowing whether it will means measuring the
  section, which means building. That is the same reason `studio/newmap.py`
  declines to pack a bank inside a modal dialog.

  **7b, second move — the scaffold.** `wiring/mapnew.py` writes the six files;
  `hacks/vanilla/newmap.py` became the dialect holding the four spellings the
  trees differ on. The danger it is built around is that two of those files are
  **parallel arrays and nothing in either says so**: `map_const` assigns a map
  its id by counting, `MapGroupPointers` is indexed by that id, so an insertion
  anywhere but the end of a group renumbers every map below it — and the game
  builds, with doors opening onto the wrong rooms. Both insertions go at the
  end, together, and the test walks both files afterwards rather than checking
  that the written lines look right.

  `MapShape.line` mints the dimension line, so the transposing order has one
  owner across read, rewrite and mint. A new map is its worst case: the grid and
  the constant are written in the same breath from the same two numbers, so a
  swap is perfectly self-consistent and produces a map that is sideways.

  **The bug the tests agreed with.** Each of the four map data files closes its
  *last* section with an explicit `ENDSECTION`, and the last section is exactly
  what a numbered tree offers as its default — so every default-answer add
  appended the map past the close, into no section at all, and the membership
  check passed because it only stopped at the next `SECTION`. Found by reading
  the generated file. Both the writer and the check now stop at `ENDSECTION`.

  **7b, third move — the crossing.** `Writer.form("newmap")` answers, so `a`
  works on a family tree, and the two forms differ in exactly the ways the trees
  do: vanilla asks for a fishing group and where the blocks go, polished asks
  for a location sign and does not ask about blocks at all, because it mints.
  A minted blob's choice list is `[]` and the field is dropped — a field
  offering one answer implies a decision that was never available. Two more
  forks surfaced at the crossing: the landmark constants lose their `LANDMARK_`
  prefix in polished (reading it with vanilla's record returns *nothing*, which
  a form renders as a text box), and the environment enum differs in one slot —
  vanilla's fifth is `ENVIRONMENT_5`, polished's is `ISOLATED`.

  Not claimed: this form does not **sketch**. `studio/newmap.py` draws prism's
  map on the grid while you type, which turns a mis-sized `.blk` into a picture
  of the wrong shape rather than a message; that needs a family block renderer
  to point at, and returning something that does not draw would be exactly the
  absence Phase 4 built `absent()` to stop saying wrong. The check survives —
  `wiring/mapnew.py` refuses a grid that is not `height x width` — it is told
  rather than shown.

- **Phase 8 — family scaffolding. Done** for the block writers it enumerated;
  the read gap they exposed was closed in Phase 10, and the residue is named at
  the end. The block an entry line points at is what Phase 6 named as the reason
  trainers and props have no adder. It opened with `wiring/flagalloc.py`, because
  the family's `event_flags.asm` is *bucketed* (`const_def`, `const_next` jumps,
  and a `const_skip [N]` directive that is not prism's `const skip`
  placeholder-name) and prism's allocator raises on the first `const_def` it
  sees; then the four blocks, smallest first, each with the trap that reading a
  generated diff caught:

  * **Item ball** (`a6c3e5e`) — `wiring/blocks.py` for the three names that have
    to agree, `hacks/vanilla/itemball.py` for the composition. The label is
    `<file stem><item camelised>` 178/178 but `HP_UP` is `HPUp` (four acronyms
    stay upper); the const takes the **file stem** (`ROUTE29`), not the map
    constant (`ROUTE_29`), and getting it wrong mints a name unique *because* it
    is wrong.
  * **Fruit tree** (`be67605`) — the block points *out of the map*:
    `fruittree FRUITTREE_ROUTE_29`'s 1-based ordinal in `script_constants.asm`
    **is** the row index into `data/items/fruit_trees.asm`, so the id lives
    across two files that must stay in step; `wiring/fruittrees.py` appends
    const and row together or refuses. Flag is `-1` — a tree regrows, there is
    no event to allocate.
  * **Hidden item** (`213a2ac`) — the first adder whose *line* splices into a
    list other than the one it reads onto: it shows on the Objects tab as a Prop
    but its line is a `bg_event`. The `hiddenitem` macro is `dwb \2, \1`
    (flag,item transposed to ROM) while the source is `hiddenitem ITEM, FLAG`
    item-first, on all 85 — copying the byte order hands the engine an item id
    where the flag belongs.
  * **Trainer** (`016b1b4`) — the first block adder real in **both** trees, and
    the `generictrainer` blocker that stalled it is cleared. A 593-call polished
    sweep and a 333-call vanilla sweep found the two dialects want **different**
    shapes: vanilla names its three texts globally with a local `.AfterScript`
    (333/333), polished carries a self-contained inline after-body plus local
    `.SeenText`/`.BeatenText` (which is prism's shape). So each dialect writes
    its own — `trainer_block` and `generictrainer_block` in `wiring/blocks.py`,
    one `wiring/trainerroster.py` reader serving both (both cite a party by
    named constant, not prism's ordinal). Reuse an existing class+party, never
    mint one; the beat flag is allocated fresh per placement
    (`EVENT_<MAP>_TRAINER`), not the binding-looking `EVENT_BEAT_CLASS_PARTY`.
    Because the bodies are authored prose, the round-trip check is structural
    (parses back to a `Trainer` with the right flag/group/id/texts), not
    byte-identity.

  Then the two writes the enumeration did *not* foresee, both polished-side and
  both forced by the shorthand idiom the item-ball census named:

  * **The splicer counted objects wrong** (`fix(eventblock)`, `f2ab585`).
    `eventblock._entries_after` read the object list as *consecutive*
    `object_event` lines and stopped at the first convenience macro, so on **89
    of 607 polished maps** the writer saw fewer objects than the reader — a
    latent corruption in the shipped trainer/NPC append and in resize's `shift`
    (Route 4's `ACE_TRAINER` never moved). It skipped shorthands and stopped at
    the true block end, so write and read object counts agreed on all 995 maps —
    on the object_event-only view. Phase 10 moved both parsers to the whole-object
    view instead: `_entries_after` now *counts* the shorthands rather than
    skipping them, in step with a reader that expands them.
  * **Polished item and hidden-item line-adders** (`feat(itemball)`, `5c3069e`,
    in `hacks/vanilla/polisheditem.py`). Polished spells these on the object line
    itself — no block — so the adders splice a line and nothing else: the ball is
    a raw 13-argument `object_event … OBJECTTYPE_ITEMBALL, PLAYEREVENT_ITEMBALL,
    item, qty, flag`, written **long rather than as `itemball_event`** because
    only the long form read back at the time. Phase 10 closed that reader gap —
    the shorthand reads back now too — so the long form is a legibility choice
    the writer is free to keep rather than a workaround it is forced into; the
    round-trip stays green either way.

- **Phase 9 — the seam is a docstring. Give it a type and a battery.**

  *9a and 9b are done — see the status note at the end of this section. What
  follows is the argument as it stood before they were run, kept because the
  battery confirmed it rather than contradicting it.*

  Every phase above this one widened a contract that nothing checks. `mount()`
  returns a `Hack` whose `reads` and `writes` are annotated `Any`; the read and
  write methods exist only as prose at the top of
  `hacks/mount.py`. There is no base class, no `Protocol`, and no test that
  asks two adapters the same question. The three `Reader` classes are unrelated
  implementations that happen to agree, and `hacks/polished/read.py` agrees
  mostly because it imports vanilla's parsers rather than because anything made
  it.

  What that costs is not hypothetical, it is just deferred. A fourth adapter —
  or a fifth method added to the protocol for a sixth phase — fails by *mounting
  successfully* and then breaking on whichever pane asks the missing question
  third. The failure is far from its cause, at runtime, in the view layer, and
  the error names a pane rather than an adapter. Phase 4 built `absent()` so
  that a capability a tree does not have degrades to absence instead of a
  crash; that machinery only works on capabilities the seam *knows about*, and
  right now the seam knows about whatever the last adapter happened to write.

  Three moves, in this order:

  **9a — the contract becomes a type.** Turn the two docstring protocols into
  `typing.Protocol` classes in `hacks/mount.py` — `Reads` and `Writes` — and
  annotate `Hack.reads: Reads` and `Hack.writes: Writes | None`. Structural, not
  nominal: no adapter inherits anything, nothing changes at runtime, and the
  fork relation between vanilla and polished stays exactly as it is. The
  docstring stays too, because a `Protocol` says *what* and the prose says
  *why* — `tables()` raising `panels.Unreadable` rather than returning `None`
  is a decision, not a signature.

  **9b — one battery, every adapter.** A single conformance test that mounts
  each tree and asks all three the same questions, replacing the overlap
  between `test_vanilla.py` and `test_polished.py` — which today cover similar
  ground by coincidence, not by construction. It checks shapes and record
  types, not values: that `maps()` answers a dict of str to str, that
  `tables()` returns a `panels.MapTables` or raises `Unreadable`, that a
  declared capability's method exists and an undeclared one's absence is
  honest. The point is that adding a method to the protocol should break every
  adapter that has not implemented it, in one file, by name.

  **9c — the leak the type will make visible.** `wiring/` is not the
  hack-agnostic layer this plan's second rule describes. This move does not fix
  that. It *counts* it, in one place, as a list with a reason each, so the debt
  is a number rather than a feeling. Paying it is a later phase and probably
  several. **Done — the census is below.**

  **When to run it.** There was a real argument for putting 9a and 9b *before*
  the rest of Phase 8: every remaining block writer — fruittree, hiddenitem,
  two trainers — adds surface to a contract nothing enforces, and the
  conformance battery is cheapest to write while the protocol is still small.
  The argument the other way was that Phase 8's remaining writers are all
  vanilla-side and mostly do not touch the read protocol. **The first was
  chosen**: 9a and 9b ran first, and the rest of Phase 8 now lands against a
  checked seam.

  **Status: Phase 9 done.**

  Four protocols, not two. The prose claimed eleven read methods; there are
  **nine that every adapter owes**, plus two that are optional and gated on a
  declared capability, so they became protocols of their own: `Measures`
  (`measure`, `measures=True` only) and `Sketches` (`sketch`, reachable only
  from an action whose `sketches` is set). Folding those two into `Reads` would
  have made the family adapters non-conforming for correctly not having them —
  the absence is the design, so the type has to be able to say so. `Writes` is
  nine methods as described. All four are `runtime_checkable`, and `panels` is
  imported under `TYPE_CHECKING` so a tree probe still pays for no studio
  import.

  **The battery found the three adapters already in agreement** — every method
  present, every parameter list identical, every answer in the seam's records.
  That is the good outcome and it is worth stating plainly: the seam was
  *informal*, not *violated*. What Phase 9 changes is not the code's behaviour
  but what happens the next time someone adds a method — which is now a named
  failure in `tests/test_seam.py` rather than a pane exploding third.

  Two things the battery deliberately does not do. It does not compare **return
  annotations**: under `from __future__ import annotations` they are strings,
  and `vanilla.Writer.editor` declares none at all, so comparing text would
  fail on agreement and pass on a lie — it calls the methods and checks the
  records instead. And it does not check **values**: what Route 29 contains is
  `test_vanilla.py`'s business, and duplicating it here would make the seam
  test fail every time a tree is updated.

  `test_falsified` is the half that took the work. Five wrong adapters, each
  caught: a missing method, a renamed parameter, a parameter added, a parameter
  that gained a default, and — the one that matters — a reader that passes
  every name check while answering `None` to everything, which is exactly the
  adapter that mounts, draws an empty studio, and blames the repo. Writing it
  also exposed that the record checks *crashed* on that last stub instead of
  reporting it; a wrong record is now one `FAIL` and a battery that keeps
  going.

  **The census (9c).** Every `import` of `hacks.prism` outside `hacks/prism/`
  and the mount: **33 files**. The numbers this plan carried before measuring
  were wrong in both directions, and the shape was wrong too — so what follows
  is the count *and* the correction.

  | package | this plan said | measured | of |
  |---|---|---|---|
  | `wiring/` | 10 | **8** | 16 |
  | `maplint/` | 7 | 7 | 10 |
  | `studio/` | 1 (`grid.py`) | **6** | 22 |
  | `shared/` | clean | 0 | 11 |
  | the prism-only CLIs | not counted | **12** | — |

  The `wiring/` overcount was prose mentions counted as imports. The `studio/`
  undercount is the one that mattered, and chasing it is what produced the real
  finding below.

  **Four kinds of leak, and only one of them is debt.**

  1. **Not a leak — prism-only tools (12 files).** `dev_server/` (4),
     `gfx_view`, `map_inspect`, `map_new`, `map_show`, `mapfit` (2), `mapview`,
     `metatiles`. These are CLIs written against prism and they never claimed
     otherwise; `prism-dev` patches a prism save and boots a prism ROM. The two
     the studio reaches — `dev_server` from `play.py` and `session.py` — are
     behind `plays`, which is the seam working, not leaking.

  2. **Not a leak — the linter (7 files).** All of `maplint/` is written
     against prism, and the seam already declares it: `ctx` is `None` for every
     other tree and the session lints exactly when `ctx` is not `None`. This is
     declared absence, the same category as `measures`. Porting the rules is a
     project, not a debt.

  3. **Misfiled, not leaking (5 files) — now moved.** `content.py`, `edits.py`,
     `offers.py`, `prefill.py`, `newmap.py` were **prism's write adapter**, and
     `hacks/prism/write.py` imports all five back — `write.py`'s own docstring
     named them. They import prism because they *are* prism. Five of the six
     `studio/` hits were this, and the fix was a move into `hacks/prism/`, not a
     decoupling — **done**: they now sit beside `write.py`. The import graph did
     not change, only the spelling of the paths, so no cycle appeared; the
     package boundary no longer reads as a seam violation it never was.

  4. **The actual debt — `wiring/` (8 of 16).** `objedit`, `scaffold`, `props`,
     `removal`, `warps`, `connections`, `mapedit`, `text` each pull prism
     parsers (`consts`, `eventheader`, `mapsource`, `spritesets`,
     `trainerparty`, `dialogue`, …). The modules built since the seam —
     `regions`, `flagalloc`, `blocks`, `mapresize`, `mapnew`, `placement` — are
     clean, as the rule intends; the older ones predate it.

  Plus one genuine studio-layer leak, **now closed**: `studio/grid.py` reached
  into `prism.swatches` for `tile_color`. That function is a pure renderer over
  data the session already read — tree-agnostic in behaviour, merely filed under
  the wrong package — so it and the `Rgb`/`Swatch` types moved to
  `shared/swatches.py` (re-exported from `prism/swatches.py` for the prism-only
  callers). `grid.py` now imports no parser at all, which the studio-seam AST
  guard confirms.

  **What the debt actually costs today, measured rather than assumed.** The
  family adapters do reach category 4: `vanilla/resize.py` imports
  `wiring.objedit`, and `vanilla/newmap.py` imports `wiring.mapnew`, which
  imports `objedit` in turn — so **mounting a vanilla or polished tree loads
  the prism parser stack**. But what they take across is `EditError`,
  `MapShape`, `Standing` and `NewMap` — exception types and geometry
  dataclasses — and none of those prism modules does file I/O at import time.
  No prism *logic* runs for a family tree. The leak is real, inert, and pays
  for itself in module load only.

  So the honest total is not 33. With the 6 misfiled files moved home, it is
  **8 modules of real debt** (category 4) — and the seam holds everywhere the
  studio actually crosses it. The reason to fix category 4 is not that it breaks
  today — it is
  that `EditError` and `MapShape` are the thin end: the field-index constants
  next door (`S_X`, `W_Y`) encode prism's `person_event` layout, and the first
  family caller that reaches for one of *those* will get a wrong answer rather
  than a crash.

- **Phase 10 — the reader's four-macro vocabulary. Done**, and the survey that
  opened it corrected the plan twice before a line was written. Not a write
  refusal; found by censusing Phase 8's item ball against the real trees, and it
  left a standing xfail pointing straight at it. `hacks/vanilla/events.py` read
  exactly four macros — `warp_event`, `coord_event`, `bg_event`, `object_event`
  — and silently dropped every other line. Gen-2 spells objects with convenience
  macros that expand to an `object_event` at assembly time, and the plan said
  *seven* — `itemball_event` and kin. **There are ten.** `maps.asm` also defines
  `pokemon_event`, `pc_nurse_event` and `mart_clerk_event`, and the parser was
  blind to those too, so the real gap was larger than the phase it was written
  into.

  **It reads vanilla whole, and the gap was polished's alone.** Vanilla writes no
  shorthand at all: its 178 item balls are a long-form
  `object_event … OBJECTTYPE_ITEMBALL` beside an `itemball` block — exactly what
  the Phase 8 writer mints and exactly what the reader reads. The compact idiom
  is polished's, and so was the blindness — **not 551 objects but 657**: 346
  balls, 54 fruit trees, 59 smash rocks, 35 strength boulders, 57 cut trees, and
  the 106 the plan's seven-macro count missed (67 wild mons, 26 nurses, 13
  clerks). The item-ball census is the sharp one: the reader surfaced **9 of 355**
  before and **355 of 355** after.

  **The fix is one vocabulary, declared once and handed to both parsers.**
  `hacks/polished/shorthand.py` holds the ten expansions — each transcribed from
  the macro body it mirrors, checkable slot for slot, because a guessed column
  feeds the same classifier the long form does. `events.parse` takes an `expand`
  map and, on a shorthand line, appends the `object_event` it assembles to *in
  file order*; vanilla passes nothing, polished passes `SHORTHANDS`. That closes
  the display half. The subtler half is handle drift: object identity is a
  positional index counted over *all* the engine's objects, so a shorthand ahead
  of a read object slides the const *name* the reader hangs on object N onto a
  different object. Expanding in file order closes that half too — but only if
  the **writer** counts the same way, and here the phase had to undo its own
  Phase 8 fix.

  **The writer had to move with the reader, and this was the trap.** `f2ab585`
  taught `eventblock._entries_after` to *skip* shorthands so the splicer's object
  count matched a reader that dropped them — the two agreed on a count that was
  wrong by 657. Now that the reader expands them, the writer counts them: each
  shorthand is one object entry, held under its own macro so `replace_entry`
  re-emits `itemball_event`, not a malformed twelve-column `object_event`. Reader
  and writer agree again, this time on the *whole* object list, on all 89 of the
  interleaved maps. Two consequences fell out, both benign and both tested: the
  object editor already refuses a line whose slot count is not the dialect's
  twelve, so a shorthand edit refuses rather than corrupts (689 polished object
  lines refuse in the round-trip, up from 22); and resize's `shift` now moves
  shorthand coordinates too, so its off-grid census rose 8 → 15 maps — the seven
  new ones a `smashrock_event` or `itemball_event` placed in a connection-overflow
  region, as legitimately off-grid as the long-form ones always were.

  **What the phase did not claim, and named rather than left silent.** The item
  balls classify as item-ball props, because the shorthand carries its own
  `OBJECTTYPE_ITEMBALL`; the fruit trees, cut trees, boulders and wild mons read
  as NPCs, because they expand to `OBJECTTYPE_COMMAND`/`_POKEMON` objects and the
  reader treats every command-object as one — the long form would read the same.
  They are visible and correctly indexed, which is the phase; reclassifying a
  floor shorthand into a prop kind is a reading refinement over *all* command
  objects, not just these, and is left for its own change. The census that drove
  the phase is now a plain `check()` in `tests/test_polished.py`
  (`test_reader_sees_every_item_ball`), counting the raw source independent of
  the reader so it stays honest whether the reader over- or under-counts.

What this plan still does not claim, and calls absences rather than debts:
`plays` for family trees (build-and-replay is engine wiring, a different
project), and `measures` — the family has no VWF; that gutter's absence *is*
the correct rendering, forever. The Diagnostics distinction ("not applicable"
is not "clean") already says this on screen.

The sentence to keep, again: nothing in these phases teaches the studio a hack
name. Each phase moves a refusal downward — from a sentence the writer says,
to data the writer declares, to a write that crosses.
