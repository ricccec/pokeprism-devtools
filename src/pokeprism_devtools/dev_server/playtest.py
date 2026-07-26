"""Patch a save to a state, and boot the ROM into it.

This is the last two steps of `prism-dev` — the ones worth having from somewhere
other than `prism-dev`. `prism-studio` wants to place an NPC and then stand next
to it, and the code that does that lived inside a questionary menu, printing to
stdout, reading its inputs off `DevServer` attributes: none of which a Textual
app can use.

So the split here is not by size, it is by who gets to speak. These functions do
the work and *return* what happened — the changed fields, the backup they took,
the warning about an untrackable emulator. Printing it is the caller's business,
because the caller is the one that knows whether it owns a terminal.

`Emulator` owns the child process and the lock over it, and nothing else. Two
callers can hold one and neither has to think about the other's threads.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

from pokeprism_devtools.hacks.prism import savefile
from pokeprism_devtools.shared import symfile

from . import apply
# The emulator is neutral — a SameBoy process, no map dialect — so it lives in
# its own module a family adapter can import without pulling prism in through
# here. Re-exported so `devplay.Emulator` still reads the same to prism.
from .emulator import Emulator, LaunchReport  # noqa: F401


class PlaytestError(RuntimeError):
    """The save can't be patched — no template, or not a real save."""


@dataclass(frozen=True)
class Layout:
    """Where prism-dev keeps its runtime state, under `.devtools/`.

    The studio boots the same save, from the same state file, into the same
    backups directory — it is the same game. Two definitions of where those live
    would eventually be two different answers.
    """
    inventory: Path
    state: Path
    presets: Path
    backups: Path

    @classmethod
    def under(cls, root: Path) -> "Layout":
        d = root / ".devtools"
        return cls(
            inventory=d / "inventory.json",
            state=d / "state.json",
            presets=d / "presets",
            backups=d / "sav-backups",
        )


@dataclass
class PatchReport:
    target: Path            # the .sav that was written
    backup: Path | None     # what the target looked like before, if it existed
    changes: list[str]      # human-readable, one per field apply_state touched


def patch_save(
    rom_path: Path,
    *,
    sym_path: Path,
    inv: dict,
    state: dict,
    backups_dir: Path,
    keep_people: bool = False,
    template: Path | None = None,
    target: Path | None = None,
) -> PatchReport:
    """Apply `state` to a save, fix both SRAM checksums, and write it out.

    Both `template` (what we read) and `target` (what we write) default to the
    save the emulator will actually load: `<rom>.sav`, beside the ROM. They are
    separate so `prism-dev --template X --out Y` can patch a save that isn't the
    live one without a second copy of this function to drift away from it.

    The template must already exist and already be a real save. The game writes
    SRAM's validity bytes the first time it saves, and a save without them boots
    to a black screen rather than an error — so refuse up front, where we can say
    why.
    """
    template = template or rom_path.with_suffix(".sav")
    target = target or rom_path.with_suffix(".sav")

    if not template.exists():
        raise PlaytestError(
            f"no template save at {template}. Run the ROM in an emulator once, "
            "complete the intro, and save in-game first."
        )

    sav = savefile.SaveFile.load(template)
    if not apply.looks_like_real_save(sav, inv):
        raise PlaytestError(
            f"the save at {template} doesn't look like a real one (its validity "
            "bytes are missing). Play the game once to create a proper save."
        )

    # Patching overwrites a save in place, and in the default case that save is
    # the user's actual game. Never destroy it silently.
    backup = None
    if target.exists():
        backups_dir.mkdir(parents=True, exist_ok=True)
        ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = backups_dir / f"{target.stem}-{ts}.sav"
        backup.write_bytes(target.read_bytes())

    changes = apply.apply_state(
        sav, state, inv,
        rom_path=rom_path, syms=symfile.SymFile.load(sym_path),
        keep_people=keep_people,
    )
    apply.recompute_checksums(sav, inv)
    sav.write(target)
    return PatchReport(target=target, backup=backup, changes=changes)
