"""Moved to `contract/mount.py`. Re-export only, removed in the next commit.

The mount is contract machinery, not an adapter: `studio/app.py` and
`studio/session.py` import it, so leaving it under `hacks/` makes the IDE
depend on the adapters it is supposed to be independent of. This shim exists so
the move changes no caller; the callers move next.
"""

from __future__ import annotations

from ..contract.mount import NearMiss, UnknownTree, mount

__all__ = ["NearMiss", "UnknownTree", "mount"]
