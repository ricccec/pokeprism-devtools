#!/usr/bin/env python3
"""Characterization tests for prism-newmap: the wizard and what it writes.

Hermetic — a temp fixture repo and a fake `questionary`, no ROM/build.

    python tests/test_map_new_cli.py

`_gather_spec` is 132 lines, the longest function in Phase 1's six packages,
and under the whole suite it executed exactly one of them — its `def`. `main`
is 68 and executed one. Nothing pinned what the wizard asks, in what order, or
what it refuses.

`tests/test_map_new.py` does not cover this: it tests `wiring/mapnew.py` and
`hacks/vanilla/newmap.py`, one underscore away and unrelated code.

**The order of the questions is part of the golden.** A wizard is a sequence,
and a refactor that reorders it changes what the user is asked and when — so
the recorded prompt list is asserted in full, not sampled.

The fake `questionary` runs each prompt's own `validate` against the canned
answer, so a scripted run also proves the answers are ones the wizard would
actually have accepted. Nothing here stubs the code under test: only the
library that reads a terminal, which no test can have.
"""

from __future__ import annotations

import contextlib
import io
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pokeprism_devtools import map_new  # noqa: E402
from pokeprism_devtools.map_new.wizard import _Aborted, _gather_spec  # noqa: E402

_failures = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global _failures
    mark = "OK  " if cond else "FAIL"
    print(f"  [{mark}] {label}{(': ' + detail) if detail else ''}")
    if not cond:
        _failures += 1


# --------------------------------------------------------------------------- #
# The fake questionary
# --------------------------------------------------------------------------- #

class _CannedAnswer:
    """What a questionary prompt object is, as far as the wizard is concerned:
    something with `.ask()`. Returning None is how questionary reports Ctrl+C,
    and is what `_ask` turns into `_Aborted`."""

    def __init__(self, value):
        self._value = value

    def ask(self):
        return self._value


class ValidationRejected(Exception):
    """A canned answer a real prompt would have refused."""


class FakeQuestionary:
    """Stands in for the `questionary` module.

    Records every prompt in order, and runs the prompt's own `validate` against
    the answer it is about to give back — so a scripted run cannot quietly rely
    on an answer the wizard would have rejected from a human.
    """

    def __init__(self, answers: list) -> None:
        self._answers = list(answers)
        self.asked: list[tuple[str, str]] = []
        self.choices_offered: dict[str, list] = {}

    def _respond(self, kind: str, message: str, validate=None, choices=None,
                 default=None):
        self.asked.append((kind, message))
        if choices is not None:
            self.choices_offered[message] = list(choices)
        if not self._answers:
            raise AssertionError(f"the wizard asked more than was scripted: {message!r}")
        value = self._answers.pop(0)
        if validate is not None and value is not None:
            verdict = validate(value)
            if verdict is not True:
                raise ValidationRejected(f"{message!r} rejected {value!r}: {verdict}")
        return _CannedAnswer(value)

    def text(self, message, **kw):
        return self._respond("text", message, **kw)

    def path(self, message, **kw):
        return self._respond("path", message, **kw)

    def select(self, message, **kw):
        return self._respond("select", message, **kw)

    def autocomplete(self, message, **kw):
        return self._respond("autocomplete", message, **kw)

    def confirm(self, message, **kw):
        return self._respond("confirm", message, **kw)

    @property
    def unused(self) -> list:
        return self._answers


class _FakeChoice:
    """`questionary.Choice`, which the wizard imports to label the group list."""

    def __init__(self, title, value=None, **kw):
        self.title = title
        self.value = value


# --------------------------------------------------------------------------- #
# The fixture
# --------------------------------------------------------------------------- #

def _fixture_repo(tmp: Path) -> Path:
    root = tmp / "repo"
    (root / "constants").mkdir(parents=True)
    (root / "maps" / "blk").mkdir(parents=True)
    (root / "contents").mkdir()

    (root / "Makefile").write_text("all:\n")
    (root / "main.asm").write_text('INCLUDE "constants.asm"\n')

    (root / "constants" / "map_dimension_constants.asm").write_text(
        "\tconst_def\n"
        "\tnewgroup ; 1\n"
        "\tmapgroup INTRO_OUTSIDE, 18, 11\n"
        "\n"
        "\tnewgroup ; 2\n"
        "\tmapgroup CAPER_RIDGE, 9, 20\n"
        "\tmapgroup CAPER_HOUSE, 4, 4\n"
        "\tmapgroup MOUND_B2F, 8, 8\n"
        "\tmapgroup KINDLE_ROAD, 9, 9\n"
    )
    (root / "constants" / "tilemap_constants.asm").write_text(
        "const_value = 0\n"
        "\tconst TILESET_NALJO_1\n"
        "\tconst TILESET_NALJO_2\n"
        "\tconst TILESET_CAVE4\n"
    )
    (root / "constants" / "music_constants.asm").write_text(
        "const_value = 0\n"
        "\tconst MUSIC_NONE\n"
        "\tconst MUSIC_NEW_BARK_TOWN\n"
    )
    (root / "constants" / "map_constants.asm").write_text(
        "const_value = 0\n"
        "\tconst PALETTE_AUTO\n"
        "\tconst PALETTE_DAY\n"
        "\tconst PALETTE_NITE\n"
    )
    (root / "constants" / "misc_constants.asm").write_text(
        "const_value = 0\n"
        "\tconst FISHGROUP_NONE\n"
        "\tconst FISHGROUP_SHORE\n"
    )
    (root / "maps" / "map_headers.asm").write_text(
        'SECTION "Map Headers", ROMX\n'
        "MapGroup1:\n"
        "\tmap_header IntroOutside, TILESET_NALJO_1, ROUTE, DUMMY2, "
        "MUSIC_NONE, 0, PALETTE_NITE, FISHGROUP_NONE\n"
        "MapGroup2:\n"
        "\tmap_header CaperRidge, TILESET_NALJO_2, TOWN, CAPER_RIDGE, "
        "MUSIC_NEW_BARK_TOWN, 0, PALETTE_AUTO, FISHGROUP_SHORE\n"
        "\tmap_header CaperHouse, TILESET_NALJO_2, INDOOR, CAPER_RIDGE, "
        "MUSIC_NEW_BARK_TOWN, 1, PALETTE_DAY, FISHGROUP_NONE\n"
    )
    (root / "maps" / "second_map_headers.asm").write_text(
        'SECTION "Second Map Headers", ROMX\n'
        "\tmap_header_2 IntroOutside, INTRO_OUTSIDE, 15, 0\n"
        "\tmap_header_2 CaperRidge, CAPER_RIDGE, 0, 0\n"
    )
    (root / "maps" / "blockdata.asm").write_text(
        'SECTION "Map block data 1", ROMX\n'
        "CaperRidge_BlockData:\n"
        '\tINCBIN "maps/blk/CaperRidge.blk.lz"\n'
    )
    (root / "maps" / "map_scripts.asm").write_text(
        'SECTION "Map Scripts 1", ROMX\n'
        'INCLUDE "maps/CaperRidge.asm"\n'
        "\n"
        "; DO NOT ADD ANYTHING BELOW THIS LINE\n"
    )
    (root / "contents" / "romx.link").write_text(
        'ROMX $01\n\t"Code 1"\n\nROMX $25\n\t"Sprites"\n'
    )
    return root


def _blk_source(tmp: Path, size: int = 90, suffix: str = ".blk") -> Path:
    src = tmp / f"OneIsland{suffix}"
    src.write_bytes(bytes(size))
    return src


def _answers(blk_src: Path) -> list:
    """A complete, valid run: 9x10 = 90 blocks, matching the .blk's size."""
    return [
        "OneIsland",                     # label
        "ONE_ISLAND",                    # const
        "9",                             # height
        "10",                            # width
        str(blk_src),                    # blk source
        2,                               # group
        "Map block data OneIsland",      # blockdata section
        "Map Scripts OneIsland",         # script section
        "Second Map Header OneIsland",   # secondary section
        "TILESET_CAVE4",                 # tileset
        "INDOOR",                        # permission
        "ONE_ISLAND",                    # landmark
        "MUSIC_NONE",                    # music
        "PALETTE_NITE",                  # palette
        "FISHGROUP_NONE",                # fishgroup
        False,                           # phone
        "0",                             # border block
        "0",                             # connection flags
    ]


#: Every prompt the wizard raises, in the order it raises them. This is the
#: golden: a wizard *is* its sequence of questions.
_EXPECTED_PROMPTS = [
    ("text", "PascalCase map label (e.g. OneIsland):"),
    ("text", "SCREAMING_SNAKE_CASE map id (e.g. ONE_ISLAND):"),
    ("text", "Map height (blocks):"),
    ("text", "Map width (blocks):"),
    ("path", "Path to the source .blk/.ablk file:"),
    ("select", "Map group (existing groups only — creating a new group isn't "
               "supported by this tool):"),
    ("text", "SECTION name for the block data (blank = mapfit default):"),
    ("text", "SECTION name for the script (blank = mapfit default):"),
    ("text", "SECTION name for the secondary header (blank = mapfit default):"),
    ("autocomplete", "Tileset (tab to autocomplete):"),
    ("select", "Permission (map type):"),
    ("text", "Landmark const (usually the map's own const, or its parent town's "
             "for an indoor sub-map):"),
    ("autocomplete", "Music (tab to autocomplete):"),
    ("select", "Palette:"),
    ("select", "Fish group:"),
    ("confirm", "Has phone service?"),
    ("text", 'Border block (usually "0"):'),
    ("text", 'Connection flags (e.g. "0", "NORTH", "NORTH | EAST"):'),
]


@contextlib.contextmanager
def _fake_questionary_module(fake):
    """Install *fake* as the `questionary` `main` imports, and the `Choice`
    the wizard imports from it."""
    import types
    module = types.ModuleType("questionary")
    for name in ("text", "path", "select", "autocomplete", "confirm"):
        setattr(module, name, getattr(fake, name))
    module.Choice = _FakeChoice
    saved = sys.modules.get("questionary")
    sys.modules["questionary"] = module
    try:
        yield module
    finally:
        if saved is None:
            del sys.modules["questionary"]
        else:
            sys.modules["questionary"] = saved


def _run_main(fake, cwd: Path) -> tuple[int, str, str]:
    import os
    out, err = io.StringIO(), io.StringIO()
    old_cwd = Path.cwd()
    os.chdir(cwd)
    try:
        with _fake_questionary_module(fake):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                try:
                    map_new.main()
                    rc = 0
                except SystemExit as e:
                    rc = e.code if isinstance(e.code, int) else 0
    finally:
        os.chdir(old_cwd)
    return rc, out.getvalue(), err.getvalue()


# --------------------------------------------------------------------------- #
# The tests
# --------------------------------------------------------------------------- #

def test_the_questions_and_the_spec(root: Path, tmp: Path) -> None:
    print("\n_gather_spec — the questions, in order, and the spec they build")
    blk_src = _blk_source(tmp)
    fake = FakeQuestionary(_answers(blk_src))
    with _fake_questionary_module(fake):
        spec, returned_blk = _gather_spec(root, fake)

    check("every prompt, in order", fake.asked == _EXPECTED_PROMPTS,
          "" if fake.asked == _EXPECTED_PROMPTS else
          f"\n--- got ---\n{fake.asked}\n--- want ---\n{_EXPECTED_PROMPTS}")
    check("no answer left over", fake.unused == [], str(fake.unused))
    check("it hands back the source .blk", returned_blk == blk_src, str(returned_blk))

    got = {
        "label": spec.label, "const": spec.const, "group": spec.group,
        "height": spec.height, "width": spec.width, "tileset": spec.tileset,
        "permission": spec.permission, "landmark": spec.landmark,
        "music": spec.music, "palette": spec.palette, "fishgroup": spec.fishgroup,
        "phone": spec.phone, "border_block": spec.border_block,
        "conn_flags": spec.conn_flags, "connections": spec.connections,
        "script_asm": spec.script_asm, "blk": spec.blk,
        "blockdata_section": spec.blockdata_section,
        "script_section": spec.script_section,
        "secondary_section": spec.secondary_section,
    }
    want = {
        "label": "OneIsland", "const": "ONE_ISLAND", "group": 2,
        "height": 9, "width": 10, "tileset": "TILESET_CAVE4",
        "permission": "INDOOR", "landmark": "ONE_ISLAND",
        "music": "MUSIC_NONE", "palette": "PALETTE_NITE",
        "fishgroup": "FISHGROUP_NONE", "phone": 0, "border_block": "0",
        "conn_flags": "0", "connections": [],
        "script_asm": "maps/OneIsland.asm", "blk": "maps/blk/OneIsland.blk",
        "blockdata_section": "Map block data OneIsland",
        "script_section": "Map Scripts OneIsland",
        "secondary_section": "Second Map Header OneIsland",
    }
    for key in want:
        check(f"spec.{key}", got[key] == want[key],
              "" if got[key] == want[key] else f"got {got[key]!r}, want {want[key]!r}")

    groups = fake.choices_offered[_EXPECTED_PROMPTS[5][1]]
    check("the group list offers both existing groups and their values",
          [c.value for c in groups] == [1, 2], str([c.value for c in groups]))
    check("a group is labelled with the maps in it, capped at three names",
          groups[1].title == "2  (CAPER_RIDGE, CAPER_HOUSE, MOUND_B2F, ...)",
          groups[1].title)


#: (what is wrong, index of the answer to spoil, the spoiled value, the text
#: the prompt must answer with). Each runs the whole wizard with one answer
#: replaced, so the validator under test is the one the wizard really installs.
_REJECTIONS = [
    ("a label that is not CamelCase", 0, "oneIsland", "must be CamelCase"),
    ("a label already wired", 0, "CaperRidge", "already wired"),
    ("a const that is not SCREAMING_SNAKE", 1, "One_Island", "must be SCREAMING_SNAKE_CASE"),
    ("a const already used", 1, "CAPER_RIDGE", "already used"),
    ("a height of zero", 2, "0", "between 1 and 255"),
    ("a height past a byte", 2, "256", "between 1 and 255"),
    ("a width that is not a number", 3, "wide", "between 1 and 255"),
    ("a tileset the tree does not define", 9, "TILESET_NOPE", "unknown tileset"),
    ("a landmark that is not SCREAMING_SNAKE", 11, "One_Island",
     "must be SCREAMING_SNAKE_CASE"),
    ("music the tree does not define", 12, "MUSIC_NOPE", "unknown music"),
]


def test_the_prompts_refuse_bad_answers(root: Path, tmp: Path) -> None:
    print("\n_gather_spec — what each prompt refuses")
    blk_src = _blk_source(tmp)
    for label, index, bad, expected in _REJECTIONS:
        answers = _answers(blk_src)
        answers[index] = bad
        fake = FakeQuestionary(answers)
        try:
            with _fake_questionary_module(fake):
                _gather_spec(root, fake)
            check(label, False, "accepted")
        except ValidationRejected as e:
            check(label, expected in str(e), str(e))


def test_the_blk_path_is_checked(root: Path, tmp: Path) -> None:
    print("\n_gather_spec — the .blk prompt")
    missing = tmp / "nope.blk"
    answers = _answers(_blk_source(tmp))
    answers[4] = str(missing)
    fake = FakeQuestionary(answers)
    try:
        with _fake_questionary_module(fake):
            _gather_spec(root, fake)
        check("a .blk that does not exist", False, "accepted")
    except ValidationRejected as e:
        check("a .blk that does not exist", "file not found" in str(e), str(e))

    wrong_kind = tmp / "OneIsland.png"
    wrong_kind.write_bytes(bytes(90))
    answers = _answers(_blk_source(tmp))
    answers[4] = str(wrong_kind)
    fake = FakeQuestionary(answers)
    try:
        with _fake_questionary_module(fake):
            _gather_spec(root, fake)
        check("a file that is not .blk or .ablk", False, "accepted")
    except ValidationRejected as e:
        check("a file that is not .blk or .ablk",
              "must be a .blk or .ablk file" in str(e), str(e))


def test_a_blk_of_the_wrong_size_warns_but_continues(root: Path, tmp: Path) -> None:
    """The dimensions and the file are two independent answers, and the wizard
    trusts the human on which is wrong — but says so, because a .blk of the
    wrong size is the mistake that silently ruins a new map."""
    print("\n_gather_spec — a .blk whose size disagrees with the dimensions")
    odd = tmp / "Odd.blk"
    odd.write_bytes(bytes(64))            # answers say 9x10 = 90
    answers = _answers(odd)
    fake = FakeQuestionary(answers)
    err = io.StringIO()
    with contextlib.redirect_stderr(err), _fake_questionary_module(fake):
        spec, _ = _gather_spec(root, fake)
    check("it warns with both numbers",
          err.getvalue() == "warning: Odd.blk is 64 bytes, expected 90 (9x10) "
                            "— continuing anyway.\n", repr(err.getvalue()))
    check("it carries on and builds the spec", spec.label == "OneIsland")

    # An .ablk is compressed, so its size says nothing about the dimensions
    # and must not be checked against them.
    ablk = tmp / "Odd.ablk"
    ablk.write_bytes(bytes(7))
    fake = FakeQuestionary(_answers(ablk))
    err = io.StringIO()
    with contextlib.redirect_stderr(err), _fake_questionary_module(fake):
        spec, _ = _gather_spec(root, fake)
    check("an .ablk's size is not checked", err.getvalue() == "", repr(err.getvalue()))
    check("the .ablk suffix reaches the spec", spec.blk == "maps/blk/OneIsland.ablk",
          spec.blk)


def test_cancelling_any_prompt_aborts(root: Path, tmp: Path) -> None:
    """Ctrl+C at questionary is a None answer, and it must stop the wizard
    wherever it lands — not fall through with None as an answer."""
    print("\n_gather_spec — cancelling")
    blk_src = _blk_source(tmp)
    for index in range(len(_EXPECTED_PROMPTS)):
        answers = _answers(blk_src)
        answers[index] = None
        fake = FakeQuestionary(answers)
        try:
            with _fake_questionary_module(fake):
                _gather_spec(root, fake)
            check(f"cancelling prompt {index} aborts", False, "kept going")
        except _Aborted:
            check(f"cancelling prompt {index} ({_EXPECTED_PROMPTS[index][1][:32]}…) aborts",
                  True)
        except ValidationRejected as e:
            check(f"cancelling prompt {index} aborts", False, f"validated instead: {e}")


def test_main_writes_the_map_and_the_spec(tmp: Path) -> None:
    print("\nprism-newmap — a full run")
    root = _fixture_repo(tmp / "full")
    blk_src = _blk_source(tmp / "full", size=90)
    fake = FakeQuestionary([*_answers(blk_src), True])   # …then "write these?"
    rc, out, err = _run_main(fake, root)

    check("exit code 0", rc == 0, f"got {rc}\n{err}")
    check("the template was written",
          (root / "maps" / "OneIsland.asm").exists())
    check("the template is the shared one",
          (root / "maps" / "OneIsland.asm").read_text()
          == map_new.TEMPLATE.format(label="OneIsland"))
    check("the .blk was copied in",
          (root / "maps" / "blk" / "OneIsland.blk").read_bytes() == bytes(90))
    check("the five source files were wired",
          "mapgroup ONE_ISLAND, 9, 10"
          in (root / "constants" / "map_dimension_constants.asm").read_text()
          and "map_header OneIsland"
          in (root / "maps" / "map_headers.asm").read_text()
          and "map_header_2 OneIsland"
          in (root / "maps" / "second_map_headers.asm").read_text()
          and "OneIsland_BlockData:" in (root / "maps" / "blockdata.asm").read_text()
          and 'INCLUDE "maps/OneIsland.asm"'
          in (root / "maps" / "map_scripts.asm").read_text())

    spec_path = root / ".devtools" / "specs" / "OneIsland.toml"
    check("the spec was saved where the next command expects it",
          spec_path.exists(), str(spec_path))
    check("it says where the spec went and what to run next",
          "Spec saved to .devtools/specs/OneIsland.toml" in out
          and "Next: prism-mapfit add --spec .devtools/specs/OneIsland.toml" in out,
          out[-400:])
    check("it points out that no connections were added",
          "Note: no connections were added" in out, out[-400:])


def test_main_leaves_the_sources_alone_when_you_say_no(tmp: Path) -> None:
    """Answering "no" at the confirmation is a real state, not a clean exit:
    the two files are already on disk and the five source files are not
    touched. The message has to say exactly that, or the tree looks corrupt."""
    print("\nprism-newmap — declining the write")
    root = _fixture_repo(tmp / "declined")
    blk_src = _blk_source(tmp / "declined", size=90)
    before = {
        p: p.read_text()
        for p in [root / "constants" / "map_dimension_constants.asm",
                  root / "maps" / "map_headers.asm",
                  root / "maps" / "second_map_headers.asm",
                  root / "maps" / "blockdata.asm",
                  root / "maps" / "map_scripts.asm"]
    }
    fake = FakeQuestionary([*_answers(blk_src), False])
    rc, out, _err = _run_main(fake, root)

    check("exit code 1", rc == 1, f"got {rc}")
    check("the five source files are byte-identical",
          all(p.read_text() == text for p, text in before.items()))
    check("the two already-written files are named",
          "Aborted — maps/OneIsland.asm and maps/blk/OneIsland.blk were already "
          "written; the five source files were not touched." in out, out[-300:])
    check("but they really were written",
          (root / "maps" / "OneIsland.asm").exists()
          and (root / "maps" / "blk" / "OneIsland.blk").exists())
    check("no spec was saved",
          not (root / ".devtools" / "specs" / "OneIsland.toml").exists())


def test_main_aborts_cleanly(tmp: Path) -> None:
    print("\nprism-newmap — cancelling the wizard")
    root = _fixture_repo(tmp / "aborted")
    answers = _answers(_blk_source(tmp / "aborted"))
    answers[0] = None
    rc, out, _err = _run_main(FakeQuestionary(answers), root)
    check("exit code 1", rc == 1, f"got {rc}")
    check("it says nothing was written",
          "Aborted — no files written." in out, out[-200:])
    check("and nothing was", not (root / "maps" / "OneIsland.asm").exists())


def test_main_outside_a_repo(tmp: Path) -> None:
    print("\nprism-newmap — run from outside a game repo")
    outside = tmp / "elsewhere"
    outside.mkdir()
    rc, out, err = _run_main(FakeQuestionary([]), outside)
    check("exit code 2", rc == 2, f"got {rc}")
    check("stdout is empty", out == "", out)
    check("stderr names the tool",
          err.startswith("prism-newmap: Could not find pokeprism repo root from "),
          repr(err))


def test_main_refuses_to_overwrite_an_existing_map(tmp: Path) -> None:
    print("\nprism-newmap — a map file that already exists")
    root = _fixture_repo(tmp / "exists")
    (root / "maps" / "OneIsland.asm").write_text("; mine\n")
    blk_src = _blk_source(tmp / "exists", size=90)
    rc, _out, err = _run_main(FakeQuestionary([*_answers(blk_src), True]), root)
    check("exit code 2", rc == 2, f"got {rc}")
    check("it names the file rather than clobbering it",
          err == "error: maps/OneIsland.asm already exists\n", repr(err))
    check("the file is untouched",
          (root / "maps" / "OneIsland.asm").read_text() == "; mine\n")


def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        root = _fixture_repo(tmp)
        test_the_questions_and_the_spec(root, tmp)
        test_the_prompts_refuse_bad_answers(root, tmp)
        test_the_blk_path_is_checked(root, tmp)
        test_a_blk_of_the_wrong_size_warns_but_continues(root, tmp)
        test_cancelling_any_prompt_aborts(root, tmp)
        test_main_writes_the_map_and_the_spec(tmp)
        test_main_leaves_the_sources_alone_when_you_say_no(tmp)
        test_main_aborts_cleanly(tmp)
        test_main_outside_a_repo(tmp)
        test_main_refuses_to_overwrite_an_existing_map(tmp)

    print()
    if _failures:
        print(f"{_failures} check(s) FAILED")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
