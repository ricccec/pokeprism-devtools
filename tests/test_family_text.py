#!/usr/bin/env python3
"""Tests for family rewording (hacks/vanilla/dialogue.py, hacks/vanilla/text.py).

Three kinds of check.

The *round trip* is the one that matters and the one that is easiest to fool.
Every text block in a stock pokecrystal and a stock polishedcrystal is parsed,
turned into prose, and written straight back with the words it already had; the
file must come back **byte-identical**. Nine thousand blocks is enough source to
contain every shape anybody has actually written, which no fixture is.

But a `rewrite` that returned its input unchanged would pass that with full
marks, so the round trip is never run alone: the *synthetic* checks change one
word and require exactly one line to move, add a line and require the macro that
puts it where you asked, and merge two boxes and require the `para` to become
something that does not draw over the line above it.

The *refusals* are the third. ~1.3% of family blocks are not a list of lines with
a line of source behind each one, and this checks that each shape is refused by
name rather than written wrong — including the one that motivated the rule: a
command sitting between the macros that a span rewrite would silently delete.

    python tests/test_family_text.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pokeprism_devtools.hacks.vanilla import box, dialogue, events, text  # noqa: E402
from pokeprism_devtools.contract import ActionError  # noqa: E402

VANILLA = Path.home() / "code/ricccec/pokecrystal"
POLISHED = Path.home() / "code/ricccec/polishedcrystal"
FAILED = 0

#: One map's worth of the shapes that matter, written against a real tree's box.
#: `TwoBoxes` is the label that holds two of them — the reason a block is
#: identified by the line it opens on and not by its label.
_SAMPLE = '''\
GreetingText:
\ttext "Hello there!"
\tline "Nice weather."

\tpara "Do come in."
\tdone

TwoBoxes:
\ttext "First box."
\tdone

\ttext "Second box."
\tdone

SplicedText:
\ttext "You got a "
\ttext_ram wStringBuffer3
\ttext "!"
\tdone

StrayCommandText:
\ttext "It is"
\tassert SOMETHING == 1
\tline "five o'clock."
\tdone

ConditionalText:
\ttext "Which build"
if DEF(FAITHFUL)
\tline "is this?"
else
\tline "is this one?"
endc
\tdone

JumpedIntoText:
\ttext "Before the label."
.Inside:
\tline "After it."
\tdone
'''


def check(label: str, cond: bool, detail: str = "") -> None:
    global FAILED
    print(f"  [{'OK  ' if cond else 'FAIL'}] {label}{f' — {detail}' if detail else ''}")
    if not cond:
        FAILED += 1


def _blocks(source: list[str]) -> dict[str, dialogue.Block]:
    """The sample's blocks by label — every label in it holds one box except
    `TwoBoxes`, which is looked up by line instead."""
    return {b.label: b for b in dialogue.parse_source(source)}


# --------------------------------------------------------------------------- #
# the parse                                                                    #
# --------------------------------------------------------------------------- #
def test_the_parse_is_one_line_per_screen_line() -> None:
    print("\nwhat the parse calls a line")
    source = _SAMPLE.split("\n")
    blocks = _blocks(source)

    g = blocks["GreetingText"]
    check("a box is its own block, opener to closer",
          [ln.macro for ln in g.lines] == ["text", "line", "para"]
          and g.closer == "done",
          f"{[ln.macro for ln in g.lines]} closed by {g.closer!r}")
    check("the block's span starts at its first macro, not at its label",
          g.lineno == 2 and g.end == 6, f"{g.lineno}..{g.end}")
    check("a blank source line above a macro is remembered, not normalised",
          [ln.blank_before for ln in g.lines] == [False, False, True])
    check("a `para` renders as a blank line in the prose",
          g.prose == "Hello there!\nNice weather.\n\nDo come in.", repr(g.prose))

    two = [b for b in dialogue.parse_source(source) if b.label == "TwoBoxes"]
    check("one label can hold two boxes, and they are two blocks",
          len(two) == 2 and [b.prose for b in two] == ["First box.", "Second box."],
          str([b.prose for b in two]))
    check("…which is why the identity is the line it opens on",
          [b.lineno for b in two] == [9, 12], str([b.lineno for b in two]))

    spliced = blocks["SplicedText"]
    check("a buffer splice is one line made of three commands, not three lines",
          len(spliced.lines) == 1
          and [d.macro for d in spliced.lines[0].draws]
          == ["text", "text_ram", "text"],
          str([d.macro for d in spliced.lines[0].draws]))
    check("and the buffer it splices is named",
          spliced.lines[0].buffers == ["wStringBuffer3"])
    check("a line built from three commands is not `simple`",
          not spliced.lines[0].simple)
    check("a plain line is", blocks["GreetingText"].lines[0].simple)

    check("`if`/`else` marks the block rather than doubling its lines",
          blocks["ConditionalText"].conditional is True)
    check("a label inside a box is recorded, not swallowed",
          blocks["JumpedIntoText"].inner_label == ".Inside")


def test_the_reader_and_the_writer_share_the_parse() -> None:
    """The whole reason the two parses were collapsed: the prose the Texts
    browser shows and the prose the reword form opens with have to be the same
    string, or the words you edit are not the words that get written."""
    print("\nthe browser and the form read the same words")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "Sample.asm"
        path.write_text(_SAMPLE + "\nSample_MapEvents:\n\tdb 0\n")
        refs = events.texts(path)
        blocks = {b.lineno: b for b in dialogue.parse(path)}
        check("every listed text is a block the writer can find by its line",
              all(r.lineno in blocks for r in refs), str([r.lineno for r in refs]))
        check("and says exactly what that block says",
              all(r.prose == blocks[r.lineno].prose for r in refs))
        check("a label with two boxes lists twice, with different words",
              [r.prose for r in refs if r.label == "TwoBoxes"]
              == ["First box.", "Second box."])


# --------------------------------------------------------------------------- #
# writing                                                                      #
# --------------------------------------------------------------------------- #
def test_one_changed_word_moves_one_line(bx: box.Box) -> None:
    print("\nchanging a word")
    source = _SAMPLE.split("\n")
    block = _blocks(source)["GreetingText"]

    out = text.rewrite(source, block, "Hello there!\nGrim weather.\n\nDo come in.", bx)
    moved = [i for i, (a, b) in enumerate(zip(source, out)) if a != b]
    check("exactly one line of the file changed",
          len(source) == len(out) and moved == [2], f"{moved}")
    check("…and it is the one whose words changed",
          out[2] == '\tline "Grim weather."', repr(out[2]))
    check("the `para` and its blank line came back untouched",
          out[3] == "" and out[4] == '\tpara "Do come in."')

    unchanged = text.rewrite(source, block, block.prose, bx)
    check("rewriting with the same words changes nothing at all",
          unchanged == source)


def test_an_added_line_gets_a_macro_that_fits(bx: box.Box) -> None:
    """`<LINE>` is absolute: a third line written as a third `line` draws over
    the second. The way to a third line is `cont`, which scrolls the box first."""
    print("\nadding a line")
    source = _SAMPLE.split("\n")
    block = _blocks(source)["GreetingText"]

    out = text.rewrite(source, block,
                       "Hello there!\nNice weather.\nIsn't it?\n\nDo come in.", bx)
    body = [ln for ln in out[1:8] if ln.strip()]
    check("the third line of a box is a `cont`, not a second `line`",
          body[:3] == ['\ttext "Hello there!"', '\tline "Nice weather."',
                       '\tcont "Isn\'t it?"'], str(body[:3]))

    out = text.rewrite(source, block, "Hello there!\nNice weather.\nDo come in.", bx)
    body = [ln for ln in out[1:7] if ln.strip()]
    check("deleting the blank demotes the `para` to something in the same box",
          body[2] == '\tcont "Do come in."', repr(body[2]))

    out = text.rewrite(source, block,
                       "Hello there!\n\nNice weather.\n\nDo come in.", bx)
    body = [ln for ln in out if ln.strip() and ln.startswith("\t")][:3]
    check("adding a blank promotes the line below it to a `para`",
          body[1] == '\tpara "Nice weather."', repr(body[1]))


def test_the_escape_and_the_closer_survive(bx: box.Box) -> None:
    print("\nquoting and the closing macro")
    source = _SAMPLE.split("\n")
    block = _blocks(source)["GreetingText"]

    out = text.rewrite(source, block, 'He said "no".\nNice weather.\n\nDo come in.', bx)
    check("a quote in the words is escaped for rgbds",
          out[1] == '\ttext "He said \\"no\\"."', repr(out[1]))
    check("the closer is still the macro it was", out[5] == "\tdone")

    short = text.rewrite(source, block, "Just this.", bx)
    check("cutting the block to one line keeps its closer",
          [ln for ln in short[1:] if ln.strip()][:2]
          == ['\ttext "Just this."', "\tdone"],
          str([ln for ln in short[1:] if ln.strip()][:2]))


# --------------------------------------------------------------------------- #
# refusals                                                                     #
# --------------------------------------------------------------------------- #
def test_the_shapes_it_will_not_write() -> None:
    print("\nwhat it refuses, and what it says")
    source = _SAMPLE.split("\n")
    blocks = _blocks(source)

    for label, expect in (("SplicedText", "wStringBuffer3"),
                          ("ConditionalText", "if"),
                          ("JumpedIntoText", ".Inside"),
                          ("StrayCommandText", "assert")):
        why = text.refuses(blocks[label], source)
        check(f"{label} is refused, and the message names the reason",
              bool(why) and expect in why, why or "(accepted!)")

    check("a plain block is not refused",
          text.refuses(blocks["GreetingText"], source) == "")


def test_a_stray_command_is_never_silently_deleted(bx: box.Box) -> None:
    """The falsification that made `_unaccounted` exist. Without the guard the
    `assert` between two macros is inside the replaced span and simply vanishes —
    and the form reports a successful edit, which is the worst way to lose a
    line."""
    print("\nthe line a span rewrite would have eaten")
    source = _SAMPLE.split("\n")
    block = _blocks(source)["StrayCommandText"]
    out = text.rewrite(source, block, block.prose, bx)
    check("a blind rewrite really would drop it — the guard is not decoration",
          "\tassert SOMETHING == 1" in source
          and "\tassert SOMETHING == 1" not in out)
    check("so the writer refuses instead of running it",
          "assert" in text.refuses(block, source))


def test_the_form_refuses_a_block_that_moved(engine: Path) -> None:
    """The action the reword form builds, over a two-file tree — the catalog it
    resolves the map through, and the engine constants the box is measured from,
    borrowed from a real checkout so the rows are the game's."""
    print("\nthe form, end to end")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "maps").mkdir()
        (root / "data/maps").mkdir(parents=True)
        (root / "constants").mkdir()
        for rel in ("constants/hardware.inc", "constants/text_constants.asm"):
            (root / rel).write_text((engine / rel).read_text())
        (root / "maps/TownA.asm").write_text(_SAMPLE + "\nTownA_MapEvents:\n\tdb 0\n")
        (root / "data/maps/attributes.asm").write_text(
            "\tmap_attributes TownA, TOWN_A, $00\n")

        action = text.EditText("TOWN_A", label="GreetingText", at="2",
                               text="Hello there!\nGrim weather.\n\nDo come in.")
        result = action.run(root)
        check("it names the block it changed", "GreetingText" in result.summary,
              result.summary)
        check("and stages exactly one edit", len(result.edits) == 1)
        check("…against the map file", result.edits[0].path == "maps/TownA.asm")
        check("whose text has the new words and not the old",
              'line "Grim weather."' in result.edits[0].new_text
              and 'line "Nice weather."' not in result.edits[0].new_text)

        spliced_at = next(b.lineno for b in dialogue.parse_source(_SAMPLE.split("\n"))
                          if b.label == "SplicedText")

        same = text.EditText("TOWN_A", label="GreetingText", at="2",
                             text="Hello there!\nNice weather.\n\nDo come in.").run(root)
        check("submitting the same words stages nothing, and says so",
              same.edits == [] and same.notes == ["unchanged — nothing to write"])

        # Three ways the form can be pointed at something it must not write:
        # a block that has moved out from under it, a form built without the
        # reference at all, and a block whose words are not one line of source.
        for at, expect in (("9999", "opening at line 9999"),
                           ("", "which block it is about"),
                           (str(spliced_at), "wStringBuffer3")):
            try:
                text.EditText("TOWN_A", label="X", at=at, text="Hi").run(root)
                check(f"at={at!r} refuses", False, "it wrote something")
            except ActionError as exc:
                check(f"at={at!r} refuses with a sentence",
                      expect in str(exc), str(exc))


# --------------------------------------------------------------------------- #
# the real trees                                                               #
# --------------------------------------------------------------------------- #
def test_every_real_block_survives_a_no_op_reword(root: Path, name: str) -> None:
    """Reword every block in a shipping game with the words it already has. The
    file must come back byte for byte — that is what "the macros are not the
    author's business" has to mean to be worth saying."""
    print(f"\nevery text block in {name}, reworded with its own words")
    bx = box.speech_box(root)
    tried = refused = 0
    broken: list[str] = []
    for path in sorted((root / "maps").glob("*.asm")):
        source = path.read_text(encoding="utf-8").split("\n")
        for block in dialogue.parse_source(source):
            if text.refuses(block, source):
                refused += 1
                continue
            tried += 1
            out = text.rewrite(source, block, block.prose, bx)
            if out != source:
                at = next((i for i, (a, b) in enumerate(zip(source, out)) if a != b),
                          min(len(source), len(out)))
                broken.append(f"{path.name}:{block.lineno} ({block.label}) "
                              f"first diff at line {at + 1}")
    check(f"{tried} blocks rewrite to the identical file", not broken,
          "; ".join(broken[:3]))
    check(f"and the {refused} it refuses are a small minority of the tree",
          0 < refused < tried // 20, f"{refused} refused of {tried + refused}")


def test_a_real_block_takes_a_real_edit(root: Path, name: str) -> None:
    """The round trip above passes for a `rewrite` that returns its input, so it
    is never the only check: this one changes a word in every block and requires
    exactly the line it changed to move."""
    print(f"\nand takes an edit, in {name}")
    bx = box.speech_box(root)
    checked = 0
    wrong: list[str] = []
    for path in sorted((root / "maps").glob("*.asm")):
        source = path.read_text(encoding="utf-8").split("\n")
        for block in dialogue.parse_source(source):
            if text.refuses(block, source) or not block.words[0]:
                continue
            checked += 1
            words = block.prose.split("\n")
            words[0] = "Zzz"
            out = text.rewrite(source, block, "\n".join(words), bx)
            moved = [i for i, (a, b) in enumerate(zip(source, out)) if a != b]
            if len(source) != len(out) or moved != [block.lines[0].lineno - 1]:
                wrong.append(f"{path.name}:{block.lineno} moved {moved}")
    check(f"{checked} blocks move exactly the line whose words changed", not wrong,
          "; ".join(wrong[:3]))


def main() -> int:
    test_the_parse_is_one_line_per_screen_line()
    test_the_reader_and_the_writer_share_the_parse()
    test_the_shapes_it_will_not_write()

    trees = [(r, r.name) for r in (VANILLA, POLISHED) if r.exists()]
    if not trees:
        print("\n(no family checkout next door — skipping every box-backed test)")
        return 1 if FAILED else 0

    # The box comes off a real engine rather than a fixture, so the row
    # arithmetic the writer does is the arithmetic the game does.
    bx = box.speech_box(trees[0][0])
    test_the_form_refuses_a_block_that_moved(trees[0][0])
    test_one_changed_word_moves_one_line(bx)
    test_an_added_line_gets_a_macro_that_fits(bx)
    test_the_escape_and_the_closer_survive(bx)
    test_a_stray_command_is_never_silently_deleted(bx)
    for root, name in trees:
        test_every_real_block_survives_a_no_op_reword(root, name)
        test_a_real_block_takes_a_real_edit(root, name)

    print(f"\n{FAILED} check(s) FAILED" if FAILED else "\nall checks passed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
