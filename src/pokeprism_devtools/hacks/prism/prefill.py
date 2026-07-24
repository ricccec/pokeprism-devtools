"""What a form opens with: the row you pointed at, read back out of the source.

The other half of `edits.py`. That module says what each `e` *writes*; this one
says what it *shows you* before you have typed anything, and the two are not the
same job — one is a dozen actions, this is one function with a branch per kind of
row.

Two rules run through all of it, and both are the difference between an editor and
a form that happens to be next to some data:

**It is read from the file, not from the table.** The table is a rendering — it
shows `PAL_OW_BROWN` where the source says `8 + PAL_OW_BROWN`, and it shows a
trainer's class, which is not on his `person_event` at all. A form filled in from
the rendering would write the rendering back.

**A field the object has no answer for is simply absent**, and `fields_for` then
does not ask. An NPC can point at a script instead of a text block; a signpost can
be a JUMPSTD, which points at nothing; a trainer can name a `.defeated_text` that
nobody ever wrote. A box offering to reword a block that does not exist could only
fail on submit, after you had typed into it.
"""

from __future__ import annotations

from pathlib import Path

from . import eventheader as eh
from ...wiring import mapedit, objedit, props
from .content import HIDDEN, ITEMBALL, TMHM, TREE
from ...studio.model import TextRef
from ...studio.panels import Ref


def prefill(root: Path, label: str, const: str, ref: Ref,
            texts: list[TextRef]) -> tuple[dict[str, str], dict[str, str]]:
    """The form's opening values for the row you picked, and which box each of its
    prose fields is really drawn in.

    Read back out of the source, not out of the table: the table is a rendering
    and this is the thing itself. A field the object has no answer for is simply
    absent, which is how `fields_for` knows not to ask — see :func:`_present`.
    """
    if ref.what == "map":
        return mapedit.values(root, label), {}

    ctx = objedit.MapEdit(root, const)
    entry = ctx.entry(ref.handle.kind, ref.handle.index)
    said = {(t.owner, t.label): t for t in texts}

    if ref.what == "warp":
        y, x = entry.coords
        to = entry.macro == "warp_def"
        return ({"y": str(y), "x": str(x),
                 "b": entry.args[objedit.W_MAP] if to else "",
                 "bw": _num(entry.args[objedit.W_TO]) if to else "1"}, {})

    if ref.what == "trigger":
        y, x = entry.coords
        return ({"y": str(y), "x": str(x),
                 "script": entry.pointer or "(nothing)"}, {})

    if ref.what == "signpost":
        y, x = entry.coords
        values = {"y": str(y), "x": str(x), "facing": entry.arg(objedit.S_FACING)}
        return _with_prose(values, {}, "text", said, entry.pointer, entry.pointer)

    if ref.what == "prop":
        return _prop(ctx, entry), {}

    body = {"sprite": entry.sprite, "y": str(entry.y), "x": str(entry.x),
            "movement": entry.movement,
            "palette": objedit.palette_of(entry.args[objedit.PALETTE])}

    if ref.what == "trainer":
        owner = entry.pointer or ""
        _, macro = objedit.trainer_macro(ctx, owner)
        values = {**body, "cls": macro[1], "party": macro[2],
                  "flag": _flag(macro[0]),
                  "sight": _num(entry.args[objedit.PARAM])}
        boxes: dict[str, str] = {}
        # Three blocks, and two of them hang off *local* labels — `.defeated_text`
        # is the name of one per trainer on the map, so they are found by owner and
        # label together. By label alone you get somebody else's trainer.
        for field, block in (("after", owner), ("seen", macro[3]),
                             ("defeated", macro[4])):
            values, boxes = _with_prose(values, boxes, field, said, owner, block)
        return values, boxes

    values = {**body, "flag": _flag(entry.event_flag)}
    return _with_prose(values, {}, "text", said, entry.pointer, entry.pointer)


def _prop(ctx: objedit.MapEdit, entry) -> dict[str, str]:
    """Which of the six this is, and what it is holding. The kind is read off the
    engine's own discriminator rather than guessed from the row."""
    y, x = entry.coords
    where = {"y": str(y), "x": str(x)}
    if entry.macro == "signpost":
        flag, item = props.item_record(ctx, entry.pointer or "")
        return {**where, "kind": HIDDEN, "item": item, "flag": _flag(flag)}

    if (prop := entry.prop) is not None:
        # A rock keeps nothing but where it is and what colour it is. Everything
        # else on the line belongs to the engine — see `eventmodel.Entry.prop`,
        # which is also why this cannot be answered from the sprite alone.
        return {**where, "kind": prop,
                "palette": objedit.palette_of(entry.args[objedit.PALETTE])}

    kinds = {"PERSONTYPE_ITEMBALL": ITEMBALL, "PERSONTYPE_TMHMBALL": TMHM,
             "PERSONTYPE_FRUITTREE": TREE}
    kind = kinds.get(entry.persontype, ITEMBALL)
    if kind == TREE:
        return {**where, "kind": TREE, "tree": entry.args[objedit.POINTER]}
    if kind == TMHM:
        # The TM is in the slot an item ball keeps its count in. See `props`.
        return {**where, "kind": TMHM, "item": entry.args[objedit.PARAM],
                "flag": _flag(entry.event_flag)}
    return {**where, "kind": ITEMBALL, "item": entry.args[objedit.POINTER],
            "quantity": _num(entry.args[objedit.PARAM]),
            "flag": _flag(entry.event_flag)}


def _with_prose(values: dict[str, str], boxes: dict[str, str], field: str,
                said: dict[tuple[str, str], TextRef], owner: str | None,
                block: str | None) -> tuple[dict[str, str], dict[str, str]]:
    """Add a prose field — but only if there is prose. An object pointing at a
    script rather than a text block simply has none, and the form then does not
    offer to reword what is not there."""
    text = said.get((owner or "", block or ""))
    if text is None:
        return values, boxes
    return {**values, field: text.prose}, {**boxes, field: text.box}


def _num(arg: str) -> str:
    """A numeric argument as a decimal, for a box that asks for a number.

    The source may say `$06`; a form that showed you that would be asking you to
    know rgbasm to move a warp. Nothing is lost by showing 6 — `objedit.same()`
    knows the two are one number, so an untouched box writes the `$06` straight
    back. An argument that is not a number at all (a symbol) is shown as it is.
    """
    n = eh.as_int(arg)
    return str(n) if n is not None else arg.strip()


def _flag(name: str) -> str:
    """-1 is how the source says "always here". The form says it with an empty
    box, which is also how you ask for it back."""
    return "" if name in ("-1", "0") else name
