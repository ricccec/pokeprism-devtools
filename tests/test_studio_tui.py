"""The shell. Driven with Textual's Pilot, not eyeballed.

Deliberately thin. Everything the studio *knows* — where a marker goes, what
colour a tile is, what the linter found — is tested in test_grid.py and
test_studio.py against the ROM and against the real renderer. What is left to
check here is only that the shell is wired to it.

Since the UX overhaul that is a bigger claim than it was, because the shell now
has an idea in it: **what is selected decides what the keys do.** So these tests
mostly ask two questions. Does pointing at a thing and pressing a key act on that
thing? And does a key that would mean nothing for the selected row *disappear*,
rather than sit in the footer waiting to disappoint someone?
"""

from __future__ import annotations

import asyncio
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from textual.widgets import DataTable, Input, OptionList, TabbedContent, TextArea

from pokeprism_devtools.shared import blocksrc, coords, eventheader, paths, swatches
from pokeprism_devtools.studio import Session, panels
from pokeprism_devtools.studio.actions import (ActionError, AddItemball, AddNpc,
                                               AddSignpost)
from pokeprism_devtools.studio.app import Studio
from pokeprism_devtools.studio.grid import MapGrid
from pokeprism_devtools.studio.newmap import NewMap
from pokeprism_devtools.studio.screens import Confirm, Findings, Form, History, Picker
from pokeprism_devtools.studio.screens.speech import Dialogue
from pokeprism_devtools.studio.tabs import ADD, Tabs

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
        cols, rows = panels.npcs(self.header, {})
        self.assertEqual(cols[:3], ["#", "y", "x"])

        # The +4 the person_event macro adds at assembly must not appear here:
        # this table is what you would *type*, not what the ROM holds.
        for row in rows:
            entry = self.header.object_events[row.ref.index]
            self.assertEqual(row.cells[1], str(entry.y))
            self.assertEqual(row.cells[2], str(entry.x))

    def test_the_three_people_tabs_partition_the_object_events(self) -> None:
        """Every person_event lands in exactly one of NPCs / Trainers / Pickups.

        Three tabs are cut out of one engine list. A person_event that fell into
        two of them could be deleted twice; one that fell into none would be
        invisible, and an invisible NPC is the worst kind.
        """
        tabs = [panels.npcs(self.header, {})[1],
                panels.trainers(self.header)[1],
                panels.pickups(self.header)[1]]
        found: list[int] = []
        for rows in tabs:
            found += [r.ref.index for r in rows
                      if r.ref.kind == eventheader.ListKind.OBJECT_EVENTS.value]

        self.assertEqual(sorted(found), list(range(len(self.header.object_events))))
        self.assertEqual(len(found), len(set(found)), "an object is on two tabs")

    def test_a_rows_index_is_the_engines_index_not_the_tabs(self) -> None:
        """The one that would silently corrupt a map. An NPC third on the NPC tab
        may be seventh in the object_events list; editing it by row number would
        rewrite whoever is really seventh."""
        rows = panels.npcs(self.header, {})[1]
        for row in rows:
            entry = self.header.object_events[row.ref.index]
            self.assertNotIn(entry.persontype, panels.TRAINER_TYPES)
            self.assertNotIn(entry.persontype, panels.PICKUP_TYPES)

    def test_a_pickup_tab_holds_both_lists(self) -> None:
        """An item ball is an object event and a hidden item is a bg event. They
        are the same thing to a person, so they share a tab — and each row has to
        remember which of the engine's two lists it really came from."""
        header = eventheader.parse_map(ROOT / "maps/BotanCity.asm")
        rows = panels.pickups(header)[1]
        kinds = {r.ref.kind for r in rows}
        self.assertIn(eventheader.ListKind.BG_EVENTS.value, kinds,
                      "BotanCity has a hidden item; it isn't on the Pickups tab")

    def test_a_signpost_tab_never_shows_a_hidden_item(self) -> None:
        header = eventheader.parse_map(ROOT / "maps/BotanCity.asm")
        for row in panels.signposts(header)[1]:
            entry = header.bg_events[row.ref.index]
            self.assertNotEqual(entry.arg(2), panels.HIDDEN_ITEM)

    def test_a_trainer_reads_his_class_off_the_macro(self) -> None:
        """A trainer's person_event says `-1` where everyone else keeps their
        event flag, because his real flag is the first argument of the `trainer`
        macro in his script. Showing the -1 would be showing a column that is
        always the same lie."""
        rows = panels.trainers(self.header)[1]
        self.assertTrue(rows, f"{MAP} has no trainers?")
        for row in rows:
            self.assertNotEqual(row.cells[-1], "-1")
            self.assertTrue(row.cells[-1].startswith("EVENT_"), row.cells)
            self.assertNotEqual(row.cells[4], "—", "no class found")

    def test_warps_name_the_destination(self) -> None:
        cols, rows = panels.warps(self.header)
        self.assertIn("to map", cols)
        for row, entry in zip(rows, self.header.warps):
            if entry.macro == "warp_def":
                self.assertEqual(row.cells[3], entry.arg(3))

    def test_wild_rows_carry_no_ref_so_the_keys_vanish(self) -> None:
        """This is how `e` and `d` disappear on the Wild tab: not a special case
        in the app, just a row that names nothing."""
        _, rows = panels.wild({})
        self.assertTrue(all(r.ref is None for r in rows))


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
                self.assertEqual((2 * row) // zoom, ty)
                self.assertEqual((2 * row + 1) // zoom, ty)
                self.assertEqual(col // zoom, tx)


class _Driven(unittest.TestCase):
    """Shared machinery: get a map on screen, and get to a tab."""

    root = ROOT

    async def ready(self, app, pilot, label: str = MAP) -> MapGrid:
        app.query_one("#filter", Input).value = label
        await pilot.pause()
        grid = app.query_one("#grid", MapGrid)
        for _ in range(400):
            await pilot.pause(0.02)
            if grid.view is not None and grid.view.label == label:
                await pilot.pause(0.2)          # let the tabs finish rebuilding
                return grid
        self.fail(f"{label} never loaded")

    async def open_tab(self, app, pilot, name: str) -> DataTable:
        tabs = app.query_one(Tabs)
        panes = tabs.query_one(TabbedContent)
        panes.active = f"pane-{name}"
        await pilot.pause(0.2)
        table = panes.get_pane(f"pane-{name}").query_one(DataTable)
        table.focus()
        await pilot.pause(0.1)
        return table

    async def go_to_row(self, app, pilot, table: DataTable, row: int) -> None:
        table.move_cursor(row=row)
        await pilot.pause(0.15)


class TestShell(_Driven):
    def test_it_comes_up_and_shows_a_map(self) -> None:
        async def go():
            app = Studio(ROOT)
            async with app.run_test() as pilot:
                await pilot.pause()
                grid = app.query_one("#grid", MapGrid)
                self.assertIsNotNone(grid.view, "no map loaded on startup")

                # Every map in the repo is offered, including the ones that don't
                # parse — hiding a broken map from the person looking for the
                # break is the worst thing this list could do.
                self.assertGreater(len(app._maps), 400)
                self.assertIn(BROKEN, [m.label for m in app._maps])
                await app.action_quit()

        drive(go())

    def test_filtering_then_picking_loads_that_map(self) -> None:
        async def go():
            app = Studio(ROOT)
            async with app.run_test() as pilot:
                grid = await self.ready(app, pilot)
                self.assertEqual(app._shown[0], MAP)
                self.assertTrue(all(MAP in label for label in app._shown))

                bd = blocksrc.load(ROOT, MAP)
                self.assertEqual(grid.view.blocks, bd.blocks)
                self.assertEqual(grid.view.size,
                                 coords.tile_size(bd.height, bd.width))
                self.assertEqual(
                    grid.view.swatches,
                    swatches.for_map(ROOT, bd.tileset_id, bd.permission))
                await app.action_quit()

        drive(go())

    def test_the_cursor_reports_the_tile_it_is_on(self) -> None:
        """The cursor's whole job: hand the forms a coordinate you can trust."""
        async def go():
            app = Studio(ROOT)
            async with app.run_test() as pilot:
                grid = await self.ready(app, pilot)
                grid.cursor = (0, 0)
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

    def test_the_tabs_are_the_partition_of_the_map(self) -> None:
        async def go():
            app = Studio(ROOT)
            async with app.run_test() as pilot:
                await self.ready(app, pilot)
                panes = app.query_one(Tabs).query_one(TabbedContent)
                names = [str(p.id) for p in panes.query("TabPane")]
                for wanted in ("pane-attributes", "pane-npcs", "pane-trainers",
                               "pane-pickups", "pane-warps", "pane-signposts",
                               "pane-triggers", "pane-connections", "pane-roof",
                               "pane-wild"):
                    self.assertIn(wanted, names)
                await app.action_quit()

        drive(go())

    def test_a_map_that_doesnt_parse_still_comes_up(self) -> None:
        """It has a shape. Showing the shape and saying why the tables are empty
        beats an empty table that reads as 'this map has no NPCs'."""
        data = Session(ROOT).load(BROKEN)

        self.assertIsNotNone(data.geometry, "a broken header still has blocks")
        self.assertEqual(data.geometry.marks, {})
        self.assertIsNotNone(data.error)
        self.assertIsNotNone(data.tab("Unreadable"), "no tab explaining the break")
        self.assertIsNone(data.tab("NPCs"), "it offered NPCs it cannot read")
        # And the parts that don't depend on the header still work.
        self.assertIsNotNone(data.tab("Connections"))
        self.assertIsNotNone(data.tab("Attributes"))

    def test_attributes_finds_the_bank_a_shipped_map_really_lives_in(self) -> None:
        """A map already in the game sits in a *shared* section — OxalisCity's
        blocks are in "Map block data 4" with a dozen others. Assuming the
        per-map name a new map would get reports every shipped map as unpinned,
        which is both wrong and exactly backwards."""
        rows = Session(ROOT).load("OxalisCity").tab("Attributes").table[1]
        banks = [r.cells[1] for r in rows if r.cells[0].startswith("Section")]
        self.assertEqual(len(banks), 3)
        for value in banks:
            self.assertRegex(value, r"^\$[0-9A-F]{2} ", value)


class TestTheFooterIsTheSelection(_Driven):
    """The core claim of the overhaul: the keys are a function of the row.

    A key that cannot do anything must not be in the footer. `check_action`
    returning None is what removes it — True would grey it out, which still reads
    as an offer.
    """

    def test_no_edit_and_no_delete_on_a_wild_encounter(self) -> None:
        async def go():
            app = Studio(ROOT)
            async with app.run_test() as pilot:
                await self.ready(app, pilot)
                await self.open_tab(app, pilot, "wild")
                self.assertIsNone(app._ref)
                self.assertIsNone(app.check_action("edit", ()))
                self.assertIsNone(app.check_action("delete", ()))
                await app.action_quit()

        drive(go())

    def test_an_npc_offers_both(self) -> None:
        async def go():
            app = Studio(ROOT)
            async with app.run_test() as pilot:
                await self.ready(app, pilot)
                await self.open_tab(app, pilot, "npcs")
                self.assertEqual(app._ref.what, "npc")
                self.assertTrue(app.check_action("edit", ()))
                self.assertTrue(app.check_action("delete", ()))
                await app.action_quit()

        drive(go())

    def test_the_add_row_can_be_added_to_but_not_deleted(self) -> None:
        async def go():
            app = Studio(ROOT)
            async with app.run_test() as pilot:
                await self.ready(app, pilot)
                table = await self.open_tab(app, pilot, "signposts")
                await self.go_to_row(app, pilot, table, table.row_count - 1)

                self.assertEqual(app._ref.what, ADD)
                self.assertEqual(app._ref.key, "signpost")
                self.assertTrue(app.check_action("edit", ()))
                self.assertIsNone(app.check_action("delete", ()),
                                  "offered to delete the Add row")
                await app.action_quit()

        drive(go())

    def test_undo_is_absent_until_there_is_something_to_undo(self) -> None:
        async def go():
            app = Studio(ROOT)
            async with app.run_test() as pilot:
                await self.ready(app, pilot)
                self.assertIsNone(app.check_action("undo", ()))
                await app.action_quit()

        drive(go())


class TestTheCursorAndTheMouse(_Driven):
    """Two places on the map, answering two different questions."""

    def test_the_cursor_fills_in_the_coordinates(self) -> None:
        """The one pair of numbers in the app you should never have to type.

        Three units are in play — an 8px graphics tile, a 16px coordinate tile,
        a 32px block — and the person_event macro adds 4 to y and x behind your
        back at assembly. A form asking for a bare y and x is a trap. A cursor on
        a tile you can see is not.
        """
        async def go():
            app = Studio(ROOT)
            async with app.run_test() as pilot:
                grid = await self.ready(app, pilot)
                grid.cursor = (12, 7)
                await pilot.pause()

                for action in (AddNpc, AddSignpost, AddItemball):
                    form = Form(action, app.session, app._const, grid.cursor)
                    await app.push_screen(form)
                    await pilot.pause(0.2)
                    self.assertEqual(form.query_one("#field-y", Input).value, "12",
                                     action.name)
                    self.assertEqual(form.query_one("#field-x", Input).value, "7",
                                     action.name)
                    app.pop_screen()
                    await pilot.pause(0.1)
                await app.action_quit()

        drive(go())

    def test_the_mouse_reports_a_tile_without_moving_the_cursor(self) -> None:
        """How you answer "the linter says warp 2, and all I know is it is at
        (2, 17)": put the pointer on 2, 17 and read the marker off.

        Walking the *cursor* there would work too — and would move the
        coordinates that every form is about to be prefilled with, which is
        exactly what you did not want to do while looking something up.
        """
        async def go():
            app = Studio(ROOT)
            async with app.run_test(size=(120, 45)) as pilot:
                grid = await self.ready(app, pilot)
                grid.cursor = (0, 0)
                grid.zoom = 2
                await pilot.pause(0.2)

                # A tile with something standing on it, so the glyph is worth
                # reading — that is the whole point of hovering it.
                where = min(grid.view.marks)
                z = grid.zoom
                await pilot.hover(MapGrid,
                                  offset=(where[1] * z, where[0] * z // 2))
                await pilot.pause(0.2)

                self.assertIsNotNone(app._mouse_at, "the mouse reported nothing")
                self.assertEqual((app._mouse_at.y, app._mouse_at.x), where)
                self.assertEqual(app._mouse_at.glyph, grid.view.marks[where])
                self.assertEqual(grid.cursor, (0, 0), "hovering moved the cursor")
                await app.action_quit()

        drive(go())


class TestRefresh(unittest.TestCase):
    """The repo is not the studio's alone.

    `_invalidate` drops the caches for the files the studio *wrote*, which it can
    do precisely because it knows what it wrote. It cannot know what you did in
    an editor, or what a `git pull` did. There is no cheap way to notice, so the
    honest design is a key you press when you know you changed something — and a
    cache that is genuinely dropped when you press it.
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

    def test_a_constant_added_by_hand_is_invisible_until_you_ask(self) -> None:
        """A form's autocomplete is read once and cached for the run.

        (The edit here renumbers the item enum, which would be a terrible thing
        to do to a real repo and is a perfectly good thing to do to a temporary
        copy that will never be assembled. What is under test is the cache, not
        the item.)
        """
        session = Session(self.root)
        self.assertNotIn("TEST_WIDGET", session.choices("items"))

        items = self.root / "constants/item_constants.asm"
        items.write_text(items.read_text().replace(
            "\tconst MASTER_BALL", "\tconst TEST_WIDGET\n\tconst MASTER_BALL", 1))

        self.assertNotIn("TEST_WIDGET", session.choices("items"),
                         "the cache is not a cache")

        session.reload()
        self.assertIn("TEST_WIDGET", session.choices("items"),
                      "reload() did not re-read the constants")

    def test_the_module_level_caches_are_cleared_too(self) -> None:
        """The bug the test above caught, named so it stays caught.

        Half the `shared` modules memoise their reads with an `@lru_cache`, which
        lives on the *function* — so it outlives any Session that thought it owned
        it. Clearing only what is on `self` leaves `consts.names` serving the
        items it read an hour ago, with total confidence. `reload()` looked right
        and was wrong, and only a test that actually edited a file found it.
        """
        from pokeprism_devtools.shared import caches, consts

        consts.names(self.root, consts.ITEMS)
        self.assertTrue(consts.names.cache_info().currsize,
                        "consts.names is not actually cached; this test is moot")

        cleared = caches.clear()
        self.assertEqual(consts.names.cache_info().currsize, 0)
        self.assertGreater(cleared, 5,
                           "cache discovery found almost nothing — it has broken, "
                           "and a cache-clearer that clears nothing is worse than "
                           "none, because it looks like it worked")

    def test_reload_rebuilds_the_linter_too(self) -> None:
        """The lint context is the other thing read once at startup — it is where
        the map list comes from, so a map somebody else added is invisible until
        it is rebuilt."""
        session = Session(self.root)
        was = session.ctx
        session.lint()

        session.reload()
        self.assertIsNot(session.ctx, was, "the same context came back")
        self.assertIsNone(session._found, "the findings survived a reload")


class TestEditing(_Driven):
    """The whole loop, on a copy: point at a row -> form -> diff -> apply -> undo.

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

    def test_enter_on_the_add_row_places_a_sign_at_the_cursor(self) -> None:
        """No palette, no typing a label. You are on the Signposts tab, you walk
        to the end of the list, and the end of the list is where you add one."""
        path = self.root / f"maps/{MAP}.asm"
        before = path.read_text()

        async def go():
            app = Studio(self.root)
            async with app.run_test() as pilot:
                grid = await self.ready(app, pilot)
                grid.cursor = (9, 11)
                await pilot.pause()

                table = await self.open_tab(app, pilot, "signposts")
                await self.go_to_row(app, pilot, table, table.row_count - 1)
                await pilot.press("enter")
                await pilot.pause(0.2)

                form = app.screen
                self.assertIsInstance(form, Form, f"enter opened {form!r}")
                self.assertIs(form._action, AddSignpost)

                # The cursor filled in the coordinates. This is the one pair of
                # numbers in the whole app you should never have to type.
                self.assertEqual(form.query_one("#field-y", Input).value, "9")
                self.assertEqual(form.query_one("#field-x", Input).value, "11")

                form.query_one("#field-text", TextArea).text = (
                    "It reads:\nBEWARE OF THE DOG")
                await pilot.pause()
                form.action_submit()
                await pilot.pause()

                confirm = app.screen
                self.assertIsInstance(confirm, Confirm, form.error)
                diff = confirm._preview.diff()
                self.assertIn("+CastroForestSign:", diff)
                self.assertIn('+\tctxt "It reads:"', diff)
                self.assertIn("+\tsignpost 9, 11, SIGNPOST_TEXT, CastroForestSign",
                              diff)

                confirm.action_yes()
                await pilot.pause()

                text = path.read_text()
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

                app.action_undo()
                await pilot.pause()
                self.assertEqual(path.read_text(), before)
                await app.action_quit()

        drive(go())

    def test_e_on_an_npc_opens_what_that_npc_says(self) -> None:
        """The whole reason the writer copies macros back positionally.

        You point at an NPC, press `e`, change one word. What lands is that word
        — not a reflowed block, not a `cont` turned into a `para`, not somebody's
        alignment whitespace tidied up. The diff should be one line long.
        """
        path = self.root / f"maps/{MAP}.asm"
        before = path.read_text().split("\n")

        async def go():
            app = Studio(self.root)
            async with app.run_test() as pilot:
                await self.ready(app, pilot)
                await self.open_tab(app, pilot, "npcs")
                self.assertEqual(app._ref.what, "npc")

                await pilot.press("e")
                await pilot.pause(0.2)

                form = app.screen
                self.assertIsInstance(form, Form, "e on an NPC opened nothing")
                area = form.query_one("#field-text", TextArea)
                # It opens with the NPC's own words already in it — that is what
                # makes this editing rather than retyping.
                self.assertTrue(area.text.strip(), "the box came up empty")

                lines = area.text.split("\n")
                nth = next(n for n, line in enumerate(lines) if line.strip())
                lines[nth] = "REWORDED"
                area.text = "\n".join(lines)
                await pilot.pause()

                form.action_submit()
                await pilot.pause()
                confirm = app.screen
                self.assertIsInstance(confirm, Confirm, form.error)
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

    def test_d_on_a_trainer_warns_about_his_party_before_you_agree(self) -> None:
        """The confirmation is not a formality.

        Deleting a trainer leaves his party behind, because deleting *that* would
        renumber every party below it in the group and re-team every trainer
        citing them by position. That is not something to find out afterwards
        from a linter. It is on the screen, above the button.
        """
        async def go():
            app = Studio(self.root)
            async with app.run_test() as pilot:
                await self.ready(app, pilot)
                table = await self.open_tab(app, pilot, "trainers")
                await self.go_to_row(app, pilot, table, 0)
                self.assertEqual(app._ref.what, "trainer")

                await pilot.press("d")
                await pilot.pause(0.3)

                confirm = app.screen
                self.assertIsInstance(confirm, Confirm, "d opened no confirmation")
                notes = " ".join(confirm._preview.notes)
                self.assertIn("orphan", notes)
                self.assertIn("renumber", notes)

                # And walking away from it writes nothing at all.
                confirm.action_no()
                await pilot.pause()
                self.assertFalse(app.session.history, "cancelling still wrote")
                await app.action_quit()

        drive(go())

    def test_d_on_an_npc_takes_it_off_the_map_and_undo_puts_it_back(self) -> None:
        path = self.root / f"maps/{MAP}.asm"
        before = path.read_text()

        async def go():
            app = Studio(self.root)
            async with app.run_test() as pilot:
                await self.ready(app, pilot)
                table = await self.open_tab(app, pilot, "npcs")
                await self.go_to_row(app, pilot, table, 0)
                ref = app._ref
                self.assertEqual(ref.what, "npc")

                await pilot.press("d")
                await pilot.pause(0.3)
                confirm = app.screen
                self.assertIsInstance(confirm, Confirm)
                confirm.action_yes()
                await pilot.pause(0.5)

                self.assertNotEqual(path.read_text(), before, "nothing was removed")
                self.assertTrue(app.session.history)

                app.action_undo()
                await pilot.pause()
                self.assertEqual(path.read_text(), before)
                await app.action_quit()

        drive(go())

    def test_d_on_a_warp_refuses_and_says_why(self) -> None:
        """A refusal with a reason beats a key that isn't there. `warp_to` is a
        position in this map's warp list, so deleting one renumbers every warp in
        the repo that points at this map — and until that is written, saying so is
        the honest answer."""
        async def go():
            app = Studio(self.root)
            async with app.run_test() as pilot:
                await self.ready(app, pilot)
                table = await self.open_tab(app, pilot, "warps")
                await self.go_to_row(app, pilot, table, 0)
                self.assertEqual(app._ref.what, "warp")

                with _Captured(app) as said:
                    await pilot.press("d")
                    await pilot.pause(0.3)

                self.assertNotIsInstance(app.screen, Confirm,
                                         "it offered to delete a warp")
                self.assertIn("renumber", " ".join(said.messages))
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
                await self.ready(app, pilot)
                form = Form(AddNpc, app.session, "CASTRO_FOREST", (2, 3))
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


class TestHistory(_Driven):
    """What you changed, and whether you can take it back."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name) / "pokeprism"
        shutil.copytree(ROOT, cls.root, symlinks=True, ignore=shutil.ignore_patterns(
            ".git", "*.o", "*.gbc", "*.sym", "*.map"))

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_a_mutation_is_undone_whole_or_not_at_all(self) -> None:
        """The rule the history panel exists to make visible.

        Adding an NPC writes the map *and* the event-flag enum. Touch one of them
        by hand and the undo must refuse — and must leave the *other* alone too.
        Half an undo is worse than none: it would put the map back while leaving
        the flag allocated, and nothing would ever say so.
        """
        session = Session(self.root)
        # An item ball, not an NPC: it always allocates an event flag, so it
        # writes the map *and* constants/event_flags.asm — and a mutation that
        # spans two files is the only kind this rule has anything to say about.
        session.act(AddItemball("CASTRO_FOREST", y="4", x="4", item="POTION"))

        applied = session.history[-1]
        self.assertIn("constants/event_flags.asm", applied.paths)
        map_rel = next(p for p in applied.paths if p.startswith("maps/"))

        # Somebody edits the flags file behind our back.
        flags = self.root / "constants/event_flags.asm"
        flags.write_text(flags.read_text() + "\n; touched by hand\n")
        map_text = (self.root / map_rel).read_text()

        blocked = session.mutations()[-1]
        self.assertFalse(blocked.undoable)
        self.assertIn("event_flags.asm", blocked.blocked)

        with self.assertRaises(Exception):
            session.undo()

        # And the map — the file that had *not* moved — is untouched.
        self.assertEqual((self.root / map_rel).read_text(), map_text,
                         "a refused undo still wrote to the other file")

    def test_a_change_a_later_one_wrote_over_says_which(self) -> None:
        session = Session(self.root)
        session.act(AddItemball("OXALIS_CITY", y="4", x="4", item="POTION"))
        session.act(AddItemball("OXALIS_CITY", y="5", x="4", item="ANTIDOTE"))

        first, second = session.mutations()
        self.assertFalse(first.undoable)
        self.assertIn("undo that one first", first.blocked)
        self.assertTrue(second.undoable, "the newest change should still be undoable")

    def test_the_window_shows_the_files_and_the_lines(self) -> None:
        async def go():
            app = Studio(self.root)
            async with app.run_test() as pilot:
                await self.ready(app, pilot)
                app.session.act(AddItemball("CASTRO_FOREST", y="6", x="6",
                                            item="POTION"))

                await pilot.press("H")
                await pilot.pause(0.3)
                window = app.screen
                self.assertIsInstance(window, History)

                mutation = window._rows[0]
                self.assertIn("POTION", mutation.summary)
                paths = [f[0] for f in mutation.files]
                self.assertIn("constants/event_flags.asm", paths)
                # The lines, not just the file: "which lines" is the question you
                # open a history panel to answer.
                self.assertTrue(any(f[1] and f[1] != "created"
                                    for f in mutation.files), mutation.files)
                await app.action_quit()

        drive(go())


class TestFindings(_Driven):
    def test_the_window_lists_the_whole_repo_and_filters(self) -> None:
        """The panel beside the grid shows what is wrong with *this* map. A
        cross-file linter exists because the change you made here breaks something
        over there, and that panel can never say so. This window is 'there'."""
        async def go():
            app = Studio(ROOT)
            async with app.run_test() as pilot:
                await self.ready(app, pilot)
                for _ in range(400):
                    await pilot.pause(0.02)
                    if app._linted:
                        break

                await pilot.press("L")
                await pilot.pause(0.3)
                window = app.screen
                self.assertIsInstance(window, Findings)

                everything = len(window._shown)
                self.assertGreater(everything, 10, "the repo lints clean?")

                window.query_one("#findings-filter", Input).value = "sprite"
                await pilot.pause(0.2)
                self.assertLess(len(window._shown), everything)
                self.assertTrue(all("sprite" in f.haystack for f in window._shown))
                await app.action_quit()

        drive(go())


class TestNewMap(unittest.TestCase):
    """Adding a map to the game: the picture first, then the whole loop.

    Every other action changes a map you are looking at. This one has nothing to
    look at — the map does not exist until five source files say it does — which
    is why `a` goes straight to it, and why this test looks at the drawing before
    it looks at the diff.
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
    def test_a_goes_straight_to_the_map_form(self) -> None:
        """There is one thing you cannot reach by pointing at a row, and it gets
        the one key that isn't about the selection."""
        wired = ["constants/map_dimension_constants.asm", "maps/map_headers.asm",
                 "maps/second_map_headers.asm", "maps/blockdata.asm",
                 "maps/map_scripts.asm"]
        before = {rel: (self.root / rel).read_text() for rel in wired}
        made = ["maps/TestIsland.asm", "maps/blk/TestIsland.ablk",
                ".devtools/specs/TestIsland.toml"]

        async def go():
            app = Studio(self.root)
            async with app.run_test() as pilot:
                for _ in range(300):
                    await pilot.pause(0.02)
                    if app._const is not None:
                        break

                await pilot.press("a")
                await pilot.pause(0.2)

                form = app.screen
                self.assertIsInstance(form, Form, "`a` did not open the map form")
                self.assertIs(form._action, NewMap)

                for name, value in self.form().items():
                    form.query_one(f"#field-{name}", Input).value = value
                await pilot.pause()

                # The map is on screen, in colour, at the size you typed — and not
                # one byte of it is in the repo yet.
                sketch = form.query_one("#sketch", MapGrid)
                self.assertIsNotNone(sketch.view, form.unsketchable)
                self.assertEqual(sketch.view.blocks, self.BLOCKS)

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


class TestChoices(unittest.TestCase):
    """What the form offers, which the form itself is not allowed to know."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.session = Session(ROOT)

    def test_every_declared_kind_can_be_answered(self) -> None:
        from pokeprism_devtools.studio.session import ADDERS
        every = {a for group in ADDERS.values() for a in group} | {NewMap}
        for action in every:
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
        text = next(f for f in AddSignpost.FIELDS if f.kind == "lines")
        self.assertEqual(text.box, "speech")
        self.assertNotEqual(self.session.measure("x", "speech").cols,
                            self.session.measure("x", "sign").cols)


class TestTheDialogueGutter(_Driven):
    """What a line costs, on the line — not in a second copy of it underneath.

    The form used to print the speech twice: once in the box you typed into, and
    again below with a count beside each line, leaving you to match them up by
    counting rows. The count now lives in the box's right margin, drawn per
    *visible* line by `render_line`, which is what keeps it aligned with the text
    when the box scrolls: there is no second scroll position to keep in step.
    """

    async def _box(self, app, pilot, text: str):
        form = Form(AddNpc, app.session, app._const, (3, 4))
        await app.push_screen(form)
        await pilot.pause(0.3)
        box = form.query_one("#field-text", Dialogue)
        box.text = text
        await pilot.pause(0.4)
        return box

    def _lines(self, box, count: int) -> list[str]:
        return [box.render_line(y).text.rstrip() for y in range(count)]

    def test_the_count_is_in_tiles_and_lands_on_its_own_line(self) -> None:
        async def go():
            app = Studio(ROOT)
            async with app.run_test(size=(100, 40)) as pilot:
                for _ in range(300):
                    await pilot.pause(0.02)
                    if app._const is not None:
                        break
                box = await self._box(
                    app, pilot,
                    "#mon Center near\nHi there.\n\n<PLAYER> is here right")
                rows = self._lines(box, 4)

                # `#` is four tiles, not one character: 16 characters, 19 tiles,
                # against an 18-column box. You find that out here, not from the
                # linter after you have saved.
                self.assertIn("#mon Center near", rows[0])
                self.assertIn("19/18", rows[0])
                self.assertIn("1 over", rows[0])

                self.assertIn("9/18", rows[1])
                self.assertNotIn("over", rows[1])

                # A blank line is a page break — the engine opens a fresh box —
                # and nothing about an empty line says so. Now it does.
                self.assertIn("new box", rows[2])

                # The worst kind of overflow: right in your game, broken in the
                # game of someone with a long name.
                self.assertIn("over at worst", rows[3])
                await app.action_quit()

        drive(go())

    def test_the_gutter_follows_the_text_when_the_box_scrolls(self) -> None:
        """The bug this design exists not to have. A panel below the box has its
        own scroll position; a gutter drawn by `render_line` cannot, because it
        is handed the line it is drawing."""
        async def go():
            app = Studio(ROOT)
            async with app.run_test(size=(100, 40)) as pilot:
                for _ in range(300):
                    await pilot.pause(0.02)
                    if app._const is not None:
                        break
                # One long line per row, each a different length, so every row's
                # count is distinguishable from every other row's.
                text = "\n".join("a" * (n + 1) for n in range(30))
                box = await self._box(app, pilot, text)

                box.scroll_to(y=10, animate=False)
                await pilot.pause(0.3)
                self.assertEqual(box.scroll_offset.y, 10, "the box did not scroll")

                # The top visible row is document line 10, which is 11 a's.
                top = box.render_line(0).text
                self.assertIn("a" * 11 + " ", top)
                self.assertIn("11/18", top)
                await app.action_quit()

        drive(go())


class TestTheSeam(unittest.TestCase):
    """The view reads no files.

    Everything the TUI draws comes from `Session.load` as plain data, and the
    knowledge of what a `person_event` is — its argument order, the `+4` its
    macro adds at assembly — stays on the model side of the line. This test is
    the only thing that keeps that true: the rule is one careless import away
    from being a comment, and the import is always the convenient thing to do.
    """

    #: The view layer. `screens/` is a directory precisely so that this list is
    #: a fact about the tree rather than a list somebody has to remember to add
    #: to — every screen is in it by construction.
    VIEW = ("app.py", "tabs.py", "grid.py")

    #: Modules that open the source tree. `coords` and `swatches` are not here:
    #: `coords.glyph_cells` and `swatches.tile_color` are the *renderer* — plain
    #: data in, colours out — and the grid is right to use them. (Both modules do
    #: also carry readers, `swatches.for_map` above all. A split would separate
    #: them; today the honest guard is at module granularity.)
    READERS = ("blocksrc", "eventheader", "wilddata", "mapsource", "blockdata",
               "metatiles", "render", "dialogue", "trainerparty", "wiring",
               "roofs", "reader")

    def _files(self) -> list[Path]:
        studio = Path(__file__).resolve().parents[1] / "src/pokeprism_devtools/studio"
        return ([studio / name for name in self.VIEW]
                + sorted((studio / "screens").glob("*.py")))

    def test_the_view_does_not_import_a_parser(self) -> None:
        import ast

        for path in self._files():
            tree = ast.parse(path.read_text())
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
                    f"studio/{path.name} imports {reader}: the view is reading "
                    f"the repo again. It should be asking Session for plain data.")

    def test_every_screen_is_checked(self) -> None:
        """The guard above is only as good as the list of files it walks."""
        names = {p.name for p in self._files()}
        for wanted in ("app.py", "tabs.py", "grid.py", "forms.py", "confirm.py",
                       "build.py", "lint.py", "history.py"):
            self.assertIn(wanted, names)


class _Captured:
    """Catch what the app `notify`s, so a refusal can be asserted on."""

    def __init__(self, app) -> None:
        self.app = app
        self.messages: list[str] = []
        self._real = app.notify

    def __enter__(self):
        def spy(message, **kwargs):
            self.messages.append(str(message))
            return self._real(message, **kwargs)
        self.app.notify = spy
        return self

    def __exit__(self, *exc) -> None:
        self.app.notify = self._real


if __name__ == "__main__":
    unittest.main(verbosity=2)
