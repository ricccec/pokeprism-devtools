"""The things on a map that are not people: balls, trees, rocks, boulders.

They are all written as `person_event`s (bar one), because the engine has one list
of things that stand on tiles — not because anybody thinks a boulder is a person.
Calling them people is what the studio used to do, and it is why a boulder came
with a box asking what it says.

Two ideas, then, and they are the same idea. **A prop is a `person_event` with no
words**: a rock has no dialogue, no event flag and no script anybody wrote —
`smashrock` is a *std* id the engine supplies, shared by every rock in the game —
so its whole form is where it stands and what colour it is. And **a pickup is a
`person_event` whose last two arguments are read four different ways**:

    person_event …, PERSONTYPE_ITEMBALL,  6,       POTION,               EVENT_…
                                          ^quantity ^item

    person_event …, PERSONTYPE_TMHMBALL,  TM_HAIL, 0,                    EVENT_…
                                          ^item    ^dead

    person_event …, PERSONTYPE_FRUITTREE, 0,       GREY_APRICORN_TREE_1, -1
                                          ^dead    ^tree id             ^never a flag

    signpost      …, SIGNPOST_ITEM, HiddenNugget      ; -> dw EVENT_… / db NUGGET

The assembler cannot see any of this: every one of those slots takes a number, and
a TM written into an item ball's item slot assembles perfectly and hands the player
`0` of it, because `.itemball` reads the *quantity* out of the slot the TM is in.
That is the class of bug this module exists to make unwriteable — the form asks
what kind of prop you want and the shape follows from the answer, rather than the
other way round. Six kinds now, and the sixth was not a new mechanism: it was the
five-kind mechanism finally being pointed at the boulder.

`engine/events.asm`: `.itemball` at 513, `.tmhm` at 529, the fruit tree at 598, and
the hidden item's three-byte record at 682. The std scripts a rock and a boulder
run are `smashrock` and `strengthboulder` (`engine/std_scripts.asm`), and what
makes them props rather than people is written down in `hacks/prism/eventmodel.Prop`.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import consts, eventheader as eh
from ...wiring.editvocab import Change, EditError, palette_of, repainted, spliced
from .objedit import FLAG, PALETTE, PARAM, POINTER, S_FACING, MapEdit, X, Y
from .scaffold import (ALWAYS, INDENT, MapCtx, Object, Scaffold, ScaffoldError,
                       allocate_flag, camel, require)

_ITEM_MOVEMENT = "SPRITEMOVEDATA_ITEM_TREE"
_ITEM_SPRITE = "SPRITE_POKE_BALL"
_TREE_SPRITE = "SPRITE_FRUIT_TREE"


def add_itemball(root: Path, map_const: str, y: int, x: int, item: str, *,
                 quantity: int = 1, flag: str | None = None,
                 sprite: str = _ITEM_SPRITE,
                 palette: str = "PAL_OW_RED") -> Scaffold:
    """A Poké Ball on the ground, holding `quantity` of an item.

    The slot a person spends on sight range is read here as *how many*
    (`engine/events.asm:513-522` copies both bytes into `wCurItemBallContents`), so
    a 6 in it is six Potions, not a ball that notices you from six tiles away.
    """
    if quantity < 1:
        raise ScaffoldError(f"an item ball holds at least one of something, not {quantity}")

    obj = Object(sprite=sprite, y=y, x=x, movement=_ITEM_MOVEMENT, palette=palette)
    obj.check(root)
    require(root, "item", item, consts.names(root, consts.ITEMS))

    ctx = MapCtx(root, map_const)
    flag_name, flag_edit = allocate_flag(root, flag or ctx.flag_name(f"ITEM_{item}"))
    ctx.add_object(obj, "PERSONTYPE_ITEMBALL", quantity, item, flag_name)

    many = f"{quantity} " if quantity > 1 else ""
    return Scaffold(
        f"{many}{item} at ({y}, {x}) in {map_const}",
        [flag_edit, ctx.to_edit(f"{many}{item} itemball at ({y}, {x})")],
        flag_name,
    )


def add_tmhm_ball(root: Path, map_const: str, y: int, x: int, item: str, *,
                  flag: str | None = None, sprite: str = _ITEM_SPRITE,
                  palette: str = "PAL_OW_YELLOW") -> Scaffold:
    """A ball holding a TM or HM. Not an item ball with a TM in it.

    `.tmhm` reads *one* byte (`engine/events.asm:529-535`), out of the slot where an
    item ball keeps its quantity. So the item goes first and the second argument is
    a dead `0` — which is what every TM ball in the repo looks like.

    There is no quantity because a TM cannot be stacked, which is the same reason
    there is no quantity to get wrong.
    """
    obj = Object(sprite=sprite, y=y, x=x, movement=_ITEM_MOVEMENT, palette=palette)
    obj.check(root)
    # Against the TMs, not against the items: `TM_HAIL` is not in the item enum in
    # any form a scanner can see (see :func:`tmhms`), and checking it there would
    # reject every TM there is. Checking it *here* also rejects a Potion, which is
    # the other half of the point — a Potion in a TM ball assembles.
    require(root, "TM or HM", item, tmhms(root))

    ctx = MapCtx(root, map_const)
    flag_name, flag_edit = allocate_flag(root, flag or ctx.flag_name(f"ITEM_{item}"))
    ctx.add_object(obj, "PERSONTYPE_TMHMBALL", item, "0", flag_name)

    return Scaffold(
        f"{item} at ({y}, {x}) in {map_const}",
        [flag_edit, ctx.to_edit(f"{item} ball at ({y}, {x})")],
        flag_name,
    )


def add_fruit_tree(root: Path, map_const: str, y: int, x: int, tree: str, *,
                   sprite: str = _TREE_SPRITE,
                   palette: str = "PAL_OW_SILVER") -> Scaffold:
    """A tree you headbutt for apricorns or berries.

    The tree *is* a constant — `GREY_APRICORN_TREE_1` — and it sits in the pointer
    slot, where the engine reads it as an id rather than an address
    (`engine/events.asm:598-604`). The id says which fruit and when it regrows, so
    two trees sharing an id share a cooldown.

    **No event flag**, and that is not an omission. A tree is not picked up, it
    regrows; every fruit tree in the repo carries `-1` here, and giving one a flag
    would make the tree itself vanish the first time you shook it.
    """
    obj = Object(sprite=sprite, y=y, x=x, movement=_ITEM_MOVEMENT, palette=palette)
    obj.check(root)
    require(root, "fruit tree", tree, trees(root))

    ctx = MapCtx(root, map_const)
    ctx.add_object(obj, "PERSONTYPE_FRUITTREE", 0, tree, ALWAYS)

    return Scaffold(
        f"{tree} at ({y}, {x}) in {map_const}",
        [ctx.to_edit(f"{tree} at ({y}, {x})")],
    )


def add_prop(root: Path, map_const: str, y: int, x: int, kind: str, *,
             palette: str | None = None) -> Scaffold:
    """A rock or a boulder: the two objects whose every argument but two is fixed.

    Everything a form could ask about one of these is already decided, and decided
    by the engine rather than by taste. The movement is what makes a boulder pushable
    (`SPRITEMOVEDATA_STRENGTH_BOULDER`) and a rock smashable; the script is a std id
    the engine supplies and every one of them in the game shares; the event flag is
    `-1`, because a rock that remembered you had smashed it would be a rock that
    never came back after a reload. The repo agrees, and it did not have to: 23 of
    the 26 boulders and 23 of the 31 rocks are already exactly this line.

    So the form asks the two questions that are left. The other three are not
    *defaults* — they are not offered, because a boulder that walks like an NPC is
    not a boulder, and if you want one you want the map file, not this.
    """
    prop = eh.PROPS.get(kind)
    if prop is None:
        raise ScaffoldError(f"{kind!r} is not a prop — those are "
                            f"{', '.join(eh.PROPS)}")

    obj = Object(sprite=prop.sprite, y=y, x=x, movement=prop.movement,
                 palette=palette or prop.palette)
    obj.check(root)

    ctx = MapCtx(root, map_const)
    # `PERSONTYPE_JUMPSTD, 0, <std>, -1` — the 0 is the unused param slot and the
    # std goes where a person keeps the pointer to what they say. It is not a
    # pointer: the macro emits a `db`, and the engine looks the id up in its own
    # table. Which is the whole reason a rock cannot be given words.
    ctx.add_object(obj, "PERSONTYPE_JUMPSTD", 0, prop.script, ALWAYS)

    return Scaffold(f"{kind} at ({y}, {x}) in {map_const}",
                    [ctx.to_edit(f"{kind} at ({y}, {x})")])


def add_hidden_item(root: Path, map_const: str, y: int, x: int, item: str, *,
                    flag: str | None = None, label: str | None = None) -> Scaffold:
    """An item hidden in the scenery, found with the Itemfinder.

    The odd one out: a `signpost`, not a `person_event`, because there is nothing
    to draw. `SIGNPOST_ITEM` points at a three-byte record — the flag, then the
    item — which is why this one needs a label as well as a flag, and why it has no
    sprite for the form to ask about.
    """
    require(root, "item", item, consts.names(root, consts.ITEMS))
    ctx = MapCtx(root, map_const)
    label = label or ctx.unique_label(camel(item))
    flag_name, flag_edit = allocate_flag(root, flag or ctx.flag_name(f"HIDDENITEM_{item}"))

    ctx.add_script(label, [f"{label}:", f"{INDENT}dw {flag_name}", f"{INDENT}db {item}"])
    ctx.add_bg_event([str(y), str(x), "SIGNPOST_ITEM", label])

    return Scaffold(
        f"hidden {item} at ({y}, {x}) in {map_const}",
        [flag_edit, ctx.to_edit(f"hidden {item} at ({y}, {x})")],
        flag_name, label,
    )


def trees(root: Path) -> frozenset[str]:
    """The fruit-tree ids. They live in the map constants, in a counter of their
    own that restarts at 1 — `RED_APRICORN_TREE_1` and its ten colours, twice
    over, plus the berry trees."""
    return frozenset(n for n in consts.names(root, consts.MAP)
                     if re.search(r"_TREE_\d+$", n))


#: `add_tm HAIL` — which is where `TM_HAIL` comes from, and the reason a plain
#: scan of the item constants cannot find it.
_ADD_TM_RE = re.compile(r"^\s*add_(tm|hm)\s+(\w+)")


def tmhms(root: Path) -> frozenset[str]:
    """Every TM and HM.

    They are not in the item enum in any form you can grep for. `constants/
    item_constants.asm` says `add_tm HAIL`, and the macro (`macros/basestats.asm`)
    builds the name at assembly time out of a string paste:

        define_s _\\@_1, "TM_\\1"
        const _\\@_1

    So `TM_HAIL` never appears in the source as a token, and the only `TM_*` names
    a constant-scanner finds are `TM_CASE` (the bag) and `TM_HM` (the pocket) —
    neither of which is a TM. Reconstruct them from the macro instead, or the form
    offers you two wrong answers and the validator rejects all 99 right ones.
    """
    path = root / consts.ITEMS
    if not path.exists():
        return frozenset()
    return frozenset(
        f"{m.group(1).upper()}_{m.group(2)}"
        for line in path.read_text().split("\n")
        if (m := _ADD_TM_RE.match(line))
    )


# --------------------------------------------------------------------------- #
# editing one that is already there                                           #
# --------------------------------------------------------------------------- #
#
# The kind is not editable and these four functions are why. An item ball and a
# hidden item are not two settings of one thing — one is a `person_event` and the
# other is a `signpost`, in different lists, and turning one into the other is a
# delete and an add wearing a dropdown. What *is* editable is everything inside a
# kind, and each kind reads those two bytes its own way. See the module docstring.

def edit_itemball(root: Path, map_const: str, index: int, y: int, x: int, item: str,
                  *, quantity: int = 1, flag: str | None = None) -> Change:
    require(root, "item", item, consts.names(root, consts.ITEMS))
    return _edit_ball(root, map_const, index, y, x, {PARAM: quantity, POINTER: item},
                      flag, f"{quantity}x {item}" if quantity != 1 else f"{item} ball",
                      f"{item} ball at ({y}, {x})")


def edit_tmhm_ball(root: Path, map_const: str, index: int, y: int, x: int, item: str,
                   *, flag: str | None = None) -> Change:
    require(root, "TM or HM", item, tmhms(root))
    # The TM goes in the slot an item ball keeps its *count* in. The count slot is
    # then spare, and a new one is written 0 — but it is not ours, so we leave it.
    # One TM ball on Route74 keeps `ObjectEvent` there, and rewriting that to 0
    # because we assumed we knew what belonged in a slot nobody asked us about is
    # exactly the edit this module exists not to make.
    return _edit_ball(root, map_const, index, y, x, {PARAM: item}, flag,
                      f"{item} ball", f"{item} ball at ({y}, {x})")


def edit_prop(root: Path, map_const: str, index: int, y: int, x: int, kind: str,
              *, palette: str) -> Change:
    """Move a rock, or repaint it. Nothing else about one is editable.

    Not even the movement — and *especially* not the movement, because eleven of
    the rocks in this repo carry `SPRITEMOVEDATA_00` or `..._ITEM_TREE` instead of
    `..._SMASHABLE_ROCK` and still run `smashrock`. Whatever those eleven are, they
    are what somebody wrote, and an edit form that "corrected" them on the way past
    would be changing the behaviour of a rock you opened in order to move it one
    tile to the left. New ones get the canonical line (:func:`add_prop`); old ones
    get moved.
    """
    if kind not in eh.PROPS:
        raise EditError(f"{kind!r} is not a prop — those are {', '.join(eh.PROPS)}")
    ctx = MapEdit(root, map_const)
    entry = ctx.entry(eh.ListKind.OBJECT_EVENTS, index)
    if entry.prop != kind:
        raise EditError(f"the object at #{index} is not a {kind} — a prop is named by "
                        f"its sprite, its persontype and the std script it runs, and "
                        f"this one does not have all three")
    # Only if it moved — you are not required to fix what you did not touch, and
    # a few of these carry a bare number where a palette name should be.
    if palette != palette_of(entry.args[PALETTE]):
        require(root, "palette", palette,
                consts.with_prefix(root, consts.SPRITES, "PAL_OW_"))
    ctx.replace_entry(eh.ListKind.OBJECT_EVENTS, index, spliced(entry, {
        Y: y, X: x, PALETTE: repainted(entry.args[PALETTE], palette)}))
    return ctx.done(f"{kind} at ({y}, {x}) in {map_const}", f"{kind} at ({y}, {x})")


def edit_fruit_tree(root: Path, map_const: str, index: int, y: int, x: int,
                    tree: str) -> Change:
    # No flag, on purpose: a tree regrows. See `add_fruit_tree`.
    require(root, "fruit tree", tree, trees(root))
    return _edit_ball(root, map_const, index, y, x, {POINTER: tree}, None,
                      tree, f"{tree} at ({y}, {x})")


def edit_hidden_item(root: Path, map_const: str, index: int, y: int, x: int,
                     item: str, *, flag: str | None = None) -> Change:
    """A hidden item: a `signpost`, and the three-byte record it points at.

    The item and the flag are not on the entry line at all — they are the `dw` and
    the `db` of the record. Which is the whole reason this kind is its own shape,
    and why the entry line here carries only a position.
    """
    require(root, "item", item, consts.names(root, consts.ITEMS))
    ctx = MapEdit(root, map_const)
    entry = ctx.entry(eh.ListKind.BG_EVENTS, index)
    pointer = entry.pointer
    if entry.arg(S_FACING) != "SIGNPOST_ITEM" or not pointer:
        raise EditError("that is not a hidden item — it points at no item record")

    was, _ = item_record(ctx, pointer)
    _set_record(ctx, pointer, ctx.flag(flag or was, was), item)

    entry = ctx.entry(eh.ListKind.BG_EVENTS, index)
    ctx.replace_entry(eh.ListKind.BG_EVENTS, index, spliced(entry, {0: y, 1: x}))
    return ctx.done(f"hidden {item} at ({y}, {x}) in {map_const}",
                    f"hidden {item} at ({y}, {x})")


def _edit_ball(root: Path, map_const: str, index: int, y: int, x: int,
               args: dict[int, object], flag: str | None,
               what: str, detail: str) -> Change:
    """The three pickups that are a `person_event`. The sprite and the movement
    are left out: they follow from the kind, and the kind cannot change."""
    ctx = MapEdit(root, map_const)
    entry = ctx.entry(eh.ListKind.OBJECT_EVENTS, index)
    changed: dict[int, object] = {Y: y, X: x, **args}
    if flag is not None:
        changed[FLAG] = ctx.flag(flag, entry.event_flag)
    ctx.replace_entry(eh.ListKind.OBJECT_EVENTS, index, spliced(entry, changed))
    return ctx.done(f"{what} at ({y}, {x}) in {map_const}", detail)


def item_record(ctx: MapEdit, label: str) -> tuple[str, str]:
    """The (flag, item) a hidden item's three-byte record holds. The read side of
    :func:`_set_record`, and what the edit form opens with."""
    flag = item = ""
    for i in ctx.block(label):
        if m := _DW_RE.match(ctx.lines[i]):
            flag = m.group("arg")
        elif m := _DB_RE.match(ctx.lines[i]):
            item = m.group("arg")
    if not flag or not item:
        raise EditError(f"{label} is not an item record — it wants a `dw` and a `db`")
    return flag, item


def _set_record(ctx: MapEdit, label: str, flag: str, item: str) -> None:
    span = ctx.block(label)
    dw = next((i for i in span if _DW_RE.match(ctx.lines[i])), None)
    db = next((i for i in span if _DB_RE.match(ctx.lines[i])), None)
    if dw is None or db is None:
        raise EditError(f"{label} is not an item record — it wants a `dw` and a `db`")
    ctx.lines[dw] = f"{INDENT}dw {flag}"
    ctx.lines[db] = f"{INDENT}db {item}"


_DW_RE = re.compile(r"^(?P<head>\s*dw\s+)(?P<arg>\S+)(?P<tail>.*)$")
_DB_RE = re.compile(r"^(?P<head>\s*db\s+)(?P<arg>\S+)(?P<tail>.*)$")
