"""Emptying every cache in the toolchain, for when the repo changed underneath it.

Half a dozen modules here memoise their reads with `@lru_cache`, keyed by the
repo root — the item constants, the charmap, the landmarks, the tileset swatches,
the textbox metrics. That is right: they are read constantly and they change
almost never, and a `Session` that re-parsed `item_constants.asm` on every
keystroke would be a `Session` nobody could type into.

But an `lru_cache` lives on the *function*, which lives on the *module*, which
lives for the whole process. So it outlives any object that might think it owns
it. `Session.reload()` can drop its own caches all it likes; if `consts.names`
still has last hour's items in it, the studio will go on offering last hour's
items, and it will do so with total confidence. That is the bug this module
exists to prevent, and it is one I shipped before writing this: `reload()` looked
right, tested wrong, and the test is the only reason it isn't still wrong.

:func:`clear` finds the caches instead of naming them. A hardcoded list is a list
somebody adds the seventh cache to and forgets — and the failure is silent, and
it is *stale data*, which is the failure you notice last and trust the most.
"""

from __future__ import annotations

import sys

_PACKAGE = "pokeprism_devtools"


def clear() -> int:
    """Empty every `lru_cache` in every module of this package that is loaded.

    Returns how many it emptied, which is worth having: "0" means the discovery
    stopped working, and a cache-clearing function that silently clears nothing
    is worse than no cache-clearing function at all.

    Only *imported* modules are walked, which is exactly the set that could be
    holding anything — a module nobody has imported has no cache to hold.
    """
    cleared = 0
    for name, module in list(sys.modules.items()):
        if not name.startswith(f"{_PACKAGE}.") and name != _PACKAGE:
            continue
        if module is None:
            continue
        for obj in vars(module).values():
            # `cache_clear` is the whole signature of an lru_cache-wrapped
            # function. Duck typing is the right tool here precisely because the
            # point is to catch the ones nobody remembered to register.
            if callable(obj) and callable(getattr(obj, "cache_clear", None)):
                obj.cache_clear()
                cleared += 1
    return cleared
