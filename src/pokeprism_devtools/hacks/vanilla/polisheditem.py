"""Polished's item ball and hidden item — the two the vanilla blocks don't fit.

Where vanilla writes a script block and points a line at it, polished *bakes the
item into the line*. An item ball is an ``object_event`` whose trailing three
args are the item, the quantity and the flag; a hidden item is a ``bg_event``
whose kind carries the item (``BGEVENT_ITEM + ETHER``) and whose fourth arg is
the flag. So neither points at a block — the whole adder is a flag and a line —
which is why they are polished's alone and live here rather than beside vanilla's
block writers. The mount declares them in :data:`.actions.POLISHED_ONLY`, the
mirror of :data:`.actions.VANILLA_ONLY`.

**The item ball is written long, not as ``itemball_event``.** The tree usually
writes the shorthand, but the read adapter reads the four base macros only — a
shorthand item ball is invisible to it — so this writes the ``object_event`` the
shorthand expands to, which is the form the studio can read back. That is also
why the palette, sprite and movement are the shorthand's own constants
(``SPRITE_BALL_CUT_TREE``, ``PAL_NPC_ENV_RED``, …): the line renders as any other
red item ball rather than as a thing visibly not one of the tree.

Both reuse nothing: a fresh event flag remembers the pickup, allocated in
polished's single flag run — its ``; Johto itemballs`` captions are comments, not
``const_next`` boundaries, so :mod:`...wiring.flagalloc` sees one bucket and a
preferred one would be a fiction. The item ball appends **unnamed**: item balls
carry no ``object_const`` even where a map names its people, so it never disturbs
the positional const list.
"""

from __future__ import annotations

from pathlib import Path

from ...contract import FLAGS, ITEMS, ActionError, Field, Result
from ...wiring import blocks, flagalloc
from . import eventblock as eb
from .entry import Entry

#: The nine object slots an item ball never varies — every ball on screen is a
#: red `SPRITE_BALL_CUT_TREE` the engine reads as `OBJECTTYPE_ITEMBALL`, so the
#: form asks for the item, the quantity and the flag and fills the rest. These
#: are the very constants `itemball_event` expands to, in polished's slot order:
#: x, y, sprite, movement, radius_y, radius_x, time, palette, type, playerevent.
_ITEMBALL_HEAD = ("SPRITE_BALL_CUT_TREE", "SPRITEMOVEDATA_STANDING_DOWN",
                  "0", "0", "-1", "PAL_NPC_ENV_RED", "OBJECTTYPE_ITEMBALL",
                  "PLAYEREVENT_ITEMBALL")


def _allocate_flag(action: Entry, root: Path,
                   default: str) -> tuple[str, object, list[str]]:
    """The flag that remembers a pickup, and the edit that creates a new one.

    A name **typed** into the box is used as it stands — two pickups sharing a
    flag is how "take either" is written — while a name merely defaulted to gets
    a suffix if it collides, since sharing there makes the second uncollectable.
    :func:`blocks.flag_name` does the suffixing against the names already in the
    file. Polished is one flag run, so there is no bucket to prefer.
    """
    try:
        flags = flagalloc.load(root)
    except flagalloc.FlagError as exc:
        raise ActionError(str(exc)) from exc

    typed = action.text("flag")
    wanted = typed or blocks.flag_name(action.map, default, flags.names)
    if flags.has(wanted):
        return wanted, None, [f"{wanted} already exists — reusing it, so this "
                              "pickup and whatever else is on it are found and "
                              "forgotten together"]
    try:
        bucket = flags.allocate(wanted)
    except flagalloc.FlagError as exc:
        raise ActionError(str(exc)) from exc
    return wanted, flags.to_edit(f"{wanted} in {bucket.label}"), [
        f"{wanted} allocated ({bucket.free} slots left in the flag file)"]


class AddPolishedItemball(Entry):
    """A Poké Ball on the ground, polished-style: one `object_event`, no block.

    The item, quantity and flag ride the object line's last three slots, so
    there is nothing to write beside it — where vanilla mints a block, three
    names and a flag, this mints only the flag. It appends the ball unnamed,
    because polished's item balls never take an `object_const`, and a name
    forced onto one would slide every later const onto the wrong object.

    **The flag is not optional.** It is what remembers the ball was picked up; a
    ball carrying `-1` is one the player takes on every visit. So blank here
    means *allocate one* — a write to `constants/event_flags.asm` — which is why
    this returns two edits where an NPC returns one.
    """
    name = "itemball"
    title = "Add an item ball"
    list_kind = "object"

    FIELDS = (
        Field("y", "Y", kind="int"),
        Field("x", "X", kind="int"),
        Field("item", "Item", choices=ITEMS, default="POTION"),
        Field("quantity", "How many", kind="int", default="1"),
        Field("flag", "Event flag", choices=FLAGS, default="",
              help="blank and one is allocated. It is what remembers you took "
                   "it — a ball without one can be picked up forever."),
    )

    def describe(self) -> str:
        qty = self.text("quantity")
        many = f"{qty} " if qty not in ("", "1") else ""
        return f"{many}{self.text('item')} at {self._where()} in {self.map}"

    def run(self, root: Path) -> Result:
        item = self.text("item")
        if not item:
            raise ActionError("an item ball with no item in it is a ball that "
                              "hands the player item 0 — name what is in it")
        # Blank means one, the ordinary case an unanswered box holds — not
        # `integer()`, which refuses "".
        quantity = self.integer("quantity") if self.text("quantity") else 1

        flag, flag_edit, note = _allocate_flag(self, root, item)
        block, _ = self._block(root)
        args = [self.text("x"), self.text("y"), *_ITEMBALL_HEAD,
                item, str(quantity), flag]
        try:
            block.add_entry("object", args, name=None)
        except eb.UnparseableEvents as exc:
            raise ActionError(str(exc)) from exc

        return Result(self.describe(),
                      ([flag_edit] if flag_edit else [])
                      + [block.to_edit(root, self.describe())],
                      [f"{flag} remembers it was taken"] + note)


class AddPolishedHiddenitem(Entry):
    """An item found by pressing A on empty ground, polished-style: a `bg_event`.

    The kind carries the item — `BGEVENT_ITEM + ETHER` — and the fourth arg is
    the flag, so like the item ball there is no block to write, only the line and
    the flag it names. It reads back onto the Objects tab (a thing on the floor),
    though its line lives in the bg list: the tab an entry reads onto and the
    list its line sits in are decided separately, here as everywhere.

    **The flag is not optional** and carries no default of `-1`: the line names
    it directly, and a hidden item without one is found again on every visit. So
    blank means *allocate one*.
    """
    name = "hiddenitem"
    title = "Add a hidden item"
    #: The line is a `bg_event`, so it splices into the bg list even though the
    #: reader shows the result on the Objects tab. See the class docstring.
    list_kind = "bg"

    FIELDS = (
        Field("y", "Y", kind="int"),
        Field("x", "X", kind="int"),
        Field("item", "Item", choices=ITEMS, default="POTION"),
        Field("flag", "Event flag", choices=FLAGS, default="",
              help="blank and one is allocated. It is what remembers you found "
                   "it — a hidden item without one is found again every visit."),
    )

    def describe(self) -> str:
        return f"hidden {self.text('item')} at {self._where()} in {self.map}"

    def run(self, root: Path) -> Result:
        item = self.text("item")
        if not item:
            raise ActionError("a hidden item with no item in it hands the player "
                              "item 0 — name what is hidden")

        flag, flag_edit, note = _allocate_flag(self, root, f"HIDDEN_{item}")
        block, _ = self._block(root)
        try:
            block.add_entry("bg", [self.text("x"), self.text("y"),
                                   f"BGEVENT_ITEM + {item}", flag])
        except eb.UnparseableEvents as exc:
            raise ActionError(str(exc)) from exc

        return Result(self.describe(),
                      ([flag_edit] if flag_edit else [])
                      + [block.to_edit(root, self.describe())],
                      [f"{flag} remembers it was found"] + note)
