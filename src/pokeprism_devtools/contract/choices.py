"""Which sort of constants a form field wants — names, never answers.

`choices=ITEMS` says a box wants an item; whether *this* tree can enumerate
items is the write adapter's `choices()` to answer, and a hack with no fruit
trees answers `[]` for :data:`TREES` and the field degrades to free text. So
naming a kind here commits nobody to having one, which is the only reason one
list can serve three engines.
"""

from __future__ import annotations

#: A field's `choices` names a set of constants the session can enumerate; the
#: form turns it into autocomplete. Empty means free text.
MAPS = "maps"
SPRITES = "sprites"
MOVEMENTS = "movements"
PALETTES = "palettes"
ITEMS = "items"
CLASSES = "classes"
DIRECTIONS = "directions"
FACINGS = "facings"
TILESETS = "tilesets"
PERMISSIONS = "permissions"
LANDMARKS = "landmarks"
MUSIC = "music"
#: The map header's palette — `PALETTE_DAY`, `PALETTE_NITE`. Not :data:`PALETTES`,
#: which is a *sprite's* `PAL_OW_RED`. Two different words spelled the same, and
#: putting one where the other goes assembles perfectly.
TIMES = "times"
FISHGROUPS = "fishgroups"
#: Event flags, which are the one kind where the list is *only* a suggestion: a
#: name that isn't in it is a name that will be created. See `Combo`.
FLAGS = "flags"
#: The TMs and HMs, which are the only items a TM ball may hold, and the fruit
#: trees, which are ids rather than items. Both are subsets of a bigger enum, and
#: offering the bigger enum would offer the mistake.
TMHMS = "tmhms"
TREES = "trees"
#: The parties of a trainer class — the one kind whose answers depend on another
#: field. See :meth:`Field.depends`.
PARTIES = "parties"
#: The map groups that exist. A bare number, and the only reason to offer a list of
#: numbers is that nothing else on the form tells you how many there are.
GROUPS = "groups"
#: The `.blk` and `.ablk` files lying about — in `../polished-map`, in `maps/blk/`,
#: in the directory you started from. The only field whose answers are *paths* and
#: not constants, and the only one whose list is read fresh every time it is asked:
#: the file you want is nearly always the one you drew a minute ago.
BLOCKS = "blocks"
#: The location sign a map shows on entry — polished's `SIGN_BUILDING`. An
#: argument of its `map` macro that vanilla's does not have at all, which is why
#: the header's arguments are a declared list per tree and not one signature.
SIGNS = "signs"
#: The `SECTION`s a new map's script and blocks may go into, one kind each
#: because the two blobs are placed independently and out of different files.
#: The only kinds whose answers are neither constants nor paths but *places* —
#: and, unlike every other kind here, the ones where an empty list means the
#: tree mints rather than chooses, so the form drops the field. See
#: `wiring/placement.py`.
SCRIPT_SECTIONS = "script-sections"
BLOCK_SECTIONS = "block-sections"
