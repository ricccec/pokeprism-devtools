"""The Gen-2 overworld, reconstructed — the write-once core two trees share.

When a save is patched to stand somewhere new, the game's `MAPSETUP_CONTINUE`
path loads the *coordinates* but not the *map*: it leaves `wScreenSave`,
`wObjectStructs` and `wMapObjects` describing wherever you were before, so the
tiles and NPCs around the new position render as the old map's. This package is
the arithmetic that rebuilds them — the same reconstruction prism worked out
during `prism-dev`'s development, lifted out so every tree that patches a save
reaches one implementation of it instead of copying it into each `play.py`.

Everything here is engine-general Gen-2, not any one hack's: it takes a tree's
own ROM bytes and symbols (`SymFile`) and its resolved `.sav` offsets as
*declared data*, and reads/writes the stock map-header, block-data, object-struct
and sprite-VRAM formats pokecrystal defines. Nothing in it imports a `hacks/`
module or knows a hack's name — the divergence between trees (the save framing:
which checksums, backup vs. co-verified extra data) stays above this line, in
each adapter's own `savefile`. See `rebuild.rebuild_map` for the one entry point.

    blockdata   map-header walk, block-grid decompress, connections, wScreenSave
    people      reset the player, clear/load NPC slots, instantiate on-screen sprites
    spritevram  the ROM sprite tables the object structs are populated from
    rebuild     the orchestration that calls the three in order
"""
