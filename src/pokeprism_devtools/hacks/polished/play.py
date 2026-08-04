"""Building polishedcrystal, and standing in it — polished's `Plays`.

The same build-and-boot shape as vanilla's and prism's — run `make`, patch a save
so you spawn where you were editing, open SameBoy — over polished's own pieces:
its save (`savefile.py`, stock-framed but rebuilt through polished's block codec),
and its ROM naming. Polished's `Makefile` has no `roms :=` list the way stock's
does, so the buildable target is derived from its `NAME`/`VERSION` and whatever
`*.gbc` are already built beside a `.sym`. Where a map lives and how big it is come
from the same `map_constants.asm` parse the reader draws the catalog with, so the
boot and the map list can never disagree.

The boot rebuilds the tiles around the spawn — the interior grid plus the connected
neighbours overlaid at the map edges — and repopulates the object engine with the
destination map's own NPCs and their sprite VRAM, so teleporting in lands on a map
that looks like itself (see `savefile.Save.stand_on`). The `make` runner and the
emulator are neutral (`shared.make`, `dev_server.emulator`).
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
from ..vanilla.read import dims, label_of, lines
from . import savefile

#: The `Makefile` assignments that name the default ROM: `<NAME><MODIFIERS>-<VERSION>.<EXTENSION>`.
#: The first assignment of each wins — the base values, before the feature targets
#: (`faithful`, `monochrome`, …) redefine `MODIFIERS`, and before the Pocket build
#: redefines `NAME`/`EXTENSION`.
_ASSIGN = re.compile(r"^\s*(NAME|MODIFIERS|VERSION|EXTENSION)\s*:?=\s*(.*?)\s*$")

#: Polished, like stock, wants the `rgbds` on `PATH` (its `rgbdscheck.asm` sets a
#: floor, not a pin). Clearing `RGBDS` drops any older toolchain a sibling in this
#: family exports. A caller that knows the machine better can override it.
_BUILD_ENV = {"RGBDS": ""}


class Player:
    """Polished's :class:`~...contract.Plays`: `make` a polishedcrystal ROM, patch its
    save to stand on a map, open SameBoy. Holds the emulator across boots so a
    second boot replaces the window rather than opening another."""

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
        return make.run_make(self._root, target, log, jobs=jobs,
                             env=env if env is not None else _BUILD_ENV)

    def boot(self, const: str, y: int, x: int, *,
             target: str | None = None, keep_people: bool = False) -> list[str]:
        """Stand at (y, x) on `const`, in a built polishedcrystal, now.

        Patches the save to stand on the tile and rebuild the tiles around it
        (from the built ROM, through polished's block codec, with the connected
        neighbours filled in at the edges), reloads the destination map's own NPCs,
        fixes the primary and backup checksums, and opens SameBoy. `keep_people`
        preserves the objects already in the save instead of reloading the map's.
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

        group, number, label, width, height = self._where(const)
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
                syms, group=group, number=number, label=label,
                width=width, height=height, y=y, x=x,
                rom_path=rom, keep_people=keep_people,
                resolve_neighbour=self._neighbour_resolver())
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
        """Resolve and check a target against what the tree can boot.

        The valid set is the default the `Makefile` names plus any `*.gbc` already
        built beside a `.sym`. When it can't be read we don't reject a caller's
        target — we can't offer a catalog, but we can't prove it wrong either. The
        default is the plain build (`polishedcrystal-<VERSION>.gbc`).
        """
        roms = _roms(self._root)
        if target is None:
            if not roms:
                raise PlayError(
                    "could not read the Makefile's NAME/VERSION, and no built "
                    "*.gbc is present — there is no default target to fall back on.")
            return roms[0]
        if roms and target not in roms:
            raise PlayError(f"{target!r} is not a target — {', '.join(roms)}")
        return target

    def _neighbour_resolver(self):
        """A `(group, map_id) -> (label, width, height) | None` over the same
        `map_constants.asm`/`attributes.asm` parse the catalog uses.

        A connection names its neighbour by numeric (group, map_id), but polished
        loads a map's blocks by label, so the edge overlay needs this reverse of the
        map catalog to find the neighbour's `<label>_BlockData` and its dimensions. A
        map with no attributes entry (no label) can't be a neighbour and is left out.
        """
        by_const = dims(self._root)
        labels = label_of(self._root)
        rev = {
            (d.group, d.map_id): (labels[const], d.width, d.height)
            for const, d in by_const.items()
            if const in labels
        }
        return lambda group, map_id: rev.get((group, map_id))

    def _where(self, const: str) -> tuple[int, int, str, int, int]:
        """The `(group, number, label, width, height)` a map constant names, from
        the same `map_constants.asm`/`blocks.asm` parse the reader draws the
        catalog with — so the boot and the map list can never disagree about which
        map this is or how big it is (the size the tile rebuild needs)."""
        d = dims(self._root).get(const)
        if d is None:
            raise PlayError(
                f"{const} is not in constants/map_constants.asm — there is no map "
                "by that name to stand on.")
        label = label_of(self._root).get(const)
        if label is None:
            raise PlayError(
                f"{const} has no map file in data/maps/blocks.asm — its block data "
                "can't be found to rebuild the tiles.")
        return d.group, d.map_id, label, d.width, d.height

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
    """Polished's bootable ROMs: the default the `Makefile` builds, then any
    `*.gbc` already built beside a `.sym`.

    Unlike stock's `roms :=` list, polished names its ROM by variables
    (`<NAME><MODIFIERS>-<VERSION>.<EXTENSION>`), so the default is reconstructed
    from those. A target name *is* the ROM filename — each build writes its own
    `.sym` beside it — so a built variant sitting in the tree is offered too,
    letting a `make faithful` ROM boot without teaching this its naming.
    """
    out: list[str] = []
    default = _default_rom(root)
    if default is not None:
        out.append(default)
    for gbc in sorted(root.glob("*.gbc")):
        if gbc.with_suffix(".sym").exists() and gbc.name not in out:
            out.append(gbc.name)
    return tuple(out)


def _default_rom(root: Path) -> str | None:
    """`<NAME><MODIFIERS>-<VERSION>.<EXTENSION>` from the `Makefile`'s first
    assignment of each — the plain build, before the feature and Pocket targets
    redefine them. `None` if the `Makefile` can't be read for NAME and VERSION."""
    vals: dict[str, str] = {}
    for raw in lines(root / "Makefile"):
        m = _ASSIGN.match(raw.split("#", 1)[0])
        if m and m.group(1) not in vals:
            vals[m.group(1)] = m.group(2)
    name, version = vals.get("NAME"), vals.get("VERSION")
    if not name or not version:
        return None
    return f"{name}{vals.get('MODIFIERS', '')}-{version}.{vals.get('EXTENSION', 'gbc')}"
