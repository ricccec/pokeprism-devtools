"""What counts as *one character* to the text engine.

A byte of pokeprism text is not a byte of Python text. ``'d`` is one character
($d0), so is ``<PLAYER>`` ($52), so is ``é`` and ``<PK>`` and ``…``. The engine
places one 8x8 tile per byte, so counting tiles means counting *charmap tokens*,
and counting Python characters gets the answer wrong in both directions:
``"I'd"`` is 3 tiles but 4 Python characters, and ``"<PLAYER>"`` is 1 byte but 8.

macros/charmap.asm is the single source of truth for that mapping — the same
table rgbds itself uses to assemble a string — so it is parsed rather than
reproduced. Longest-match is the rule rgbds applies (``CHARSUB`` in the ``dtxt``
macro walks the string taking the longest charmap entry at each position), so it
is the rule here.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

_REL = "macros/charmap.asm"

#: `charmap "x", $80` and `ctxtmap "x", $80, 1011` — the latter also carries the
#: token's Huffman code, which is no concern of ours. A token may be declared by
#: both (`…` is a ctxtmap, `<...>` a charmap alias for the same byte); the first
#: declaration wins, which matches rgbds.
_MAP_RE = re.compile(
    r'^\s*(?:ctxtmap|charmap)\s+"((?:[^"\\]|\\.)*)"\s*,\s*(\$[0-9a-fA-F]+|\d+)'
)

#: Ends a string early, wherever it appears. 105 strings in maps/ carry it inline
#: rather than relying on a following `done`.
TERMINATOR = "@"


@lru_cache(maxsize=4)
def tokens(root: Path) -> dict[str, int]:
    """Every charmap token -> its byte."""
    out: dict[str, int] = {}
    for line in (root / _REL).read_text().split("\n"):
        m = _MAP_RE.match(line)
        if not m:
            continue
        tok = m.group(1).replace('\\"', '"').replace("\\\\", "\\")
        val = m.group(2)
        out.setdefault(tok, int(val[1:], 16) if val.startswith("$") else int(val))
    return out


@lru_cache(maxsize=4)
def _by_length(root: Path) -> tuple[str, ...]:
    """Tokens longest-first, so the scan below is a longest match."""
    return tuple(sorted(tokens(root), key=len, reverse=True))


def tokenize(root: Path, text: str) -> list[str]:
    """Split a source string into charmap tokens, longest match first.

    A character with no charmap entry is returned as itself. That is not an error
    here — `text_unknown` reports it — because refusing to tokenize would take
    the width rules down with it.
    """
    out: list[str] = []
    i = 0
    table = _by_length(root)
    while i < len(text):
        for tok in table:
            if text.startswith(tok, i):
                out.append(tok)
                i += len(tok)
                break
        else:
            out.append(text[i])
            i += 1
    return out
