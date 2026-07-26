# The live family plan — what is left to build

This is the forward-looking half of the family write story. The completed work —
Phases 5 through 10, which took the family tree from read-only to a full writer
that round-trips to the byte — is history now and lives in
`family-write-plan.md`. What remains is one scoped-but-unbuilt phase and a
roadmap of deferred capabilities, none blocking another.

It inherits the two rules the branch was built on: hack differences live in
adapters and cross the seam as **declared data** — only `hacks/mount.py` knows a
hack's name — and mechanics that a CLI could someday wrap live in `wiring/`
(primitives in, `Change` out), decoupled from the studio. For *what is true now*
(the capability matrix, the seam's shape), read `STATE.md`.

- **Phase 11 — the family's first lint: does the dialogue fit the box.
  Planned, not built.** The linter (`maplint/`) is prism-only today, and the
  reason given has always been "the family has no VWF." That reason was measured
  this cycle and found to be answering the wrong question.

  **The want.** Flag a dialogue line that crosses the screen boundary and
  overflows its box — for vanilla and polished, not only prism. A line one tile
  too wide writes over the box's right border; a speech with more visual lines
  than the box has rows draws into the map behind it. Both assemble cleanly and
  neither shows up until someone walks into that exact conversation.

  **The premise, corrected by measurement.** "The family is fixed-width" is not
  quite true: polished ships a variable-width font (`tools/vwf.c`,
  `home/vwf.asm`, `PlaceVWFString`) — but only for menus (Bill's PC item names,
  ability graphics). Overworld map dialogue in *both* trees runs through the
  fixed-width `PlaceString`/`PlaceNextChar` path in `home/text.asm`, one tile per
  glyph. So overflow of *map dialogue* is exact fixed-width tile counting in both
  trees. This is the sharp distinction the old note blurred: **overflow is a fit
  question and the fit is fixed-width, even where a menu elsewhere is not.** If
  polished ever routed dialogue through the VWF, this exactness would break and
  the lint would owe pixel widths; it does not today, and a rule can assert that
  the dialogue path is still `PlaceNextChar` so the assumption is checked, not
  trusted.

  **Why it is not `Measures.measure`.** `measure` refuses to answer in
  characters because *VWF pixel* width is unknowable without the glyph metrics —
  a live preview of proportional text. Overflow is the other question: count the
  printable tiles between the script's own break controls and compare to the box
  width. That is ground truth, not a guess, so it belongs in a lint `ctx`, and
  the family `Measures` absence stays exactly as principled as it was.

  **How much is already in place.** Less than the phase number suggests. The
  break vocabulary is already read — `hacks/vanilla/events.py` parses
  `text/line/cont/para/next`, and the family model is *simpler* than prism's
  because one macro is one visual line, with no inline `<LINE>`/`<NEXT>` cursor
  codes to interpret inside a string. The box geometry is one constant,
  `TEXTBOX_INNERW = SCREEN_WIDTH − BORDER_WIDTH = 18`, under the same names
  prism's `textbox.metrics` already reads. The finding channel is hack-neutral:
  `maplint/diagnostics.py` (`Diagnostic`, `Severity`, `apply_suppressions`)
  imports only stdlib, and the studio's Diagnostics panel renders it today. And
  prism's own `rules_text.text_width` is *already* tile arithmetic
  (`line.determinate` vs `block.box.cols`), not VWF — the only prism-bound parts
  of it are the charmap and the `dtxt` control-code expansions.

  **The one architectural decision — a lint capability, not a rule-subset
  switch.** The session lints via `maplint.run(self.ctx)`, which runs *every*
  prism rule against a prism `LintContext`; a family ctx that only knows text
  would crash the geometry and sprite rules. So `Hack.ctx` should become a lint
  capability that runs itself: `ctx.lint() -> list[Diagnostic]`, `ctx.mentions(d,
  const)`, `ctx.source_lines(rel)`. The session calls `self.ctx.lint()` instead
  of reaching into `maplint`. Prism's `LintContext` gains a three-line `lint()`
  wrapper; the family gets a small `FamilyLintContext` whose `lint()` runs only
  the text rules. This keeps [[no-hack-branching-outside-mount]] intact — the
  session still branches only on `ctx is not None`, never on a name, and each
  context owns its rule set. The alternative, teaching the session which rules a
  tree supports, leaks rule-set knowledge above the seam and ages badly.

  **Where it lives.** `hacks/vanilla/lint/` — a family charmap reader, a family
  box-metrics reader (a trim of prism's, which already reads `TEXTBOX_INNERW`), a
  dialogue→visual-lines pass (mostly already in `events.py`), and the rules.
  Polished imports it the way it already imports vanilla's read mechanics. The
  overflow *arithmetic* — determinate tiles vs cols, row vs last-row — is
  identical to prism's two rules, so lift just that comparison into a neutral
  helper both call; keep the parsing family-local. No sharing past the
  arithmetic, and `keep-mechanics-cli-extractable` survives — a `family-maplint`
  CLI wraps the same rules.

  **Three moves.** (A — **done**) The
  `ctx.lint()`/`mentions()`/`source_lines()` capability refactor; prism behaviour
  unchanged, proven by `test_maplint`/`test_studio` staying green. (B — **done
  for vanilla**) The family determinate-overflow lint: family charmap + box
  reader + two rules — `text-width` (a visual line past 18 tiles, counting
  control-code expansions like `<POKE>`) and `text-rows` (more visual lines than
  the box holds before a required `para`/scroll) — and `Hack.ctx` wired in
  vanilla's `claim.py`. This is the first non-`None` family `ctx`.
  (C, deferred) the buffer refinements: name worst-case (`<PLAYER>` at its
  seven-letter longest, prism's `text-width-name`) and unbounded headroom
  (`text-buffer`). The family charmaps carry `<PLAYER>`/`<RIVAL>`, so these port
  cleanly once the determinate core has proven out.

  **The correction Move B forced.** The plan above assumed one family text engine,
  so "polished imports vanilla's lint" whole. It does not: the map *event* format
  is shared, but the text engines diverge — vanilla is the classic
  `dict`+`print_name`→ROM `db`, polished is `_dtxt`/Huffman `ctxtmap` with an
  n-gram string table (closer to prism). The overflow *counting* holds for both,
  and the box, the dialogue parse, the rules and the neutral `maplint.textfit`
  arithmetic are all shared; only the width `Metrics` reader is engine-specific.
  So `Hack.ctx` is wired for vanilla now, and **polished is the fast-follow** — it
  brings its own n-gram width reader and reuses everything else, the same fork
  relation its writer already has with vanilla's.

  **Verification, the usual way.** Calibrate the box width by measuring the
  widest non-overflowing real line across both trees, then falsify: widen a
  known-good line one tile past 18 and confirm the catch, and confirm the
  intentional-overflow suppression path (`; maplint: ignore-file[text-width]`,
  the PhanceroRoom idiom) still works. Baseline both real trees so the lint ships
  green and only *new* overflows fail. Acceptance: nothing known-good flagged,
  every flagged line genuinely over 18.

## The roadmap past the seam — what is left to build

With Phase 9c category 4 paid, the seam has no structural debt; what remains is
capability, each item its own phase, none blocking another. Grouped by kind, and
every one is deferred-but-buildable unless marked permanent.

- **Lint (Phase 11 above).** The family dialogue-overflow lint and its `ctx.lint()`
  seam prep; then (C) the name-buffer and unbounded-buffer refinements. Whether
  any of prism's geometry / warp-target / sprite / flag / trainer rules are worth
  a family port is a separate, unsurveyed question.
- **Connection *adding* (both trees).** `hacks/prism/connections` is two-sided;
  deletion already refuses on the neighbour's side. Adding needs its own survey
  of how each tree wires the reciprocal connection before it is scoped.
- **Family rewording.** Editing existing dialogue text — the reworder
  (`hacks/prism/text.reword`) is prism-parser-based; a family one writes against
  the fixed-width charmap. Related to Phase 11's charmap reader, not the same job.
- **`EditMap` / attributes-tab editing for family trees.** The header-facts
  editor is unclaimed for vanilla and polished.
- **Family map *sketch*.** The new-map form does not draw the grid while you
  type; it needs a family block renderer to point at, and returning a
  non-drawing stand-in would be the exact wrong-absence Phase 4's `absent()`
  exists to prevent.
- **Family `plays`.** Build-and-boot — a patched save, an emulator — is engine
  wiring and a separate project. It gates the prism-only CLIs (`dev_server`,
  `gfx_view`, `map_inspect`, …).
- **Permanent, do not build: family VWF pixel-metrics live `measure`.** Map
  dialogue is fixed-width in both trees, so there are no per-glyph pixel widths
  to sum for it; the `Measures` gutter's absence is the correct rendering. (The
  menu VWF polished ships is off the dialogue path and out of scope.) Overflow is
  covered by the tile-counting lint, not by `measure`.

The sentence to keep, again: nothing in these phases teaches the studio a hack
name. Each phase moves a refusal downward — from a sentence the writer says,
to data the writer declares, to a write that crosses.
