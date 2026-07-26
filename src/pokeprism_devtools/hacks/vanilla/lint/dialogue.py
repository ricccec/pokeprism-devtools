"""Every rendered line of a map's dialogue, and the box it draws in.

The family model is a cursor walked by a stream of script commands. `text` opens
the box and draws until a `@`; `line`/`cont`/`para`/`next` each carry a break code
that ends the line before them and start the next; `done` closes the box. Most
boxes are one `text` whose string holds the break codes inline, so one source
macro is one visual line and the parse barely has to think.

What makes it a cursor and not a line-per-macro is the buffer commands. A `@` ends
a *draw*, not the box — it hands control back to the command interpreter, which
runs the next command at the same cursor. So `line "your @"`, `text_ram
wStringBuffer3`, `text "…"` is one visual line, `your <mon>…`, split across three
commands because a name is spliced into the middle of it. The parse has to join
them: a `text_ram` (or a `text` after one) continues the current line rather than
starting a box of its own, which is the whole reason it accumulates onto a line
in progress instead of emitting one per macro.

What each line needs to be judged: where it lands (from the box's cursor rules)
and how wide it is (from the tree's own `Metrics`). The width reader is the only
part that differs between family trees; this parse, and the rules over it, do not.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import box
from .box import Box
from .metrics import Metrics

#: Break macro -> what it does to the cursor. Each carries a leading break code,
#: so it ends the line before it and starts a new one: `para` at the top row of a
#: fresh box, `line` at the absolute second row, `cont` scrolls and reuses it,
#: `next`/`next1` walk down relatively (the latter is polished's).
_BREAK = {
    "para": box.OPEN, "line": box.LINE_ABS,
    "cont": box.SCROLL, "next": box.DOWN_2, "next1": box.DOWN_1,
}
#: Draw commands — `TX_START` under two names. They print a string at the cursor
#: without moving to a new line, so they open the box's first line if none is open
#: yet and otherwise continue the line in progress (the `text` after a `text_ram`).
_DRAW = frozenset({"text", "text_start"})
#: Buffer commands — they splice a WRAM string onto the current line. `text_ram`
#: (and its legacy alias) prints a named buffer; `text_buffer` prints a numbered
#: one. A name buffer is bounded, any other is unbounded — `_add_ram` decides.
_RAM = frozenset({"text_ram", "text_from_ram", "text_buffer"})
#: Commands that close the box: `done`/`prompt` end a speech, `page` ends a dex
#: page, `text_end` ends the raw text stream.
_END = frozenset({"done", "prompt", "page", "text_end"})
#: rgbds conditional assembly. `if`/`elif`/`else`/`endc` guard branches only one
#: of which compiles — `if DEF(FAITHFUL) / text "…" / else / text "…" / endc` is
#: one visual line in two builds, not two on top of each other. A branch boundary
#: reopens the line from where the conditional started, so the alternatives are
#: measured as siblings instead of concatenated into one impossible line.
_COND_OPEN = frozenset({"if"})
_COND_ALT = frozenset({"else", "elif"})
_COND_END = frozenset({"endc"})

#: A label at column zero — a new text block starts here, so the open box (if any)
#: closes. This is what ends a box that runs to the next label with no `done`.
_LABEL_RE = re.compile(r"^\w+::?")
_MACRO_RE = re.compile(r"^\s*(\w+)\b(.*)$")
_STR_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')
#: The WRAM label or buffer id a `text_ram`/`text_buffer` prints — its first arg.
_RAM_ARG_RE = re.compile(r"^\s*(\w+)")
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
    unbounded: list[str] = field(default_factory=list)  # buffers with no bound

    @property
    def worst(self) -> int:
        """Tiles when every name buffer here is at its longest — the width a
        seven-letter name makes real. `text-width-name`'s question. This does not
        include `unbounded` buffers, which have no worst case to add."""
        return self.determinate + self.bounded


@dataclass(frozen=True)
class Block:
    """One text box's worth of rendered lines, `text` through `done`."""
    lines: list[Line]


def parse(root: Path, path: Path, metrics: Metrics) -> list[Block]:
    """Every dialogue box in one map file."""
    speech = box.speech_box(root)
    blocks: list[Block] = []
    cur: list[dict] = []
    cond: list[int] = []    # row each open conditional began on, for its branches
    base: int | None = None  # a branch boundary: next line reopens from this row

    def close() -> None:
        nonlocal base
        drawn = [b for b in cur if b["text"] or b["unbounded"]]
        if drawn:
            blocks.append(Block([_freeze(b) for b in drawn]))
        cur.clear()
        cond.clear()
        base = None

    for i, raw in enumerate(path.read_text(encoding="utf-8").split("\n"), start=1):
        if _LABEL_RE.match(raw):
            close()
            continue
        m = _MACRO_RE.match(_decomment(raw))
        if not m:
            continue
        word, rest = m.group(1), m.group(2)

        if word in _COND_OPEN:
            cond.append(cur[-1]["row"] if cur else speech.first_row)
        elif word in _COND_ALT and cond:
            base = cond[-1]          # the alternative reopens from the branch's top
        elif word in _COND_END:
            if cond:
                cond.pop()
            base = None
        elif word in _END:
            close()
        elif word in _BREAK and (cur or base is not None):
            prev = base if base is not None else cur[-1]["row"]
            cur.append(_open(i, word, speech.rows_for(_BREAK[word], prev)))
            _add_strings(cur[-1], root, metrics, rest)
            base = None
        elif word in _DRAW or word in _RAM:
            if not cur or base is not None:
                cur.append(_open(i, word, base if base is not None else speech.first_row))
                base = None
            if word in _RAM:
                _add_ram(cur[-1], metrics, rest)
            else:
                _add_strings(cur[-1], root, metrics, rest)
        # anything else — a sound, a pause, an unmodelled command — draws nothing
        # that moves the cursor off this line, so it neither opens nor breaks one.

    close()
    return blocks


def _open(lineno: int, macro: str, row: int) -> dict:
    """A fresh line builder — a mutable line accumulating its commands' widths."""
    return {"lineno": lineno, "macro": macro, "row": row,
            "det": 0, "bnd": 0, "text": [], "unbounded": []}


def _add_strings(b: dict, root: Path, metrics: Metrics, rest: str) -> None:
    """Charge a draw command's string(s) to the line — literal and name widths,
    stopping at the `@` that ends the draw exactly as the engine does."""
    for s in (_INTERP_RE.sub("", _unescape(x)) for x in _STR_RE.findall(rest)):
        b["det"] += metrics.determinate(root, s)
        b["bnd"] += metrics.bounded(root, s)
        b["text"].append(s)


def _add_ram(b: dict, metrics: Metrics, rest: str) -> None:
    """Charge a `text_ram`/`text_buffer` to the line. A name buffer adds its
    worst case to the bounded width, like an inline `<PLAYER>`; any other buffer
    holds something the text cannot bound, so it is recorded unbounded and adds
    no width — the worst case is unknown, not zero, which `text-buffer` reads."""
    m = _RAM_ARG_RE.match(rest)
    target = m.group(1) if m else ""
    if target in metrics.ram_bound:
        b["bnd"] += metrics.ram_bound[target]
    elif target:
        b["unbounded"].append(target)


def _freeze(b: dict) -> Line:
    return Line(b["lineno"], b["macro"], b["row"], b["det"], b["bnd"],
                "".join(b["text"]), b["unbounded"])


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
