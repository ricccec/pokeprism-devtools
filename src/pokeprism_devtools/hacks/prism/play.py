"""Building the ROM, and standing in it — prism's :class:`~..seam.Plays`.

The other half of the loop, and the only part of the studio that leaves the source
tree: it runs `make`, patches a save, and opens an emulator. Everything else in
`studio/` reads and writes `.asm` files; this runs a compiler and a game. It lives
below the seam because every byte of it is prism's: the `make` targets, the save
format the patcher writes, the emulator that comes up. The session drives it
through :class:`Player` and knows none of that — see `hacks/seam.py`.

The save, the state file and the backups are `prism-dev`'s. The studio does not
keep a second game — what it overrides is *where you are standing*, and nothing
else, so playtesting a map does not cost you the character you play it as.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from pathlib import Path

from ...dev_server import apply as devapply
from ...dev_server import inventory, playtest as devplay
from ...shared import make, paths
from ..seam import PlayError

#: The two ROMs this repo builds, and whether each one is the *debug* build — which
#: is the word `shared/paths.py` uses for the same distinction, so this table is
#: also the translation between them.
#:
#: `make` on its own is the `all` target: both ROMs, plus the GBS and the images.
#: That is minutes you did not ask for, and worse, it leaves *both* ROMs on disk
#: and freshly dated, which is precisely the state in which "whichever ROM is
#: lying around" stops being a safe way to choose one. So the target is named, and
#: named again on the way back out — see :func:`boot`.
TARGETS: dict[str, bool] = {"prism": True, "nodebug": False}

#: The debug build. It is the one the dev server's tooling is written against, and
#: the one you want when the map you are standing in is a map you made ten seconds
#: ago and may have got wrong.
DEFAULT_TARGET = "prism"


def _debug(target: str) -> bool:
    if target not in TARGETS:
        raise PlayError(f"{target!r} is not a target — {' or '.join(TARGETS)}")
    return TARGETS[target]


def build(root: Path, log: Callable[[str], None], *,
          target: str = DEFAULT_TARGET, jobs: int | None = None,
          env: Mapping[str, str] | None = None) -> bool:
    """`make -j<n> <target>`, streamed a line at a time. True if the ROM built.

    Prism's part is the two words above the shared runner: *which* target is a
    real one (`_debug` rejects anything but `prism`/`nodebug`), and that a job
    count under one is a refusal to explain. The streaming itself is every
    tree's, and lives in `shared.make`.

    Prism pins no toolchain of its own — `env=None` (the default) inherits the
    environment, which is where prism's `rgbds` is already selected. A caller may
    still override it, the same handle vanilla uses to escape that same default.
    """
    _debug(target)
    jobs = jobs if jobs is not None else (os.cpu_count() or 1)
    if jobs < 1:
        raise PlayError("you cannot run fewer than one job")
    return make.run_make(root, target, log, jobs=jobs, env=env)


def boot(root: Path, emulator: devplay.Emulator, const: str, y: int, x: int, *,
         target: str = DEFAULT_TARGET, keep_people: bool = False) -> list[str]:
    """Stand at (y, x) on this map, in the game, now.

    `y` and `x` are coordinate tiles, which is what the grid cursor reports and
    what `wYCoord`/`wXCoord` hold. No `+4` here: that offset lives inside the
    object structs, and `hacks/prism/people.py` is the one that knows about it.

    **The ROM is the one named, or none.** No falling back to the other build: you
    said which target, the build wrote that one, and handing back the *other* one
    because it happens to exist is how you end up patching a save against a game
    you are not about to play. If it isn't there, the build did not produce it, and
    that is worth being told rather than papered over.
    """
    debug = _debug(target)
    try:
        rom = paths.rom_path(root, debug=debug, fallback=False)
        sym = paths.sym_path(root, debug=debug, fallback=False)
    except FileNotFoundError as e:
        # Nothing built. Patching a save against a ROM that isn't there would read
        # map headers out of whatever *is* there, which is nothing.
        raise PlayError(str(e)) from e

    layout = devplay.Layout.under(root)
    layout.inventory.parent.mkdir(parents=True, exist_ok=True)
    inv = inventory.load_or_build(root, sym, layout.inventory, log=lambda _: None)

    state = devapply.load_state(layout.state, layout.presets)
    state.setdefault("map", {}).update({"name": const, "y": y, "x": x})

    try:
        report = devplay.patch_save(
            rom, sym_path=sym, inv=inv, state=state,
            backups_dir=layout.backups, keep_people=keep_people,
        )
    except devplay.PlaytestError as e:
        raise PlayError(str(e)) from e

    return report.changes + emulator.launch(rom).warnings


class Player:
    """Prism's :class:`~..seam.Plays`: `make`, patch prism's save, open SameBoy.

    Thin over the module functions — they carry the argument, the reasons and
    the tests. What the class adds is the two things the seam wants an object
    for: it holds the emulator (so a second boot replaces the window, not opens
    a new one — see :meth:`boot`), and it resolves the session's `target=None`
    into prism's own :data:`DEFAULT_TARGET`, so no default target has to live
    above the seam.
    """

    def __init__(self, root: Path) -> None:
        self._root = root
        #: Held across boots, so booting again replaces the window you are
        #: already looking at instead of opening a second one behind it.
        self._emulator = devplay.Emulator()

    def targets(self) -> tuple[str, ...]:
        """Prism's build targets, the default (`prism`, the debug build) first."""
        return tuple(TARGETS)

    def keeps(self, line: str) -> bool:
        """Whether a quiet build still shows this line — the shared grep."""
        return make.is_build_problem(line)

    def build(self, log: Callable[[str], None], *,
              target: str | None = None, jobs: int | None = None,
              env: Mapping[str, str] | None = None) -> bool:
        return build(self._root, log,
                     target=target or DEFAULT_TARGET, jobs=jobs, env=env)

    def boot(self, const: str, y: int, x: int, *,
             target: str | None = None, keep_people: bool = False) -> list[str]:
        return boot(self._root, self._emulator, const, y, x,
                    target=target or DEFAULT_TARGET, keep_people=keep_people)
