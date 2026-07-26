"""Building a stock pokecrystal, and standing in it — vanilla's `Plays`.

The family half of the build-and-boot loop. It shares the shape of prism's — run
`make`, patch a save so you spawn where you were editing, open SameBoy — but none
of its bytes: the targets are pokecrystal's ROMs (not `prism`/`nodebug`), the save
is the stock Gen-2 one (`savefile.py`, not prism's RTC-trailer layout), and where a
map lives is read from vanilla's own `map_constants.asm` through the reader that
already parses it. The `make` runner and the emulator are the only pieces neither
tree owns, and both come from neutral modules (`shared.make`, `dev_server.emulator`)
so nothing here reaches into prism.
"""

from __future__ import annotations

import datetime as dt
import os
from collections.abc import Callable
from pathlib import Path

from ...dev_server.emulator import Emulator
from ...shared import make
from ...shared.symfile import SymFile
from ..seam import PlayError
from . import read, savefile

#: The pokecrystal ROMs worth booting, the plain build first. Each is a `make`
#: file target that also writes its own `.sym` beside it (`Makefile`, `-n $*.sym`),
#: so the target name *is* the ROM filename — no debug/nodebug guessing about which
#: file on disk was the one asked for, the way prism has to.
_TARGETS = ("pokecrystal.gbc", "pokecrystal_debug.gbc")

#: A stock pokecrystal wants rgbds v1.0.0 or newer (its `rgbdscheck.asm` fails the
#: build otherwise). But the shell that launches the studio may export `RGBDS`
#: pointing at the *older* toolchain a sibling in this family pins — clearing that
#: override drops the build back to the `rgbds` on `PATH`, which is the modern one.
#: This is the whole of vanilla's toolchain difference, said once, as data.
_BUILD_ENV = {"RGBDS": ""}


class Player:
    """Vanilla's :class:`~..seam.Plays`: `make` a pokecrystal ROM, patch its save
    to stand on a map, open SameBoy. Holds the emulator across boots so a second
    boot replaces the window rather than opening another."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._emulator = Emulator()

    def targets(self) -> tuple[str, ...]:
        return _TARGETS

    def keeps(self, line: str) -> bool:
        """Whether a quiet build still shows this line — the shared grep."""
        return make.is_build_problem(line)

    def build(self, log: Callable[[str], None], *,
              target: str | None = None, jobs: int | None = None) -> bool:
        target = self._target(target)
        jobs = jobs if jobs is not None else (os.cpu_count() or 1)
        if jobs < 1:
            raise PlayError("you cannot run fewer than one job")
        return make.run_make(self._root, target, log, jobs=jobs, env=_BUILD_ENV)

    def boot(self, const: str, y: int, x: int, *,
             target: str | None = None, keep_people: bool = False) -> list[str]:
        """Stand at (y, x) on `const`, in a built pokecrystal, now.

        `keep_people` is part of the seam's boot and ignored here on purpose:
        standing you on a map touches only the four position bytes, never the
        map's objects, so there is nothing about people to keep or drop.
        """
        target = self._target(target)
        rom = self._root / target
        sym = rom.with_suffix(".sym")
        if not rom.exists():
            raise PlayError(f"no {target} to boot — run `make {target}` first.")
        if not sym.exists():
            raise PlayError(
                f"{target} has no {sym.name} beside it — the studio patches the "
                "save by symbol, so rebuild it with symbols.")

        group, number = self._where(const)
        template = rom.with_suffix(".sav")
        if not template.exists():
            raise PlayError(
                f"no save at {template.name}. Run {target} in an emulator once, "
                "finish the intro, and save in-game — there is no save to stand in "
                "until then.")

        try:
            save = savefile.Save.load(template)
            syms = SymFile.load(sym)
            if not save.looks_real(syms):
                raise PlayError(
                    f"the save at {template.name} doesn't look real (its validity "
                    "bytes are missing). Play the game once to create a proper save.")
            backup = self._backup(template)
            save.stand_on(syms, group=group, number=number, y=y, x=x)
            save.write(template)
        except savefile.SaveError as e:
            raise PlayError(str(e)) from e

        changes = [f"map = {const} at ({y}, {x})  [group {group}, map {number}]"]
        if backup is not None:
            changes.append(f"backed up the previous save to {backup.name}")
        return changes + self._emulator.launch(rom).warnings

    # -- the pieces ---------------------------------------------------------- #
    def _target(self, target: str | None) -> str:
        target = target or _TARGETS[0]
        if target not in _TARGETS:
            raise PlayError(f"{target!r} is not a target — {' or '.join(_TARGETS)}")
        return target

    def _where(self, const: str) -> tuple[int, int]:
        """The `(group, number)` a map constant names, from the same
        `map_constants.asm` parse the reader draws the catalog with — so the
        boot and the map list can never disagree about which map this is."""
        d = read.dims(self._root).get(const)
        if d is None:
            raise PlayError(
                f"{const} is not in constants/map_constants.asm — there is no map "
                "by that name to stand on.")
        return d.group, d.map_id

    def _backup(self, template: Path) -> Path | None:
        """Copy the save before overwriting it. Patching a save writes over the
        player's actual game, so never do it without leaving the previous bytes
        somewhere to be put back."""
        d = self._root / ".devtools" / "sav-backups"
        d.mkdir(parents=True, exist_ok=True)
        ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        dest = d / f"{template.stem}-{ts}.sav"
        dest.write_bytes(template.read_bytes())
        return dest
