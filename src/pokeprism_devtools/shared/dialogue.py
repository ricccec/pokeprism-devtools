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

def decomment(raw: str) -> str:
    """Drop the comment, if there is one — but a `;` inside a string is a
    semicolon, not a comment.

    `raw.split(";")[0]` is what this used to be, and it silently truncated every
    line whose dialogue contains a semicolon (`line "gift as well;"` measured as
    an *empty* line). 27 blocks are written that way. It matters twice over: the
    linter was measuring those lines as zero tiles wide, and a rewrite that
    believed it would have written the emptiness back into the game.
    """
    out: list[str] = []
    in_string = escaped = False
    for ch in raw:
        if escaped:
            out.append(ch)
            escaped = False
            continue
        if ch == "\\":
            out.append(ch)
            escaped = True
            continue
        if ch == '"':
            in_string = not in_string
        elif ch == ";" and not in_string:
            break
        out.append(ch)
    return "".join(out)


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
    #: Whether a blank source line sat above this one. Pure formatting, and the
    #: repo is of two minds about it — 2621 `para`s have one and 1412 don't — so
    #: a rewrite copies what was there rather than imposing a house style and
    #: churning a thousand blocks nobody touched.
    blank_before: bool = False

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
    #: Last source line of the block, inclusive. With `lineno` this is the span a
    #: rewrite replaces — the label above it is not ours to touch.
    end: int = 0
    #: The macro that closed the block, or "" when an `@` inside the last string
    #: did. 105 of pokeprism's strings terminate that way, and a rewrite that
    #: "helpfully" converted them to `done` would be churn in 105 files.
    ends_with: str = ""


def sign_owners(source: list[str]) -> set[str]:
    """Top-level labels whose text is drawn in the full-screen signpost box.

    Two ways in, and both are needed: the `SIGNPOST_LOAD` event type, and the
    `loadsignpost` script command (only Route55 uses it, and it is registered as
    a plain `SIGNPOST_READ`, so reading the event header alone gets it wrong).
    """
    owners: set[str] = set()
    owner: str | None = None
    for raw in source:
        line = decomment(raw)
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
    return parse_source(root, path.read_text().split("\n"))


def parse_source(root: Path, source: list[str]) -> list[Block]:
    """The same, over lines already in hand rather than a file on disk.

    For a caller who is partway through changing the map and needs to find a
    block in the file as it *will* be — editing an object rewrites its line and
    rewords what it says, and both land in one file, so both have to be spliced
    into one buffer before any of it is written. See `wiring/objedit.py`.
    """
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
    #: The last source line that belonged to the block, and what closed it.
    last = 0
    closer = ""

    def close_line() -> None:
        nonlocal det, bnd, unb, unk, parts
        if not open_block:
            return
        blank = at >= 2 and source[at - 2].strip() == ""
        cur.append(Line(at, macro, act, row, " ".join(parts), det, bnd,
                        list(unb), list(unk), blank))
        det = bnd = 0
        unb, unk, parts = [], [], []

    def close_block() -> None:
        nonlocal open_block, closer
        if not open_block:
            return
        close_line()
        blocks.append(Block(label, owner, box, opened, list(cur), last, closer))
        cur.clear()
        open_block = False
        closer = ""

    for i, raw in enumerate(source, start=1):
        line = decomment(raw).rstrip()

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
            opened = last = i
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
            last, closer = i, name
            close_block()
            continue

        if action is not None:
            close_line()
            row = box.rows_for(action, row)
            macro, act, at = name, action, i
            last = i
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
            last = i
            continue

        if name == "text_from_ram":
            unb.append("text_from_ram")
            last = i
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


# -- writing ------------------------------------------------------------------ #
#
# The studio's promise is that you write the words and the macros are somebody
# else's problem. That only holds if the macros survive being somebody else's
# problem, which is what the functions below are careful about.

_ESCAPE = str.maketrans({'"': '\\"'})

#: The macros a line you have just written may get, per box, in the order they are
#: tried — the last being the fallback that always works.
#:
#: `<LINE>` is **absolute**: it goes to the speech box's second row, wherever the
#: cursor was. So a *third* line written as `line` does not move down, it draws over
#: the second — and the way to a third line is `cont`, which scrolls the box up and
#: frees the row first. Which is why this cannot be one constant: the right macro
#: depends on where the cursor already is.
#:
#: A signpost is a different set of macros entirely, because it is not a two-row box
#: you scroll: `next` is *relative* and walks down a ten-row window. The repo is
#: unanimous about the split (`line`/`para`/`cont` only in speech text, `next`/`nl`
#: only in sign text, 453 maps), and a `line` in a signpost would land every added
#: line on row 9, on top of the last one.
_WRITE = {
    "speech": ("line", "cont"),
    "sign": ("next",),
}

#: What the macros above do to the cursor. :func:`render` is handed a block and some
#: prose — it has no `root` to read the engine with, as `textbox.metrics` does — so
#: the handful of macros it may *emit* are named here. Every macro it *copies back*
#: arrives with its action already measured, on the `Line` it came from.
_ACTS = {"line": textbox.LINE_ABS, "cont": textbox.SCROLL, "para": textbox.NEW_BOX,
         "next": textbox.DOWN_2, "nl": textbox.DOWN_1}

#: The first line after a blank, which in a speech box starts a fresh one. A
#: signpost has no fresh box to start — it is one window — so a blank line there is
#: a blank *row*, which is what `nl` is. See :func:`render`.
_NEW_BOX = "para"
_BLANK_ROW = "nl"


def _clobbering(block: Block) -> set[int]:
    """The lines of this block that *already* draw over one another.

    Almost always empty — one block in pokeprism does it — and they are left
    exactly as they are. A macro is only ever rewritten here because the lines
    above it moved and it no longer means what it meant; a block that was written
    wrong in the first place is a bug somebody has to have *seen* to have written,
    and `maplint`'s text-clobber is what says so. Silently repairing it would put a
    diff in a form you opened to change one word.
    """
    cursor = textbox.Cursor(block.box)
    out: set[int] = set()
    for i, line in enumerate(block.lines):
        if cursor.clobbers(line.action):
            out.add(i)
        cursor.move(line.action)
    return out


def _words(block: Block) -> list[str]:
    """Each rendered line's words, one per line, terminator stripped."""
    texts = [line.text for line in block.lines]
    if texts and not block.ends_with and texts[-1].endswith(charmap.TERMINATOR):
        texts[-1] = texts[-1][:-1]   # the terminator is punctuation, not words
    return texts


def plain(block: Block) -> str:
    """A block as editable prose: one screen line per line, and a blank line
    wherever the text starts a fresh box. This is what a person types into.

    It shows no macros, which is the point — you write the words. What makes that
    safe is that :func:`render` walks the old lines in lockstep and copies each
    one's macro back, so the `cont` that scrolls the box is still a `cont` when
    you have only changed a word in it.
    """
    out: list[str] = []
    for i, (line, words) in enumerate(zip(block.lines, _words(block))):
        if i and line.action == textbox.NEW_BOX:
            out.append("")
        out.append(words)
    return "\n".join(out)


def render(block: Block, text: str, source: list[str] | None = None,
           indent: str = "\t") -> list[str]:
    """Edited prose back into macro lines.

    The prose and the old block's lines are walked **in lockstep**, and each old
    line hands back its macro and its blank-line-above. Two reasons, both learned
    from the repo rather than guessed:

    *The macros are not interchangeable.* `cont` scrolls the box, `next` moves a
    single row, `nl` leaves an empty one — 49 blocks use it — and none of them is
    a `line`. Reusing them positionally means a wording edit changes wording.

    *There is no house style to impose.* 2621 `para`s have a blank source line
    above them and 1412 don't. A rewrite that picked one would churn a thousand
    blocks nobody asked it to touch, so it copies what was there instead.

    *A line you add gets the macro that leaves it where you put it*, which is not
    always `line`. `<LINE>` is absolute — it goes to the speech box's second row —
    so a third line written as a third `line` draws straight over the second, and
    the linter says `text-clobber` about a block this function wrote. The cursor is
    therefore simulated as the lines are emitted, exactly as `maplint.rules_text`
    simulates it when reading them: `line` while its row is free, `cont` once it is
    not, because `cont` scrolls the box up and frees it again. A signpost is written
    in `next`, which walks down its ten rows and cannot collide with itself.

    *The blank lines, though, are yours.* A blank is the only way `plain` has of
    saying "a fresh box starts here", so where the prose and the old line disagree
    about that, **the prose wins**: a blank you added promotes the line below it to
    a `para`, and a blank you deleted demotes a `para` back to a `line`. Only that
    one bit is overridden — a `cont` you left alone is still a `cont`.

    A line whose words you did **not** change is copied back from `source`
    verbatim, byte for byte — its own spacing, its own quoting, its own
    everything. That is what makes it safe to run this over a block you barely
    touched: `nl   ""` keeps the alignment somebody chose, and the diff shows
    only the line you actually edited. A promoted or demoted line is *not* copied
    back, even though its words are untouched: its macro has to change, and
    copying the old bytes would throw that away and silently write the old box.
    """
    old = block.lines
    was = _words(block)
    box = block.box
    out: list[str] = []
    i = 0                     # index into the old rendered lines, in lockstep
    fresh_box = False         # a blank line was seen; the next line starts a box

    cursor = textbox.Cursor(box)
    already = _clobbering(block)     # lines that drew over each other before we came

    def written() -> str:
        """The macro for a line that has no old one to copy — the first one whose
        row is still free, and failing that the one that *makes* room."""
        if not out:
            return old[0].macro if old else _OPENERS[0]      # the block's opener
        choices = _WRITE[box.kind]
        for macro in choices[:-1]:
            if not cursor.clobbers(_ACTS[macro]):
                return macro
        return choices[-1]

    def emit(prose: str, at: int, blank: bool, macro: str, kept: bool = True) -> None:
        # `bool(out)` — never a blank line above the first: the span starts at the
        # opener, so a blank above it belongs to whatever came before and is not
        # ours to move.
        blank = blank and bool(out)
        if kept and source is not None and at < len(old) and prose == was[at]:
            line = source[old[at].lineno - 1]          # untouched: copy it back
        else:
            line = f'{indent}{macro} "{prose.translate(_ESCAPE)}"'
        out.append(f"\n{line}" if blank else line)
        # A copied-back line still moves the cursor, and by its *own* action, which
        # it brought with it. Only a line we invent has to be told.
        cursor.move(old[at].action if kept and at < len(old) else _ACTS.get(macro, ""))

    # Nothing is stripped, at either end: `plain` and `render` are exact inverses,
    # and one prose line is one rendered line. A *leading* blank is a genuinely
    # empty first line (`ctxt ""`) and eating it would splice the second line's
    # words into the opener; a *trailing* blank is a block whose terminator sits
    # alone on the last line (`line "@"`), and eating that moves the `@` up a line.
    for prose in text.split("\n"):
        if not prose.strip():
            # A blank means a new box — *unless* the old block had a genuinely
            # empty rendered line here (an `nl`), in which case that is what the
            # blank is, and it survives.
            if i < len(old) and was[i] == "" and old[i].action != textbox.NEW_BOX:
                emit("", i, old[i].blank_before, old[i].macro)
                i += 1
            elif box.kind == "sign":
                # There is no fresh box to start: a signpost is one window. So a
                # blank line in one is a blank row, and it is written down as such
                # rather than promoting the line below it to a `para` no signpost
                # in the repo has ever contained.
                emit("", i, False, _BLANK_ROW, kept=False)
            else:
                fresh_box = True
            continue

        # The opener is never promoted: the box it opens is already the first one,
        # and a `para` in its place would open the text with a screen-clear.
        starts_box = fresh_box and i > 0
        # Keep the old line's macro only where it *agrees* with the prose about
        # starting a box. Where they disagree the prose is the edit, and the macro
        # becomes the plain one for what the prose asked for.
        kept = i < len(old) and starts_box == (i > 0 and old[i].action == textbox.NEW_BOX)
        if kept:
            macro, blank = old[i].macro, old[i].blank_before
            if i not in already and cursor.clobbers(old[i].action):
                # It was a `line` under a `para` and it is now a `line` under a
                # `line`, because you merged the two boxes above it. The words are
                # yours and the macro is ours: keeping it would draw this line over
                # the one before it, which is a thing you did not ask for and could
                # not see. (Unless the block *arrived* clobbering — then it is not
                # ours to quietly repair, and `already` is what remembers that.)
                macro, kept = written(), False
        else:
            macro, blank = (_NEW_BOX if starts_box else written()), starts_box
        emit(prose, i, blank, macro, kept)
        fresh_box = False
        i += 1

    if not out:
        emit("", 0, False, old[0].macro if old else _OPENERS[0])

    if block.ends_with:
        out.append(f"{indent}{block.ends_with}")
    elif not out[-1].rstrip().endswith(f'{charmap.TERMINATOR}"'):
        # It ended with an `@` inside the last string. Put it back where it was —
        # 105 of pokeprism's strings terminate this way, and converting them to
        # `done` would be a diff in 105 files that nobody asked for. (Unless the
        # last line came back verbatim, in which case it still has its own.)
        out[-1] = out[-1][:-1] + f'{charmap.TERMINATOR}"'
    return out


def rewrite(source: list[str], block: Block, text: str) -> list[str]:
    """The map's source with one block's text replaced, and nothing else.

    The span is the block's own macros — `lineno` to `end`. The label above it is
    not ours: scripts jump to it, and a rewrite that moved it would be a rewrite
    that broke every caller.
    """
    body = "\n".join(render(block, text, source)).split("\n")
    return source[:block.lineno - 1] + body + source[block.end:]
