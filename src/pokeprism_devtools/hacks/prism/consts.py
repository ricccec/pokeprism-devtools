"""Does this constant exist? — asked of the enums the content scaffolds emit.

rgbds resolves symbols at *link* time, so a typo'd species or a Pokémon that
this fork doesn't have (pokeprism drops most of the Kanto dex) doesn't surface
until the whole ROM links, minutes later, as ``Unknown symbol "RATTATA"`` with
nothing to say about which trainer you were writing.

The build does catch these — that's why there's no lint rule here. But a tool
that is *about* to write one into three files should say so before it does.
"""

from __future__ import annotations

from ...shared.constants import (names as _names, suggest as _suggest,
                                 with_prefix as _with_prefix)

#: The reading itself is rgbasm's, not prism's — `const NAME` binds a name the
#: same way in every gen-2 tree, so the mechanism moved to `shared/constants.py`
#: where the family adapter can reach it without importing prism. What stays here
#: is the half that *is* prism's: which file holds which set. Re-exported under
#: the names prism's callers already use.
names = _names
with_prefix = _with_prefix
suggest = _suggest

SPECIES = "constants/pokemon_constants.asm"
ITEMS = "constants/item_constants.asm"
MOVES = "constants/move_constants.asm"
SPRITES = "constants/sprite_constants.asm"

#: The enums a `map_header` names. One list, read by both the form that offers
#: them and the action that checks what you typed — because a form that suggests
#: a constant its own validator would then reject is worse than no form.
TILESETS = "constants/tilemap_constants.asm"
MAP = "constants/map_constants.asm"           # the permissions, and PALETTE_*
MUSIC = "constants/music_constants.asm"
MISC = "constants/misc_constants.asm"         # FISHGROUP_*
LANDMARKS = "constants/landmark_constants.asm"
