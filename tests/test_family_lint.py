#!/usr/bin/env python3
"""Tests for the family dialogue-overflow linter (hacks/vanilla/lint).

Two kinds of check, the same shape as the maplint suite. The *synthetic* ones
craft a handful of overflow lines and prove each is caught — one tile past the
box, the invisible `#`->POKé expansion, a `next` off the bottom row — and that a
line exactly the box's width is *not*. The *real-tree* ones lint a stock
pokecrystal checkout and require it to come back clean: a shipping game has no
overflow, so a finding there is the lint crying wolf. Both need engine files
(the charmap, the widths, the box constants), so both skip when no checkout sits
next door.

    python tests/test_family_lint.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pokeprism_devtools.hacks import mount as hackmount  # noqa: E402
from pokeprism_devtools.hacks import seam  # noqa: E402
from pokeprism_devtools.hacks.polished import lint as polished_lint  # noqa: E402
from pokeprism_devtools.hacks.vanilla import lint  # noqa: E402
from pokeprism_devtools.hacks.vanilla.lint import box, dialogue, metrics, rules  # noqa: E402
from pokeprism_devtools.maplint.diagnostics import Severity, apply_suppressions  # noqa: E402

VANILLA = Path.home() / "code/ricccec/pokecrystal"
POLISHED = Path.home() / "code/ricccec/polishedcrystal"
FAILED = 0

#: One box each: a fitting line and its overflowing twin, the `#` trap, and a
#: `next` walked off the bottom. Written to a scratch file and measured against a
#: real tree's engine, so the numbers are the engine's, not a fixture's.
_SAMPLE = '''\
FitsText:
\ttext "123456789012345678"
\tline "1234567890123456789"
\tdone

PokeText:
\ttext "#mon Center near"
\tdone

RowsText:
\ttext "row one"
\tline "row two"
\tnext "off the bottom"
\tdone

PriceText:
\ttext "Yours for {d:SOME_PRICE}!"
\tdone
'''

#: The name-bound cases, kept in their own sample so the linenos above stay put.
#: A line that packs to exactly the box at a seven-letter name is the boundary the
#: authors design to (`<PLAYER> obtained a`, 18 tiles — the real LakeOfRage line),
#: and must *not* warn; one tile wider must; a short line with room to spare must
#: not. `<PLAYER>` is the family name token both trees carry.
_NAME_SAMPLE = '''\
NameFits:
\ttext "<PLAYER> obtained a"

NameBreaks:
\ttext "<PLAYER> and I are set"

NameRoomy:
\ttext "<PLAYER>!"
\tdone
'''

#: The buffer cases. A `text_ram` splices a WRAM string onto the line it lands on,
#: so the parser must *join* it — `BufOverflow`'s buffer sits on the same line as
#: the 18 tiles before it, not a fresh line of its own. Its content is unbounded,
#: so the only certain overflow is when the fixed text already fills the box and
#: the buffer has nowhere to go; a roomy line and a *name* buffer (bounded, not
#: unbounded) must stay silent. `wPlayerName` is a name in both trees; any other
#: `wStringBuffer*` is scratch the text cannot bound.
_BUFFER_SAMPLE = '''\
BufOverflow:
\ttext "123456789012345678"
\ttext_ram wStringBuffer3
\tdone

BufRoomy:
\ttext "Hi "
\ttext_ram wStringBuffer3
\tdone

BufName:
\ttext "Hi "
\ttext_ram wPlayerName
\tdone
'''


def check(label: str, cond: bool, detail: str = "") -> None:
    global FAILED
    print(f"  [{'OK  ' if cond else 'FAIL'}] {label}{f' — {detail}' if detail else ''}")
    if not cond:
        FAILED += 1


def _lines(root: Path, sample: Path):
    """Every rendered line in the sample, keyed by the macro's source lineno."""
    m = metrics.load(root)
    out = {}
    for blk in dialogue.parse(root, sample, m):
        for ln in blk.lines:
            out[ln.lineno] = ln
    return out


def test_the_channel_loads_no_prism() -> None:
    """The whole point of de-prisming maplint's __init__: a family tree's linter
    reaches the finding channel without dragging in the tree it is not written
    against. Asserted at runtime over sys.modules, because it is an import fact."""
    print("\nthe family linter imports no prism")
    prism = [name for name in sys.modules if "hacks.prism" in name]
    # `import ... vanilla.lint` at the top of this file has already run; its own
    # modules must not have pulled prism in. (vanilla.read would, at mount — that
    # is the mount discovering every hack, not the linter, and it is not imported
    # here.)
    check("importing hacks.vanilla.lint loads no hacks.prism module", not prism, str(prism[:3]))


def test_metrics_read_from_the_engine(root: Path) -> None:
    print("\nthe widths are read out of vanilla's text engine")
    m = metrics.load(root)
    check("`#` prints 4 tiles (POKé)", m.width.get("#") == 4, str(m.width.get("#")))
    check("`<TRAINER>` prints 7", m.width.get("<TRAINER>") == 7, str(m.width.get("<TRAINER>")))
    check("`<PKMN>` prints 2", m.width.get("<PKMN>") == 2, str(m.width.get("<PKMN>")))
    check("a name buffer counts as nothing determinate (`<PLAYER>` -> 0)",
          m.width.get("<PLAYER>") == 0, str(m.width.get("<PLAYER>")))
    check("the terminator ends a string", "@" in m.control)
    check("`<LINE>` is a break, not a glyph", "<LINE>" in m.control)


def test_the_box_from_source(root: Path) -> None:
    print("\nthe box is measured from constants, not assumed")
    b = box.speech_box(root)
    check("the interior is 18 tiles wide (TEXTBOX_INNERW)", b.cols == 18, str(b.cols))
    check("`line` lands two rows below `text`, at the last row",
          b.second_row == b.first_row + 2 == b.last_row,
          f"first={b.first_row} second={b.second_row} last={b.last_row}")


def test_falsification(root: Path) -> None:
    print("\nwiden a good line and the lint catches it")
    with tempfile.TemporaryDirectory() as d:
        sample = Path(d) / "Sample.asm"
        sample.write_text(_SAMPLE)
        ln = _lines(root, sample)
        b = box.speech_box(root)

        check("a line exactly 18 tiles fits", ln[2].determinate == 18 and ln[2].determinate <= b.cols)
        check("one more tile overflows", ln[3].determinate == 19 and ln[3].determinate > b.cols)
        check("the `#`->POKé line is 19 tiles though it reads as 16 characters",
              ln[7].determinate == 19, str(ln[7].determinate))
        check("a `next` after `line` lands on row 18, past the box's last row",
              ln[13].row == 18 and ln[13].row > b.last_row, f"row {ln[13].row}")
        check("an rgbds interpolation is not counted as literal text",
              ln[17].determinate <= b.cols, f"{ln[17].determinate} for {ln[17].text!r}")


def test_the_rules_and_suppression(root: Path) -> None:
    print("\nthe rules fire, and a source comment waves them off")
    with tempfile.TemporaryDirectory() as d:
        sample = Path(d) / "Sample.asm"
        sample.write_text(_SAMPLE)
        blocks = dialogue.parse(root, sample, metrics.load(root))

        class Ctx:
            pass
        ctx = Ctx()
        ctx.root, ctx.metrics = root, metrics.load(root)
        ctx.box = box.speech_box(root)
        ctx.map_files = {"SAMPLE": sample}
        ctx.rel = lambda p: "maps/Sample.asm"
        ctx.text_blocks = lambda const: blocks

        found = []
        for rule in rules.ALL:
            found += rule(ctx)
        codes = sorted({d.code for d in found})
        check("both rules fire", codes == ["text-rows", "text-width"], str(codes))
        check("the width message names the culprit expansion",
              any("`#` prints 4 tiles" in d.message for d in found))

        src = _SAMPLE.split("\n")
        # Suppress the #-trap finding by an inline comment on its own line.
        trap = next(d for d in found if "prints 4 tiles" in d.message)
        marked = list(src)
        marked[trap.line - 1] += "  ; maplint: ignore[text-width]"
        kept = apply_suppressions(found, {"maps/Sample.asm": marked})
        check("an inline ignore drops just that finding",
              trap not in kept and len(kept) == len(found) - 1)

        filewide = ["; maplint: ignore-file[text-width]"] + src
        kept2 = apply_suppressions(found, {"maps/Sample.asm": filewide})
        check("ignore-file[text-width] drops every width finding, keeps the rows one",
              {d.code for d in kept2} == {"text-rows"})


def test_the_real_tree_is_clean(root: Path) -> None:
    print("\na stock pokecrystal lints clean — a finding here is a false alarm")
    ctx = lint.build(root)
    found = ctx.lint()
    check("no dialogue overflow in the shipping game", found == [],
          "; ".join(d.location for d in found[:5]))


def _name_rule_over_sample(root: Path, m) -> list:
    """Run `text-width-name` over `_NAME_SAMPLE` with the tree's own metrics."""
    with tempfile.TemporaryDirectory() as d:
        sample = Path(d) / "Sample.asm"
        sample.write_text(_NAME_SAMPLE)
        blocks = dialogue.parse(root, sample, m)

        class Ctx:
            pass
        ctx = Ctx()
        ctx.root, ctx.metrics, ctx.box = root, m, box.speech_box(root)
        ctx.map_files = {"SAMPLE": sample}
        ctx.rel = lambda p: "maps/Sample.asm"
        ctx.text_blocks = lambda const: blocks
        return rules.text_width_name(ctx)


def _check_name_rule(engine: str, root: Path, m) -> None:
    """Shared name-overflow checks — identical for vanilla and polished, since the
    rule, the box and the seven-letter bound are all shared; only the reader that
    filled `m` forks."""
    print(f"\n{engine}: a line breaks only once a long name is substituted")
    check("`<PLAYER>` carries a seven-tile worst case, not a determinate width",
          m.bound.get("<PLAYER>") == 7 and m.width.get("<PLAYER>") == 0,
          f"bound={m.bound.get('<PLAYER>')} width={m.width.get('<PLAYER>')}")
    check("a plain glyph has no name bound", "#" not in m.bound and "a" not in m.bound)

    found = _name_rule_over_sample(root, m)
    lines = sorted(d.line for d in found)
    check("it warns on the line that overflows a long name, and only it",
          lines == [5], str(lines))
    check("the boundary line that packs to exactly 18 does not warn", 2 not in lines)
    check("a line with room to spare does not warn", 8 not in lines)
    if found:
        d = found[0]
        check("it is a warning, not an error", d.severity == Severity.WARNING, str(d.severity))
        check("the message contrasts the before-name and after-name widths",
              "14 tiles before" in d.message and "up to 21 after" in d.message, d.message)


def test_name_bound_and_overflow(root: Path) -> None:
    _check_name_rule("vanilla", root, metrics.load(root))


def _buffer_rule_over_sample(root: Path, m):
    """`text-buffer` findings and the parsed lines, over `_BUFFER_SAMPLE`."""
    with tempfile.TemporaryDirectory() as d:
        sample = Path(d) / "Sample.asm"
        sample.write_text(_BUFFER_SAMPLE)
        blocks = dialogue.parse(root, sample, m)
        lines = {l.lineno: l for blk in blocks for l in blk.lines}

        class Ctx:
            pass
        ctx = Ctx()
        ctx.root, ctx.metrics, ctx.box = root, m, box.speech_box(root)
        ctx.map_files = {"SAMPLE": sample}
        ctx.rel = lambda p: "maps/Sample.asm"
        ctx.text_blocks = lambda const: blocks
        return rules.text_buffer(ctx), lines


def _check_buffer_rule(engine: str, root: Path, m) -> None:
    """Shared buffer checks — the parse and the rule are one code path for both
    trees, and only the declared name bound forks. A `text_ram` joins the line it
    lands on, an unbounded buffer overflows only a line already full, and a name
    buffer is bounded, not unbounded."""
    print(f"\n{engine}: a spliced buffer overflows only a line already full")
    found, lines = _buffer_rule_over_sample(root, m)

    check("`text_ram` joins its buffer onto the line before it, not a new one",
          lines[2].determinate == 18 and lines[2].unbounded == ["wStringBuffer3"],
          f"det={lines[2].determinate} unb={lines[2].unbounded}")
    check("a name buffer via `text_ram` is bounded, not unbounded",
          lines[12].bounded == 7 and not lines[12].unbounded,
          f"bnd={lines[12].bounded} unb={lines[12].unbounded}")

    warned = sorted(d.line for d in found)
    check("it warns where the fixed text already fills the box, and only there",
          warned == [2], str(warned))
    check("a line with room for the buffer does not warn", 7 not in warned)
    check("a bounded name buffer is not a text-buffer finding", 12 not in warned)
    if found:
        d = found[0]
        check("it is a warning, not an error", d.severity == Severity.WARNING, str(d.severity))
        check("the message names the buffer with nowhere to go",
              "wStringBuffer3" in d.message and "fills" in d.message, d.message)


def test_buffer_overflow(root: Path) -> None:
    _check_buffer_rule("vanilla", root, metrics.load(root))


def test_the_seam_conformance(root: Path) -> None:
    print("\nthe mounted vanilla ctx is a seam.Lints")
    hack = hackmount.mount(root)
    check("vanilla now carries a ctx", hack.ctx is not None)
    check("it satisfies the Lints protocol", isinstance(hack.ctx, seam.Lints))
    for name in ("lint", "mentions", "source_lines", "invalidate"):
        check(f"it answers {name}()", callable(getattr(hack.ctx, name, None)))


#: The polished fast-follow. Same box, same parse, same rules — the fork is the
#: width reader, which resolves a byte through the Huffman n-gram table instead
#: of vanilla's dict. The checks below pin the two things that fork: n-grams draw
#: their expansion's tiles (not one), and the `#`-style expansion that reads
#: shorter than it draws is still the surprise the width message must name.
def test_polished_metrics_read_from_ngrams(root: Path) -> None:
    print("\npolished reads widths out of its n-gram table, not vanilla's dict")
    m = polished_lint.load(root)
    check("`#` prints 4 tiles (Poké)", m.width.get("#") == 4, str(m.width.get("#")))
    check("`#mon` prints 7 (Pokémon)", m.width.get("#mon") == 7, str(m.width.get("#mon")))
    check("a name buffer counts as nothing (`<PLAYER>` -> 0)",
          m.width.get("<PLAYER>") == 0, str(m.width.get("<PLAYER>")))
    check("an n-gram draws its whole expansion (`the ` -> 4 tiles, not 1)",
          m.width.get("the ") == 4, str(m.width.get("the ")))
    check("an apostrophe ligature inside an n-gram is one tile (`'s ` -> 2, not 3)",
          m.width.get("'s ") == 2, str(m.width.get("'s ")))
    check("a graphic ligature is a single tile (`<PK>` falls through to 1)",
          m.width.get("<PK>") is None, str(m.width.get("<PK>")))


def test_polished_falsification(root: Path) -> None:
    print("\npolished catches the same overflows, and names only the real surprise")
    m = polished_lint.load(root)
    b = box.speech_box(root)
    check("the box is 18 tiles wide, as vanilla's", b.cols == 18, str(b.cols))
    with tempfile.TemporaryDirectory() as d:
        sample = Path(d) / "Sample.asm"
        sample.write_text(_SAMPLE)
        ln = {l.lineno: l for blk in dialogue.parse(root, sample, m) for l in blk.lines}
        check("a line exactly 18 tiles fits", ln[2].determinate == 18)
        check("one more tile overflows", ln[3].determinate == 19)
        check("the `#mon`->Pokémon line is 19 tiles though it reads as 16 characters",
              ln[7].determinate == 19, str(ln[7].determinate))
        check("a `next` after `line` lands past the box's last row",
              ln[13].row == 18 and ln[13].row > b.last_row, f"row {ln[13].row}")

        class Ctx:
            pass
        ctx = Ctx()
        ctx.root, ctx.metrics, ctx.box = root, m, b
        ctx.map_files = {"SAMPLE": sample}
        ctx.rel = lambda p: "maps/Sample.asm"
        ctx.text_blocks = lambda const: dialogue.parse(root, sample, m)
        found = []
        for rule in rules.ALL:
            found += rule(ctx)
        check("both rules fire", sorted({d.code for d in found}) == ["text-rows", "text-width"])
        trap = next((d for d in found if d.line == 7), None)
        check("the width message names `#mon`, the token that draws wider than it reads",
              trap is not None and "`#mon` prints 7 tiles" in trap.message,
              trap.message if trap else "no finding on the #mon line")


def test_polished_real_tree_is_clean(root: Path) -> None:
    print("\na stock polishedcrystal lints clean — a finding here is a false alarm")
    found = polished_lint.build(root).lint()
    check("no dialogue overflow in the shipping game", found == [],
          "; ".join(d.location for d in found[:5]))


def test_polished_name_bound_and_overflow(root: Path) -> None:
    _check_name_rule("polished", root, polished_lint.load(root))


def test_polished_buffer_overflow(root: Path) -> None:
    _check_buffer_rule("polished", root, polished_lint.load(root))


def test_polished_seam_conformance(root: Path) -> None:
    print("\nthe mounted polished ctx is a seam.Lints")
    hack = hackmount.mount(root)
    check("polished now carries a ctx", hack.ctx is not None)
    check("it satisfies the Lints protocol", isinstance(hack.ctx, seam.Lints))


def main() -> int:
    test_the_channel_loads_no_prism()
    if not VANILLA.exists():
        print("\n(no pokecrystal checkout next door — skipping the engine-backed tests)")
    else:
        test_metrics_read_from_the_engine(VANILLA)
        test_the_box_from_source(VANILLA)
        test_falsification(VANILLA)
        test_the_rules_and_suppression(VANILLA)
        test_name_bound_and_overflow(VANILLA)
        test_buffer_overflow(VANILLA)
        test_the_real_tree_is_clean(VANILLA)
        test_the_seam_conformance(VANILLA)

    if not POLISHED.exists():
        print("\n(no polishedcrystal checkout next door — skipping the polished tests)")
    else:
        test_polished_metrics_read_from_ngrams(POLISHED)
        test_polished_falsification(POLISHED)
        test_polished_name_bound_and_overflow(POLISHED)
        test_polished_buffer_overflow(POLISHED)
        test_polished_real_tree_is_clean(POLISHED)
        test_polished_seam_conformance(POLISHED)

    print()
    if FAILED:
        print(f"{FAILED} check(s) FAILED")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
