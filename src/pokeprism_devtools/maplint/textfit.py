"""Moved to `shared/textfit.py`. Re-export only, removed in the next commit.

Two subtractions over a tile count, and the family's overflow rules import them
— so leaving them here makes the IDE depend on prism's linter. This shim exists
so the move changes no caller; the callers move next.
"""

from __future__ import annotations

from ..shared.textfit import below_box, overshoot

__all__ = ["below_box", "overshoot"]
