"""The pokecrystal family's map listing, read with no opinion about it.

`data/maps/maps.asm` lists every map and the source file that holds it; this
returns the first of those files that exists, as `(label, text)`. That is the
one read vanilla and polished share when they recognise a tree — and all they
share: *which* file, not what its contents mean. Where the event block sits in
it — vanilla's `_MapEvents` tail, polished's `_MapScriptHeader` head — is each
hack's own question, asked in its own `claim.py`, never here. It lives in
`shared/` so that neither hack imports the other to borrow it.
"""

from __future__ import annotations

import re
from pathlib import Path

_LISTING = re.compile(r"^\s*map\s+(\w+)\s*,")


def first_listed_map(root: Path) -> tuple[str, str] | None:
    """The first map `data/maps/maps.asm` lists whose source file is present, as
    `(label, source text)`. `None` when that file is absent, lists no map, or
    lists only maps whose `.asm` is missing — every "there is nothing here to
    read", which the caller then reports in its own words."""
    try:
        listing = (root / "data/maps/maps.asm").read_text(encoding="utf-8")
    except OSError:
        return None
    for m in map(_LISTING.match, listing.splitlines()):
        if m is None:
            continue
        src = root / f"maps/{m.group(1)}.asm"
        if src.exists():
            return m.group(1), src.read_text(encoding="utf-8", errors="replace")
    return None
