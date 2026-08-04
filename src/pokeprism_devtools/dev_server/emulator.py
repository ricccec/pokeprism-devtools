"""Moved to `shared/emulator.py`. Re-export only, removed in the next commit.

Launching a Game Boy ROM is nobody's dialect, and both family play adapters
import it — so leaving it inside prism's dev-server CLI makes the IDE depend on
prism. This shim exists so the move changes no caller; the callers move next.
"""

from __future__ import annotations

from ..shared.emulator import Emulator, LaunchReport

__all__ = ["Emulator", "LaunchReport"]
