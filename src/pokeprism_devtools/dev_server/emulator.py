"""The SameBoy child process — launching a `.gbc`, and replacing it next time.

Pulled out of `playtest.py` because it is the one part of the playtest story that
is nobody's dialect: launching a Game Boy ROM and killing the last window is the
same whether the ROM is prism's or a stock pokecrystal's. `playtest.py` also
patches prism's save, and reaches most of `hacks/prism` to do it, so anything that
imported it for the emulator alone would drag that whole tree in. Here the only
neighbour is `launcher`, which knows how to find SameBoy and nothing about maps —
so a family play adapter can hold an emulator without importing prism.
"""

from __future__ import annotations

import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import launcher


@dataclass
class LaunchReport:
    launched: bool
    #: Whether we found an emulator to run at all. Not finding one is a shrug —
    #: the ROM and the save are still on disk and the user can open them by hand.
    #: Finding one and failing to start it is an error.
    found: bool = True
    command: str = ""
    replaced: bool = False       # we killed a previous instance to do this
    warnings: list[str] = field(default_factory=list)


class Emulator:
    """The SameBoy process, if we managed to get hold of one.

    Re-launching means killing the instance we started last time, which we can
    only do if we started it *as* SameBoy. When all we could find was the macOS
    `open -a` shim, the PID we hold is the shim's, not the emulator's, and the
    old window stays up — so say so, once, rather than silently failing to
    replace it.
    """

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._lock = threading.RLock()

    @property
    def running(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    def stop(self) -> bool:
        """Kill the emulator we started. Returns whether there was one."""
        with self._lock:
            if not self.running:
                self._proc = None
                return False
            proc = self._proc
            assert proc is not None
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            self._proc = None
            return True

    def launch(self, rom_path: Path, *, focus: bool = True) -> LaunchReport:
        cmd, trackable = launcher.build_cmd(rom_path)
        if cmd is None:
            return LaunchReport(launched=False, found=False, warnings=[
                f"SameBoy not found. Launch {rom_path} manually, or set "
                "$SAMEBOY_BIN to the binary path."
            ])

        replaced = self.stop()
        warnings = []
        if not trackable:
            warnings.append(
                "SameBoy.app not found via $SAMEBOY_BIN, $PATH, or Spotlight; "
                "using `open -a`. Re-launch will not be able to terminate the "
                "previous instance. Set $SAMEBOY_BIN to the SameBoy binary "
                "path to fix."
            )

        try:
            proc = subprocess.Popen(cmd)
        except OSError as e:
            return LaunchReport(launched=False, warnings=[*warnings, f"failed to launch: {e}"])

        with self._lock:
            self._proc = proc
        if focus:
            # The window takes a moment to exist; there is nothing to raise
            # before it does.
            time.sleep(1)
            launcher.focus_after_launch()
        return LaunchReport(launched=True, command=cmd[0], replaced=replaced,
                            warnings=warnings)
