"""Does the dialogue fit its box? The family's overflow rules.

Nothing here fails to assemble. A line one tile too wide writes its last glyph
over the box's right border; a line that lands past the bottom row draws into the
map behind it. Both look fine in the source, and neither shows up until someone
walks into that exact conversation — which is the entire reason to check it here.

The trap `text-width` exists for is that `#` is one character and prints `POKé`,
four tiles, so `"#mon Center near"` is sixteen characters, comfortably inside
eighteen, and nineteen tiles — one too many. No amount of staring at the string
finds it. `text-width-name` is the same trap sprung a step later: `<PLAYER>` reads
as nothing and draws up to seven, so a line that fits in testing overflows the
moment someone types a long name. The comparisons themselves are `maplint.textfit`,
shared with prism's rules verbatim; what feeds them — the box, the widths, the
name bounds — is the family's own.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ....maplint import textfit
from ....maplint.diagnostics import Diagnostic, Severity
from . import charmap

if TYPE_CHECKING:
    from .context import FamilyLintContext
    from .dialogue import Line


def text_width(ctx: FamilyLintContext) -> list[Diagnostic]:
    """A line wider than the box however you slice it.

    Only the *determinate* part is counted — literal glyphs and the fixed ROM
    expansions (`#` -> POKé). No assumption about anyone's name, so there is no
    false positive: the engine runs off the edge of the box every time."""
    box = ctx.box
    out = []
    for const, path in sorted(ctx.map_files.items()):
        rel = ctx.rel(path)
        for block in ctx.text_blocks(const):
            for line in block.lines:
                over = textfit.overshoot(line.determinate, box.cols)
                if over <= 0:
                    continue
                out.append(Diagnostic(
                    "text-width", Severity.ERROR, rel, line.lineno,
                    f"this line is {line.determinate} tiles wide but the "
                    f"{box.name} is {box.cols} — {over} too many"
                    f"{_because(ctx, line)}",
                ))
    return out


def text_width_name(ctx: FamilyLintContext) -> list[Diagnostic]:
    """A line that fits until somebody uses all the letters in their name.

    `<PLAYER>` prints whatever is in `wPlayerName`, and the naming screen lets that
    be seven characters (`PLAYER_NAME_LENGTH - 1`). A line that fits a four-letter
    test name and overflows a seven-letter one is a real bug a playthrough never
    shows you, because you named yourself something short and never looked back.

    Warned, not errored, and only where the determinate part still fits: a line
    already too wide is `text-width`'s to report, and the one exactly at the box
    (`<PLAYER> obtained a`, 18 tiles at a seven-letter name) is the boundary the
    authors packed to, not an overflow."""
    box = ctx.box
    out = []
    for const, path in sorted(ctx.map_files.items()):
        rel = ctx.rel(path)
        for block in ctx.text_blocks(const):
            for line in block.lines:
                if line.determinate > box.cols or line.worst <= box.cols:
                    continue        # already an error, or genuinely fine
                out.append(Diagnostic(
                    "text-width-name", Severity.WARNING, rel, line.lineno,
                    f"this line is {line.determinate} tiles before any name is "
                    f"substituted, but up to {line.worst} after — "
                    f"{line.worst - box.cols} over the {box.name}'s {box.cols}. It "
                    f"fits a short name and breaks on a long one",
                ))
    return out


def text_rows(ctx: FamilyLintContext) -> list[Diagnostic]:
    """A line that lands below the last row inside the box.

    `<LINE>` is absolute — it cannot leave the box — but `<NEXT>` and `<LNBRK>`
    are relative, so two of them in a two-row box put the cursor off the bottom
    of the window, and the text lands in whatever is drawn behind it."""
    box = ctx.box
    out = []
    for const, path in sorted(ctx.map_files.items()):
        rel = ctx.rel(path)
        for block in ctx.text_blocks(const):
            for line in block.lines:
                if not textfit.below_box(line.row, box.last_row):
                    continue
                out.append(Diagnostic(
                    "text-rows", Severity.ERROR, rel, line.lineno,
                    f"`{line.macro}` puts this line on row {line.row}, past the "
                    f"{box.name}'s last row ({box.last_row}) — it draws outside the box",
                ))
    return out


def _because(ctx: FamilyLintContext, line: Line) -> str:
    """Name the control codes doing the damage, when there are any.

    Without this the message is a bare number — and the author already counted the
    characters, which is how they got here. What they need to hear is that `#` is
    four of them.

    The test is `width > len(token)`, not `width > 1`: it names exactly the tokens
    that draw wider than they read — `#` (one character, four tiles). It must not
    be `> 1`, because polished's n-grams (`the `, `It's `) are several tiles too
    but exactly as many as their letters, so calling them out would bury the one
    token that actually surprises the author under a list of ones that do not."""
    metrics = ctx.metrics
    grew = {tok: metrics.width[tok]
            for tok in set(charmap.tokenize(ctx.root, line.text))
            if metrics.width.get(tok, 1) > len(tok)}
    if not grew:
        return ""
    parts = ", ".join(f"`{t}` prints {w} tiles" for t, w in sorted(grew.items()))
    return f" ({parts})"


ALL = (text_width, text_width_name, text_rows)
