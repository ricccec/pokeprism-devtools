"""Does this constant exist? — asked of the enums the content scaffolds emit.

rgbds resolves symbols at *link* time, so a typo'd species or a Pokémon that
this fork doesn't have (pokeprism drops most of the Kanto dex) doesn't surface
until the whole ROM links, minutes later, as ``Unknown symbol "RATTATA"`` with
nothing to say about which trainer you were writing.

The build does catch these — that's why there's no lint rule here. But a tool
that is *about* to write one into three files should say so before it does.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

SPECIES = "constants/pokemon_constants.asm"
ITEMS = "constants/item_constants.asm"
MOVES = "constants/move_constants.asm"
SPRITES = "constants/sprite_constants.asm"

#: `const NAME`, `NAME EQU x`, `NAME = x`, `NAME EQUS "…"` — every way a name is
#: bound at file scope. Values are irrelevant here; only existence is.
_CONST_RE = re.compile(r"^\s*const\s+([A-Za-z_]\w*)\s*(?:;.*)?$")
_DEF_RE = re.compile(r"^([A-Za-z_]\w*)\s+(?:EQU|EQUS|=)\s")


@lru_cache(maxsize=16)
def names(root: Path, rel: str) -> frozenset[str]:
    """Every constant name defined in one constants file."""
    path = root / rel
    if not path.exists():
        return frozenset()

    out: set[str] = set()
    for line in path.read_text().split("\n"):
        if m := _CONST_RE.match(line):
            out.add(m.group(1))
        elif m := _DEF_RE.match(line):
            out.add(m.group(1))
    return frozenset(out)


def with_prefix(root: Path, rel: str, prefix: str) -> frozenset[str]:
    return frozenset(n for n in names(root, rel) if n.startswith(prefix))


def suggest(name: str, known: frozenset[str], limit: int = 3) -> list[str]:
    """The closest few real names, for an error message that helps."""
    import difflib
    return difflib.get_close_matches(name, known, n=limit, cutoff=0.6)
