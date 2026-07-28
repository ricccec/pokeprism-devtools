"""What counts as one character to the family text engine.

A byte of dialogue is not a byte of Python: `<PLAYER>` is one byte ($52), so is
`é` and `#` and `<……>`. The engine places one 8x8 tile per byte on the dialogue
path, so counting tiles means counting *charmap tokens*, and counting Python
characters gets it wrong both ways — `"I'd"` is 3 tiles but 4 characters, and
`"<PLAYER>"` is 1 byte but 8.

`constants/charmap.asm` is the table rgbds itself assembles with, so it is parsed
rather than reproduced — a fork that adds a glyph gets it counted for free. This
is the family's copy of prism's `charmap`, kept here because the seam forbids a
family module reaching into prism's; the file it reads and the macros it accepts
are the family's, not prism's `macros/charmap.asm`.

It sits beside `.box` and `.dialogue` rather than inside `.lint` for the reason
they do: both halves of the family's text work read it. The linter counts a
line's tiles to report an overflow after the fact, and `.measures` counts the
same tiles under the reword box while you can still shorten the line.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

_REL = "constants/charmap.asm"

#: `charmap "x", $80`, and polished's `ctxtmap "x", $80, 1011` (whose third
#: argument, a Huffman code, is no concern of a tile count). The first
#: declaration of a token wins, which is the rule rgbds applies.
_MAP_RE = re.compile(
    r'^\s*(?:ctxtmap|charmap)\s+"((?:[^"\\]|\\.)*)"\s*,\s*(\$[0-9a-fA-F]+|\d+)'
)

#: Ends a string wherever it appears — the family carries it inline in a `db`
#: rather than always relying on a following `done`.
TERMINATOR = "@"


@lru_cache(maxsize=4)
def tokens(root: Path) -> tuple[str, ...]:
    """Every charmap token, longest-first so a scan is a longest match."""
    seen: dict[str, None] = {}
    for line in (root / _REL).read_text().split("\n"):
        if m := _MAP_RE.match(line):
            tok = m.group(1).replace('\\"', '"').replace("\\\\", "\\")
            seen.setdefault(tok, None)
    return tuple(sorted(seen, key=len, reverse=True))


def tokenize(root: Path, text: str) -> list[str]:
    """Split a source string into charmap tokens, longest match first.

    A character with no charmap entry is returned as itself and counts as one
    tile — rgbds would have rejected it, so on a tree that builds this never
    happens, and refusing to tokenize would take the width count down with it.
    """
    out: list[str] = []
    i = 0
    table = tokens(root)
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
