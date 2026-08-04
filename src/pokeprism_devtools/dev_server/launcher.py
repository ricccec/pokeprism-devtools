"""Moved to `shared/launcher.py`. Re-export only, removed in the next commit.

It travels with `emulator.py`, which is its only importer: finding SameBoy on
this machine is the same question whichever tree built the ROM.
"""

from __future__ import annotations

from ..shared.launcher import build_cmd, focus_after_launch

__all__ = ["build_cmd", "focus_after_launch"]
