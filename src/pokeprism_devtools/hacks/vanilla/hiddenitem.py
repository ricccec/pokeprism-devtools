"""The hidden item — a `bg_event` and the `hiddenitem` block it points at.

Its own module for the same reason the item ball has one: it is a block-writing
adder, not a one-line splice. But it writes into a *different* list. An item
ball is an `object_event` on the Objects tab; a hidden item reads onto that same
tab (it is a thing on the floor), yet its line is a `bg_event` — the sign the
engine reads to hand you the item — so the line splices into the bg list while
the offer sits under `object`. The seam holds: the tab an entry reads onto and
the list its line lives in are decided separately, here as everywhere.

It is also vanilla's alone. Polished bakes the item into the `bg_event` itself
(`BGEVENT_ITEM + NUGGET`) with no block anywhere, so there is nothing here for
it to reuse — which is why this lands in :data:`.actions.VANILLA_ONLY` beside
the item ball rather than as a branch.

The two irregularities the tree was measured for, both in `wiring/blocks.py`:
the label casing (`PP_UP` is `PpUp` here, not the ball's `PPUp`) and the
argument order (`hiddenitem ITEM, FLAG`, though the macro emits them reversed).
"""

from __future__ import annotations

from pathlib import Path

from ...studio.actions import FLAGS, ITEMS, ActionError, Field, Result
from ...wiring import blocks, flagalloc, regions
from . import eventblock as eb
from .entry import Entry

#: Where a hidden item's flag belongs by convention. The tree keeps two such
#: buckets, Johto and Kanto, and this prefers the Johto one — most hidden items
#: are Johto's, and where a Kanto map's flag lands is said out loud in the note
#: rather than filed silently under the wrong region.
_HIDDEN_BUCKET = "Johto hidden items"


class AddHiddenitem(Entry):
    """An item on the floor you only find by pressing A on empty ground.

    The engine reaches it in two hops: a `bg_event` of kind `BGEVENT_ITEM` on
    the tile, pointing at a script whose whole body is `hiddenitem ITEM, FLAG`.
    So this adder writes the same two halves the item ball does — a block in the
    scripts region and a line in an event list — but the line is a `bg_event`,
    not an `object_event`, and it carries no flag of its own. Bg events are
    unnamed (no `object_const_def`), which is the one thing here simpler than a
    ball: there is no const to mint, only the label and the flag.

    **The flag is not optional.** It is what remembers the item was taken; the
    `hiddenitem` line will not assemble without it, and one carrying nothing is
    an item the player finds again on every visit. So blank means *allocate one*
    — a write to `constants/event_flags.asm` — which is why this action returns
    two edits where a signpost returns one.
    """
    name = "hiddenitem"
    title = "Add a hidden item"
    #: The line is a `bg_event`, so it splices into the bg list — even though
    #: the reader shows the result on the Objects tab. The offer's tab and the
    #: line's list are not the same thing; see this module's docstring.
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

        path, label = self._file(root)
        text = path.read_text()

        # The flag first: it is written *into* the block, not onto the line, so
        # its name has to be settled before the block can be spelled.
        flag, flag_edit, note = self._flag(root, item)

        # Then the block, in memory. As with the item ball, both writes land in
        # this one file, so they cannot be two Edits off the same base — splice,
        # reparse, and let the entry writer produce the single Edit whose base
        # is still what is on disk. See `regions.spliced`.
        try:
            script = blocks.unique_label(
                text, f"{label}Hidden{blocks.plain_camel(item)}")
            body = blocks.hiddenitem(script, item, flag)
        except blocks.BlockError as exc:
            raise ActionError(str(exc)) from exc
        try:
            staged = regions.spliced(text, regions.SCRIPTS, body,
                                     layout=self.layout)
            block = eb.parse_text(staged, path, self.anchor)
        except (regions.RegionError, eb.UnparseableEvents) as exc:
            raise ActionError(str(exc)) from exc

        try:
            block.add_entry("bg", [self.text("x"), self.text("y"),
                                   "BGEVENT_ITEM", script])
        except eb.UnparseableEvents as exc:
            raise ActionError(str(exc)) from exc

        edit = block.to_edit(root, self.describe())
        return Result(self.describe(),
                      ([flag_edit] if flag_edit else []) + [edit],
                      [f"{script} hides the {item}; {flag} remembers it was taken"]
                      + note)

    def _flag(self, root: Path, item: str) -> tuple[str, object, list[str]]:
        """The flag, and the edit that creates it when it is new.

        Mirrors the item ball: a name **typed** into the box is used as it
        stands, and a name this action merely defaulted to gets a suffix if it
        collides. The default is `EVENT_<map>_HIDDEN_<item>` — 83 of the 85 in
        the tree — reached by handing :func:`blocks.flag_name` the item already
        prefixed with `HIDDEN_`. The other two are story-named
        (`EVENT_FOUND_BERSERK_GENE_IN_CERULEAN_CITY`), which is why the box is
        editable rather than a rule.
        """
        try:
            flags = flagalloc.load(root)
        except flagalloc.FlagError as exc:
            raise ActionError(str(exc)) from exc

        typed = self.text("flag")
        wanted = typed or blocks.flag_name(self.map, f"HIDDEN_{item}", flags.names)
        if flags.has(wanted):
            return wanted, None, [f"{wanted} already exists — reusing it, so "
                                  "this item and whatever else is on it are "
                                  "found and forgotten together"]
        try:
            bucket = flags.allocate(wanted, prefer=_HIDDEN_BUCKET)
        except flagalloc.FlagError as exc:
            raise ActionError(str(exc)) from exc
        note = [f"{wanted} allocated in {bucket.label!r}"]
        if bucket.label != _HIDDEN_BUCKET:
            note.append(f"the {_HIDDEN_BUCKET!r} bucket is full, so it went to "
                        f"{bucket.label!r} instead — the grouping is a comment, "
                        "not something the engine reads")
        return wanted, flags.to_edit(f"{wanted} in {bucket.label}"), note
