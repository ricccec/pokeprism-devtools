"""Polished's dialogue-overflow linter — the family lint with an n-gram reader.

Polished shares the overflow *question* with vanilla, and almost all the answer:
the map event format is the same, so the box, the dialogue parse, the two rules
and the neutral tile arithmetic are vanilla's, reused here unchanged. What it
does not share is the text *engine*. Vanilla dispatches each byte through a
`dict 'token', Handler` table and prints ROM strings by name; polished stores its
strings Huffman-compressed and resolves a byte through an n-gram table
(`data/text/ngrams.asm`) instead — so it forks the one engine-specific piece, the
width `Metrics` reader, exactly as polished's read and write adapters fork
vanilla's rather than pretending the two trees are peers.

The subtlety the fork carries is that an n-gram is one ROM byte but several
screen tiles: `#` is `$4d`, whose string is `Poké`, four tiles, and `the ` is
`$3e`, whose string is four tiles of its own. So the width of every n-gram token
must be *its expansion's* tile count, and that expansion is counted in the
engine's un-compressed charmap, where an apostrophe ligature like `'s` is one
tile and not two — which is why the count is a tokenise, not a `len`.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from ..vanilla.lint import charmap
from ..vanilla.lint.context import FamilyLintContext
from ..vanilla.lint.metrics import Metrics

_CHARMAP = "constants/charmap.asm"
_NGRAMS = "data/text/ngrams.asm"

#: The files polished's box, charmap and widths are read from. It is vanilla's
#: list with the engine file swapped: the n-gram table, not `home/text.asm`.
_ENGINE_FILES = ("constants/hardware.inc", "constants/text_constants.asm",
                 _CHARMAP, _NGRAMS)

#: The cursor and terminator codes — the polished analogue of vanilla's set of
#: control handlers, and engine knowledge the same way. A width run stops at any
#: of these; on the dialogue path the line breaks are the `line`/`next` macros,
#: so inline these appear only as the terminator, but naming them keeps the count
#: honest if one ever does.
_CONTROL = frozenset({
    charmap.TERMINATOR, "<DONE>", "<PROMPT>", "<NEXT>", "<LINE>", "<CONT>",
    "<PARA>", "<LNBRK>",
})

_MAP_RE = re.compile(
    r'^\s*(?:ctxtmap|charmap)\s+"((?:[^"\\]|\\.)*)"\s*,\s*(\$[0-9a-fA-F]+|\d+)'
)
_RANGE_RE = re.compile(
    r"^\s*DEF\s+(NGRAMS_START|NGRAMS_END)\s+EQU\s+(\$[0-9a-fA-F]+|\d+)"
)
_DR_RE = re.compile(r"^\s*dr\s+\.(\S+)")
_RAWCHAR_RE = re.compile(r'^\.([^\s:]+):\s*rawchar\s+"((?:[^"\\]|\\.)*)"')
_DW_RE = re.compile(r"^\.([^\s:]+):\s*dw\b")


@lru_cache(maxsize=4)
def load(root: Path) -> Metrics:
    """Every n-gram token's tile width, read out of polished's engine.

    A token whose byte falls in the n-gram range prints its expansion — several
    tiles for one byte — and gets that tile count; a name buffer (`<PLAYER>`,
    stored in WRAM) has no determinate width and gets zero; every other byte is a
    single tile and falls through to the shared `determinate`'s default of one."""
    byte_of = _bytes_of(root)
    start, end = _ngram_range(root)
    plain = tuple(sorted((tok for tok, b in byte_of.items() if not start <= b <= end),
                         key=len, reverse=True))
    tiles_by_byte = _ngram_tiles(root, start, plain)

    width: dict[str, int] = {}
    for token, byte in byte_of.items():
        if start <= byte <= end and byte in tiles_by_byte:
            width[token] = tiles_by_byte[byte]
    return Metrics(width, _CONTROL)


def build(root: Path) -> FamilyLintContext:
    """Polished's family linter: its n-gram width reader over the shared rules."""
    from ..vanilla.read import label_of
    return FamilyLintContext(root, load, dict(label_of(root)), _ENGINE_FILES)


def _bytes_of(root: Path) -> dict[str, int]:
    """token -> byte, first declaration winning, as rgbds resolves the charmap."""
    out: dict[str, int] = {}
    for line in (root / _CHARMAP).read_text().split("\n"):
        if m := _MAP_RE.match(line):
            tok = _unescape(m.group(1))
            out.setdefault(tok, _num(m.group(2)))
    return out


def _ngram_range(root: Path) -> tuple[int, int]:
    """The `$0a..$51` byte window the n-gram table fills, read from its `DEF`s."""
    bounds: dict[str, int] = {}
    for line in (root / _CHARMAP).read_text().split("\n"):
        if m := _RANGE_RE.match(line):
            bounds[m.group(1)] = _num(m.group(2))
    return bounds["NGRAMS_START"], bounds["NGRAMS_END"]


def _num(text: str) -> int:
    """A charmap literal, `$4d` or plain decimal, as an int."""
    return int(text[1:], 16) if text.startswith("$") else int(text)


def _ngram_tiles(root: Path, start: int, plain: tuple[str, ...]) -> dict[int, int]:
    """byte -> tiles it draws, resolved through the n-gram string table.

    The table is byte-ordered from `start`: the nth `dr .label` is byte
    `start + n`, and each `.label` is either a `rawchar` string (its tiles, in the
    un-compressed charmap where a ligature is one tile) or a `dw` at a WRAM name,
    which prints something with no determinate width — zero here, its bound is a
    later rule's business."""
    src = (root / _NGRAMS).read_text().split("\n")
    byte_of_label: dict[str, int] = {}
    seen = 0
    for line in src:
        if m := _DR_RE.match(line):
            byte_of_label[m.group(1)] = start + seen
            seen += 1

    tiles: dict[int, int] = {}
    for line in src:
        if m := _RAWCHAR_RE.match(line):
            label, expansion = m.group(1), m.group(2)
            if (byte := byte_of_label.get(label)) is not None:
                tiles[byte] = _tile_count(_unescape(expansion), plain)
        elif m := _DW_RE.match(line):
            if (byte := byte_of_label.get(m.group(1))) is not None:
                tiles[byte] = 0
    return tiles


def _tile_count(expansion: str, plain: tuple[str, ...]) -> int:
    """Tiles an n-gram expansion draws — its tokens up to the terminator.

    Counted in the un-compressed (`plain`) charmap, longest match first, so the
    apostrophe ligatures (`'s`, `'d`) that are one tile each are one tile each,
    and a byte with no charmap entry still counts as the single tile it draws."""
    text = expansion.split(charmap.TERMINATOR, 1)[0]
    n, i = 0, 0
    while i < len(text):
        for tok in plain:
            if text.startswith(tok, i):
                i += len(tok)
                break
        else:
            i += 1
        n += 1
    return n


def _unescape(tok: str) -> str:
    return tok.replace('\\"', '"').replace("\\\\", "\\")
