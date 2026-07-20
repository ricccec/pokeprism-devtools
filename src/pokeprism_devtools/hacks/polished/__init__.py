"""The polishedcrystal adapter: the family's stress test, read-only.

Polished is a pokecrystal fork and this package leans on that ancestry
deliberately: the label carving, the `map_attributes` grammar and the
`def_*` lists are vanilla's, imported from `hacks/vanilla` rather than
forked. What it keeps for itself is everything polished changed — the event
block opens the map file instead of closing it, `object_event` lost the
palette column and gained an `OBJECTTYPE_COMMAND` mode, hidden items moved
inline into `BGEVENT_ITEM + ITEM`, trainers split into `trainer` and
`generictrainer`, a wild mon grew a form axis, and tile palettes became a
binary `*_attributes.bin` beside the metatiles.

`docs/polished-crystal-feasibility.md` picked those differences as the
proof the seam holds; every one of them crosses as declared data, and the
port never hears polished's name.
"""
