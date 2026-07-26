"""Every rendered line of a map's dialogue, and the box it draws in.

The family model is simpler than prism's: one break macro is one visual line.
`text` opens a box, each of `line`/`cont`/`para`/`next` ends the line before it
and starts the next, and `done` — or a `@` inside the last string — closes the
box. There is no inline `<LINE>`/`<NEXT>` cursor code to interpret *inside* a
string, so a source line maps to a rendered line without walking the bytes.

What each line needs to be judged: where it lands (from the box's cursor rules)
and how wide it is (from the tree's own `Metrics`). The width reader is the only
part that differs between family trees; this parse, and the rules over it, do not.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import box
from .box import Box
from .metrics import Metrics

#: Break macro -> what it does to the cursor. `text` opens the box; `para` starts
#: a fresh one at the top row; `line` is the absolute second row; `cont` scrolls
#: and reuses it; `next`/`next1` walk down relatively (the latter is polished's).
_ACTION = {
    "text": box.OPEN, "para": box.OPEN, "line": box.LINE_ABS,
    "cont": box.SCROLL, "next": box.DOWN_2, "next1": box.DOWN_1,
}
_OPENER = "text"
_ENDERS = frozenset({"done", "prompt", "page"})

_MACRO_RE = re.compile(r"^\s*(\w+)\b(.*)$")
_STR_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')
#: rgbds string interpolation — `{d:PRICE}` assembles to the *value* of PRICE, a
#: handful of digits, not the forty characters of its name. It is the family's
#: `deciram`: a variable the source cannot bound, so it is dropped from the
#: determinate count rather than measured as literal text (which flagged every
#: price line in the game as a fifty-tile overflow).
_INTERP_RE = re.compile(r"\{[^}]*\}")


@dataclass(frozen=True)
class Line:
    """One rendered line of a box."""
    lineno: int          # 1-based, in the map's asm
    macro: str           # the macro that opened it: text, line, para, …
    row: int             # the screen row it lands on
    determinate: int     # tiles certain to draw — literals and fixed expansions
    bounded: int         # extra tiles when every name buffer on it is at its bound
    text: str            # the source string(s), joined — for naming the culprit

    @property
    def worst(self) -> int:
        """Tiles when every name buffer here is at its longest — the width a
        seven-letter name makes real. `text-width-name`'s question."""
        return self.determinate + self.bounded


@dataclass(frozen=True)
class Block:
    """One text box's worth of rendered lines, `text` through `done`."""
    lines: list[Line]


def parse(root: Path, path: Path, metrics: Metrics) -> list[Block]:
    """Every dialogue box in one map file."""
    speech = box.speech_box(root)
    blocks: list[Block] = []
    cur: list[Line] = []

    def close() -> None:
        if cur:
            blocks.append(Block(list(cur)))
            cur.clear()

    for i, raw in enumerate(path.read_text(encoding="utf-8").split("\n"), start=1):
        m = _MACRO_RE.match(_decomment(raw))
        if not m:
            continue
        word, rest = m.group(1), m.group(2)

        if word == _OPENER:
            close()
            cur.append(_line(root, speech, i, word, speech.first_row, metrics, rest))
        elif word in _ACTION and cur:
            row = speech.rows_for(_ACTION[word], cur[-1].row)
            cur.append(_line(root, speech, i, word, row, metrics, rest))
        elif word in _ENDERS:
            close()
            continue
        if cur and _terminates(rest):
            close()

    close()
    return blocks


def _line(root: Path, speech: Box, lineno: int, macro: str, row: int,
          metrics: Metrics, rest: str) -> Line:
    strings = [_INTERP_RE.sub("", _unescape(s)) for s in _STR_RE.findall(rest)]
    width = sum(metrics.determinate(root, s) for s in strings)
    bnd = sum(metrics.bounded(root, s) for s in strings)
    return Line(lineno, macro, row, width, bnd, "".join(strings))


def _terminates(rest: str) -> bool:
    """Whether a `@` inside one of this macro's strings ends the box itself."""
    return any("@" in _unescape(s) for s in _STR_RE.findall(rest))


def _decomment(raw: str) -> str:
    """Drop a trailing comment, but not a `;` inside a string."""
    out: list[str] = []
    in_string = escaped = False
    for ch in raw:
        if escaped:
            out.append(ch)
            escaped = False
        elif ch == "\\":
            out.append(ch)
            escaped = True
        elif ch == '"':
            in_string = not in_string
            out.append(ch)
        elif ch == ";" and not in_string:
            break
        else:
            out.append(ch)
    return "".join(out)


def _unescape(s: str) -> str:
    return s.replace('\\"', '"')
