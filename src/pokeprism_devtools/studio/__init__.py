"""prism-studio — author a map without hand-editing the four files it lives in.

An NPC is one thing to a person and four to the repo: a `person_event` in the
map's event header, the text it points at, an event flag allocated in the middle
of an enum where a hand-written one invalidates every save, and — if he battles —
a party in a group reached by *position*. Get any of them wrong and it still
assembles.

The studio is the place where it's one thing again. Its model lives in
:mod:`.session`; the TUI is a view over it.
"""

from __future__ import annotations

from .session import Applied, MapRef, Preview, Session, SessionError

__all__ = ["Applied", "MapRef", "Preview", "Session", "SessionError"]
