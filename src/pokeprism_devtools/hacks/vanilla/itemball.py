"""The item ball — the first family adder that writes the block it points at.

Its own module because it is a different *kind* of write from everything in
:mod:`.actions`. Those splice one line into one list and are done. This one
touches two files, writes into two regions of the first, allocates a save-file
bit, and mints three names that have to agree with each other or the map
assembles into something subtly wrong.

It is also vanilla's alone. Polished spells the same object on screen as three
extra `object_event` arguments (`itemball_event`) with no block anywhere, so
there is nothing here for it to reuse — which is why this lands in
:data:`.actions.VANILLA_ONLY` as declared data rather than as a branch.

The names, the measurements behind them, and the two bugs that reading a
generated diff caught are all written down in `asmedit/blocks.py`.
"""

from __future__ import annotations

from pathlib import Path

from ...contract import FLAGS, ITEMS, ActionError, Field, Result
from ...asmedit import blocks, flagalloc, regions
from . import eventblock as eb
from .entry import Entry

#: Where an item ball's flag belongs by convention. Preferred, not required —
#: it is full in vanilla and :meth:`AddItemball._flag` says so when it falls
#: back rather than failing on a comment.
_ITEM_BUCKET = "Sprite visibility flags"


class AddItemball(Entry):
    """A Poké Ball on the ground — the first adder that writes a block.

    Everything above this class splices one line. This one writes three things
    that have to agree, in two files, and the reason it is the first of the
    scaffolding adders is that its block is the smallest there is: a label and
    one `itemball` macro, 178 times out of 178 with nothing else in it. What is
    hard about an item ball is not its body, it is the names.

    **The flag is not optional and that is the whole point of the class.** The
    flag is what remembers the ball was picked up; an item ball carrying `-1`
    is one the player takes again every time they walk back into the room. So
    unlike `AddNpc`, where a blank flag is a real answer meaning "always
    there", a blank here means *allocate one* — and allocating it is a write to
    `constants/event_flags.asm`, which is why this action returns two edits
    where every other adder returns one.

    **Nine of the object's thirteen slots are not offered**, and they are not
    defaults either. Every item ball in the tree is
    `SPRITE_POKE_BALL, SPRITEMOVEDATA_STILL, 0, 0, -1, -1, 0,
    OBJECTTYPE_ITEMBALL, 0` — all 178, no exceptions — and each of the nine is
    a way to write a ball that is not a ball. A radius makes it wander; the
    type is what makes the engine read its block as an item at all. Same
    reasoning as prism's `add_prop`: what is decided by the engine is not a
    question worth asking.
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
        # Blank means one, and blank is what an unanswered box holds. Not
        # `integer()`, which refuses "" — a ball with no number typed into it
        # is the ordinary case, not a malformed one.
        quantity = self.integer("quantity") if self.text("quantity") else 1

        path, label = self._file(root)
        text = path.read_text()

        # The block first, in memory. Both writes land in this one file and an
        # Edit carries the whole of it, so they cannot be two Edits built off
        # the same base — see `regions.spliced`. Splice, reparse, then let the
        # entry writer produce the single Edit whose base is still what is on
        # disk.
        try:
            script = blocks.unique_label(text, f"{label}{blocks.camel(item)}")
            body = blocks.itemball(script, item, quantity)
        except blocks.BlockError as exc:
            raise ActionError(str(exc)) from exc
        try:
            staged = regions.spliced(text, regions.SCRIPTS, body,
                                     layout=self.layout)
            block = eb.parse_text(staged, path, self.anchor)
        except (regions.RegionError, eb.UnparseableEvents) as exc:
            raise ActionError(str(exc)) from exc

        # `label`, not `self.map`: the consts are prefixed with the map file's
        # stem and the map constant is spelled differently for every map whose
        # name ends in a number. See `asmedit/blocks.object_const`.
        const = blocks.object_const([n for n, _ in block.names], label,
                                    "POKE_BALL")
        if block.const_lineno is None:
            # 40 of the 388 vanilla maps have no object at all, and so no
            # `object_const_def` header to hang a name on. The ball would
            # assemble unnamed — the engine finds its flag on the object's own
            # line and never looks a const up — but the *next* named object
            # added to that map would then be refused forever, because the
            # consts are positional and a list that names none of one object
            # cannot grow. Refusing now beats writing the map into that corner.
            raise ActionError(
                f"{label} has no objects yet, so there is no "
                "object_const_def block to name this ball in. Adding the "
                "header is not wired up — this adder extends a const list, it "
                "does not start one.")
        flag, flag_edit, note = self._flag(root, item)

        try:
            block.add_entry("object", self.shape.args({
                "y": self.text("y"), "x": self.text("x"),
                "sprite": "SPRITE_POKE_BALL",
                "movement": "SPRITEMOVEDATA_STILL",
                # Not PAL_NPC_RED. A ball's palette comes from its sprite, and
                # all 178 write a bare 0 here rather than a PAL_ name.
                "palette": "0",
                "type": "OBJECTTYPE_ITEMBALL",
                "script": script, "flag": flag,
            }), name=const)
        except eb.UnparseableEvents as exc:
            raise ActionError(str(exc)) from exc

        edit = block.to_edit(root, self.describe())
        return Result(self.describe(),
                      ([flag_edit] if flag_edit else []) + [edit],
                      [f"{script} holds the item; {const} names the ball"]
                      + note)

    def _flag(self, root: Path, item: str) -> tuple[str, object, list[str]]:
        """The flag, and the edit that creates it when it is new.

        A name **typed** into the box that already exists is used as it stands:
        two balls sharing a flag is a legitimate thing to want, and it is how
        "take either one of these" is written. A name this action merely
        defaulted to is not — it collides only when the map already holds a
        ball of the same item, and sharing there would make the second ball
        uncollectable. So the default gets a suffix and the typed name does
        not. See `asmedit/blocks.flag_name`.
        """
        try:
            flags = flagalloc.load(root)
        except flagalloc.FlagError as exc:
            raise ActionError(str(exc)) from exc

        typed = self.text("flag")
        wanted = typed or blocks.flag_name(self.map, item, flags.names)
        if flags.has(wanted):
            return wanted, None, [f"{wanted} already exists — reusing it, so "
                                  "this ball and the one already on it vanish "
                                  "together"]
        try:
            bucket = flags.allocate(wanted, prefer=_ITEM_BUCKET)
        except flagalloc.FlagError as exc:
            raise ActionError(str(exc)) from exc
        note = [f"{wanted} allocated in {bucket.label!r}"]
        if bucket.label != _ITEM_BUCKET:
            # Said out loud rather than swallowed. The conventional bucket is
            # full in vanilla — 0 free, measured — and the engine does not care
            # (`CheckObjectFlag` compares the id against -1 and nothing else),
            # but the next person reading the flag file will wonder why a ball's
            # flag is filed under the Kanto people.
            note.append(f"the {_ITEM_BUCKET!r} bucket is full, so it went to "
                        f"{bucket.label!r} instead — the grouping is a comment, "
                        "not something the engine reads")
        return wanted, flags.to_edit(f"{wanted} in {bucket.label}"), note
