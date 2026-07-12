"""Building the ROM, and standing in it.

The other half of the loop, and the only part of the studio that leaves the source
tree: it runs `make`, patches a save, and opens an emulator. Everything else in
`studio/` reads and writes `.asm` files; this runs a compiler and a game.

The save, the state file and the backups are `prism-dev`'s. The studio does not
keep a second game — what it overrides is *where you are standing*, and nothing
else, so playtesting a map does not cost you the character you play it as.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from ..dev_server import apply as devapply
from ..dev_server import inventory, playtest as devplay
from ..shared import paths


class PlayError(RuntimeError):
    """Nothing built, or the save could not be patched. Carries a message for a
    human, because every one of these is something you can do something about."""


def build(root: Path, log: Callable[[str], None]) -> bool:
    """`make`, streamed a line at a time. True if the ROM built.

    Streamed rather than captured because it takes minutes, and a progress bar
    that cannot fail is worse than the compiler's own output: when the map you
    just added doesn't link, the reason is in these lines, and it names your map.
    """
    proc = subprocess.Popen(
        ["make"], cwd=root,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )
    assert proc.stdout is not None
    with proc.stdout:
        for line in proc.stdout:
            log(line.rstrip("\n"))
    return proc.wait() == 0


def boot(root: Path, emulator: devplay.Emulator, const: str, y: int, x: int, *,
         keep_people: bool = False) -> list[str]:
    """Stand at (y, x) on this map, in the game, now.

    `y` and `x` are coordinate tiles, which is what the grid cursor reports and
    what `wYCoord`/`wXCoord` hold. No `+4` here: that offset lives inside the
    object structs, and `shared/people.py` is the one that knows about it.
    """
    try:
        rom = paths.rom_path(root)
    except FileNotFoundError as e:
        # Nothing built. Patching a save against a ROM that isn't there would read
        # map headers out of whatever *is* there, which is nothing.
        raise PlayError(str(e)) from e

    layout = devplay.Layout.under(root)
    layout.inventory.parent.mkdir(parents=True, exist_ok=True)
    sym = paths.sym_path(root)
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
