"""prism-studio — author a map without hand-editing the four files it lives in.

An NPC is one thing to a person and four to the repo: a `person_event` in the
map's event header, the text it points at, an event flag allocated in the middle
of an enum where a hand-written one invalidates every save, and — if he battles —
a party in a group reached by *position*. Get any of them wrong and it still
assembles.

The studio is the place where it's one thing again. Its model lives in
:mod:`.session`; the TUI is a view over it, and the view reads no files —
everything it draws comes through :meth:`.session.Session.load`, and everything
it changes goes out as an :class:`.actions.Action` whose fields it renders
without knowing what they mean.
"""

from __future__ import annotations

import sys

from .session import (Applied, MapData, MapGeometry, MapRef, Preview, Session,
                      SessionError)

__all__ = ["Applied", "MapData", "MapGeometry", "MapRef", "Preview", "Session",
           "SessionError", "main"]


def main(argv: list[str] | None = None) -> int:
    """The `prism-studio` entry point.

    Imports the TUI lazily so that this module — the model — stays usable, and
    importable, without a widget library installed. `textual` is an optional
    extra precisely because the studio is one module among twelve tools, and the
    honest thing to do when it's missing is say so.
    """
    try:
        from .app import main as run
    except ModuleNotFoundError as exc:
        if exc.name != "textual":
            raise
        print("prism-studio needs textual, which is an optional extra:\n"
              "    pip install 'pokeprism-devtools[studio]'\n"
              "The other prism-* tools work without it.", file=sys.stderr)
        return 2
    return run(argv)
