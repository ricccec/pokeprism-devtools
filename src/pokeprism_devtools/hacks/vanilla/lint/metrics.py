"""How many tiles each token prints, read out of vanilla's text engine.

This is the one piece of the family overflow lint that is engine-specific, and
it is vanilla's alone. A control code is one byte in the source and many tiles on
the screen — `#` is a single character that prints `POKé`, four tiles, so
`"#mon Center"` is eleven characters and fourteen tiles — and the widths are
read, never reproduced, so a fork that redefines an expansion is measured
correctly for free.

Vanilla dispatches every character byte through the `dict 'token', Handler`
table in `home/text.asm`: a handler either moves the cursor (`LineChar`,
`Paragraph`, …), or `print_name`s a string. A `print_name` of a ROM label — a
`db "…@"` right there in the file — is a *determinate* expansion this measures;
a `print_name` of a WRAM buffer (`wPlayerName`) is a name, which has no width
until someone types it and so counts as nothing here (its bound is `text-width`'s
Move-C business, not this). Polished dispatches the same glyphs through a Huffman
n-gram table instead, so it will bring its own reader of this one shape; every
other part of the family lint is shared.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from . import charmap

_TEXT_ASM = "home/text.asm"

#: Handlers that move the cursor or end the string rather than printing a glyph.
#: A width count stops at these — they are the breaks between visual lines, and
#: in a `db` they only ever appear as the terminator. Read off the `dict` table's
#: destinations in home/text.asm; naming them is engine knowledge, not parsing.
_CONTROL = frozenset({
    "LineChar", "NextLineChar", "LineFeedChar", "CarriageReturnChar", "NullChar",
    "Paragraph", "ContText", "_ContText", "_ContTextNoPause", "DoneText", "PromptText",
})

_DICT_RE = re.compile(r"^\s*dict\s+'((?:[^'\\]|\\.)*)'\s*,\s*(\S+)")
_PRINT_NAME_RE = re.compile(r"^(\w+):+\s*print_name\s+(\w+)")
_ROM_STR_RE = re.compile(r'^(\w+)::?\s+db\s+"((?:[^"\\]|\\.)*)"')


@dataclass(frozen=True)
class Metrics:
    """Every token's determinate cost in tiles, and the tokens that end a string.

    `width` holds only the tokens that are not a plain one-tile glyph: the ROM
    expansions at their measured width, and the WRAM name buffers at zero. Every
    other token falls through to one tile, which is what the engine places for it.
    """
    width: dict[str, int]
    control: frozenset[str]

    def determinate(self, root: Path, text: str) -> int:
        """Tiles a source string is certain to draw — literals and fixed ROM
        expansions, stopping at the first control code or terminator."""
        total = 0
        for tok in charmap.tokenize(root, text):
            if tok in self.control:
                break
            total += self.width.get(tok, 1)
        return total


@lru_cache(maxsize=4)
def load(root: Path) -> Metrics:
    """Read the dict table and the strings it prints, once per tree."""
    src = (root / _TEXT_ASM).read_text().split("\n")

    handler_of: dict[str, str] = {}      # token -> the routine that draws it
    prints: dict[str, str] = {}          # handler -> the buffer/label it prints
    rom: dict[str, str] = {}             # ROM label -> its string
    for line in src:
        if m := _DICT_RE.match(line):
            handler_of[_unescape(m.group(1))] = m.group(2)
        if m := _PRINT_NAME_RE.match(line):
            prints[m.group(1)] = m.group(2)
        elif m := _ROM_STR_RE.match(line):
            rom[m.group(1)] = m.group(2)

    control = {charmap.TERMINATOR}
    width: dict[str, int] = {}
    for token, handler in handler_of.items():
        if handler in _CONTROL:
            control.add(token)
            continue
        target = prints.get(handler)
        if target in rom:
            width[token] = _rom_width(root, rom[target])
        elif target and target.startswith("w"):
            width[token] = 0             # a name: no determinate width to count
    return Metrics(width, frozenset(control))


def _rom_width(root: Path, text: str) -> int:
    """Tiles a ROM expansion prints — its tokens up to the terminator. Every one
    is a plain glyph (`"POKé@"` is four, `"<PK><MN>@"` is two), so counting the
    tokens is the whole of it."""
    n = 0
    for tok in charmap.tokenize(root, text):
        if tok == charmap.TERMINATOR:
            break
        n += 1
    return n


def _unescape(tok: str) -> str:
    return tok.replace('\\"', '"').replace("\\\\", "\\")
