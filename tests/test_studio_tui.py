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
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pokeprism_devtools.shared import blocksrc, coords, eventheader, paths, swatches
from pokeprism_devtools.studio import Session, panels
from pokeprism_devtools.studio.app import Studio
from pokeprism_devtools.studio.grid import MapGrid

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
    VIEW = ("app.py", "grid.py")

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
