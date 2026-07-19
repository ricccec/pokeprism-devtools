"""The pokeprism adapter: every module that reads or writes prism itself.

The line these modules sit behind is drawn by one question — *would a second
adapter have to reimplement this?* A module is here because it parses prism's
asm dialect (`person_event`, `map_header`, `ctxt`), knows where prism keeps a
thing (`data/wild/`, `trainers/groups/`), or replays prism's engine (sprite
VRAM packing, WRAM structs, the ROM's palette tables). What stays in
`shared/` is mechanism over data already extracted — edit splicing, LZ,
RGBDS .map/.sym parsing, coordinate tiles — which an adapter for any hack
would import unchanged.

Differences between hacks cross the seam above (`studio.session` / `MapData`)
as declared data, never as an `if hack:` — see docs/adapter-plan.md and
docs/polished-crystal-feasibility.md, whose Phase 1 this package is.
"""
