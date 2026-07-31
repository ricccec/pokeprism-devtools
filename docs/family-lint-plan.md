# The live family plan — what is left to build

This is the forward-looking half of the family story, and it is nearly empty. The
completed work — Phases 5 through 11, which took the family tree from read-only to
a full writer that round-trips to the byte and then to a linter, a boot and a
measurer — is history now and lives in `family-write-plan.md`, alongside the
roadmap that followed it and has since emptied. For *what is true now* (the
capability matrix, the seam's shape), read `STATE.md`.

It inherits the two rules the branch was built on: hack differences live in
adapters and cross the seam as **declared data** — only `hacks/mount.py` knows a
hack's name — and mechanics that a CLI could someday wrap live in `wiring/`
(primitives in, `Change` out), decoupled from the studio.

## What is left

With Phase 9c category 4 paid, the seam has no structural debt, and the capability
matrix is full. Two items remain, one of them a question and one of them a refusal
to build:

- **Would any of prism's other lint rules earn a family port?** Phase 11 shipped
  the four dialogue-overflow rules (`text-width`, `text-width-name`, `text-rows`,
  `text-buffer`) for vanilla and polished. Whether prism's geometry, warp-target,
  sprite, flag or trainer rules are worth the same treatment is **unsurveyed** —
  nobody has yet asked, rule by rule, which of them describe a Gen-2 fact the
  family trees share and which describe prism. That survey is the work; the port,
  if any survives it, is the smaller half. The `ctx.lint()` capability it would
  ship into already exists, so nothing structural is in the way.
- **Permanent, do not build: family VWF *pixel*-metrics live `measure`.** Map
  dialogue is fixed-width in both trees, so there are no per-glyph pixel widths to
  sum for it. This is not the item above and never was: fixed width is exactly what
  makes the *tile* count the gutter shows correct, and what has no answer is the
  pixel width of a proportional font. (The menu VWF polished ships — `tools/vwf.c`,
  `home/vwf.asm`, `PlaceVWFString` — is off the dialogue path and out of scope.)

Separately from either, one thing is not work but a **standing unknown**: no save
in any tree points a `wVariableSprites` slot at a *still* sprite, so the engine has
never confirmed our still-sprite VRAM sizing. Closing it needs a captured
game-written save, not a code change. See `docs/save-patch.md`.

The sentence to keep, again: nothing here teaches the studio a hack name. Each
phase moves a refusal downward — from a sentence the writer says, to data the
writer declares, to a write that crosses.
