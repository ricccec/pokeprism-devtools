"""What `e` and `d` act on — one thing, on one map, named opaquely.

The one record in the vocabulary that travels *both* ways: the adapter mints the
handle inside it, the view carries it around without looking, and the adapter is
handed it back to resolve. Everything about that round trip is in :class:`Ref`.
"""

from __future__ import annotations

from collections.abc import Hashable
from dataclasses import dataclass

#: The `what` of the Ref an "Add new…" row carries. Minted by :func:`add_ref`,
#: recognised by the session's adders — the view only ever sees it as a truthy
#: :attr:`Ref.adds`.
ADD = "add"


@dataclass(frozen=True)
class Ref:
    """What `e` and `d` act on: enough to name one thing on one map.

    **Opaque to the view.** `tabs.py` reads a Ref off the highlighted row and
    hands it straight back to the session, which is the only side of the seam
    allowed to know a `person_event` from a `signpost`. The view's whole share
    of the knowledge is the three declared affordances — "this row names
    something" (the Ref exists at all), :attr:`adds`, :attr:`deletable` — plus
    equality, for finding the row that carries a Ref again. The *fields* are the
    port's own, and no view code may read them.

    Identity itself is not even the port's: it is the adapter's **handle**,
    carried whole and resolved by handing it back. Prism's is a list kind and a
    position, because that is all its source can say about an object; vanilla's
    carries the `object_const_def` name its scripts address the object by. The
    port stores whatever it was given and does no arithmetic on it — all it
    needs of a handle is equality, for finding the row that carries it again.
    A prop's handle can name either engine list — a hidden item is filed with
    the signs — which is exactly why the list is in the handle and not implied
    by `what`.
    """
    #: npc | trainer | prop | signpost | warp | trigger | connection | map
    what: str
    #: The adapter's name for the entry, when this row is one. None for the rows
    #: that are not event entries: the map itself, a connection, "Add new…".
    handle: Hashable | None = None
    #: A connection's direction, or the kind an "Add new…" row offers.
    key: str = ""

    # -- the view-facing surface -------------------------------------------- #
    @property
    def adds(self) -> str:
        """The kind of thing this row would add — the word the tab declared in
        `Tab.adds` — or "" for a row that names something that already exists."""
        return self.key if self.what == ADD else ""

    @property
    def deletable(self) -> bool:
        """Whether `d` exists on this row. The map's own rows say no — deleting
        a whole map is not something the studio does — and so does an "Add
        new…" row, which names nothing yet."""
        return self.what not in (ADD, "map")


def add_ref(kind: str) -> Ref:
    """The Ref an "Add new…" row carries. Minted here, on the port side, so the
    view never assembles a Ref of its own — it draws the dim row because
    `Tab.adds` told it to, and hands back what it was given."""
    return Ref(ADD, key=kind)
