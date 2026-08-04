"""Rules about dialogue: does the text actually fit in the box it's drawn in?

Nothing here fails to assemble. A line one tile too wide writes its last
character over the textbox's right border and leaves a hole in the frame; a line
that lands past the bottom row writes into the map behind the box. Both look
completely fine in the source, which is the point.

The trap this exists for is that a control code is one byte in the source and
many tiles on the screen. ``#`` is a single character and prints ``Poké``, so
``ctxt "#mon Center near"`` — sixteen characters, comfortably inside eighteen —
renders as *Pokémon Center near*, which is nineteen tiles and one too many.
There is exactly that bug in pokeprism, and no amount of staring at the string
finds it.
"""

from __future__ import annotations

from ..hacks.prism import charmap, dialogue, textbox
from ..shared import textfit
from .context import LintContext
from ..contract import Diagnostic, Severity


def text_width(ctx: LintContext) -> list[Diagnostic]:
    """A line that is too wide however you slice it.

    Only the *determinate* part is counted here — literal glyphs and the fixed
    ROM expansions (`#` -> Poké, `<TRNER>` -> Trainer). No assumption about
    anybody's name is involved, so there is no way for this to be a false
    positive: the text engine will run off the edge of the box every single time.
    """
    out = []
    for const, info in sorted(ctx.map_infos.items()):
        path = ctx.rel(info.path)
        for block in ctx.text_blocks(const):
            for line in block.lines:
                over = textfit.overshoot(line.determinate, block.box.cols)
                if over <= 0:
                    continue
                out.append(Diagnostic(
                    "text-width", Severity.ERROR, path, line.lineno,
                    f"this line is {line.determinate} tiles wide but the "
                    f"{block.box.name} is {block.box.cols} — {over} too many"
                    f"{_because(ctx, line)}",
                ))
    return out


def text_width_name(ctx: LintContext) -> list[Diagnostic]:
    """A line that fits until somebody uses all the letters in their name.

    `<PLAYER>` prints whatever is in wPlayerName, and the naming screen lets that
    be seven characters (PLAYER_NAME_LENGTH - 1). A line that fits a four-letter
    test name and overflows a seven-letter one is a real bug that a playthrough
    will never show you, because you named yourself after yourself.

    Only buffers with a bound the engine actually enforces are counted — names,
    nicknames, items. The general-purpose `<STRBF*>` buffers hold whatever a
    script last put in them, and guessing is what `text-buffer` is for.
    """
    out = []
    for const, info in sorted(ctx.map_infos.items()):
        path = ctx.rel(info.path)
        for block in ctx.text_blocks(const):
            for line in block.lines:
                cols = block.box.cols
                if line.determinate > cols or line.worst <= cols:
                    continue        # already an error, or genuinely fine
                out.append(Diagnostic(
                    "text-width-name", Severity.WARNING, path, line.lineno,
                    f"this line is {line.determinate} tiles before any name is "
                    f"substituted, but up to {line.worst} after — {line.worst - cols} "
                    f"over the {block.box.name}'s {cols}. It fits a short name and "
                    f"breaks on a long one",
                ))
    return out


def text_buffer(ctx: LintContext) -> list[Diagnostic]:
    """A line whose spare room may not be enough for whatever the buffer holds.

    `<STRBF1>`..`<STRBF4>` are scratch: a script fills one and the text prints it.
    It might be a two-digit score, it might be a twelve-letter item. Nothing in
    the text says which, so this reports the headroom and stops there rather than
    inventing a bound — assuming the worst turns `"Rounds won:   <STRBF3>"` into
    an overflow that can never happen.

    The bar is the longest name the engine can put in *any* buffer: clear that and
    no content can overflow, whatever the script had in mind.
    """
    limit = max(ctx.textbox_metrics.bound.values(), default=0)
    out = []
    for const, info in sorted(ctx.map_infos.items()):
        path = ctx.rel(info.path)
        for block in ctx.text_blocks(const):
            for line in block.lines:
                if not line.unbounded:
                    continue
                room = block.box.cols - line.worst
                if room >= limit:
                    continue
                names = ", ".join(sorted(set(line.unbounded)))
                out.append(Diagnostic(
                    "text-buffer", Severity.INFO, path, line.lineno,
                    f"{room} tiles left for {names}, whose content this tool cannot "
                    f"bound — it overflows the {block.box.name} if the script put "
                    f"more than {room} characters there (a name can be up to {limit})",
                ))
    return out


def text_rows(ctx: LintContext) -> list[Diagnostic]:
    """A line that lands below the last row inside the box.

    The cursor moves are not interchangeable. `<LINE>` is absolute — it always
    goes to the box's second row — but `<NEXT>` and `<LNBRK>` are relative, two
    rows and one row below wherever the last line began. So `next` twice in a
    two-row speech box puts the cursor on row 18, which is off the bottom of the
    screen entirely, and the text lands in whatever is behind the window.
    """
    out = []
    for const, info in sorted(ctx.map_infos.items()):
        path = ctx.rel(info.path)
        for block in ctx.text_blocks(const):
            for line in block.lines:
                if not textfit.below_box(line.row, block.box.last_row):
                    continue
                out.append(Diagnostic(
                    "text-rows", Severity.ERROR, path, line.lineno,
                    f"`{line.macro}` puts this line on row {line.row}, past the "
                    f"{block.box.name}'s last row ({block.box.last_row}) — it draws "
                    f"outside the box",
                ))
    return out


def text_clobber(ctx: LintContext) -> list[Diagnostic]:
    """Two lines drawn on the same row, with nothing scrolling between them.

    `<LINE>` is absolute, so a second `line` in one box does not move down — it
    goes back to the same row and overwrites what the first one put there. The
    way to get a third line is `cont`, which scrolls the box up first.
    """
    out = []
    for const, info in sorted(ctx.map_infos.items()):
        path = ctx.rel(info.path)
        for block in ctx.text_blocks(const):
            seen: dict[int, int] = {}          # row -> the line that claimed it
            for line in block.lines:
                if line.action == textbox.NEW_BOX:
                    seen.clear()
                elif line.action == textbox.SCROLL:
                    seen.pop(line.row, None)   # scrolled away; the row is free
                elif line.row in seen:
                    out.append(Diagnostic(
                        "text-clobber", Severity.WARNING, path, line.lineno,
                        f"`{line.macro}` draws on row {line.row} again, over the line "
                        f"at :{seen[line.row]} — `<LINE>` is absolute, so this "
                        f"overwrites rather than moving down. Use `cont` to scroll",
                    ))
                seen[line.row] = line.lineno
    return out


def text_unknown(ctx: LintContext) -> list[Diagnostic]:
    """A character with no charmap entry.

    rgbds would reject it, so this should never fire on a repo that builds — it
    is here because every width above is counted in charmap tokens, and a
    character the tokenizer does not recognise is silently counted as one tile.
    If that assumption ever breaks, this says so instead of quietly mis-measuring.
    """
    out = []
    for const, info in sorted(ctx.map_infos.items()):
        path = ctx.rel(info.path)
        for block in ctx.text_blocks(const):
            for line in block.lines:
                if not line.unknown:
                    continue
                bad = ", ".join(repr(c) for c in sorted(set(line.unknown)))
                out.append(Diagnostic(
                    "text-unknown", Severity.ERROR, path, line.lineno,
                    f"{bad} is not in macros/charmap.asm, so its width is a guess",
                ))
    return out


def _because(ctx: LintContext, line: dialogue.Line) -> str:
    """Name the control codes doing the damage, when there are any.

    Without this the message is just a number — and the author already counted
    the characters, which is how they got here. What they need to hear is that
    `#` is four of them.
    """
    mt = ctx.textbox_metrics
    grew = {tok: mt.width[tok]
            for tok in set(charmap.tokenize(ctx.root, line.text))
            if mt.width.get(tok, 1) > 1}
    if not grew:
        return ""
    parts = ", ".join(f"`{t}` prints {w} tiles" for t, w in sorted(grew.items()))
    return f" ({parts})"


ALL = (text_width, text_width_name, text_buffer, text_rows, text_clobber, text_unknown)
