"""Moved to `contract/suppressions.py`. Re-export only, removed next commit.

Two linters in two products read `; maplint: ignore[...]`, and the module
answers in `Diagnostic`, which is already contract vocabulary — so every other
home inverts an arrow. This shim exists so the move changes no caller; the
callers move next.
"""

from __future__ import annotations

from ..contract.suppressions import (apply_suppressions, file_suppressed_codes,
                                     suppressed_codes)

__all__ = ["apply_suppressions", "file_suppressed_codes", "suppressed_codes"]
