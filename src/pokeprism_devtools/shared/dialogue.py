"""Every line of text a map draws, and the box it draws it in.

The unit here is the *rendered line*, not the source line: ``ctxt`` opens one,
each cursor-moving macro (``line``, ``para``, ``cont``, ``next``, ``nl``) ends
the previous one and opens the next, and ``done`` — or an ``@`` inside a string,
which 105 of pokeprism's strings use instead — closes the block.

Which box a block lands in is not visible in the block. A signpost is reached
either by ``signpost y, x, SIGNPOST_LOAD, Label`` in the event header, or by a
script that calls the ``loadsignpost`` command — Route55's direction sign does
the latter, checks which way you're facing, and jumps to one of four *local*
labels. Local labels belong to the last top-level label in rgbds, so the box is
a property of the block's owner, and that is how it is resolved here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import charmap, textbox
from .textbox import Box, Metrics

#: Opens a text block. `stxt` is `loadsignpost`'s flavour of `ctxt` (macros/text.asm)
_OPENERS = ("text", "ctxt", "stxt")

_LABEL_RE = re.compile(r"^(\.?\w+):{0,2}\s*$")
_MACRO_RE = re.compile(r"^\s*(\w+)\b(.*)$")
_STR_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')
_SIGN_RE = re.compile(r"^\s*signpost\s+[^,]+,\s*[^,]+,\s*SIGNPOST_LOAD\s*,\s*(\w+)")
_LOADSIGN_RE = re.compile(r"^\s*loadsignpost\b")


@dataclass(frozen=True)
class Line:
    """One rendered line of a text block."""
    lineno: int          # 1-based, in the map's asm
    macro: str           # the macro that opened it: ctxt, line, para, …
    action: str          # what that macro did to the cursor ("" for an opener)
    row: int             # the screen row it lands on
    text: str            # the source string(s), joined
    determinate: int     # tiles that are certain
    bounded: int         # extra tiles when every bounded buffer is at its max
    unbounded: list[str] = field(default_factory=list)   # <STRBF*>, text_from_ram
    unknown: list[str] = field(default_factory=list)     # not in the charmap

    @property
    def worst(self) -> int:
        """Tiles when every buffer we *can* bound is at its bound."""
        return self.determinate + self.bounded


@dataclass(frozen=True)
class Block:
    label: str           # the label the text hangs off
    owner: str           # the top-level label that owns it (== label, unless local)
    box: Box
    lineno: int          # where the block opens
    lines: list[Line]


def sign_owners(source: list[str]) -> set[str]:
    """Top-level labels whose text is drawn in the full-screen signpost box.

    Two ways in, and both are needed: the `SIGNPOST_LOAD` event type, and the
    `loadsignpost` script command (only Route55 uses it, and it is registered as
    a plain `SIGNPOST_READ`, so reading the event header alone gets it wrong).
    """
    owners: set[str] = set()
    owner: str | None = None
    for raw in source:
        line = raw.split(";")[0]
        if m := _SIGN_RE.match(line):
            owners.add(m.group(1))
        if m := _LABEL_RE.match(line.rstrip()):
            if not m.group(1).startswith("."):
                owner = m.group(1)
        elif _LOADSIGN_RE.match(line) and owner:
            owners.add(owner)
    return owners


def parse(root: Path, path: Path) -> list[Block]:
    """Every text block in one map."""
    source = path.read_text().split("\n")
    mt = textbox.metrics(root)
    bx = textbox.boxes(root)
    signs = sign_owners(source)

    blocks: list[Block] = []
    cur: list[Line] = []
    box = bx["speech"]
    owner = label = ""
    opened = 0
    open_block = False

    # the line being accumulated
    row = 0
    macro = ""
    act = ""
    at = 0
    det = bnd = 0
    unb: list[str] = []
    unk: list[str] = []
    parts: list[str] = []

    def close_line() -> None:
        nonlocal det, bnd, unb, unk, parts
        if not open_block:
            return
        cur.append(Line(at, macro, act, row, " ".join(parts), det, bnd,
                        list(unb), list(unk)))
        det = bnd = 0
        unb, unk, parts = [], [], []

    def close_block() -> None:
        nonlocal open_block
        if not open_block:
            return
        close_line()
        blocks.append(Block(label, owner, box, opened, list(cur)))
        cur.clear()
        open_block = False

    for i, raw in enumerate(source, start=1):
        line = raw.split(";")[0].rstrip()

        if m := _LABEL_RE.match(line):
            name = m.group(1)
            if not name.startswith("."):
                close_block()
                owner = name
            label = name
            continue

        m = _MACRO_RE.match(line)
        if not m:
            continue
        name, rest = m.group(1), m.group(2)

        if name in _OPENERS:
            close_block()
            box = bx["sign"] if owner in signs else bx["speech"]
            open_block = True
            opened = i
            row, macro, act, at = box.first_row, name, "", i
            det, bnd, unb, unk, parts = _measure(root, mt, rest)
            if _terminates(root, rest):
                close_block()
            continue

        if not open_block:
            continue

        token = mt.macro_token.get(name)
        action = mt.action.get(token) if token else None

        if action == textbox.END:
            close_block()
            continue

        if action is not None:
            close_line()
            row = box.rows_for(action, row)
            macro, act, at = name, action, i
            det, bnd, unb, unk, parts = _measure(root, mt, rest)
            # `@` inside this macro's own string still closes the block
            if _terminates(root, rest):
                close_block()
            continue

        if name == "deciram":
            # deciram addr, bytes, digits -> prints `digits` tiles
            args = [a.strip() for a in rest.split(",")]
            try:
                det += int(args[-1])
            except (ValueError, IndexError):
                pass
            continue

        if name == "text_from_ram":
            unb.append("text_from_ram")
            continue

    close_block()
    return blocks


def _measure(root: Path, mt: Metrics, rest: str):
    det = bnd = 0
    unb: list[str] = []
    unk: list[str] = []
    parts: list[str] = []
    for s in _STR_RE.findall(rest):
        s = s.replace('\\"', '"')
        d, b, u, k = mt.tiles(root, s)
        det += d
        bnd += b
        unb += u
        unk += k
        parts.append(s)
    return det, bnd, unb, unk, parts


def _terminates(root: Path, rest: str) -> bool:
    """Whether a `@` inside one of these strings ends the block itself."""
    return any(charmap.TERMINATOR in charmap.tokenize(root, s.replace('\\"', '"'))
               for s in _STR_RE.findall(rest))
