"""The shell. Driven with Textual's Pilot, not eyeballed.

Deliberately thin. Everything the studio *knows* — where a marker goes, what
colour a tile is, what the linter found — is tested in test_grid.py and
test_studio.py against the ROM and against the real renderer. What is left to
check here is only that the shell is wired to it: that picking a map fills the
grid and the tables, that the cursor reports the tile it is actually on, and that
the two maps in this repo which don't parse still come up instead of taking the
app down with them.
"""

from __future__ import annotations

import asyncio
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from textual.widgets import Input, OptionList, TextArea

from pokeprism_devtools.shared import blocksrc, coords, eventheader, paths, swatches
from pokeprism_devtools.studio import Session, panels
from pokeprism_devtools.studio.actions import ActionError
from pokeprism_devtools.studio.app import Studio
from pokeprism_devtools.studio.forms import Confirm, Form, Palette, Picker
from pokeprism_devtools.studio.grid import MapGrid
from pokeprism_devtools.studio.newmap import NewMap

ROOT = paths.repo_root(Path.home() / "code/ricccec/pokeprism")

#: An outdoor map with objects on it, a connection, and grass.
MAP = "CastroForest"
#: Its event header does not parse: no object_events count. It still has a shape.
BROKEN = "HaywardMartElevator"


def drive(coro):
    return asyncio.run(coro)


class TestPanels(unittest.TestCase):
    """The tables, without a terminal in sight."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.header = eventheader.parse_map(ROOT / f"maps/{MAP}.asm")

    def test_objects_are_source_coordinates(self) -> None:
        cols, rows = panels.objects(self.header)
        self.assertEqual(cols[:3], ["#", "y", "x"])
        self.assertEqual(len(rows), len(self.header.object_events))

        # The +4 the person_event macro adds at assembly must not appear here:
        # this table is what you would *type*, not what the ROM holds.
        for row, entry in zip(rows, self.header.object_events):
            self.assertEqual(row[1], str(entry.y))
            self.assertEqual(row[2], str(entry.x))

    def test_warps_name_the_destination(self) -> None:
        cols, rows = panels.warps(self.header)
        self.assertIn("to map", cols)
        for row, entry in zip(rows, self.header.warps):
            if entry.macro == "warp_def":
                self.assertEqual(row[3], entry.arg(3))


class TestGridWidget(unittest.TestCase):
    def test_the_letter_never_leaves_its_tile(self) -> None:
        """The property the whole grid rests on, at every zoom the widget offers.

        A letter is drawn on its marker's colour, so a letter in the wrong cell
        is a marker painted on a tile that has nothing on it — the grid lying
        about where an NPC stands, which is the one thing it must never do.
        """
        marks = {(6, 9): coords.PERSON, (0, 0): coords.WARP}
        for zoom in (2, 3, 4):
            cells = coords.glyph_cells(marks, zoom)
            for (row, col), glyph in cells.items():
                ty, tx = next(t for t, g in marks.items()
                              if coords.glyph_cells({t: g}, zoom) == {(row, col): g})
                # Both halves of the letter's cell, and the cell itself, are
                # inside the tile that owns it.
                self.assertEqual((2 * row) // zoom, ty)
                self.assertEqual((2 * row + 1) // zoom, ty)
                self.assertEqual(col // zoom, tx)


class TestShell(unittest.TestCase):
    def test_it_comes_up_and_shows_a_map(self) -> None:
        async def go():
            app = Studio(ROOT)
            async with app.run_test() as pilot:
                await pilot.pause()
                grid = app.query_one("#grid", MapGrid)
                self.assertIsNotNone(grid.view, "no map loaded on startup")

                # Every map in the repo is offered, including the ones that
                # don't parse — hiding a broken map from the person looking for
                # the break is the worst thing this list could do.
                self.assertGreater(len(app._maps), 400)
                self.assertIn(BROKEN, [m.label for m in app._maps])
                await app.action_quit()

        drive(go())

    def test_filtering_then_picking_loads_that_map(self) -> None:
        async def go():
            app = Studio(ROOT)
            async with app.run_test() as pilot:
                app.query_one("#filter").value = MAP
                await pilot.pause()
                # A substring filter, so the gates that lead into the forest are
                # offered too — which is the point of a filter over a search box.
                self.assertEqual(app._shown[0], MAP)
                self.assertTrue(all(MAP in label for label in app._shown))

                # Wait for the load worker, which reads four files.
                for _ in range(200):
                    await pilot.pause(0.02)
                    view = app.query_one("#grid", MapGrid).view
                    if view is not None and view.label == MAP:
                        break

                bd = blocksrc.load(ROOT, MAP)
                self.assertEqual(view.blocks, bd.blocks)
                self.assertEqual(view.size, coords.tile_size(bd.height, bd.width))
                self.assertEqual(
                    view.swatches,
                    swatches.for_map(ROOT, bd.tileset_id, bd.permission))
                await app.action_quit()

        drive(go())

    def test_the_cursor_reports_the_tile_it_is_on(self) -> None:
        """The cursor's whole job: hand P3's forms a coordinate you can trust."""
        async def go():
            app = Studio(ROOT)
            async with app.run_test() as pilot:
                await pilot.pause()
                grid = app.query_one("#grid", MapGrid)
                for _ in range(200):
                    await pilot.pause(0.02)
                    if grid.view is not None:
                        break

                self.assertEqual(grid.cursor, (0, 0))
                grid.action_move(3, 5)
                await pilot.pause()
                self.assertEqual(grid.cursor, (3, 5))

                # Clamped at the edges, never wrapped: a map has edges, and a
                # cursor that reappears on the far side is lying about that.
                grid.action_move(-99, -99)
                await pilot.pause()
                self.assertEqual(grid.cursor, (0, 0))

                rows, cols = grid.view.size
                grid.action_move(9999, 9999)
                await pilot.pause()
                self.assertEqual(grid.cursor, (rows - 1, cols - 1))
                await app.action_quit()

        drive(go())

    def test_a_map_that_doesnt_parse_still_comes_up(self) -> None:
        """It has a shape. Showing the shape and saying why the tables are empty
        beats an empty table that reads as 'this map has no NPCs'."""
        data = Session(ROOT).load(BROKEN)

        self.assertIsNotNone(data.geometry, "a broken header still has blocks")
        self.assertEqual(data.geometry.marks, {})
        self.assertIn("error", data.tables)
        self.assertNotIn("Objects", data.tables)
        # And the parts that don't depend on the header still work.
        self.assertIn("Connections", data.tables)


class TestTextPreview(unittest.TestCase):
    """The tile counter under the dialogue box — the reason the text rules exist.

    A speech box is 18 columns of *tiles*, and a tile is not a character: `#`
    expands to four of them. So the count has to come from the same width engine
    the linter uses, and it has to arrive while you can still shorten the line.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.session = Session(ROOT)

    def test_a_line_that_does_not_fit_says_so(self) -> None:
        p = self.session.measure("#mon Center near\nHi.")
        self.assertEqual(p.cols, 18)
        self.assertFalse(p.fits)
        # `#` is four tiles: "#mon Center near" is 16 characters and 19 tiles.
        self.assertEqual(p.lines[0].tiles, 19)
        self.assertEqual(p.lines[0].over, 1)
        self.assertEqual(p.lines[1].over, 0)

    def test_a_line_that_fits_until_the_player_has_a_long_name(self) -> None:
        """The worst kind of overflow: correct in your game, broken in theirs."""
        p = self.session.measure("<PLAYER> is here right")
        self.assertTrue(p.fits, "it fits as written")
        self.assertTrue(p.risky, "and not once <PLAYER> is at its longest")
        self.assertEqual(p.lines[0].over_at_worst, 3)

    def test_a_sign_is_measured_in_the_speech_box(self) -> None:
        """Obvious as the opposite sounds. SIGNPOST_TEXT ends in a `jumptext`,
        which draws in the ordinary bubble; only SIGNPOST_LOAD opens the
        full-screen signpost window. Measure a sign against the signpost box and
        every sign you write is a tile too wide, in-game and nowhere else."""
        from pokeprism_devtools.studio.actions import AddSignpost
        text = next(f for f in AddSignpost.FIELDS if f.kind == "lines")
        self.assertEqual(text.box, "speech")
        self.assertNotEqual(self.session.measure("x", "speech").cols,
                            self.session.measure("x", "sign").cols)


class TestChoices(unittest.TestCase):
    """What the form offers, which the form itself is not allowed to know."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.session = Session(ROOT)

    def test_every_declared_kind_can_be_answered(self) -> None:
        from pokeprism_devtools.studio.catalog import CATALOG
        for action in CATALOG:
            for f in action.FIELDS:
                if f.choices:
                    self.assertTrue(
                        self.session.choices(f.choices),
                        f"{action.name}.{f.name} wants {f.choices!r} and the "
                        f"session has nothing to offer for it")

    def test_a_class_the_engine_would_crash_on_is_not_offered(self) -> None:
        from pokeprism_devtools.shared import trainerparty
        offered = set(self.session.choices("classes"))
        null = {cls for cls, group in trainerparty.class_groups(ROOT).items()
                if group is None}
        self.assertTrue(null, "the repo has classes with a NULL group")
        self.assertEqual(offered & null, set())

    def test_an_unknown_kind_is_free_text_not_a_crash(self) -> None:
        self.assertEqual(self.session.choices("wombats"), [])


class TestEditing(unittest.TestCase):
    """The whole loop, on a copy: palette -> form -> diff -> apply -> undo.

    On a *copy*. This test writes to a repo, and the repo it must never write to
    is the one you have work in progress in.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name) / "pokeprism"
        shutil.copytree(ROOT, cls.root, symlinks=True, ignore=shutil.ignore_patterns(
            ".git", "*.o", "*.gbc", "*.sym", "*.map"))

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    async def _ready(self, app, pilot) -> MapGrid:
        """Filter to the map, wait for the load worker."""
        app.query_one("#filter", Input).value = MAP
        await pilot.pause()
        grid = app.query_one("#grid", MapGrid)
        for _ in range(300):
            await pilot.pause(0.02)
            if grid.view is not None and grid.view.label == MAP:
                return grid
        self.fail(f"{MAP} never loaded")

    def test_placing_a_sign_from_the_cursor_and_taking_it_back(self) -> None:
        path = self.root / f"maps/{MAP}.asm"
        before = path.read_text()

        async def go():
            app = Studio(self.root)
            async with app.run_test() as pilot:
                grid = await self._ready(app, pilot)
                grid.action_move(9, 11)
                await pilot.pause()

                # `a` opens the palette. It is a list of what the CATALOG says
                # can be done, and nothing here knows what any of them are.
                await pilot.press("a")
                await pilot.pause()
                palette = app.screen
                self.assertIsInstance(palette, Palette)

                options = palette.query_one("#picker-list", OptionList)
                titles = [str(o.prompt) for o in options._options]
                options.highlighted = titles.index("Add a signpost")
                await pilot.press("enter")
                await pilot.pause()

                form = app.screen
                self.assertIsInstance(form, Form)

                # The cursor filled in the coordinates. This is the reason the
                # grid was built before the forms were: it is the one pair of
                # numbers in the whole app that you should never have to type.
                self.assertEqual(form.query_one("#field-y", Input).value, "9")
                self.assertEqual(form.query_one("#field-x", Input).value, "11")

                area = form.query_one("#field-text", TextArea)
                area.text = "It reads:\nBEWARE OF THE DOG"
                await pilot.pause()

                form.action_submit()
                await pilot.pause()

                # The diff is of the very edits that will land, not a rendering
                # of what might.
                confirm = app.screen
                self.assertIsInstance(confirm, Confirm)
                diff = confirm._preview.diff()
                self.assertIn("+CastroForestSign:", diff)
                self.assertIn('+\tctxt "It reads:"', diff)
                self.assertIn("+\tsignpost 9, 11, SIGNPOST_TEXT, CastroForestSign",
                              diff)

                confirm.action_yes()
                await pilot.pause()

                text = path.read_text()
                self.assertNotEqual(text, before, "nothing was written")
                self.assertIn("BEWARE OF THE DOG", text)

                # And the map redraws with the sign on it, at the cursor, which
                # is still where you left it.
                for _ in range(300):
                    await pilot.pause(0.02)
                    if (9, 11) in app.query_one("#grid", MapGrid).view.marks:
                        break
                grid = app.query_one("#grid", MapGrid)
                self.assertEqual(grid.view.marks[(9, 11)], coords.SIGN)
                self.assertEqual(grid.cursor, (9, 11))

                # Undo puts back exactly what was there.
                app.action_undo()
                await pilot.pause()
                self.assertEqual(path.read_text(), before)

                await app.action_quit()

        drive(go())

    def test_rewording_a_line_changes_that_line_and_nothing_else(self) -> None:
        """The whole reason the writer copies macros back positionally.

        You change a word. What lands is that word — not a reflowed block, not a
        `cont` turned into a `para`, not somebody's alignment whitespace tidied
        up. The diff should be one line long.
        """
        path = self.root / f"maps/{MAP}.asm"
        before = path.read_text().split("\n")

        async def go():
            app = Studio(self.root)
            async with app.run_test() as pilot:
                await self._ready(app, pilot)

                await pilot.press("e")
                await pilot.pause()
                picker = app.screen
                self.assertIsInstance(picker, Picker)
                self.assertTrue(app._texts, "the map says nothing?")

                # Pick a block with more than one line in it, so that "one line
                # changed" is a claim with something to prove.
                i, block = next((i, t) for i, t in enumerate(app._texts)
                                if len(t.prose.split("\n")) > 2)
                picker.query_one("#picker-list", OptionList).highlighted = i
                await pilot.press("enter")
                await pilot.pause()

                form = app.screen
                self.assertIsInstance(form, Form)
                # It opens with the words already in it — that is what makes this
                # editing rather than retyping.
                area = form.query_one("#field-text", TextArea)
                self.assertEqual(area.text, block.prose)

                lines = block.prose.split("\n")
                nth = next(n for n, line in enumerate(lines) if line.strip())
                lines[nth] = "REWORDED"
                area.text = "\n".join(lines)
                await pilot.pause()

                form.action_submit()
                await pilot.pause()
                confirm = app.screen
                self.assertIsInstance(confirm, Confirm)
                confirm.action_yes()
                await pilot.pause()

                after = path.read_text().split("\n")
                self.assertEqual(len(after), len(before), "the file changed length")
                differ = [n for n, (a, b) in enumerate(zip(before, after)) if a != b]
                self.assertEqual(len(differ), 1,
                                 f"{len(differ)} lines changed, not 1: "
                                 f"{[after[n] for n in differ][:4]}")
                self.assertIn("REWORDED", after[differ[0]])

                app.action_undo()
                await pilot.pause()
                self.assertEqual(path.read_text().split("\n"), before)
                await app.action_quit()

        drive(go())

    def test_an_action_that_cannot_be_built_writes_nothing(self) -> None:
        """A sprite that doesn't exist is caught in the form, with the form still
        full of what you typed — not by rgblink, five minutes later."""
        path = self.root / f"maps/{MAP}.asm"
        before = path.read_text()

        async def go():
            app = Studio(self.root)
            async with app.run_test() as pilot:
                await self._ready(app, pilot)
                form = Form(_action("Add an NPC"), app.session, "CASTRO_FOREST", (2, 3))
                await app.push_screen(form)
                await pilot.pause()

                form.query_one("#field-sprite", Input).value = "SPRITE_YOUNGSTR"
                form.query_one("#field-text", TextArea).text = "Hello."
                form.action_submit()
                await pilot.pause()

                self.assertIs(app.screen, form, "the form left, taking the values")
                self.assertIn("Did you mean SPRITE_YOUNGSTER", form.error)
                self.assertEqual(path.read_text(), before)
                await app.action_quit()

        drive(go())


class TestNewMap(unittest.TestCase):
    """Adding a map to the game: the picture first, then the whole loop.

    Every other action changes a map you are looking at. This one has nothing to
    look at — the map does not exist until five source files say it does — which
    is why it draws itself out of the form, and why this test looks at the
    drawing before it looks at the diff.
    """

    HEIGHT, WIDTH = 4, 5
    #: 20 blocks, none of them 0, so a picture of them is a picture of something.
    BLOCKS = bytes((i * 7) % 100 + 1 for i in range(HEIGHT * WIDTH))

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls._tmp.name)
        cls.root = tmp / "pokeprism"
        shutil.copytree(ROOT, cls.root, symlinks=True, ignore=shutil.ignore_patterns(
            ".git", "*.o", "*.gbc", "*.sym", "*.map"))
        # The .blk as it comes out of polished-map: somewhere else entirely, and
        # named whatever you called it there.
        cls.blk = tmp / "drawn-this-morning.ablk"
        cls.blk.write_bytes(cls.BLOCKS)
        cls.session = Session(ROOT)          # read-only: a sketch writes nothing

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def form(self, **override: str) -> dict[str, str]:
        """A complete, valid form. Every constant in it is real."""
        return {
            "label": "TestIsland", "const": "TEST_ISLAND", "group": "1",
            "height": str(self.HEIGHT), "width": str(self.WIDTH),
            "blk": str(self.blk),
            "tileset": "TILESET_FOREST", "permission": "CAVE",
            "landmark": "SPECIAL_MAP", "music": "MUSIC_ROUTE_2",
            "palette": "PALETTE_NITE", "fishgroup": "FISHGROUP_POND",
            "phone": "0", "border_block": "0", "conn_flags": "0", "bank": "",
            "blockdata_section": "", "script_section": "", "secondary_section": "",
        } | override

    # -- the picture ------------------------------------------------------------ #
    def test_the_blk_is_on_the_grid_before_it_is_written(self) -> None:
        view = self.session.sketch(NewMap(**self.form()))
        self.assertIsNotNone(view)
        self.assertEqual((view.height, view.width), (self.HEIGHT, self.WIDTH))
        self.assertEqual(view.blocks, self.BLOCKS)
        self.assertEqual(view.size, coords.tile_size(self.HEIGHT, self.WIDTH))
        self.assertTrue(view.swatches, "no colours: the tileset never resolved")
        self.assertEqual(view.marks, {}, "nothing stands on a map this new")

    def test_a_blk_that_is_the_wrong_size_says_so_rather_than_drawing(self) -> None:
        """The one mistake that silently ruins a new map. The engine copies
        height x width bytes and reads whatever follows the file into the rest —
        which is why it shows up in-game as a band of garbage along the bottom
        rather than as an error."""
        with self.assertRaises(ActionError) as caught:
            self.session.sketch(NewMap(**self.form(height="9")))
        self.assertIn("holds 20 blocks", str(caught.exception))
        self.assertIn("9×5 = 45", str(caught.exception))

    def test_a_tileset_that_does_not_exist_is_refused_not_guessed(self) -> None:
        """Falling back to tileset 0 would draw a picture of a map that does not
        exist, and the picture would look perfectly fine."""
        with self.assertRaises(ActionError) as caught:
            self.session.sketch(NewMap(**self.form(tileset="TILESET_FORREST")))
        self.assertIn("TILESET_FORREST", str(caught.exception))

    def test_a_half_filled_form_asks_for_the_rest_instead_of_failing(self) -> None:
        """The normal state of a form you are typing into is 'not answerable yet'.
        That is not an error, and it must not read like one."""
        with self.assertRaises(ActionError) as caught:
            self.session.sketch(NewMap(**self.form(blk="")))
        self.assertIn("point at the", str(caught.exception))

    # -- the writing ------------------------------------------------------------- #
    def test_adding_a_map_and_taking_it_back(self) -> None:
        wired = ["constants/map_dimension_constants.asm", "maps/map_headers.asm",
                 "maps/second_map_headers.asm", "maps/blockdata.asm",
                 "maps/map_scripts.asm"]
        before = {rel: (self.root / rel).read_text() for rel in wired}
        made = ["maps/TestIsland.asm", "maps/blk/TestIsland.ablk",
                ".devtools/specs/TestIsland.toml"]

        async def go():
            app = Studio(self.root)
            async with app.run_test() as pilot:
                await self._loaded(app, pilot)

                await pilot.press("a")
                await pilot.pause()
                palette = app.screen
                options = palette.query_one("#picker-list", OptionList)
                titles = [str(o.prompt) for o in options._options]
                options.highlighted = titles.index("Add a new map")
                await pilot.press("enter")
                await pilot.pause()

                form = app.screen
                self.assertIsInstance(form, Form)
                for name, value in self.form().items():
                    form.query_one(f"#field-{name}", Input).value = value
                await pilot.pause()

                # The map is on screen, in colour, at the size you typed — and
                # not one byte of it is in the repo yet. This is the whole reason
                # the studio exists rather than another wizard.
                sketch = form.query_one("#sketch", MapGrid)
                self.assertIsNotNone(sketch.view, form.unsketchable)
                self.assertEqual(sketch.view.blocks, self.BLOCKS)
                self.assertEqual(form.unsketchable, "")

                form.action_submit()
                await pilot.pause()
                confirm = app.screen
                self.assertIsInstance(confirm, Confirm, form.error)

                diff = confirm._preview.diff()
                for line in ("+\tmapgroup TEST_ISLAND, 4, 5",
                             "+\tmap_header TestIsland, TILESET_FOREST, CAVE,",
                             "+\tmap_header_2 TestIsland, TEST_ISLAND, 0, 0",
                             "+TestIsland_BlockData:",
                             '+\tINCBIN "maps/blk/TestIsland.ablk.lz"',
                             '+INCLUDE "maps/TestIsland.asm"',
                             "+++ b/maps/blk/TestIsland.ablk"):
                    self.assertIn(line, diff)

                confirm.action_yes()
                await pilot.pause()

                # The blocks that landed are the blocks that were drawn.
                self.assertEqual((self.root / "maps/blk/TestIsland.ablk").read_bytes(),
                                 self.BLOCKS)
                for rel in made:
                    self.assertTrue((self.root / rel).exists(), f"{rel} not written")

                # And the studio is looking at it: a map you added and then had to
                # go and find would be a map you might not have added.
                for _ in range(300):
                    await pilot.pause(0.02)
                    grid = app.query_one("#grid", MapGrid)
                    if grid.view is not None and grid.view.label == "TestIsland":
                        break
                self.assertEqual(app._wanted, "TestIsland")
                self.assertEqual(grid.view.blocks, self.BLOCKS)
                self.assertIn("TestIsland", app._shown)

                # Undo unmakes it — including the files it created, and including
                # the map you are standing on.
                app.action_undo()
                await pilot.pause()
                for rel in made:
                    self.assertFalse((self.root / rel).exists(), f"{rel} survived undo")
                for rel, text in before.items():
                    self.assertEqual((self.root / rel).read_text(), text, rel)
                self.assertNotIn("TestIsland", app._shown)

                await app.action_quit()

        drive(go())

    async def _loaded(self, app, pilot) -> None:
        """Wait for whatever map the list opens on. Adding a map needs no map,
        but the studio still has one selected, and the palette wants it."""
        for _ in range(300):
            await pilot.pause(0.02)
            if app._const is not None:
                return
        self.fail("no map ever loaded")


def _action(title: str):
    from pokeprism_devtools.studio.catalog import CATALOG
    return next(a for a in CATALOG if a.title == title)


class TestTheSeam(unittest.TestCase):
    """The view reads no files.

    Everything the TUI draws comes from `Session.load` as plain data, and the
    knowledge of what a `person_event` is — its argument order, the `+4` its
    macro adds at assembly — stays on the model side of the line. This test is
    the only thing that keeps that true: the rule is one careless import away
    from being a comment, and the import is always the convenient thing to do.

    It also happens to be the boundary a non-Python frontend would need. That is
    a happy side effect, not the reason; see `docs/adapter-plan.md`.
    """

    #: The view layer.
    VIEW = ("app.py", "grid.py", "forms.py")

    #: Modules that open the source tree. `coords` and `swatches` are not here:
    #: `coords.glyph_cells` and `swatches.tile_color` are the *renderer* — plain
    #: data in, colours out — and the grid is right to use them. (Both modules do
    #: also carry readers, `swatches.for_map` above all. A split would separate
    #: them; today the honest guard is at module granularity.)
    READERS = ("blocksrc", "eventheader", "wilddata", "mapsource", "blockdata",
               "metatiles", "render", "dialogue", "trainerparty", "wiring")

    def test_the_view_does_not_import_a_parser(self) -> None:
        import ast
        studio = Path(__file__).resolve().parents[1] / "src/pokeprism_devtools/studio"

        for name in self.VIEW:
            tree = ast.parse((studio / name).read_text())
            imported: list[str] = []
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    imported.extend(
                        f"{node.module or ''}.{a.name}" for a in node.names)
                elif isinstance(node, ast.Import):
                    imported.extend(a.name for a in node.names)

            for reader in self.READERS:
                offenders = [i for i in imported if reader in i.split(".")]
                self.assertEqual(
                    offenders, [],
                    f"studio/{name} imports {reader}: the view is reading the "
                    f"repo again. It should be asking Session for plain data.")


if __name__ == "__main__":
    unittest.main(verbosity=2)
