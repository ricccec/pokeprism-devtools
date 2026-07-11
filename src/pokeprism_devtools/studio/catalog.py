"""Everything the studio can do, in the order the palette offers it.

Its own module for one reason: `CATALOG` is the single thing that has to know
about *every* action, so an action big enough to want a file of its own — adding
a map is — would otherwise have to import the list it is a member of. This is the
list, and it depends on the actions rather than the other way round.

`EditText` is deliberately absent. It needs a text block to act on, so it is
reached by picking one (`e` on a map), not by choosing it from a menu and then
being asked which of a map's forty blocks you meant.
"""

from __future__ import annotations

from .actions import (Action, AddHiddenItem, AddItemball, AddNpc, AddSignpost,
                      AddTrainer, AddWarp, Connect, Remove)
from .newmap import NewMap

CATALOG: tuple[type[Action], ...] = (
    NewMap,
    AddNpc, AddTrainer, AddItemball, AddHiddenItem, AddSignpost,
    Remove, Connect, AddWarp,
)
