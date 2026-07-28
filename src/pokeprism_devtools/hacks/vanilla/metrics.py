"""How many tiles each token prints, read out of vanilla's text engine.

This is the one piece of the family's text measuring that is engine-specific, and
it is vanilla's alone. A control code is one byte in the source and many tiles on
the screen — `#` is a single character that prints `POKé`, four tiles, so
`"#mon Center"` is eleven characters and fourteen tiles — and the widths are
read, never reproduced, so a fork that redefines an expansion is measured
correctly for free.

Vanilla dispatches every character byte through the `dict 'token', Handler`
table in `home/text.asm`: a handler either moves the cursor (`LineChar`,
`Paragraph`, …), or `print_name`s a string. A `print_name` of a ROM label — a
`db "…@"` right there in the file — is a *determinate* expansion this measures;
a `print_name` of a WRAM buffer (`wPlayerName`) is a name, which has no
*determinate* width — it counts as nothing to `determinate`, but carries a
worst-case `bound` (seven tiles) that `bounded` sums for `text-width-name`.
Polished dispatches the same glyphs through a Huffman n-gram table instead, so it
brings its own reader of this one shape (`..polished.metrics`); every other part
of the measuring is shared.

Two things read these widths, which is why they sit here rather than in `.lint`:
the linter, to report a line that already overflows, and `.measures`, to put the
tile count in the reword box's gutter while the line is still yours to shorten.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from . import box, charmap

_TEXT_ASM = "home/text.asm"
_TEXT_CONSTANTS = "constants/text_constants.asm"

#: The files vanilla's box, charmap and widths are read from — the last, the
#: dict-and-print_name engine in `home/text.asm`, is the one polished spells
#: differently. Both readers of these widths degrade when one is missing: the
#: linter to silence, the reword gutter to absence.
ENGINE_FILES = ("constants/hardware.inc", _TEXT_CONSTANTS,
                "constants/charmap.asm", _TEXT_ASM)

#: WRAM name buffer -> the constant bounding how long its content can get. The
#: engine can only tell us a `print_name` prints a variable; how many letters the
#: naming screen lets that be is semantic, so the mapping is declared and the
#: number is read from source. Every family name buffer is `PLAYER_NAME_LENGTH`,
#: which counts its terminator — the printed name is one shorter. This is the
#: family's analogue of prism's `_BUFFER_BOUNDS`, and it is what `text-width-name`
#: measures the worst case against.
_NAME_BOUND = {
    "wMomsName": "PLAYER_NAME_LENGTH",
    "wPlayerName": "PLAYER_NAME_LENGTH",
    "wRivalName": "PLAYER_NAME_LENGTH",
    "wRedsName": "PLAYER_NAME_LENGTH",
    "wGreensName": "PLAYER_NAME_LENGTH",
}

#: Handlers that move the cursor or end the string rather than printing a glyph.
#: A width count stops at these — they are the breaks between visual lines, and
#: in a `db` they only ever appear as the terminator. Read off the `dict` table's
#: destinations in home/text.asm; naming them is engine knowledge, not parsing.
_CONTROL = frozenset({
    "LineChar", "NextLineChar", "LineFeedChar", "CarriageReturnChar", "NullChar",
    "Paragraph", "ContText", "_ContText", "_ContTextNoPause", "DoneText", "PromptText",
})

#: rgbds string interpolation — `{d:PRICE}` assembles to the *value* of PRICE, a
#: handful of digits, not the forty characters of its name. It is the family's
#: `deciram`: a variable the source cannot bound, so it is dropped before the
#: count rather than measured as literal text (which flagged every price line in
#: the game as a fifty-tile overflow).
_INTERP_RE = re.compile(r"\{[^}]*\}")

_DICT_RE = re.compile(r"^\s*dict\s+'((?:[^'\\]|\\.)*)'\s*,\s*(\S+)")
_PRINT_NAME_RE = re.compile(r"^(\w+):+\s*print_name\s+(\w+)")
_ROM_STR_RE = re.compile(r'^(\w+)::?\s+db\s+"((?:[^"\\]|\\.)*)"')


@dataclass(frozen=True)
class Tiles:
    """What one source string costs, every way of asking at once.

    Four answers rather than a width, because "how wide is this line" has four
    honest ones and collapsing them loses the distinction the reader needs: a line
    that is over *now*, a line that is over once somebody's name is long, a line
    whose width nobody can know, and a line with a token the engine cannot print.
    """
    determinate: int          # tiles certain to draw
    bounded: int              # extra tiles when every name on it is at its longest
    unbounded: list[str]      # buffers with no bound at all — width unknowable
    unknown: list[str]        # tokens with no charmap entry; a typo'd `<PLAYR>`


@dataclass(frozen=True)
class Metrics:
    """Every token's determinate cost in tiles, and the tokens that end a string.

    `width` holds only the tokens that are not a plain one-tile glyph: the ROM
    expansions at their measured width, and the WRAM name buffers at zero. Every
    other token falls through to one tile, which is what the engine places for it.

    `bound` is the *other* thing a name buffer can be: `<PLAYER>` draws nothing
    determinate, but it draws up to seven tiles once someone types a seven-letter
    name. So a name token sits in both dicts — zero in `width`, its worst case in
    `bound` — and the two are summed by different readers (`determinate` and
    `bounded`) for the two questions `text-width` and `text-width-name` ask.

    `ram_bound` is those same names reached the *other* way: not the inline
    `<PLAYER>` token but the `text_ram wPlayerName` script command, which prints a
    WRAM buffer straight onto the line. It maps the WRAM label to the worst case,
    for the dialogue parser to charge to the line a `text_ram` lands on — a name
    buffer bounds, any other buffer is unbounded and has no entry here.

    `unbounded` is the third thing a buffer token can be: it prints WRAM the text
    cannot bound at all, so it has neither a determinate width nor a worst case —
    zero in `width`, absent from `bound`, and named here. Vanilla has none (every
    buffer its engine prints inline is a name the naming screen bounds); polished
    prints `wTrendyPhrase`, whose content is somebody's typed phrase. A width sum
    that quietly counted these as zero would call a line safe on the strength of a
    string nobody has written yet, so the gutter names them instead.
    """
    width: dict[str, int]
    control: frozenset[str]
    bound: dict[str, int] = field(default_factory=dict)
    ram_bound: dict[str, int] = field(default_factory=dict)
    unbounded: frozenset[str] = frozenset()

    def tiles(self, root: Path, text: str) -> Tiles:
        """Everything one source string costs, in a single walk of its tokens.

        There is one walk and this is it, for the reason there is one parse: the
        linter reads a line's width off disk and the reword gutter reads it out of
        the box you are typing into, and a studio that told you sixteen while the
        linter said nineteen would be worse than one that said nothing. Both stop
        at the first control code, exactly as the engine does — a `@` ends the
        draw and whatever follows it is the next line's problem.
        """
        det = bnd = 0
        unbounded: list[str] = []
        unknown: list[str] = []
        known = charmap.tokens(root)
        for tok in charmap.tokenize(root, _INTERP_RE.sub("", text)):
            if tok in self.control:
                break
            if tok in self.unbounded:
                unbounded.append(tok)
            elif tok not in known:
                unknown.append(tok)
            det += self.width.get(tok, 1)
            bnd += self.bound.get(tok, 0)
        return Tiles(det, bnd, unbounded, unknown)

    def determinate(self, root: Path, text: str) -> int:
        """Tiles a source string is certain to draw — literals and fixed ROM
        expansions, stopping at the first control code or terminator."""
        return self.tiles(root, text).determinate

    def bounded(self, root: Path, text: str) -> int:
        """Extra tiles a string can grow when every name buffer on it is at its
        longest. Nothing until a name is substituted, up to seven per name after —
        the worst-case arithmetic `text-width-name` warns on, stopping at the first
        control code exactly as `determinate` does."""
        return self.tiles(root, text).bounded


def engine_is_readable(root: Path, files: tuple[str, ...]) -> bool:
    """Whether this tree's text engine is all on disk to be measured against.

    A checkout mid-edit, or a fixture that is a handful of maps and no engine, can
    be read and written and linted; what it cannot be is *measured*, because the
    charmap and the widths are the measurement. Both readers of the widths ask
    this and degrade rather than crash on the first `read_text` — the linter to
    silence, the mount to `measures=False`, which is a gutter that is absent
    instead of a gutter that is wrong.
    """
    return all((root / f).is_file() for f in files)


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

    consts = box.equs(root, _TEXT_CONSTANTS, {})
    control = {charmap.TERMINATOR}
    width: dict[str, int] = {}
    bound: dict[str, int] = {}
    unbounded: set[str] = set()
    for token, handler in handler_of.items():
        if handler in _CONTROL:
            control.add(token)
            continue
        target = prints.get(handler)
        if target in rom:
            width[token] = _rom_width(root, rom[target])
        elif target and target.startswith("w"):
            width[token] = 0             # a name: no determinate width to count
            if target in _NAME_BOUND:    # …but a worst case once someone types it
                bound[token] = consts[_NAME_BOUND[target]] - 1
            else:
                unbounded.add(token)     # WRAM this text cannot bound at all
    ram_bound = {buf: consts[c] - 1 for buf, c in _NAME_BOUND.items()}
    return Metrics(width, frozenset(control), bound, ram_bound,
                   frozenset(unbounded))


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
