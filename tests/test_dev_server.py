#!/usr/bin/env python3
"""Characterization tests for prism-dev's dev server — what it asks, and what
it leaves in `state.json`.

Hermetic: a temp repo, a canned `inventory.json`, and a fake `questionary`. No
`.sym` is parsed, no save is patched, no emulator is spawned.

    python tests/test_dev_server.py

**Nothing here was executed by anything before this file.** Five test files
import `dev_server` and every one of them reaches `apply`, `inventory` or
`playtest`; `cli.py` imports `tui` lazily, on the interactive branch only, so
under the whole suite `tui.py` ran **zero** lines and never entered
`sys.modules`. Phase 1b's uncovered functions at least ran their `def`.

`DevServer` reads no stdin — every prompt is a `questionary` call. So the fake
below is the one `tests/test_map_new_cli.py` installs for the new-map wizard,
plus the `Separator` that four of these editors use and the `disabled=` that the
bag's full pocket needs. As there, **the fake runs each prompt's own `validate`**
against the answer it is about to hand back, so a scripted run also proves the
answers are ones the editor would have accepted from a human.

**The fixture's shape is chosen from the mutations it has to be able to fail
on**, not from what a representative repo looks like — Phase 1b lost ten
mutations to a fixture whose shape made right and wrong output identical. Every
oddity in `_INVENTORY` and `_STATE` is annotated with the mutation it exists to
catch.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pokeprism_devtools.dev_server import playtest, tui  # noqa: E402

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
    """What a questionary prompt is, as far as an editor is concerned: something
    with `.ask()`. Returning None is how questionary reports Ctrl+C, and every
    editor here reads None as "go back"."""

    def __init__(self, value):
        self._value = value

    def ask(self):
        return self._value


class ValidationRejected(Exception):
    """A canned answer a real prompt would have refused."""


class FakeQuestionary:
    """Stands in for the `questionary` module.

    Records every prompt in order with the choices it offered, and runs the
    prompt's own `validate` against the answer it is about to give back.
    """

    def __init__(self, answers: list) -> None:
        self._answers = list(answers)
        self.asked: list[tuple[str, str]] = []
        self.choices_offered: list[list] = []

    def _respond(self, kind: str, message: str, validate=None, choices=None,
                 default=None):
        self.asked.append((kind, message))
        self.choices_offered.append(list(choices) if choices is not None else [])
        if not self._answers:
            raise AssertionError(f"asked more than was scripted: {message!r}")
        value = self._answers.pop(0)
        if validate is not None and value is not None:
            verdict = validate(value)
            if verdict is not True:
                raise ValidationRejected(f"{message!r} rejected {value!r}: {verdict}")
        return _CannedAnswer(value)

    def text(self, message, **kw):
        return self._respond("text", message, **kw)

    def select(self, message, **kw):
        return self._respond("select", message, **kw)

    def autocomplete(self, message, **kw):
        return self._respond("autocomplete", message, **kw)

    def confirm(self, message, **kw):
        return self._respond("confirm", message, **kw)

    @property
    def unused(self) -> list:
        return self._answers

    def titles(self, index: int) -> list[str]:
        """The labels one prompt offered, `Separator`s included as ''."""
        return [c.title for c in self.choices_offered[index]]


class _FakeChoice:
    def __init__(self, title, value=None, disabled=None, **kw):
        self.title = title
        self.value = value
        self.disabled = disabled


class _FakeSeparator:
    def __init__(self, line: str = "") -> None:
        self.title = ""
        self.value = None
        self.disabled = None


@contextlib.contextmanager
def _fake_questionary_module(fake):
    """Install *fake* as the `questionary` every editor imports, and the two
    names they import from it."""
    module = types.ModuleType("questionary")
    for name in ("text", "select", "autocomplete", "confirm"):
        setattr(module, name, getattr(fake, name))
    module.Choice = _FakeChoice
    module.Separator = _FakeSeparator
    saved = sys.modules.get("questionary")
    sys.modules["questionary"] = module
    try:
        yield module
    finally:
        if saved is None:
            del sys.modules["questionary"]
        else:
            sys.modules["questionary"] = saved


# --------------------------------------------------------------------------- #
# The fixture
# --------------------------------------------------------------------------- #

#: A fixed mtime for the fake .sym, so "has the ROM been rebuilt?" is a question
#: the test controls rather than one the filesystem answers.
SYM_MTIME = 1_600_000_000

#: The canned inventory. Every oddity here is deliberate; the comment says which
#: mutation it exists to fail on.
_INVENTORY = {
    "schema": None,          # filled in from the module, so a schema bump
                             # rebuilds the fixture rather than silently
                             # falling through to `build()` and a real .sym
    "maps": [
        # width != height on every map, so `_coord_bound` transposing the axes
        # cannot pass. Phase 1b was bitten by exactly this with `mapgroup`'s
        # (H, W), on a fixture that could not tell them apart.
        {"name": "CAPER_RIDGE", "width": 20, "height": 9},
        {"name": "CAPER_HOUSE", "width": 4, "height": 6},
    ],
    "bag_caps": {
        # Small enough that a pocket can actually be filled, so the "pocket
        # full" disabled branch runs.
        "items": 3, "balls": 2, "key_items": 2,
    },
    "items": [
        {"name": "POTION", "id": 1, "pocket": "ITEM"},
        {"name": "ANTIDOTE", "id": 2, "pocket": "ITEM"},
        {"name": "ETHER", "id": 3, "pocket": "ITEM"},
        # A ball and a key item, so a pocket editor offering *every* item
        # instead of filtering on `pocket` is distinguishable.
        {"name": "POKE_BALL", "id": 4, "pocket": "BALL"},
        {"name": "GREAT_BALL", "id": 5, "pocket": "BALL"},
        {"name": "BICYCLE", "id": 6, "pocket": "KEY_ITEM"},
        {"name": "OLD_ROD", "id": 7, "pocket": "KEY_ITEM"},
    ],
    "moves": [
        {"name": "TACKLE", "id": 1},
        {"name": "EMBER", "id": 2},
        {"name": "SCRATCH", "id": 3},
        {"name": "GROWL", "id": 4},
        {"name": "LEER", "id": 5},
    ],
    "species_data": {
        "CYNDAQUIL": {"hp": 39, "learnset": []},
        "SENTRET": {"hp": 35, "learnset": []},
        "TOTODILE": {"hp": 50, "learnset": []},
    },
    "event_flags": [
        {"name": "EVENT_GOT_A_POKEMON", "id": 1},
        {"name": "EVENT_BEAT_FALKNER", "id": 2},
        {"name": "EVENT_MET_BILL", "id": 3},
    ],
    "engine_flags": [
        {"name": "ENGINE_POKEDEX", "id": 1},
        {"name": "ENGINE_BIKE_SHOP_CALL_ENABLED", "id": 2},
    ],
    "tmhms": [
        # Alphabetical order and bit order disagree completely, so sorting the
        # owned list by name instead of by `bit` fails. In a real inventory
        # `bit` is the entry's index, which is what this reproduces.
        {"name": "TM_ZAP_CANNON", "move": "ZAP_CANNON", "kind": "TM",
         "num": 1, "bit": 0},
        {"name": "TM_HEADBUTT", "move": "HEADBUTT", "kind": "TM",
         "num": 2, "bit": 1},
        {"name": "TM_CURSE", "move": "CURSE", "kind": "TM", "num": 3, "bit": 2},
        {"name": "HM_CUT", "move": "CUT", "kind": "HM", "num": 1, "bit": 3},
    ],
}

#: The state the server opens on. Deliberately partial: `party` and `flags` are
#: present, `tmhms` is present-but-short, and the items pocket carries one
#: bare-string entry — state.json's shorthand for quantity 1, which the pocket
#: editor normalises on the way in.
_STATE = {
    "player": {"name": "RED", "money": 3000, "badges": [1, 0, 0]},
    "map": {"name": "CAPER_RIDGE", "x": 4, "y": 6},
    "party": [
        # Two slots, so `party.pop(idx)` cannot be confused with `party.pop()`,
        # and a nickname on only one of them.
        {"species": "CYNDAQUIL", "level": 12, "nickname": "Cyn"},
        {"species": "SENTRET", "level": 3},
    ],
    "items": {
        # One dict and one bare string in each shape of pocket — the bare
        # string is state.json's shorthand for quantity 1, and it is the only
        # input `_normalized` does anything to. Without one in the *key item*
        # pocket, giving key items a quantity they must never carry is a
        # change no assertion can see.
        "items": [{"name": "POTION", "qty": 3}, "ANTIDOTE"],
        "key_items": ["BICYCLE"],
        # "balls" is absent on purpose: "(template)" and an explicit empty
        # pocket are different states, and this file is careful about that.
    },
    "flags": {"event": ["EVENT_GOT_A_POKEMON"], "engine": []},
    "tmhms": ["TM_HEADBUTT"],
}


def _fixture(tmp: Path) -> Path:
    root = tmp / "repo"
    root.mkdir(parents=True)
    (root / "Makefile").write_text("all:\n")
    (root / "main.asm").write_text('INCLUDE "constants.asm"\n')
    # `shared/paths.rom_path` hardcodes prism's ROM filenames — the leak named
    # in `tests/test_products.py::KNOWN_LEAKS` and handed to Phase 5. The status
    # block prints the ROM's name, so the fixture has to spell it that way too.
    (root / "pokeprism.gbc").write_bytes(b"")

    dev = root / ".devtools"
    (dev / "presets").mkdir(parents=True)
    (dev / "sav-backups").mkdir()

    sym = root / "pokeprism.sym"
    sym.write_text("")
    os.utime(sym, (SYM_MTIME, SYM_MTIME))

    inv = dict(_INVENTORY)
    inv["schema"] = _inventory_schema()
    (dev / "inventory.json").write_text(json.dumps(inv, indent=2))
    (dev / "state.json").write_text(json.dumps(_STATE, indent=2))
    (dev / "presets" / "default.json").write_text(
        json.dumps({"player": {"name": "PRESET"}}, indent=2))
    (dev / "presets" / "champion.json").write_text(
        json.dumps({"player": {"name": "CHAMP", "money": 999999}}, indent=2))
    return root


def _inventory_schema() -> int:
    from pokeprism_devtools.dev_server import inventory
    return inventory.INVENTORY_SCHEMA


class _StubEmulator:
    """Stands where the SameBoy subprocess would. A real process boundary, so
    everything on this side of it runs unchanged."""

    def __init__(self) -> None:
        self.running = False
        self.launched: list[Path] = []

    def launch(self, rom_path: Path):
        self.launched.append(rom_path)
        self.running = True
        return types.SimpleNamespace(
            replaced=False, warnings=[], launched=True, found=True,
            command=f"sameboy {rom_path.name}")


def _server(root: Path, **kw) -> tui.DevServer:
    """A `DevServer` on the fixture, with the emulator stubbed and the watcher
    thread never started (the tests that want it start it themselves)."""
    dev = root / ".devtools"
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        server = tui.DevServer(
            root=root,
            sym_path=root / "pokeprism.sym",
            debug=True,
            state_path=dev / "state.json",
            inventory_path=dev / "inventory.json",
            presets_dir=dev / "presets",
            sav_backups_dir=dev / "sav-backups",
            keep_people=False,
            rebuild_inventory=False,
            **{"auto_relaunch": False, **kw},
        )
    server.emulator = _StubEmulator()
    return server


def _drive(server, method: str, answers: list, *args) -> tuple[FakeQuestionary, str]:
    """Run one editor against a canned script, and hand back what it asked and
    what it printed."""
    fake = FakeQuestionary(answers)
    out = io.StringIO()
    with _fake_questionary_module(fake), contextlib.redirect_stdout(out):
        getattr(server, method)(*args)
    return fake, out.getvalue()


def _written(root: Path) -> dict:
    return json.loads((root / ".devtools" / "state.json").read_text())


# --------------------------------------------------------------------------- #
# The status block
# --------------------------------------------------------------------------- #

def test_the_status_block(tmp: Path) -> None:
    print("\nDevServer — the status block")
    root = _fixture(tmp / "status")
    server = _server(root)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        server._print_status_block()

    got = _normalise_mtime(out.getvalue())
    want = (
        "\n"
        "  Build:   pokeprism.gbc    sym mtime: <when>\n"
        "  State:   .devtools/state.json\n"
        "           player: name=     'RED'  money=3000  badges=[1, 0, 0]\n"
        "           map:    CAPER_RIDGE  at (4, 6)\n"
        "           party:  CYNDAQUIL@L12, SENTRET@L3\n"
        "           items:  2 items, 1 key\n"
        "           flags:  1 event, 0 engine\n"
        "           tmhms:  1/4 owned\n"
        "  SameBoy: not running\n"
        "\n"
    )
    check("every line, as recorded", got == want,
          "" if got == want else f"\n--- got ---\n{got}\n--- want ---\n{want}")

    # Not a golden: the point is that the field *tracks the .sym*, which is what
    # tells you your build is stale. Asserting the strftime format here would
    # only restate it, and would break on a machine in another timezone.
    os.utime(root / "pokeprism.sym", (SYM_MTIME + 86_400, SYM_MTIME + 86_400))
    later = _server(root)
    out2 = io.StringIO()
    with contextlib.redirect_stdout(out2):
        later._print_status_block()
    check("the mtime field follows the .sym",
          _mtime_field(out2.getvalue()) != _mtime_field(out.getvalue()),
          _mtime_field(out2.getvalue()))


def test_the_status_block_on_a_bare_state(tmp: Path) -> None:
    """A state that overrides nothing has to read as "(template)" everywhere,
    not as zero of everything — they mean opposite things at launch."""
    print("\nDevServer — the status block with nothing overridden")
    root = _fixture(tmp / "bare")
    (root / ".devtools" / "state.json").write_text("{}\n")
    server = _server(root)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        server._print_status_block()
    got = _normalise_mtime(out.getvalue())
    want = (
        "\n"
        "  Build:   pokeprism.gbc    sym mtime: <when>\n"
        "  State:   .devtools/state.json\n"
        "           player: name=       '?'  money=?  badges=?\n"
        "           map:    ?  at (?, ?)\n"
        "           party:  (template)\n"
        "           items:  (template)\n"
        "           flags:  0 event, 0 engine\n"
        "           tmhms:  (template)\n"
        "  SameBoy: not running\n"
        "\n"
    )
    check("every line, as recorded", got == want,
          "" if got == want else f"\n--- got ---\n{got}\n--- want ---\n{want}")


def _mtime_field(text: str) -> str:
    line = next(l for l in text.splitlines() if "sym mtime:" in l)
    return line.split("sym mtime:")[1].strip()


def _normalise_mtime(text: str) -> str:
    return text.replace(_mtime_field(text), "<when>")


# --------------------------------------------------------------------------- #
# The menu loop
# --------------------------------------------------------------------------- #

#: What the top menu offers, in order. A menu *is* its list.
_TOP_MENU = [
    "Launch  (patch .sav, spawn SameBoy)",
    "Edit player...",
    "Edit map / position...",
    "Reset state from preset...",
    "",                                    # Separator
    "Edit party...",
    "Edit items...",
    "Edit flags...",
    "Edit TM/HMs...",
    "",                                    # Separator
    "Quit",
]


def test_the_menu_offers_these_things_in_this_order(tmp: Path) -> None:
    print("\nDevServer.run — the menu")
    root = _fixture(tmp / "menu")
    server = _server(root)
    fake, out = _drive(server, "run", ["quit"])

    check("one prompt, and it is the menu", fake.asked == [("select", "What now?")],
          str(fake.asked))
    check("the menu, in order", fake.titles(0) == _TOP_MENU, str(fake.titles(0)))
    check("it says the emulator was left alone only if it is running",
          "SameBoy is still running" not in out, out[-200:])


def test_the_launch_entry_renames_itself_once_sameboy_is_up(tmp: Path) -> None:
    """The first entry is "Launch" or "Re-launch" depending on whether SameBoy
    is already running — the one place the menu is not a constant."""
    print("\nDevServer.run — Launch vs Re-launch")
    root = _fixture(tmp / "relaunch")
    server = _server(root)
    server.emulator.running = True
    fake, out = _drive(server, "run", ["quit"])
    check("it reads Re-launch", fake.titles(0)[0]
          == "Re-launch  (patch .sav, spawn SameBoy)", fake.titles(0)[0])
    check("and it says SameBoy was left alone",
          "SameBoy is still running" in out, out[-200:])


def test_every_menu_entry_reaches_its_editor(tmp: Path) -> None:
    """The dispatch table, checked entry by entry. A menu that offers a thing
    and runs another is the failure this table exists to prevent."""
    print("\nDevServer.run — the dispatch")
    root = _fixture(tmp / "dispatch")
    # In the order the menu offers them, which is not the order the dispatch
    # table spells them — the table is grouped by what an entry does, the menu
    # by how often you reach for it.
    wanted = {
        "launch": "_patch_and_launch",
        "edit_player": "_edit_player",
        "edit_map": "_edit_map",
        "reset_preset": "_reset_preset",
        "edit_party": "_edit_party",
        "edit_items": "_edit_items",
        "edit_flags": "_edit_flags",
        "edit_tmhms": "_edit_tmhms",
    }
    for value, method in wanted.items():
        server = _server(root)
        called: list[str] = []
        setattr(server, method, lambda *a, **k: called.append(method))
        _drive(server, "run", [value, "quit"])
        check(f"{value} runs {method}", called == [method], str(called))

    # And the values the menu offers are exactly the keys of that table, so a
    # renamed entry cannot quietly stop being reachable.
    server = _server(root)
    fake, _ = _drive(server, "run", ["quit"])
    offered = [c.value for c in fake.choices_offered[0] if c.value is not None]
    check("the menu's values are the dispatch's keys, plus quit",
          offered == [*wanted, "quit"], str(offered))


def test_an_editor_that_raises_does_not_take_the_server_down(tmp: Path) -> None:
    """A failed edit prints and returns to the menu — the server is long-lived
    and a traceback would end the session."""
    print("\nDevServer.run — an editor that raises")
    root = _fixture(tmp / "raises")
    server = _server(root)

    def _boom() -> None:
        raise RuntimeError("the map fell over")

    server._edit_map = _boom
    fake = FakeQuestionary(["edit_map", "quit"])
    out, err = io.StringIO(), io.StringIO()
    with _fake_questionary_module(fake), contextlib.redirect_stdout(out), \
            contextlib.redirect_stderr(err):
        rc = server.run()
    check("it comes back to the menu", len(fake.asked) == 2, str(fake.asked))
    check("exit code 0", rc == 0, str(rc))
    check("the error names itself on stderr",
          err.getvalue() == "\nerror: the map fell over\n", repr(err.getvalue()))


def test_ctrl_c_at_the_menu_quits(tmp: Path) -> None:
    print("\nDevServer.run — cancelling the menu")
    root = _fixture(tmp / "cancel")
    server = _server(root)
    fake, _out = _drive(server, "run", [None])
    check("one prompt and then out", len(fake.asked) == 1, str(fake.asked))


# --------------------------------------------------------------------------- #
# The player
# --------------------------------------------------------------------------- #

def test_edit_player(tmp: Path) -> None:
    print("\n_edit_player")
    root = _fixture(tmp / "player")
    server = _server(root)
    fake, _ = _drive(server, "_edit_player", ["name", "PIKA", "back"])

    check("the menu shows what is set now",
          fake.titles(0) == ["Name    : RED", "Money   : 3000",
                             "Badges  : [1, 0, 0]", "← Back"], str(fake.titles(0)))
    check("the prompts, in order",
          fake.asked == [("select", "Edit player"),
                         ("text", "Player name (1–7 chars, GB charset):"),
                         ("select", "Edit player")], str(fake.asked))
    check("the menu redraws with the new name",
          fake.titles(2)[0] == "Name    : PIKA", fake.titles(2)[0])
    check("state.json has it", _written(root)["player"]["name"] == "PIKA",
          str(_written(root)["player"]))

    server = _server(root)
    fake, _ = _drive(server, "_edit_player", ["money", "12345", "back"])
    check("money is stored as a number, not the string that was typed",
          _written(root)["player"]["money"] == 12345,
          repr(_written(root)["player"]["money"]))


def test_the_player_prompts_refuse_bad_answers(tmp: Path) -> None:
    print("\n_edit_player — what each prompt refuses")
    root = _fixture(tmp / "player_bad")
    for label, script, expected in [
        ("an eight-character name", ["name", "TOOLONG!", "back"], "1–7 chars"),
        ("an empty name", ["name", "", "back"], "1–7 chars"),
        ("money past the cap", ["money", "1000000", "back"], "must be 0..999999"),
        ("money that is not a number", ["money", "lots", "back"], "not an integer"),
        ("a badge byte past 255", ["badges", "256", "back"], "must be 0..255"),
    ]:
        try:
            _drive(_server(root), "_edit_player", script)
            check(label, False, "accepted")
        except ValidationRejected as e:
            check(label, expected in str(e), str(e))


def test_all_three_badge_bytes_are_asked_for_and_kept_together(tmp: Path) -> None:
    """Badges are one field spread over three prompts, and a cancel part-way
    through must leave all three alone rather than write a partial set."""
    print("\n_edit_player — badges")
    root = _fixture(tmp / "badges")
    fake, _ = _drive(_server(root), "_edit_player", ["badges", "7", "3", "1", "back"])
    check("it asks for each region by name",
          [m for _, m in fake.asked if "badges" in m]
          == ["Naljo badges (0–255 bitmask):", "Rijon badges (0–255 bitmask):",
              "Other badges (0–255 bitmask):"], str(fake.asked))
    check("all three land", _written(root)["player"]["badges"] == [7, 3, 1],
          str(_written(root)["player"]["badges"]))

    root = _fixture(tmp / "badges_cancel")
    _drive(_server(root), "_edit_player", ["badges", "7", None, "back"])
    check("cancelling the second leaves all three as they were",
          _written(root)["player"]["badges"] == [1, 0, 0],
          str(_written(root)["player"]["badges"]))


# --------------------------------------------------------------------------- #
# The map and the tile you stand on
# --------------------------------------------------------------------------- #

def test_edit_map(tmp: Path) -> None:
    print("\n_edit_map")
    root = _fixture(tmp / "map")
    server = _server(root)
    fake, _ = _drive(server, "_edit_map", ["name", "CAPER_HOUSE", "back"])
    check("the menu shows what is set now",
          fake.titles(0) == ["Map name : CAPER_RIDGE", "X coord  : 4",
                             "Y coord  : 6", "← Back"], str(fake.titles(0)))
    check("the map list is every map in the inventory, sorted",
          fake.choices_offered[1] == ["CAPER_HOUSE", "CAPER_RIDGE"],
          str(fake.choices_offered[1]))
    check("state.json has it", _written(root)["map"]["name"] == "CAPER_HOUSE",
          str(_written(root)["map"]))


def test_the_coord_bounds_come_from_the_map_and_not_from_each_other(tmp: Path) -> None:
    """A block is two tiles per axis, so the coord runs 0..(blocks*2 - 1) —
    **from that axis's own dimension.** The fixture's maps are all
    width != height, because a square map cannot tell a transposition apart,
    which is the mistake Phase 1b found in `mapgroup`'s (H, W)."""
    print("\n_edit_map — the coord bounds")
    root = _fixture(tmp / "coords")

    # CAPER_RIDGE is 20 wide, 9 tall.
    fake, _ = _drive(_server(root), "_edit_map", ["x", "10", "back"])
    check("X is bounded by the width", fake.asked[1] == ("text", "X coord (0–39):"),
          str(fake.asked[1]))
    fake, _ = _drive(_server(root), "_edit_map", ["y", "10", "back"])
    check("Y is bounded by the height", fake.asked[1] == ("text", "Y coord (0–17):"),
          str(fake.asked[1]))

    # CAPER_HOUSE is 4 wide, 6 tall — the other way round, so a bound that
    # always read one dimension would agree with the first map and not this one.
    root2 = _fixture(tmp / "coords2")
    (root2 / ".devtools" / "state.json").write_text(
        json.dumps({**_STATE, "map": {"name": "CAPER_HOUSE", "x": 0, "y": 0}}))
    fake, _ = _drive(_server(root2), "_edit_map", ["x", "3", "back"])
    check("and on a taller-than-wide map they are the other way round",
          fake.asked[1] == ("text", "X coord (0–7):"), str(fake.asked[1]))
    fake, _ = _drive(_server(root2), "_edit_map", ["y", "3", "back"])
    check("…on both axes", fake.asked[1] == ("text", "Y coord (0–11):"),
          str(fake.asked[1]))


def test_an_unknown_map_falls_back_to_a_whole_byte(tmp: Path) -> None:
    """A tile coord is one byte, so a map the inventory has never heard of gets
    0..255 rather than a crash or a zero-width bound."""
    print("\n_edit_map — a map the inventory does not know")
    root = _fixture(tmp / "unknown_map")
    (root / ".devtools" / "state.json").write_text(
        json.dumps({**_STATE, "map": {"name": "NOWHERE", "x": 0, "y": 0}}))
    fake, _ = _drive(_server(root), "_edit_map", ["x", "200", "back"])
    check("0..255", fake.asked[1] == ("text", "X coord (0–255):"), str(fake.asked[1]))


def test_the_map_prompts_refuse_bad_answers(tmp: Path) -> None:
    print("\n_edit_map — what each prompt refuses")
    root = _fixture(tmp / "map_bad")
    for label, script, expected in [
        ("a map the tree does not define", ["name", "ATLANTIS", "back"],
         "unknown map: ATLANTIS"),
        ("an X past the map's width", ["x", "40", "back"], "must be 0..39"),
        ("a Y past the map's height", ["y", "18", "back"], "must be 0..17"),
    ]:
        try:
            _drive(_server(root), "_edit_map", script)
            check(label, False, "accepted")
        except ValidationRejected as e:
            check(label, expected in str(e), str(e))


# --------------------------------------------------------------------------- #
# The party
# --------------------------------------------------------------------------- #

def test_edit_party_lists_six_slots_however_many_are_filled(tmp: Path) -> None:
    print("\n_edit_party")
    root = _fixture(tmp / "party")
    fake, _ = _drive(_server(root), "_edit_party", [("back", None)])
    check("six slots, then clear, then back",
          fake.titles(0) == ["Slot 1: CYNDAQUIL L12  'Cyn'", "Slot 2: SENTRET L3",
                             "Slot 3: (empty)", "Slot 4: (empty)",
                             "Slot 5: (empty)", "Slot 6: (empty)",
                             "Clear party", "← Back"], str(fake.titles(0)))

    root = _fixture(tmp / "party_empty")
    (root / ".devtools" / "state.json").write_text(json.dumps({**_STATE, "party": []}))
    fake, _ = _drive(_server(root), "_edit_party", [("back", None)])
    check("an empty party is not offered a Clear",
          "Clear party" not in fake.titles(0), str(fake.titles(0)))


def test_edit_a_party_slot(tmp: Path) -> None:
    print("\n_edit_party — one slot")
    root = _fixture(tmp / "slot")
    fake, _ = _drive(_server(root), "_edit_party",
                     [("slot", 0), "level", "20", "back", ("back", None)])
    check("the slot menu shows what is set, and what is defaulted",
          fake.titles(1) == ["Species  : CYNDAQUIL", "Level    : 12",
                             "Nickname : Cyn", "Moves    : (from learnset)",
                             "Remove slot", "← Back"], str(fake.titles(1)))
    check("the level lands", _written(root)["party"][0]["level"] == 20,
          str(_written(root)["party"][0]))
    check("and nothing else in the slot moved",
          _written(root)["party"][0]["species"] == "CYNDAQUIL"
          and _written(root)["party"][0]["nickname"] == "Cyn",
          str(_written(root)["party"][0]))


def test_removing_a_slot_removes_that_slot(tmp: Path) -> None:
    """Two slots in the fixture, and the *first* is removed — with one slot,
    `party.pop(idx)` and `party.pop()` are the same call."""
    print("\n_edit_party — removing")
    root = _fixture(tmp / "party_remove")
    _drive(_server(root), "_edit_party", [("slot", 0), "remove", ("back", None)])
    check("the named slot went and the other stayed",
          [m["species"] for m in _written(root)["party"]] == ["SENTRET"],
          str(_written(root)["party"]))


def test_a_slot_abandoned_before_a_species_is_dropped(tmp: Path) -> None:
    """Opening an empty slot allocates it lazily; backing out without naming a
    species drops it again — that is what the code says it does, and for the
    *next* slot after the last filled one it is what happens."""
    print("\n_edit_party — an abandoned empty slot")
    root = _fixture(tmp / "party_abandon")
    _drive(_server(root), "_edit_party", [("slot", 2), "back", ("back", None)])
    check("the party is as it was", len(_written(root)["party"]) == 2,
          str(_written(root)["party"]))

    root = _fixture(tmp / "party_fill")
    _drive(_server(root), "_edit_party",
           [("slot", 2), "species", "TOTODILE", "back", ("back", None)])
    check("but naming a species keeps the slot, with a default level",
          _written(root)["party"][2] == {"species": "TOTODILE", "level": 5},
          str(_written(root)["party"]))


def test_abandoning_a_slot_past_the_end_leaves_no_gaps(tmp: Path) -> None:
    """Opening slot 5 with two mons in the party appends *three* empty dicts to
    reach it. Backing out has to drop all three, not just the one that was
    asked for: `apply._apply_party` refuses an entry with no species, so a gap
    left behind kills the *next* launch with `invalid party entry: {}` and the
    only way out is editing state.json by hand.

    Filling a slot past the end and then removing it is the same story with an
    extra step, so both ways out of the slot editor are driven here.
    """
    print("\n_edit_party — abandoning a slot past the end of the party")
    for label, script in [
        ("backing out of it", [("slot", 4), "back", ("back", None)]),
        ("filling it and then removing it",
         [("slot", 4), "species", "TOTODILE", "remove", ("back", None)]),
    ]:
        root = _fixture(tmp / f"party_gaps_{label.split()[0]}")
        _drive(_server(root), "_edit_party", script)
        party = _written(root)["party"]
        check(f"{label}: the party is as it was",
              party == [{"species": "CYNDAQUIL", "level": 12, "nickname": "Cyn"},
                        {"species": "SENTRET", "level": 3}], str(party))
        refuses = _apply_party_refuses(party)
        check(f"{label}: and the patcher takes it",
              not refuses, "the patcher still refuses it")


def test_a_hand_written_gap_is_left_alone(tmp: Path) -> None:
    """Only *trailing* empties are dropped. A `{}` someone put in the middle of
    state.json by hand is not ours to guess about — removing it would silently
    renumber every slot after it."""
    print("\n_edit_party — a gap that was not ours")
    root = _fixture(tmp / "party_handgap")
    (root / ".devtools" / "state.json").write_text(json.dumps({
        **_STATE, "party": [{"species": "CYNDAQUIL", "level": 12}, {},
                            {"species": "SENTRET", "level": 3}]}))
    _drive(_server(root), "_edit_party", [("slot", 2), "remove", ("back", None)])
    check("the slot asked for went, the hand-written gap stayed",
          _written(root)["party"] == [{"species": "CYNDAQUIL", "level": 12}, {}],
          str(_written(root)["party"]))


def _apply_party_refuses(party: list[dict]) -> bool:
    """What `apply` does with an entry that has no species — asked of the real
    function, so this stays true if its message or its guard changes."""
    from pokeprism_devtools.dev_server import apply as apply_mod
    try:
        apply_mod._apply_party(None, party, {"pokemon": [], "moves": [], "items": [],
                                             "species_data": {}, "move_pp": []},
                               {}, lambda _n: 0)
    except ValueError as e:
        return "invalid party entry" in str(e)
    except Exception:
        return False
    return False


def test_a_nickname_is_cleared_by_blanking_it(tmp: Path) -> None:
    print("\n_edit_party — nicknames")
    root = _fixture(tmp / "nick")
    _drive(_server(root), "_edit_party",
           [("slot", 0), "nickname", "", "back", ("back", None)])
    check("a blank removes the key rather than storing an empty string",
          "nickname" not in _written(root)["party"][0],
          str(_written(root)["party"][0]))

    root = _fixture(tmp / "nick2")
    _drive(_server(root), "_edit_party",
           [("slot", 1), "nickname", "Sen", "back", ("back", None)])
    check("and a name is stored on the slot it was asked about",
          _written(root)["party"][1].get("nickname") == "Sen",
          str(_written(root)["party"][1]))


def test_moves_are_four_prompts_and_a_way_out(tmp: Path) -> None:
    print("\n_edit_party — moves")
    root = _fixture(tmp / "moves")
    fake, _ = _drive(_server(root), "_edit_party",
                     [("slot", 0), "moves", "TACKLE", "EMBER", "", "",
                      "back", ("back", None)])
    check("four prompts, numbered",
          [m for _, m in fake.asked if m.startswith("Move ")]
          == ["Move 1 (blank = empty, '-' = revert to learnset):",
              "Move 2 (blank = empty, '-' = revert to learnset):",
              "Move 3 (blank = empty, '-' = revert to learnset):",
              "Move 4 (blank = empty, '-' = revert to learnset):"], str(fake.asked))
    check("the blanks are dropped, the order is kept",
          _written(root)["party"][0]["moves"] == ["TACKLE", "EMBER"],
          str(_written(root)["party"][0]))

    root = _fixture(tmp / "moves_revert")
    _drive(_server(root), "_edit_party",
           [("slot", 0), "moves", "TACKLE", "EMBER", "", "", "back", ("back", None)])
    server = _server(root)
    _drive(server, "_edit_party", [("slot", 0), "moves", "-", "back", ("back", None)])
    check("a single dash reverts the slot to its learnset",
          "moves" not in _written(root)["party"][0], str(_written(root)["party"][0]))


def test_clearing_the_party_asks_first(tmp: Path) -> None:
    print("\n_edit_party — clearing")
    root = _fixture(tmp / "party_clear")
    fake, _ = _drive(_server(root), "_edit_party",
                     [("clear", None), False, ("back", None)])
    check("it asks", ("confirm", "Clear all party slots?") in fake.asked,
          str(fake.asked))
    check("and no means no", len(_written(root)["party"]) == 2,
          str(_written(root)["party"]))

    root = _fixture(tmp / "party_clear2")
    _drive(_server(root), "_edit_party", [("clear", None), True, ("back", None)])
    check("yes empties it, explicitly", _written(root)["party"] == [],
          str(_written(root)["party"]))


def test_the_party_prompts_refuse_bad_answers(tmp: Path) -> None:
    print("\n_edit_party — what each prompt refuses")
    root = _fixture(tmp / "party_bad")
    for label, script, expected in [
        ("a species the tree does not define",
         [("slot", 0), "species", "MISSINGNO", "back", ("back", None)],
         "unknown species: MISSINGNO"),
        ("a level of zero", [("slot", 0), "level", "0", "back", ("back", None)],
         "must be 1..100"),
        ("a level past 100", [("slot", 0), "level", "101", "back", ("back", None)],
         "must be 1..100"),
        ("a nickname past ten characters",
         [("slot", 0), "nickname", "ELEVENCHARS", "back", ("back", None)],
         "max 10 chars"),
        ("a move the tree does not define",
         [("slot", 0), "moves", "HYPER_NOPE", "back", ("back", None)],
         "unknown move: HYPER_NOPE"),
    ]:
        try:
            _drive(_server(root), "_edit_party", script)
            check(label, False, "accepted")
        except ValidationRejected as e:
            check(label, expected in str(e), str(e))


# --------------------------------------------------------------------------- #
# The bag
# --------------------------------------------------------------------------- #

def test_edit_items_lists_the_three_pockets(tmp: Path) -> None:
    print("\n_edit_items")
    root = _fixture(tmp / "items")
    fake, _ = _drive(_server(root), "_edit_items", ["back"])
    check("each pocket, with how full it is against its cap",
          fake.titles(0) == ["Items pocket       2/3", "Balls pocket       (template)",
                             "Key items pocket   1/2", "← Back"],
          str(fake.titles(0)))


def test_an_inventory_without_bag_caps_says_so(tmp: Path) -> None:
    """The caps arrive with the inventory schema, so an old inventory.json has
    to be told to rebuild rather than crash on a missing key."""
    print("\n_edit_items — no bag caps")
    root = _fixture(tmp / "nocaps")
    inv = json.loads((root / ".devtools" / "inventory.json").read_text())
    del inv["bag_caps"]
    (root / ".devtools" / "inventory.json").write_text(json.dumps(inv))
    server = _server(root)
    fake, out = _drive(server, "_edit_items", [])
    check("it asks nothing", fake.asked == [], str(fake.asked))
    check("and says how to fix it",
          out == "(inventory has no bag_caps — rebuild it: --rebuild-inventory)\n",
          repr(out))


def test_a_pocket_offers_only_its_own_items(tmp: Path) -> None:
    """The fixture has items in all three pockets, so an editor that offered
    every item in the inventory would be caught here rather than pass."""
    print("\n_edit_pocket — what it offers")
    root = _fixture(tmp / "pocket_offers")
    fake, _ = _drive(_server(root), "_edit_items",
                     ["balls", ("add", None), "POKE_BALL", "1",
                      ("back", None), "back"])
    check("the ball pocket offers balls and nothing else",
          fake.choices_offered[2] == ["GREAT_BALL", "POKE_BALL"],
          str(fake.choices_offered[2]))

    root = _fixture(tmp / "pocket_offers2")
    fake, _ = _drive(_server(root), "_edit_items",
                     ["items", ("add", None), "ETHER", "1", ("back", None), "back"])
    check("and an item already in the pocket is not offered twice",
          fake.choices_offered[2] == ["ETHER"], str(fake.choices_offered[2]))


def test_adding_to_a_pocket(tmp: Path) -> None:
    print("\n_edit_pocket — adding")
    root = _fixture(tmp / "pocket_add")
    fake, _ = _drive(_server(root), "_edit_items",
                     ["items", ("add", None), "ETHER", "5", ("back", None), "back"])
    check("the pocket's own header counts against the cap",
          fake.asked[1] == ("select", "Items pocket — 2/3"), str(fake.asked[1]))
    check("the bare-string shorthand was normalised on the way in",
          _written(root)["items"]["items"][:2]
          == [{"name": "POTION", "qty": 3}, {"name": "ANTIDOTE", "qty": 1}],
          str(_written(root)["items"]["items"]))
    check("and the new entry carries the quantity that was typed",
          _written(root)["items"]["items"][2] == {"name": "ETHER", "qty": 5},
          str(_written(root)["items"]["items"]))


def test_a_full_pocket_offers_the_add_row_disabled(tmp: Path) -> None:
    """The caps in the fixture are small enough to reach — with prism's real
    ones this branch would need 50 scripted answers and would never be tested."""
    print("\n_edit_pocket — a full pocket")
    root = _fixture(tmp / "pocket_full")
    fake, _ = _drive(_server(root), "_edit_items",
                     ["items", ("add", None), "ETHER", "1", ("back", None), "back"])
    full = fake.choices_offered[4]
    add = next(c for c in full if c.title == "Add item...")
    check("the row is still there", add.title == "Add item...", add.title)
    check("but it is disabled, and says why", add.disabled == "pocket full",
          repr(add.disabled))
    check("and it offers no value to pick", add.value is None, repr(add.value))


def test_a_quantity_of_zero_removes_the_entry(tmp: Path) -> None:
    print("\n_edit_pocket — quantities")
    root = _fixture(tmp / "pocket_qty")
    _drive(_server(root), "_edit_items",
           ["items", ("entry", 0), "9", ("back", None), "back"])
    check("a quantity is edited in place",
          _written(root)["items"]["items"][0] == {"name": "POTION", "qty": 9},
          str(_written(root)["items"]["items"]))

    root = _fixture(tmp / "pocket_qty0")
    _drive(_server(root), "_edit_items",
           ["items", ("entry", 0), "0", ("back", None), "back"])
    check("and zero takes it out of the pocket",
          [e["name"] for e in _written(root)["items"]["items"]] == ["ANTIDOTE"],
          str(_written(root)["items"]["items"]))


def test_a_key_item_has_no_quantity(tmp: Path) -> None:
    """Key items are the pocket the writer rejects a `qty` on, so the editor
    must not offer one — and its rows remove on a single press."""
    print("\n_edit_pocket — key items")
    root = _fixture(tmp / "pocket_key")
    fake, _ = _drive(_server(root), "_edit_items",
                     ["key_items", ("add", None), "OLD_ROD", ("back", None), "back"])
    check("no quantity is asked for",
          not any("uantity" in m for _, m in fake.asked), str(fake.asked))
    check("and none is stored",
          _written(root)["items"]["key_items"] == [{"name": "BICYCLE"},
                                                   {"name": "OLD_ROD"}],
          str(_written(root)["items"]["key_items"]))
    check("its rows are labelled as one-press removals",
          fake.titles(1)[0] == "  [-] BICYCLE", str(fake.titles(1)))

    root = _fixture(tmp / "pocket_key2")
    _drive(_server(root), "_edit_items",
           ["key_items", ("remove_one", 0), ("back", None), "back"])
    check("and pressing one removes that row",
          _written(root)["items"]["key_items"] == [], "removed")


def test_clearing_a_pocket_is_not_the_same_as_giving_it_back(tmp: Path) -> None:
    """The distinction the whole editor turns on: an empty list means "launch
    with an empty pocket", an absent key means "leave the template's alone"."""
    print("\n_edit_pocket — cleared versus template")
    root = _fixture(tmp / "pocket_clear")
    fake, _ = _drive(_server(root), "_edit_items",
                     ["items", ("clear", None), True, ("back", None), "back"])
    check("clearing asks first",
          ("confirm", "Clear the items pocket?") in fake.asked, str(fake.asked))
    check("and leaves an explicit empty pocket",
          _written(root)["items"]["items"] == [], str(_written(root)["items"]))

    root = _fixture(tmp / "pocket_template")
    fake, _ = _drive(_server(root), "_edit_items",
                     ["items", ("template", None), True, "back"])
    check("giving it back asks first",
          ("confirm", "Stop overriding the items pocket (use the template's)?")
          in fake.asked, str(fake.asked))
    check("and removes the key entirely",
          "items" not in _written(root)["items"], str(_written(root)["items"]))
    # Normalising to dict form happens per pocket, as that pocket is opened —
    # so a pocket nobody edited keeps the shorthand the user wrote by hand.
    check("leaving the other pockets alone, shorthand and all",
          _written(root)["items"]["key_items"] == ["BICYCLE"],
          str(_written(root)["items"]))


def test_browsing_a_template_pocket_leaves_no_trace(tmp: Path) -> None:
    """`balls` is absent from the fixture's state. Opening its editor and
    backing out must not create `"balls": []`, which would mean "no balls" at
    the next launch rather than "whatever the template has".

    Backing out does not itself save, so the trace this is about is the one
    left **in memory** — it reaches the file on the next unrelated edit. The
    second half is what makes that visible; without it the cleanup can be
    deleted and every assertion still passes.
    """
    print("\n_edit_pocket — browsing a pocket that is not overridden")
    root = _fixture(tmp / "pocket_browse")
    before = (root / ".devtools" / "state.json").read_text()
    server = _server(root)
    _drive(server, "_edit_items", ["balls", ("back", None), "back"])
    check("state.json is untouched",
          (root / ".devtools" / "state.json").read_text() == before, "written")

    _drive(server, "_edit_player", ["name", "PIKA", "back"])
    check("and the next edit does not carry an empty pocket into it",
          "balls" not in _written(root)["items"], str(_written(root)["items"]))


def test_the_pocket_prompts_refuse_bad_answers(tmp: Path) -> None:
    print("\n_edit_pocket — what each prompt refuses")
    root = _fixture(tmp / "pocket_bad")
    for label, script, expected in [
        ("an item that is not in this pocket",
         ["items", ("add", None), "POKE_BALL", ("back", None), "back"],
         "unknown items item: POKE_BALL"),
        ("an item already in the pocket",
         ["items", ("add", None), "POTION", ("back", None), "back"],
         "already in pocket: POTION"),
        ("a quantity of 100",
         ["items", ("add", None), "ETHER", "100", ("back", None), "back"],
         "must be 1..99"),
        ("a quantity of zero on a new entry",
         ["items", ("add", None), "ETHER", "0", ("back", None), "back"],
         "must be 1..99"),
    ]:
        try:
            _drive(_server(root), "_edit_items", script)
            check(label, False, "accepted")
        except ValidationRejected as e:
            check(label, expected in str(e), str(e))


# --------------------------------------------------------------------------- #
# The flags
# --------------------------------------------------------------------------- #

def test_edit_flags_offers_the_two_groups_with_their_counts(tmp: Path) -> None:
    print("\n_edit_flags")
    root = _fixture(tmp / "flags")
    fake, _ = _drive(_server(root), "_edit_flags", ["back"])
    check("both groups, counted",
          fake.titles(0) == ["Event flags   (1 set)", "Engine flags  (0 set)",
                             "← Back"], str(fake.titles(0)))


def test_setting_and_unsetting_a_flag(tmp: Path) -> None:
    print("\n_edit_flag_group")
    root = _fixture(tmp / "flag_add")
    fake, _ = _drive(_server(root), "_edit_flags",
                     ["event", ("add", None), "EVENT_MET_BILL",
                      ("back", None), "back"])
    check("the group's header counts what is set",
          fake.asked[1] == ("select", "Event flags — 1 set"), str(fake.asked[1]))
    check("the set flags are listed as one-press removals",
          fake.titles(1)[0] == "  [-] EVENT_GOT_A_POKEMON", str(fake.titles(1)))
    check("the flag lands",
          _written(root)["flags"]["event"] == ["EVENT_GOT_A_POKEMON",
                                               "EVENT_MET_BILL"],
          str(_written(root)["flags"]))

    root = _fixture(tmp / "flag_remove")
    _drive(_server(root), "_edit_flags",
           ["event", ("remove_one", "EVENT_GOT_A_POKEMON"), ("back", None), "back"])
    check("and pressing a listed flag unsets it",
          _written(root)["flags"]["event"] == [], str(_written(root)["flags"]))

    # The autocomplete accepts any flag the tree defines, set or not, so
    # "set it again" is a thing a user can type. It has to be a no-op, or the
    # same flag ends up in the list twice.
    root = _fixture(tmp / "flag_again")
    _drive(_server(root), "_edit_flags",
           ["event", ("add", None), "EVENT_GOT_A_POKEMON", ("back", None), "back"])
    check("setting a flag that is already set changes nothing",
          _written(root)["flags"]["event"] == ["EVENT_GOT_A_POKEMON"],
          str(_written(root)["flags"]))


def test_the_unset_picker_only_appears_when_something_is_set(tmp: Path) -> None:
    print("\n_edit_flag_group — the unset picker")
    root = _fixture(tmp / "flag_unset")
    fake, _ = _drive(_server(root), "_edit_flags",
                     ["event", ("remove", None), "EVENT_GOT_A_POKEMON",
                      ("back", None), "back"])
    check("it offers what is set, plus a cancel",
          fake.titles(2) == ["EVENT_GOT_A_POKEMON", "← Cancel"], str(fake.titles(2)))
    check("and unsets what was picked",
          _written(root)["flags"]["event"] == [], str(_written(root)["flags"]))

    root = _fixture(tmp / "flag_none")
    fake, _ = _drive(_server(root), "_edit_flags", ["engine", ("back", None), "back"])
    check("an empty group offers only Set and Back",
          fake.titles(1) == ["Set flag...", "← Back"], str(fake.titles(1)))


def test_clearing_a_flag_group_asks_first(tmp: Path) -> None:
    print("\n_edit_flag_group — clearing")
    root = _fixture(tmp / "flag_clear")
    fake, _ = _drive(_server(root), "_edit_flags",
                     ["event", ("clear", None), False, ("back", None), "back"])
    check("it asks", ("confirm", "Clear all event flags?") in fake.asked,
          str(fake.asked))
    check("and no means no",
          _written(root)["flags"]["event"] == ["EVENT_GOT_A_POKEMON"],
          str(_written(root)["flags"]))


def test_the_engine_group_is_the_same_editor_on_a_different_list(tmp: Path) -> None:
    """Both groups run one function with a different label and inventory key —
    so the engine group has to be driven too, or half the arguments are unproven."""
    print("\n_edit_flag_group — the engine group")
    root = _fixture(tmp / "flag_engine")
    fake, _ = _drive(_server(root), "_edit_flags",
                     ["engine", ("add", None), "ENGINE_POKEDEX",
                      ("back", None), "back"])
    check("it is headed as engine flags",
          fake.asked[1] == ("select", "Engine flags — 0 set"), str(fake.asked[1]))
    check("it offers the engine flag names",
          fake.choices_offered[2] == ["ENGINE_BIKE_SHOP_CALL_ENABLED",
                                      "ENGINE_POKEDEX"],
          str(fake.choices_offered[2]))
    check("and it writes to the engine list",
          _written(root)["flags"] == {"event": ["EVENT_GOT_A_POKEMON"],
                                      "engine": ["ENGINE_POKEDEX"]},
          str(_written(root)["flags"]))


def test_an_unknown_flag_is_refused(tmp: Path) -> None:
    print("\n_edit_flag_group — what it refuses")
    root = _fixture(tmp / "flag_bad")
    try:
        _drive(_server(root), "_edit_flags",
               ["event", ("add", None), "EVENT_NOPE", ("back", None), "back"])
        check("a flag the tree does not define", False, "accepted")
    except ValidationRejected as e:
        check("a flag the tree does not define", "unknown flag: EVENT_NOPE" in str(e),
              str(e))


# --------------------------------------------------------------------------- #
# The TM/HMs
# --------------------------------------------------------------------------- #

def test_edit_tmhms_labels_by_number_and_orders_by_bit(tmp: Path) -> None:
    """The list is offered as `TM01 ZAP_CANNON` but stored as `TM_ZAP_CANNON`,
    and ordered by the ownership bit rather than by either spelling. The
    fixture's names are alphabetically backwards from their bits so that
    sorting by name cannot pass."""
    print("\n_edit_tmhms")
    root = _fixture(tmp / "tmhm")
    fake, _ = _drive(_server(root), "_edit_tmhms",
                     [("add", None), "TM01 ZAP_CANNON", ("back", None)])
    check("the header counts owned against the whole list",
          fake.asked[0] == ("select", "TM/HMs — 1/4 owned"), str(fake.asked[0]))
    check("what is owned is shown by its number and move",
          fake.titles(0)[0] == "  [-] TM02 HEADBUTT", str(fake.titles(0)))
    check("the addable list is in bit order, not alphabetical",
          fake.choices_offered[1] == ["TM01 ZAP_CANNON", "TM03 CURSE", "HM01 CUT"],
          str(fake.choices_offered[1]))
    check("and the owned list is stored by name, in bit order",
          _written(root)["tmhms"] == ["TM_ZAP_CANNON", "TM_HEADBUTT"],
          str(_written(root)["tmhms"]))


def test_owning_all_and_clearing_all(tmp: Path) -> None:
    print("\n_edit_tmhms — own all, clear all")
    root = _fixture(tmp / "tmhm_all")
    fake, _ = _drive(_server(root), "_edit_tmhms",
                     [("own_all", None), True, ("back", None)])
    check("it asks, naming the number", ("confirm", "Own all 4 TM/HMs?") in fake.asked,
          str(fake.asked))
    check("and every one lands, in bit order",
          _written(root)["tmhms"] == ["TM_ZAP_CANNON", "TM_HEADBUTT", "TM_CURSE",
                                      "HM_CUT"], str(_written(root)["tmhms"]))

    root = _fixture(tmp / "tmhm_clear")
    _drive(_server(root), "_edit_tmhms", [("clear", None), True, ("back", None)])
    check("clearing leaves an explicit empty list, not an absent key",
          _written(root)["tmhms"] == [], str(_written(root).get("tmhms", "absent")))


def test_giving_the_tmhms_back_to_the_template(tmp: Path) -> None:
    print("\n_edit_tmhms — back to the template")
    root = _fixture(tmp / "tmhm_template")
    _drive(_server(root), "_edit_tmhms", [("template", None), True])
    check("the key goes entirely", "tmhms" not in _written(root),
          str(list(_written(root))))


def test_browsing_the_tmhms_leaves_no_trace(tmp: Path) -> None:
    """The one the file's own comment warns about: an empty `"tmhms": []`
    created just by opening the menu would mean "own nothing" at launch."""
    print("\n_edit_tmhms — browsing a state that does not override them")
    root = _fixture(tmp / "tmhm_browse")
    state = {k: v for k, v in _STATE.items() if k != "tmhms"}
    (root / ".devtools" / "state.json").write_text(json.dumps(state))
    before = (root / ".devtools" / "state.json").read_text()
    fake, _ = _drive(_server(root), "_edit_tmhms", [("back", None)])
    check("no Use-template row is offered, since it is not overridden",
          not any("template" in t for t in fake.titles(0)), str(fake.titles(0)))
    check("state.json is untouched",
          (root / ".devtools" / "state.json").read_text() == before, "written")


def test_an_inventory_without_tmhms_says_so(tmp: Path) -> None:
    print("\n_edit_tmhms — no tmhms in the inventory")
    root = _fixture(tmp / "tmhm_none")
    inv = json.loads((root / ".devtools" / "inventory.json").read_text())
    del inv["tmhms"]
    (root / ".devtools" / "inventory.json").write_text(json.dumps(inv))
    fake, out = _drive(_server(root), "_edit_tmhms", [])
    check("it asks nothing", fake.asked == [], str(fake.asked))
    check("and says how to fix it",
          out == "(inventory has no tmhms — rebuild it: --rebuild-inventory)\n",
          repr(out))


def test_the_tmhm_prompt_refuses_bad_answers(tmp: Path) -> None:
    print("\n_edit_tmhms — what it refuses")
    root = _fixture(tmp / "tmhm_bad")
    for label, answer, expected in [
        ("one that is already owned", "TM02 HEADBUTT", "already owned"),
        ("one the tree does not define", "TM99 NOPE", "unknown TM/HM"),
        ("the stored name rather than the offered label", "TM_CURSE",
         "unknown TM/HM"),
    ]:
        try:
            _drive(_server(root), "_edit_tmhms",
                   [("add", None), answer, ("back", None)])
            check(label, False, "accepted")
        except ValidationRejected as e:
            check(label, expected in str(e), str(e))


# --------------------------------------------------------------------------- #
# The presets
# --------------------------------------------------------------------------- #

def test_reset_from_a_preset(tmp: Path) -> None:
    print("\n_reset_preset")
    root = _fixture(tmp / "preset")
    fake, out = _drive(_server(root), "_reset_preset",
                       [root / ".devtools" / "presets" / "champion.json", True])
    check("it offers every preset by filename, sorted, plus a cancel",
          fake.titles(0) == ["champion.json", "default.json", "← Cancel"],
          str(fake.titles(0)))
    check("it asks before overwriting, naming both files",
          fake.asked[1] == ("confirm",
                            "Overwrite .devtools/state.json with champion.json?"),
          str(fake.asked[1]))
    check("the preset replaces the state whole",
          _written(root) == {"player": {"name": "CHAMP", "money": 999999}},
          str(_written(root)))
    check("and it says which preset it used",
          out == "Reset state from champion.json\n", repr(out))


def test_declining_the_reset_changes_nothing(tmp: Path) -> None:
    print("\n_reset_preset — declining")
    root = _fixture(tmp / "preset_no")
    before = (root / ".devtools" / "state.json").read_text()
    _drive(_server(root), "_reset_preset",
           [root / ".devtools" / "presets" / "default.json", False])
    check("state.json is untouched",
          (root / ".devtools" / "state.json").read_text() == before, "written")

    root = _fixture(tmp / "preset_cancel")
    before = (root / ".devtools" / "state.json").read_text()
    fake, _ = _drive(_server(root), "_reset_preset", [None])
    check("and cancelling the picker asks nothing further", len(fake.asked) == 1,
          str(fake.asked))
    check("nor writes", (root / ".devtools" / "state.json").read_text() == before,
          "written")


def test_no_presets_at_all(tmp: Path) -> None:
    print("\n_reset_preset — an empty presets directory")
    root = _fixture(tmp / "preset_empty")
    for p in (root / ".devtools" / "presets").glob("*.json"):
        p.unlink()
    fake, out = _drive(_server(root), "_reset_preset", [])
    check("it asks nothing", fake.asked == [], str(fake.asked))
    check("and says so", out == "(no presets in presets/)\n", repr(out))


# --------------------------------------------------------------------------- #
# Where the state is written, and where it is not
# --------------------------------------------------------------------------- #

def test_an_edit_never_writes_over_a_preset(tmp: Path) -> None:
    """Autosave goes to the state file the server was opened with, and the
    presets come out byte-identical — they are the thing you reset *to*.

    **The case that matters is a server with no state.json**, which opens on
    `presets/default.json`. With one on disk the state file and the state
    *source* are the same path, so writing to the wrong one is invisible: that
    is the shape the first version of this test had, and a seeded mutation
    walked straight through it.
    """
    print("\nDevServer — autosave never touches presets/")
    root = _fixture(tmp / "autosave")
    (root / ".devtools" / "state.json").unlink()
    presets = root / ".devtools" / "presets"
    before = {p.name: p.read_text() for p in presets.glob("*.json")}
    _drive(_server(root), "_edit_player", ["name", "PIKA", "back"])
    check("every preset is byte-identical",
          {p.name: p.read_text() for p in presets.glob("*.json")} == before,
          "a preset was rewritten")
    check("and the edit went to state.json, which did not exist before",
          _written(root)["player"]["name"] == "PIKA", str(_written(root)["player"]))

    # And with a state.json present, the same edit still lands there.
    root = _fixture(tmp / "autosave2")
    before = {p.name: p.read_text() for p in
              (root / ".devtools" / "presets").glob("*.json")}
    _drive(_server(root), "_edit_player", ["name", "PIKA", "back"])
    check("the presets are untouched with a state file too",
          {p.name: p.read_text() for p in
           (root / ".devtools" / "presets").glob("*.json")} == before,
          "a preset was rewritten")
    check("and the state file has the edit",
          _written(root)["player"]["name"] == "PIKA", str(_written(root)["player"]))


def test_the_status_line_follows_the_state_source(tmp: Path) -> None:
    """The server opens on `presets/default.json` when there is no state.json,
    and the status block says so — until the first edit, which autosaves to
    state.json and must move the line with it."""
    print("\nDevServer — which file the state came from")
    root = _fixture(tmp / "source")
    (root / ".devtools" / "state.json").unlink()
    server = _server(root)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        server._print_status_block()
    check("it names the preset it fell back to",
          "State:   .devtools/presets/default.json" in out.getvalue(),
          out.getvalue()[:200])

    _drive(server, "_edit_player", ["name", "PIKA", "back"])
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        server._print_status_block()
    check("and after an edit it names state.json",
          "State:   .devtools/state.json" in out.getvalue(), out.getvalue()[:200])


# --------------------------------------------------------------------------- #
# Rebuilding the inventory when the ROM is rebuilt
# --------------------------------------------------------------------------- #

def test_a_newer_sym_refreshes_the_inventory(tmp: Path) -> None:
    """The one thing the server does behind your back. It must fire only when
    the .sym is genuinely newer, and it must write the rebuilt inventory out."""
    print("\nDevServer — a new build")
    root = _fixture(tmp / "stale")
    server = _server(root)
    rebuilt: list[Path] = []

    def _fake_build(r, s):
        rebuilt.append(s)
        return {"schema": _inventory_schema(), "maps": [], "rebuilt": True}

    from pokeprism_devtools.dev_server import inventory
    saved = inventory.build
    inventory.build = _fake_build
    try:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            unchanged = server._refresh_inventory_if_stale()
        check("an unchanged .sym rebuilds nothing",
              unchanged is None and rebuilt == [], str(rebuilt))

        os.utime(root / "pokeprism.sym", (SYM_MTIME + 60, SYM_MTIME + 60))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            stale = server._refresh_inventory_if_stale()
        check("a newer .sym does", stale is True and len(rebuilt) == 1, str(rebuilt))
        check("and it says so",
              out.getvalue()
              == "(detected new build — refreshing inventory from .sym)\n",
              repr(out.getvalue()))
        check("the rebuilt inventory is written back",
              json.loads((root / ".devtools" / "inventory.json").read_text())
              .get("rebuilt") is True, "not written")
        check("and the server is now using it", server.inv.get("rebuilt") is True,
              str(list(server.inv)))
    finally:
        inventory.build = saved


def test_the_watcher_thread_picks_up_a_rebuild(tmp: Path) -> None:
    """The background watcher is the only path that runs *while you are
    building*, and until this it was the one body no test reached. It must
    rebuild without printing — a questionary prompt owns the terminal — and it
    must re-launch only when asked to.
    """
    print("\nDevServer — the rebuild watcher")
    import time

    for auto in (False, True):
        root = _fixture(tmp / f"watch_{auto}")
        server = _server(root, auto_relaunch=auto)
        rebuilt: list = []

        def _fake_build(r, s):
            rebuilt.append(s)
            return {"schema": _inventory_schema(), "maps": [], "rebuilt": True}

        from pokeprism_devtools.dev_server import inventory
        saved_build, saved_poll = inventory.build, tui.SYM_POLL_SECONDS
        inventory.build = _fake_build
        tui.SYM_POLL_SECONDS = 0.01
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                server._start_rebuild_watcher()
                os.utime(root / "pokeprism.sym", (SYM_MTIME + 60, SYM_MTIME + 60))
                deadline = time.time() + 5.0
                while not rebuilt and time.time() < deadline:
                    time.sleep(0.02)
        finally:
            server._watcher_stop.set()
            server._watcher_thread.join(timeout=3.0)
            inventory.build, tui.SYM_POLL_SECONDS = saved_build, saved_poll

        check(f"auto_relaunch={auto}: it rebuilt on its own", len(rebuilt) == 1,
              str(rebuilt))
        check(f"auto_relaunch={auto}: silently — a prompt owns the terminal",
              out.getvalue() == "", repr(out.getvalue()))
        wrote = json.loads(
            (root / ".devtools" / "inventory.json").read_text()).get("rebuilt")
        check(f"auto_relaunch={auto}: it wrote the new inventory out",
              wrote is True, "" if wrote else "not written")
        check(f"auto_relaunch={auto}: and re-launched only if asked",
              bool(server.emulator.launched) is auto,
              str(server.emulator.launched))


def test_a_missing_sym_is_not_a_rebuild(tmp: Path) -> None:
    """`make clean` removes the .sym. That is not a new build, and treating it
    as one would rebuild the inventory from a file that is not there."""
    print("\nDevServer — a .sym that went away")
    root = _fixture(tmp / "nosym")
    server = _server(root)
    (root / "pokeprism.sym").unlink()
    check("it reports nothing and raises nothing",
          server._refresh_inventory_if_stale() is None, "raised or reported")


# --------------------------------------------------------------------------- #
# Launching
# --------------------------------------------------------------------------- #

def test_launching_patches_the_save_then_spawns_the_emulator(tmp: Path) -> None:
    print("\nDevServer — launch")
    root = _fixture(tmp / "launch")
    server = _server(root)
    calls: list[dict] = []

    def _fake_patch(rom_path, **kw):
        calls.append({"rom": rom_path, **kw})
        return types.SimpleNamespace(
            backup=root / ".devtools" / "sav-backups" / "old.sav",
            target=root / "pokeprism.sav",
            changes=["wMoney = 3000", "wMapNumber = 2"])

    saved = playtest.patch_save
    playtest.patch_save = _fake_patch
    try:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            server._patch_and_launch()
    finally:
        playtest.patch_save = saved

    check("the save is patched against the ROM the status block names",
          calls[0]["rom"] == root / "pokeprism.gbc", str(calls[0]["rom"]))
    check("with the server's own inventory, state and flags",
          calls[0]["inv"] is server.inv and calls[0]["state"] is server.state
          and calls[0]["keep_people"] is False, str(sorted(calls[0])))
    check("it reports the backup, the target and every field it changed",
          out.getvalue() ==
          "Backed up pokeprism.sav → .devtools/sav-backups/old.sav\n"
          "Wrote pokeprism.sav (2 fields changed)\n"
          "  wMoney = 3000\n"
          "  wMapNumber = 2\n"
          "Launching sameboy pokeprism.gbc...\n", repr(out.getvalue()))
    check("and the emulator got the same ROM",
          server.emulator.launched == [root / "pokeprism.gbc"],
          str(server.emulator.launched))


def test_a_failed_patch_does_not_launch(tmp: Path) -> None:
    """Booting the old save after a failed patch is the worst outcome here: the
    game comes up, looks fine, and is not what you asked for."""
    print("\nDevServer — a patch that fails")
    root = _fixture(tmp / "launch_fail")
    server = _server(root)

    def _fake_patch(rom_path, **kw):
        raise playtest.PlaytestError("no template .sav to patch")

    saved = playtest.patch_save
    playtest.patch_save = _fake_patch
    try:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            server._patch_and_launch()
    finally:
        playtest.patch_save = saved

    check("the error is reported", err.getvalue()
          == "error: no template .sav to patch\n", repr(err.getvalue()))
    check("nothing is claimed to have been written",
          "Wrote" not in out.getvalue(), repr(out.getvalue()))
    # Recorded, not endorsed: `_patch_and_launch` launches anyway, so the game
    # comes up on the *old* save. Pinned here so a later phase can change it on
    # purpose rather than by accident — this phase moves code, it does not
    # decide what should happen after a failed patch.
    check("but the emulator is spawned regardless — recorded, not endorsed",
          server.emulator.launched == [root / "pokeprism.gbc"],
          str(server.emulator.launched))


def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        test_the_status_block(tmp)
        test_the_status_block_on_a_bare_state(tmp)
        test_the_menu_offers_these_things_in_this_order(tmp)
        test_the_launch_entry_renames_itself_once_sameboy_is_up(tmp)
        test_every_menu_entry_reaches_its_editor(tmp)
        test_an_editor_that_raises_does_not_take_the_server_down(tmp)
        test_ctrl_c_at_the_menu_quits(tmp)

        test_edit_player(tmp)
        test_the_player_prompts_refuse_bad_answers(tmp)
        test_all_three_badge_bytes_are_asked_for_and_kept_together(tmp)

        test_edit_map(tmp)
        test_the_coord_bounds_come_from_the_map_and_not_from_each_other(tmp)
        test_an_unknown_map_falls_back_to_a_whole_byte(tmp)
        test_the_map_prompts_refuse_bad_answers(tmp)

        test_edit_party_lists_six_slots_however_many_are_filled(tmp)
        test_edit_a_party_slot(tmp)
        test_removing_a_slot_removes_that_slot(tmp)
        test_a_slot_abandoned_before_a_species_is_dropped(tmp)
        test_abandoning_a_slot_past_the_end_leaves_no_gaps(tmp)
        test_a_hand_written_gap_is_left_alone(tmp)
        test_a_nickname_is_cleared_by_blanking_it(tmp)
        test_moves_are_four_prompts_and_a_way_out(tmp)
        test_clearing_the_party_asks_first(tmp)
        test_the_party_prompts_refuse_bad_answers(tmp)

        test_edit_items_lists_the_three_pockets(tmp)
        test_an_inventory_without_bag_caps_says_so(tmp)
        test_a_pocket_offers_only_its_own_items(tmp)
        test_adding_to_a_pocket(tmp)
        test_a_full_pocket_offers_the_add_row_disabled(tmp)
        test_a_quantity_of_zero_removes_the_entry(tmp)
        test_a_key_item_has_no_quantity(tmp)
        test_clearing_a_pocket_is_not_the_same_as_giving_it_back(tmp)
        test_browsing_a_template_pocket_leaves_no_trace(tmp)
        test_the_pocket_prompts_refuse_bad_answers(tmp)

        test_edit_flags_offers_the_two_groups_with_their_counts(tmp)
        test_setting_and_unsetting_a_flag(tmp)
        test_the_unset_picker_only_appears_when_something_is_set(tmp)
        test_clearing_a_flag_group_asks_first(tmp)
        test_the_engine_group_is_the_same_editor_on_a_different_list(tmp)
        test_an_unknown_flag_is_refused(tmp)

        test_edit_tmhms_labels_by_number_and_orders_by_bit(tmp)
        test_owning_all_and_clearing_all(tmp)
        test_giving_the_tmhms_back_to_the_template(tmp)
        test_browsing_the_tmhms_leaves_no_trace(tmp)
        test_an_inventory_without_tmhms_says_so(tmp)
        test_the_tmhm_prompt_refuses_bad_answers(tmp)

        test_reset_from_a_preset(tmp)
        test_declining_the_reset_changes_nothing(tmp)
        test_no_presets_at_all(tmp)

        test_an_edit_never_writes_over_a_preset(tmp)
        test_the_status_line_follows_the_state_source(tmp)

        test_a_newer_sym_refreshes_the_inventory(tmp)
        test_the_watcher_thread_picks_up_a_rebuild(tmp)
        test_a_missing_sym_is_not_a_rebuild(tmp)

        test_launching_patches_the_save_then_spawns_the_emulator(tmp)
        test_a_failed_patch_does_not_launch(tmp)

    print()
    if _failures:
        print(f"{_failures} check(s) FAILED")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
