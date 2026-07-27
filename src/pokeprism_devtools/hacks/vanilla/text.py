"""Rewording dialogue that is already in the game — the family's half.

The other family write modules add things. This one changes what a thing *says*,
which is a narrower and more dangerous job: the words are the only part of a text
block a person means to touch, and everything around them — the `cont` that
scrolls the box, the `para` that opens a fresh one, the label a script jumps to —
has to come back exactly as it was.

So the splice is the block's own macros and nothing else. The label above it is
not ours to move: a script jumps to it, and every jump would break. And the macros
are put back *positionally* from the block itself, so changing a word in the third
line of a box leaves the first two byte-identical, along with the alignment
whitespace somebody chose and the blank line they left above it.

**Which block, by where it starts.** Not by its label: a family label can hold two
boxes — 10 do in vanilla, 100 in polished — and `next(b for b in blocks if b.label
== label)` would take the first every time, so rewording the second one would
quietly edit the first. The reference the form carries is the line the box opens
on, and a file that no longer has a box there is a refusal rather than a guess.

**And a block it will not touch.** ~1.3% of the family's boxes are not a list of
lines with a line of source behind each one, and this refuses those by name rather
than writing something plausible:

* a *spliced* line — `line "your @"` / `text_ram wStringBuffer3` / `text "…"` is
  one line on screen and three commands in the file, so there is no line of prose
  to put back into any one of them;
* a *conditional* block — `if DEF(FAITHFUL)` guards two versions of the same line,
  which the prose shows one after the other, so an edit cannot say which it meant;
* a *jump target inside the box*, which a rewrite of the span would move;
* a block with no closing macro, which nothing in either tree actually is — it is
  refused so the writer never has to invent a terminator.

Re-deriving the split for the spliced ones is possible and is not attempted: it
would mean deciding where in your new sentence the buffer goes, which is a
question only you can answer and the form has no way to ask.
"""

from __future__ import annotations

from pathlib import Path

from ...shared.edits import Edit
from ...studio.actions import Action, ActionError, Field, Result
from . import box, dialogue
from .box import Box
from .dialogue import TERMINATOR, Block

#: The macros a line you have just written may get, in the order they are tried —
#: the last being the fallback that always works.
#:
#: `<LINE>` is **absolute**: it goes to the box's second row wherever the cursor
#: was. So a *third* line written as `line` does not move down, it draws over the
#: second — and the way to a third line is `cont`, which scrolls the box up and
#: frees the row first. Which is why this is a sequence and not a constant: the
#: right macro depends on where the cursor already is.
_WRITE = ("line", "cont")

#: What the macros above do to the cursor. :func:`render` is handed a block and
#: some prose, so the handful of macros it may *emit* are named here. Every macro
#: it *copies back* arrives with its action already on the `Line` it came from.
_ACTS = {"line": box.LINE_ABS, "cont": box.SCROLL, "para": box.OPEN}

#: The first line after a blank, which starts a fresh box.
_NEW_BOX = "para"
#: What a block with nothing left in it opens with.
_OPENER = "text"

_ESCAPE = str.maketrans({'"': '\\"'})


class TextError(RuntimeError):
    """This block can't be reworded, and the message says why to a human."""


def refuses(block: Block, source: list[str]) -> str:
    """Why this block cannot be spliced positionally, or `""` when it can.

    Every reason names the thing in the way, because the answer to all of them is
    the same — open the file — and that is only useful if you know what to look
    for when you get there.
    """
    if not block.closer:
        return (f"{block.label} has no `done` closing it, so where its words end "
                "is not something this can read off the file")
    if block.conditional:
        return (f"{block.label} is guarded by `if`/`else`, so two of its lines are "
                "two versions of one line — the words above cannot say which "
                "build you meant")
    if block.inner_label:
        return (f"{block.inner_label} is a label inside {block.label}'s box, and "
                "rewriting the box would move it — every script that jumps there "
                "would land somewhere else")
    for n, line in enumerate(block.lines, start=1):
        if not line.simple:
            what = ", ".join(line.buffers) or "another command"
            return (f"line {n} of {block.label} splices {what} into the middle of "
                    f"it, so its words are not one line of source to put back")
    if any(TERMINATOR in words for words in block.words):
        return (f"{block.label} carries a `{TERMINATOR}` inside a line, which "
                "hands the rest of it to another command")
    if stray := _unaccounted(block, source):
        return (f"line {stray} sits inside {block.label}'s box and is not one of "
                f"its words — `{source[stray - 1].strip()}` — so a rewrite of the "
                "box would delete it")
    return ""


def _unaccounted(block: Block, source: list[str]) -> int:
    """The first line of the block's span that :func:`render` would not put back.

    The span is replaced whole, so anything inside it that the render does not
    emit is a line **deleted** by an edit that never mentioned it. Two of
    polished's blocks carry an `assert` between their macros and two carry a
    `text_decimal`, and all four lost it silently before this existed — which is
    the worst shape a bug can have here, because the form reports success and the
    line is gone.

    Rather than model every command that might appear, this asks the question the
    other way round: is every line in the span one this writer emits? A `no` is a
    refusal naming the line, and a command nobody has thought of yet gets the same
    treatment as the ones we know about.
    """
    kept = {draw.lineno for line in block.lines for draw in line.draws}
    kept |= {line.lineno - 1 for line in block.lines if line.blank_before}
    kept.add(block.end)                                   # the closer
    if block.end >= 2 and not source[block.end - 2].strip():
        kept.add(block.end - 1)                           # the blank above it
    return next((n for n in range(block.lineno, block.end + 1) if n not in kept), 0)


def reword(root: Path, path: Path, at: int, prose: str) -> Edit:
    """One block's words replaced by `prose`, the rest of the file untouched.

    `at` is the line the box opens on — see the module docstring on why the label
    is not enough. `prose` is what :attr:`.dialogue.Block.prose` produces: one
    screen line per line, a blank line wherever a fresh box starts. No macros,
    because the macros are not the author's business — they are copied back from
    what was there.
    """
    original = path.read_text(encoding="utf-8")
    source = original.split("\n")

    block = next((b for b in dialogue.parse_source(source) if b.lineno == at), None)
    if block is None:
        raise TextError(f"{path.name} has no text block opening at line {at} any "
                        "more — the file moved under the form. Pick it again.")
    if why := refuses(block, source):
        raise TextError(why)

    text = "\n".join(rewrite(source, block, prose, box.speech_box(root)))
    return Edit(f"maps/{path.stem}.asm", text != original,
                f"{block.label}: reworded", text, base=original)


def rewrite(source: list[str], block: Block, prose: str, bx: Box) -> list[str]:
    """The map's source with one block's text replaced, and nothing else.

    The span is the block's own macros — `lineno` to `end`. The label above it is
    not ours: scripts jump to it, and a rewrite that moved it would be a rewrite
    that broke every caller.
    """
    body = "\n".join(render(block, prose, source, bx)).split("\n")
    return source[:block.lineno - 1] + body + source[block.end:]


def render(block: Block, prose: str, source: list[str], bx: Box,
           indent: str = "\t") -> list[str]:
    """Edited prose back into macro lines.

    The prose and the old block's lines are walked **in lockstep**, and each old
    line hands back its macro and its blank-line-above. Two reasons, both read off
    the repo rather than guessed:

    *The macros are not interchangeable.* `cont` scrolls the box and `line` jumps
    to its second row absolutely; swapping them means a wording edit changes
    wording.

    *There is no house style to impose.* The trees are of two minds about a blank
    source line above a `para`, so this copies what was there rather than picking
    one and churning a thousand blocks nobody asked it to touch.

    *A line you add gets the macro that leaves it where you put it*, which is not
    always `line`. `<LINE>` is absolute, so a third line written as a third `line`
    draws straight over the second — and `text-rows` would then report a finding
    against text this studio wrote. The cursor is therefore simulated as the lines
    are emitted, exactly as the linter simulates it when reading them: `line`
    while its row is free, `cont` once it is not, because `cont` scrolls the box
    up and frees it again.

    *The blank lines, though, are yours.* A blank is the only way the prose has of
    saying "a fresh box starts here", so where the prose and the old line disagree
    about that, **the prose wins**: a blank you added promotes the line below it
    to a `para`, and a blank you deleted demotes a `para` back to a `line`. Only
    that one bit is overridden — a `cont` you left alone is still a `cont`.

    A line whose words you did **not** change is copied back from `source`
    verbatim, byte for byte — its own spacing, its own quoting, its own
    everything. That is what makes it safe to run this over a block you barely
    touched: the diff shows only the line you actually edited. A promoted or
    demoted line is *not* copied back, even though its words are untouched: its
    macro has to change, and copying the old bytes would throw that away and
    silently write the old box.
    """
    old = block.lines
    was = block.words
    out: list[str] = []
    i = 0                     # index into the old rendered lines, in lockstep
    fresh_box = False         # a blank line was seen; the next line starts a box

    cursor = box.Cursor(bx)
    already = _clobbering(block, bx)   # lines that drew over each other before us

    def written() -> str:
        """The macro for a line with no old one to copy — the first one whose row
        is still free, and failing that the one that *makes* room."""
        if not out:
            return old[0].macro if old else _OPENER      # the block's opener
        for macro in _WRITE[:-1]:
            if not cursor.clobbers(_ACTS[macro]):
                return macro
        return _WRITE[-1]

    def emit(words: str, at: int, blank: bool, macro: str, kept: bool = True) -> None:
        # `bool(out)` — never a blank above the first line: the span starts at the
        # opener, so a blank above it belongs to whatever came before and is not
        # ours to move.
        blank = blank and bool(out)
        if kept and at < len(old) and words == was[at]:
            line = source[old[at].lineno - 1]          # untouched: copy it back
        else:
            line = f'{indent}{macro} "{words.translate(_ESCAPE)}"'
        out.append(f"\n{line}" if blank else line)
        # A copied-back line still moves the cursor, and by its *own* action,
        # which it brought with it. Only a line we invent has to be told.
        cursor.move(old[at].action if kept and at < len(old) else _ACTS.get(macro, ""))

    # Nothing is stripped, at either end: the prose and the block are exact
    # inverses, and one prose line is one rendered line. A *leading* blank is a
    # genuinely empty first line (`text ""`) and eating it would splice the second
    # line's words into the opener.
    for words in prose.split("\n"):
        if not words.strip():
            # A blank means a new box — *unless* the old block had a genuinely
            # empty rendered line here, in which case that is what the blank is,
            # and it survives.
            if i < len(old) and was[i] == "" and old[i].action != box.OPEN:
                emit("", i, old[i].blank_before, old[i].macro)
                i += 1
            elif fresh_box and i < len(old) and was[i] == "":
                # An empty line that *is* the box break — `para ""`, which BATTLE
                # TOWER uses to leave a cleared box on screen. It costs two blanks
                # in the prose (one saying "new box", one for its own empty words)
                # and this is the second of them. Without this the pair reads as
                # one long "start a box" and the `para ""` is dropped, which is a
                # line of the game deleted by an edit that changed nothing.
                emit("", i, old[i].blank_before, old[i].macro)
                i += 1
                fresh_box = False
            else:
                fresh_box = True
            continue

        # The opener is never promoted: the box it opens is already the first one,
        # and a `para` in its place would open the text with a screen-clear.
        starts_box = fresh_box and i > 0
        # Keep the old line's macro only where it *agrees* with the prose about
        # starting a box. Where they disagree the prose is the edit, and the macro
        # becomes the plain one for what the prose asked for.
        kept = i < len(old) and starts_box == (i > 0 and old[i].action == box.OPEN)
        if kept:
            macro, blank = old[i].macro, old[i].blank_before
            if i not in already and cursor.clobbers(old[i].action):
                # It was a `line` under a `para` and it is now a `line` under a
                # `line`, because you merged the two boxes above it. The words are
                # yours and the macro is ours: keeping it would draw this line
                # over the one before it, which is a thing you did not ask for and
                # could not see. (Unless the block *arrived* clobbering — then it
                # is not ours to quietly repair, and `already` remembers that.)
                macro, kept = written(), False
        else:
            macro, blank = (_NEW_BOX if starts_box else written()), starts_box
        emit(words, i, blank, macro, kept)
        fresh_box = False
        i += 1

    if not out:
        emit("", 0, False, old[0].macro if old else _OPENER)
    # The closer goes back as the *line* it was, not as its macro re-spelled:
    # polished indents a `done` inside a script block with two tabs, and 63 of
    # its blocks would otherwise come back with the indentation changed by an
    # edit that touched no words. There is no terminator to guess at either — a
    # block with no closing macro is refused before it reaches here. The blank
    # line above it, where there is one, is the closer's rather than the last
    # text line's, so it comes back with the closer.
    blank = block.end >= 2 and not source[block.end - 2].strip()
    out.append(f"\n{source[block.end - 1]}" if blank else source[block.end - 1])
    return out


def _clobbering(block: Block, bx: Box) -> set[int]:
    """The lines of this block that *already* draw over one another.

    Almost always empty, and they are left exactly as they are. A macro is only
    ever rewritten here because the lines above it moved and it no longer means
    what it meant; a block that was written wrong in the first place is a bug
    somebody has to have *seen* to have written, and the linter's `text-rows` is
    what says so. Silently repairing it would put a diff in a form you opened to
    change one word.
    """
    cursor = box.Cursor(bx)
    out: set[int] = set()
    for i, line in enumerate(block.lines):
        if cursor.clobbers(line.action):
            out.add(i)
        cursor.move(line.action)
    return out


class EditText(Action):
    """Reword a text block that is already in the game.

    Reached by *picking one* — `t` on a map, or `e` on a row whose object says
    something. What arrives here is prose; the macros come back from the block
    itself. `at` is not a field on the form: you pointed at the block, and a box
    you could type in would aim your new words at a different one.
    """

    name = "reword"
    title = "Edit dialogue"
    FIELDS = (
        Field("label", "Text block", kind="fixed"),
        Field("text", "What it says", kind="lines"),
    )

    def __init__(self, map_const: str, **values: str) -> None:
        super().__init__(**values)
        self.map = map_const

    def describe(self) -> str:
        return f"reword {self.text('label')}"

    def run(self, root: Path) -> Result:
        from .read import label_of
        label = label_of(root).get(self.map)
        if label is None:
            raise ActionError(f"{self.map} is not a map in this tree.")
        if not self.text("at"):
            raise ActionError(
                "this form was opened without saying which block it is about — "
                "pick the text again from the map.")
        try:
            edit = reword(root, root / f"maps/{label}.asm", self.integer("at"),
                          self.values.get("text", ""))
        except (TextError, OSError) as e:
            raise ActionError(str(e)) from e
        return Result(edit.detail, [edit] if edit.changed else [],
                      [] if edit.changed else ["unchanged — nothing to write"])
