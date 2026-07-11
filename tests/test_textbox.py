#!/usr/bin/env python3
"""Tests for the text-width engine — charmap, box geometry, dialogue parsing.

The unit tests run against the hermetic fixture in test_maplint. The interesting
half is the real-repo pass, which pins the facts the rules were calibrated on:
pokeprism's dialogue stops dead at 18 tiles and its signs at 17, and the handful
of lines that don't are either a deliberate easter egg or a genuine bug. If a
change to the width model quietly shifts either cliff, that shows up here.

    python tests/test_textbox.py
"""

from __future__ import annotations

import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_maplint import _fixture  # noqa: E402

from pokeprism_devtools.shared import charmap, dialogue, textbox  # noqa: E402

_failures = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global _failures
    mark = "OK  " if cond else "FAIL"
    print(f"  [{mark}] {label}{(': ' + detail) if detail else ''}")
    if not cond:
        _failures += 1


def test_tokenizer(root: Path) -> None:
    """One tile per charmap token — which is not one tile per Python character."""
    print("\nthe tokenizer counts tiles, not characters")

    check("a digraph is one token", charmap.tokenize(root, "I'd") == ["I", "'d"],
          str(charmap.tokenize(root, "I'd")))
    check("a control code is one token",
          charmap.tokenize(root, "<PLAYER>!") == ["<PLAYER>", "!"],
          str(charmap.tokenize(root, "<PLAYER>!")))
    check("longest match wins", charmap.tokenize(root, "<PK><MN>") == ["<PK>", "<MN>"],
          str(charmap.tokenize(root, "<PK><MN>")))
    check("a plain string is one token per character",
          charmap.tokenize(root, "abc") == ["a", "b", "c"])


def test_metrics(root: Path) -> None:
    """Widths come out of the engine source, not out of this file."""
    print("\nwidths are derived from home/text.asm")
    mt = textbox.metrics(root)

    check("`#` prints Poké — four tiles, from PlacePOKeText", mt.width["#"] == 4,
          str(mt.width.get("#")))
    check("`<TRNER>` prints Trainer — seven", mt.width["<TRNER>"] == 7,
          str(mt.width.get("<TRNER>")))
    check("`<PKMN>` is two tiles, not seven (it expands to <PK><MN>)",
          mt.width["<PKMN>"] == 2, str(mt.width.get("<PKMN>")))
    check("a plain letter is one tile", mt.width["a"] == 1)

    check("`<PLAYER>` is bounded by the naming screen, at 7",
          mt.bound["<PLAYER>"] == 7, str(mt.bound))
    check("`<STRBF1>` is unbounded — a script decides what's in it",
          "<STRBF1>" in mt.unbounded, str(mt.unbounded))

    check("`<LINE>` is absolute", mt.action["<LINE>"] == textbox.LINE_ABS)
    check("`<NEXT>` is relative, two rows", mt.action["<NEXT>"] == textbox.DOWN_2)
    check("`@` ends the string", mt.action["@"] == textbox.END)
    check("the `line` macro emits <LINE>", mt.macro_token["line"] == "<LINE>")


def test_boxes(root: Path) -> None:
    """Two boxes, and neither one's shape is written down here."""
    print("\nbox geometry is measured, not assumed")
    bx = textbox.boxes(root)

    speech = bx["speech"]
    check("the speech box is 18 wide (SCREEN_WIDTH - BORDER_WIDTH)",
          speech.cols == 18, str(speech.cols))
    check("its two rows are 14 and 16", (speech.first_row, speech.second_row) == (14, 16),
          str(speech))
    check("<LINE> is absolute: it lands on 16 from anywhere",
          speech.rows_for(textbox.LINE_ABS, 14) == 16
          and speech.rows_for(textbox.LINE_ABS, 16) == 16)
    check("<NEXT> is relative: two rows down, wherever you are",
          speech.rows_for(textbox.DOWN_2, 14) == 16
          and speech.rows_for(textbox.DOWN_2, 16) == 18)

    sign = bx["sign"]
    check("the signpost is 17 wide — its body starts at x=2, border at x=19",
          sign.cols == 17, str(sign.cols))
    check("and runs from row 7 to row 16", (sign.first_row, sign.last_row) == (7, 16),
          str(sign))


def test_expansion_beats_eyeballing(root: Path) -> None:
    """The bug this whole module exists for."""
    print("\na control code is one character and many tiles")
    mt = textbox.metrics(root)

    text = "#mon Center near"
    det, bnd, unb, unk = mt.tiles(root, text)
    check("'#mon Center near' is 16 characters", len(text) == 16)
    check("...and 19 tiles, because `#` prints Poké", det == 19, str(det))
    check("...which is one too many for an 18-wide box",
          det > textbox.boxes(root)["speech"].cols)

    det, bnd, _, _ = mt.tiles(root, "Nice to meet you <PLAYER>")
    check("a <PLAYER> line is certain up to the substitution", det == 17, str(det))
    check("...and seven more when the name is at its longest", bnd == 7, str(bnd))


def test_terminator(root: Path) -> None:
    """105 strings in pokeprism end with `@` rather than a following `done`."""
    print("\nan `@` inside a string ends the block")
    mt = textbox.metrics(root)
    det, _, _, _ = mt.tiles(root, "Bye!@ignored")
    check("nothing after the terminator is counted", det == 4, str(det))


def test_sign_context(tmp: Path, root: Path) -> None:
    """Which box a block lands in is a property of its owner, not of its text."""
    print("\nsign text is found through the event header, and through the script")

    # SIGNPOST_LOAD in the event header is the obvious way in. The other way is a
    # script that calls `loadsignpost` — Route55's direction sign is registered as
    # a plain SIGNPOST_READ and switches to the full-screen box at runtime, and
    # its text hangs off *local* labels under it.
    (root / "maps" / "TownD.asm").write_text(
        "PlainSign:\n"
        '\tctxt "Drawn in the speech box"\n'
        "\tdone\n\n"
        "BoardSign:\n"
        '\tctxt "Drawn in the sign box"\n'
        "\tdone\n\n"
        "FacingSign:\n"
        "\tcheckcode VAR_FACING\n"
        "\tloadsignpost -1\n\n"
        ".FacingDown\n"
        '\tctxt "Also the sign box"\n'
        "\tdone\n\n"
        "TownD_MapEventHeader:: db 0, 0\n\n"
        ".Warps\n\tdb 0\n\n"
        ".CoordEvents\n\tdb 0\n\n"
        ".BGEvents\n\tdb 1\n"
        "\tsignpost 1, 1, SIGNPOST_LOAD, BoardSign\n\n"
        ".ObjectEvents\n\tdb 0\n"
    )
    blocks = {b.label: b for b in dialogue.parse(root, root / "maps" / "TownD.asm")}

    check("a SIGNPOST_LOAD target is drawn in the sign box",
          blocks["BoardSign"].box.name == "signpost", blocks["BoardSign"].box.name)
    check("a block with no signpost is drawn in the speech box",
          blocks["PlainSign"].box.name == "speech textbox", blocks["PlainSign"].box.name)
    check("a local label under a `loadsignpost` script is sign text too",
          blocks[".FacingDown"].box.name == "signpost", blocks[".FacingDown"].box.name)
    check("...and it is owned by the top-level label above it",
          blocks[".FacingDown"].owner == "FacingSign", blocks[".FacingDown"].owner)


def test_real_repo() -> None:
    """The calibration: what pokeprism's 13,900 lines of dialogue actually do."""
    root = Path(__file__).resolve().parent.parent.parent / "pokeprism"
    if not (root / "maps").is_dir():
        print("\n(skipping real-repo pass — ../pokeprism not found)")
        return

    print("\nreal repo: the corpus agrees with the model")
    lines: Counter[str] = Counter()
    widest: dict[str, int] = {}
    macros: dict[str, set[str]] = {}
    over, rows, unknown = [], [], []

    for path in sorted((root / "maps").glob("*.asm")):
        for block in dialogue.parse(root, path):
            box = block.box.name
            for line in block.lines:
                lines[box] += 1
                widest[box] = max(widest.get(box, 0), line.determinate)
                macros.setdefault(box, set()).add(line.macro)
                if line.determinate > block.box.cols:
                    over.append((path.name, line.lineno, line.determinate))
                if line.row > block.box.last_row:
                    rows.append((path.name, line.lineno, line.row))
                unknown += line.unknown

    check("every map's dialogue parses", lines["speech textbox"] > 13000, str(lines))
    check("every character in maps/ is in the charmap", not unknown,
          str(Counter(unknown).most_common(5)))

    # The two contexts use *disjoint* cursor macros. That is what makes the
    # speech/sign split checkable rather than a guess, and it holds across 453 maps.
    check("`line`/`para`/`cont` are speech-only",
          not ({"line", "para", "cont"} & macros.get("signpost", set())),
          str(macros.get("signpost")))
    check("`next`/`nl` are sign-only",
          not ({"next", "nl"} & macros.get("speech textbox", set())),
          str(macros.get("speech textbox") or set()))

    check("no line lands past the bottom of its box", not rows, str(rows[:3]))
    check("sign text never exceeds the sign box's 17", widest.get("signpost", 0) <= 17,
          str(widest))

    # 13 of the 16 are PhanceroRoom's "Glitch City" easter egg, which is corrupt
    # on purpose. The other three are real, and one of them — Route77Pokecenter's
    # "#mon Center near" — is only visible once `#` is expanded to Poké.
    #
    # It was 11 of 14 until `dialogue.decomment` taught the parser that a `;`
    # inside a string is a semicolon and not a comment. Two of the glitch lines
    # contain one, and used to be truncated to nothing and measured as zero tiles
    # wide — so the linter could not see that they overflowed. They always did.
    real = sorted(f"{f}:{l}" for f, l, _ in over if f != "PhanceroRoom.asm")
    check("the deliberate glitch text is the bulk of the overflow",
          sum(1 for f, _, _ in over if f == "PhanceroRoom.asm") == 13, str(len(over)))
    check("and exactly three real overflows remain",
          real == ["MtEmberSmallRoom.asm:171", "MtEmberWest.asm:184",
                   "Route77Pokecenter.asm:8"], str(real))
    check("each of them is one tile over",
          all(w == 19 for f, _, w in over if f != "PhanceroRoom.asm"),
          str([w for f, _, w in over if f != "PhanceroRoom.asm"]))


def test_the_writer() -> None:
    """Rewriting a block you didn't change must not change it.

    This is the property the whole dialogue editor rests on. The studio will run
    `rewrite` over blocks in a repo it does not own, and if the round trip is
    lossy then editing one NPC's line silently reformats his neighbour's — or
    worse, drops the `cont` that scrolls his box. So: every text block in the
    repo, out and back, byte for byte.
    """
    root = Path(__file__).resolve().parent.parent.parent / "pokeprism"
    if not (root / "maps").is_dir():
        print("\n(skipping the writer's round trip — ../pokeprism not found)")
        return
    print("\nthe writer: what you didn't touch, it doesn't touch")

    total = clean = 0
    churn: list[str] = []
    for path in sorted((root / "maps").glob("*.asm")):
        source = path.read_text().split("\n")
        for block in dialogue.parse(root, path):
            total += 1
            if dialogue.rewrite(source, block, dialogue.plain(block)) == source:
                clean += 1
            elif len(churn) < 5:
                churn.append(f"{path.name}:{block.label}")
    check(f"all {total} blocks survive an untouched round trip",
          clean == total, str(churn))

    # And an edit lands, alone. One word, one line — not a reflowed block.
    path = root / "maps/AcaniaDocks.asm"
    source = path.read_text().split("\n")
    block = next(b for b in dialogue.parse(root, path)
                 if b.label == "AcaniaDocksNPC1")
    out = dialogue.rewrite(source, block,
                           dialogue.plain(block).replace("Glaceon", "Vaporeon"))
    moved = [i for i, (a, b) in enumerate(zip(source, out)) if a != b]
    check("changing one word changes exactly one line",
          len(moved) == 1 and len(out) == len(source), str(moved))
    check("and it is the line with the word in it",
          "Vaporeon" in out[moved[0]] and out[moved[0]].startswith("\tline "),
          out[moved[0]].strip() if moved else "")

    # The macros are not interchangeable, and the round trip must not level them.
    kinds = {ln.macro for _, b in
             ((p, b) for p in [root / "maps/AcaniaDocks.asm"]
              for b in dialogue.parse(root, p))
             for ln in b.lines}
    check("`cont` survives the trip (it scrolls the box; `line` doesn't)",
          "cont" in kinds, str(sorted(kinds)))


def test_a_semicolon_is_not_a_comment() -> None:
    """`line "gift as well;"` is a line of dialogue, not an empty one.

    The parser used to cut every source line at the first `;`. A string that
    contains one was therefore truncated to nothing and measured as zero tiles —
    so the linter could not see it overflow, and the writer would have written
    the emptiness back into the game.
    """
    print("\na `;` inside a string is a semicolon")
    check("the comment is dropped", dialogue.decomment('\tline "x"  ; note') ==
          '\tline "x"  ')
    check("the semicolon is not",
          dialogue.decomment('\tline "gift as well;"') == '\tline "gift as well;"')
    check("nor is one inside an escaped quote",
          dialogue.decomment(r'ctxt "he said \"go;\" and left"')
          == r'ctxt "he said \"go;\" and left"')

    root = Path(__file__).resolve().parent.parent.parent / "pokeprism"
    if not (root / "maps").is_dir():
        return
    block = next(b for b in dialogue.parse(root, root / "maps/AzaleaGym.asm")
                 if b.label == ".before_giving_TM_text")
    line = next(ln for ln in block.lines if "gift" in ln.text)
    check("so the line is measured, not silently zero",
          line.text == "gift as well;" and line.determinate > 0,
          f"{line.text!r} -> {line.determinate} tiles")


def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        root = _fixture(tmp)
        test_tokenizer(root)
        test_metrics(root)
        test_boxes(root)
        test_expansion_beats_eyeballing(root)
        test_terminator(root)
        test_sign_context(tmp, root)
    test_real_repo()
    test_a_semicolon_is_not_a_comment()
    test_the_writer()

    print()
    if _failures:
        print(f"{_failures} check(s) FAILED")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
