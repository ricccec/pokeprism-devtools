"""Every rendered line of a map's dialogue, and the source macros behind it.

The family model is a cursor walked by a stream of script commands. `text` opens
the box and draws until a `@`; `line`/`cont`/`para`/`next` each carry a break code
that ends the line before them and start the next; `done` closes the box. Most
boxes are one `text` whose break codes are the macros under it, so one source
macro is one visual line and the walk barely has to think.

What makes it a cursor and not a line-per-macro is the buffer commands. A `@` ends
a *draw*, not the box — it hands control back to the command interpreter, which
runs the next command at the same cursor. So `line "your @"`, `text_ram
wStringBuffer3`, `text "…"` is one visual line, `your <mon>…`, split across three
commands because a name is spliced into the middle of it. So a :class:`Line` here
holds a *list* of :class:`Draw`s, one per source macro that put ink on it, and the
distinction between "one line, one macro" and "one line, three macros" is the
whole reason :mod:`.text` can reword the first and refuses the second.

**There is one parse, and this is it.** There used to be two — a naive
line-per-macro reading behind the Texts browser, and the linter's cursor walk —
and they disagreed about which lines exist. That is survivable while both only
*read*; it stops being survivable the moment something writes, because the block
the reader shows you and the block the writer splices have to be the same block or
your edit lands on the wrong line. So the reader (`events.texts`), the measurer
(`lint/dialogue`) and the writer (`text`) all come through here, and each adds its
own layer: prose, tile widths, macros back.

No widths and no rows are computed here, and that is deliberate. Both need the
engine read off disk — the charmap, `home/text.asm`, the box constants — and the
Texts browser must keep working on a tree whose engine files are mid-edit or
absent. So a `Line` carries what its *action* is and which line its cursor starts
from, and :func:`rows` turns that into screen rows for the two callers that have a
`Box` to ask.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import box
from .box import Box

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
#: one.
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
_TOP_LABEL = re.compile(r"^(\w+):{1,2}")
#: A local label, which belongs to the last top-level one. It does *not* close the
#: box: `done` has almost always done that already, and the rare one that lands
#: mid-box is recorded instead (:attr:`Block.inner_label`) so the writer can refuse
#: to splice across a jump target rather than move it.
_LOCAL_LABEL = re.compile(r"^(\.\w+):{1,2}")
_MACRO_RE = re.compile(r"^\s*(\w+)\b(.*)$")
_STR_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')
#: The WRAM label or buffer id a `text_ram`/`text_buffer` prints — its first arg.
_RAM_ARG_RE = re.compile(r"^\s*(\w+)")

#: Ends a *draw*. The family carries it inline in a string rather than always
#: relying on a following `done`.
TERMINATOR = "@"


@dataclass(frozen=True)
class Draw:
    """One source macro's contribution to a rendered line."""
    lineno: int          # 1-based, in the map's asm
    macro: str           # text, line, para, text_ram, …
    strings: tuple[str, ...] = ()   # its quoted strings, unescaped
    buffer: str = ""     # the WRAM label a text_ram/text_buffer prints


@dataclass(frozen=True)
class Line:
    """One rendered line of a box — everything that lands on one screen row."""
    action: str          # what the macro that opened it did to the cursor
    #: The line whose row this one's cursor starts from, by index into the
    #: block — `None` for the box's own first line. Normally the line above;
    #: for the second branch of a conditional, the line the `if` sat under, so
    #: the alternatives are siblings rather than a stack.
    starts_from: int | None
    draws: tuple[Draw, ...]
    #: Whether a blank source line sat above this one. Pure formatting, and the
    #: repo is of two minds about it, so a rewrite copies what was there rather
    #: than imposing a house style and churning blocks nobody touched.
    blank_before: bool = False

    @property
    def lineno(self) -> int:
        return self.draws[0].lineno

    @property
    def macro(self) -> str:
        return self.draws[0].macro

    @property
    def text(self) -> str:
        """The source strings on this line, joined — what it says."""
        return "".join(s for d in self.draws for s in d.strings)

    @property
    def buffers(self) -> list[str]:
        return [d.buffer for d in self.draws if d.buffer]

    @property
    def simple(self) -> bool:
        """Whether this line is one macro with one string, which is the shape a
        positional rewrite can put back. Anything else — a name spliced into the
        middle of it, a macro that draws nothing of its own — is a line whose
        words do not map onto one source line, and :mod:`.text` refuses it."""
        return len(self.draws) == 1 and len(self.draws[0].strings) == 1


@dataclass(frozen=True)
class Block:
    """One text box's worth of rendered lines, `text` through `done`."""
    label: str           # what a script jumps to, or `.local` under an owner
    owner: str           # the top-level label that owns it (== label, unless local)
    lineno: int          # where the block's first macro is
    #: Last source line of the block, inclusive. With `lineno` this is the span a
    #: rewrite replaces — the label above it is not ours to touch.
    end: int
    #: The macro that closed the block, or "" where a label, the end of the file
    #: or an `@` inside the last string did.
    closer: str
    lines: tuple[Line, ...]
    #: Whether `if`/`else`/`endc` guard part of this block. Two branches are one
    #: line in two builds, so the prose has more lines than the box draws.
    conditional: bool = False
    #: A local label found *inside* the box — a jump target a splice would move.
    inner_label: str = ""

    @property
    def words(self) -> list[str]:
        """Each rendered line's words, terminator stripped where it is the thing
        that closed the block. 105 strings in the family end that way rather than
        with a `done`, and showing the `@` would invite somebody to delete it."""
        out = [line.text for line in self.lines]
        if out and not self.closer and out[-1].endswith(TERMINATOR):
            out[-1] = out[-1][:-1]
        return out

    @property
    def prose(self) -> str:
        """The block as editable text: one screen line per line, a blank line
        wherever it starts a fresh box. What the Texts browser lists and what the
        reword form opens with — see :func:`.text.render` for the way back."""
        out: list[str] = []
        for i, (line, words) in enumerate(zip(self.lines, self.words)):
            if i and line.action == box.OPEN:
                out.append("")
            out.append(words)
        return "\n".join(out)


def parse(path: Path) -> list[Block]:
    """Every dialogue box in one map file."""
    return parse_source(path.read_text(encoding="utf-8").split("\n"))


def parse_source(source: list[str]) -> list[Block]:
    """The same, over lines already in hand — for a caller partway through
    changing the map, who needs to find a block in the file as it *will* be."""
    blocks: list[Block] = []
    lines: list[dict] = []
    owner = label = ""
    block_label = block_owner = ""
    last = 0
    closer = ""
    inner = ""
    conditional = False
    #: Where each open conditional began, by line index — `None` for one that
    #: opened before the box had a line.
    cond: list[int | None] = []
    #: A branch boundary: the next line reopens from this line rather than from
    #: the one above it. Two variables because the index is legitimately `None`.
    base: int | None = None
    on_base = False

    def begin(lineno: int, macro: str, action: str, frm: int | None) -> None:
        nonlocal block_label, block_owner
        if not lines:
            block_label, block_owner = label, owner
        lines.append({"action": action, "from": frm, "draws": [],
                      "blank": lineno >= 2 and source[lineno - 2].strip() == ""})

    def close() -> None:
        nonlocal lines, closer, inner, conditional, cond, base, on_base
        # Nothing is dropped here, and `Line.starts_from` is why: it is an index
        # into this list, so removing a line renumbers the ones that point past
        # it. A line that draws nothing (a bare `text_start`) is a line the
        # linter has no width to report and the writer refuses to splice, and
        # both say so for themselves.
        if lines:
            blocks.append(Block(
                block_label, block_owner, lines[0]["draws"][0].lineno, last,
                closer, tuple(_freeze(ln) for ln in lines), conditional, inner))
        lines = []
        closer = inner = ""
        conditional = False
        cond = []
        base, on_base = None, False

    for i, raw in enumerate(source, start=1):
        if m := _TOP_LABEL.match(raw):
            close()
            owner = label = m.group(1)
            continue
        if m := _LOCAL_LABEL.match(raw.strip()):
            if lines and not inner:
                inner = m.group(1)
            label = m.group(1)
            continue

        m = _MACRO_RE.match(_decomment(raw))
        if not m:
            continue
        word, rest = m.group(1), m.group(2)

        if word in _COND_OPEN:
            conditional = True
            cond.append(len(lines) - 1 if lines else None)
        elif word in _COND_ALT and cond:
            conditional = True
            base, on_base = cond[-1], True
        elif word in _COND_END:
            if cond:
                cond.pop()
            base, on_base = None, False
        elif word in _END:
            last, closer = i, word
            close()
        elif word in _BREAK and (lines or on_base):
            begin(i, word, _BREAK[word], base if on_base else len(lines) - 1)
            base, on_base = None, False
            lines[-1]["draws"].append(_draw(i, word, rest))
            last = i
        elif word in _DRAW or word in _RAM:
            if not lines or on_base:
                # A draw with no break before it opens the box's first line, and
                # its cursor has not moved — hence the empty action, which
                # `rows` reads as "wherever we already are".
                begin(i, word, "", base if on_base else None)
                base, on_base = None, False
            lines[-1]["draws"].append(_draw(i, word, rest))
            last = i
        # anything else — a sound, a pause, an unmodelled command — draws nothing
        # that moves the cursor off this line, so it neither opens nor breaks one.

    close()
    return blocks


def rows(block: Block, bx: Box) -> list[int]:
    """The screen row each of a block's lines lands on.

    Not a field on `Line`, because it takes a `Box` read off the engine and the
    Texts browser has to work without one. The linter asks (a row past the last
    one draws over the map) and so does the writer (a `line` whose row is taken
    draws over the line above it); both hold the same box while they do.
    """
    out: list[int] = []
    for line in block.lines:
        prev = bx.first_row if line.starts_from is None else out[line.starts_from]
        out.append(bx.rows_for(line.action, prev))
    return out


def _draw(lineno: int, macro: str, rest: str) -> Draw:
    strings = tuple(_unescape(s) for s in _STR_RE.findall(rest))
    if macro in _RAM:
        m = _RAM_ARG_RE.match(rest)
        return Draw(lineno, macro, strings, m.group(1) if m else "")
    return Draw(lineno, macro, strings)


def _freeze(ln: dict) -> Line:
    return Line(ln["action"], ln["from"], tuple(ln["draws"]), ln["blank"])


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
