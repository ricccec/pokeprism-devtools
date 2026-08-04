"""Building a stock pokecrystal, and standing in it — vanilla's `Plays`.

The family half of the build-and-boot loop. It shares the shape of prism's — run
`make`, patch a save so you spawn where you were editing, open SameBoy — but none
of its bytes: the targets are pokecrystal's ROMs (not `prism`/`nodebug`), the save
is the stock Gen-2 one (`savefile.py`, not prism's RTC-trailer layout), and where a
map lives is read from vanilla's own `map_constants.asm` through the reader that
already parses it. The `make` runner and the emulator are the only pieces neither
tree owns, and both come from neutral modules (`shared.make`, `dev_server.emulator`)
so nothing here reaches into prism.

The boot rebuilds the whole map, not just the position: standing you on a tile
also reconstructs the tiles and objects around it (`shared.overworld.rebuild`,
the engine-general core prism drives too) so the overworld comes up clean rather
than over the previous map's state. See :meth:`Player.boot`.
"""

from __future__ import annotations

import datetime as dt
import os
import re
from collections.abc import Callable, Mapping
from pathlib import Path

from ...dev_server.emulator import Emulator
from ...shared import make
from ...shared.devtools import make_devtools_dir
from ...shared.symfile import SymFile
from ...contract import PlayError
from . import read, savefile

#: The line in the `Makefile` that opens the list of ROMs `make` knows how to
#: build. What follows is a backslash-continued run of `*.gbc` names.
_ROMS = re.compile(r"^\s*roms\s*:=")

#: Vanilla's *default* toolchain, and only the default — a caller may override it
#: (see :meth:`Player.build`). A stock pokecrystal wants rgbds v1.0.0 or newer (its
#: `rgbdscheck.asm` fails the build otherwise), and pins none itself: clearing
#: `RGBDS` means "use the `rgbds` on `PATH`", which is portable to any set-up
#: pokecrystal machine. It is written as a clear rather than a bare `{}` because
#: the shell that launches the studio may export `RGBDS` pointing at the *older*
#: toolchain a sibling in this family pins, and this drops that on the floor.
_BUILD_ENV = {"RGBDS": ""}


class Player:
    """Vanilla's :class:`~...contract.Plays`: `make` a pokecrystal ROM, patch its save
    to stand on a map, open SameBoy. Holds the emulator across boots so a second
    boot replaces the window rather than opening another."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._emulator = Emulator()

    def targets(self) -> tuple[str, ...]:
        return _roms(self._root)

    def keeps(self, line: str) -> bool:
        """Whether a quiet build still shows this line — the shared grep."""
        return make.is_build_problem(line)

    def build(self, log: Callable[[str], None], *,
              target: str | None = None, jobs: int | None = None,
              env: Mapping[str, str] | None = None) -> bool:
        target = self._target(target)
        jobs = jobs if jobs is not None else (os.cpu_count() or 1)
        if jobs < 1:
            raise PlayError("you cannot run fewer than one job")
        # `env=None` means "vanilla's declared default"; a caller that knows the
        # machine's toolchain better than `_BUILD_ENV` does can override it.
        return make.run_make(self._root, target, log, jobs=jobs,
                             env=env if env is not None else _BUILD_ENV)

    def boot(self, const: str, y: int, x: int, *,
             target: str | None = None, keep_people: bool = False) -> list[str]:
        """Stand at (y, x) on `const`, in a built pokecrystal, now.

        Patches the save to stand on the tile *and* rebuild the map around it —
        the tiles and the objects, read from the built ROM — then fixes the
        primary and backup checksums and opens SameBoy. `keep_people` preserves
        the objects already in the save instead of reloading the destination
        map's own; it gates the NPC half of the rebuild, exactly as it does for
        prism through the shared core.
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
            map_changes = save.stand_on(
                syms, group=group, number=number, y=y, x=x,
                rom_path=rom, keep_people=keep_people)
            save.write(template)
        except savefile.SaveError as e:
            raise PlayError(str(e)) from e

        changes = [f"map = {const} at ({y}, {x})  [group {group}, map {number}]"]
        changes += map_changes
        if backup is not None:
            changes.append(f"backed up the previous save to {backup.name}")
        return changes + self._emulator.launch(rom).warnings

    # -- the pieces ---------------------------------------------------------- #
    def _target(self, target: str | None) -> str:
        """Resolve and check a target against what the tree actually builds.

        The valid set is read from the `Makefile`, so a target the studio can
        hand back is one `make` really knows. When the list can't be read (a
        tree mid-edit), we don't reject — we can't offer a catalog, but we also
        can't prove a caller's target wrong, so we trust it. The default is the
        first ROM the `Makefile` lists, which is the plain build."""
        roms = _roms(self._root)
        if target is None:
            if not roms:
                raise PlayError(
                    "the Makefile lists no ROMs to build (no `roms :=`) — there "
                    "is no default target to fall back on.")
            return roms[0]
        if roms and target not in roms:
            raise PlayError(f"{target!r} is not a target — {', '.join(roms)}")
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
        d = make_devtools_dir(self._root, "sav-backups")
        ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        dest = d / f"{template.stem}-{ts}.sav"
        dest.write_bytes(template.read_bytes())
        return dest


def _roms(root: Path) -> tuple[str, ...]:
    """The ROMs `make` builds, in `Makefile` order — read from its `roms :=`
    list, not guessed, so the studio offers exactly the targets the tree does
    and no others. The old two-target guess omitted three real ROMs, one of
    them the debug build a save was already made for; a list read from source
    can't drift from what `make` will accept.

    Each of these targets writes its own `.sym` beside the ROM (the `Makefile`'s
    `-n $*.sym`), so a target name *is* the ROM filename — no debug/nodebug
    indirection about which file on disk was meant, the way prism needs.

    `roms :=` is one logical line spread across physical ones with trailing
    backslashes; we read from the assignment until the first line that does not
    continue. A tree whose `Makefile` can't be read yields `()`: the honest "I
    can't see the build," which the callers degrade around rather than a stale
    baked-in list. Cheap enough (one small file, scanned to the block's end)
    that it re-reads each call instead of caching a Makefile a person may edit.
    """
    out: list[str] = []
    collecting = False
    for raw in read.lines(root / "Makefile"):
        if _ROMS.match(raw):
            collecting = True
        if collecting:
            out += re.findall(r"\S+\.gbc", raw)
            if not raw.rstrip().endswith("\\"):
                break
    return tuple(out)
