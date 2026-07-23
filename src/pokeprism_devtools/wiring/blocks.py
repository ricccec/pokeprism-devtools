"""The block an entry line points at, and the names it is reached by.

An `object_event` is the small half of adding an item ball. The other half is
two lines somewhere else in the same file::

    Route29Potion:
        itemball POTION

and a name in three places that must agree with each other: the label the entry
line points at, the `const` that gives the object its ordinal, and the event
flag that remembers the ball was picked up. This module mints those three names
and formats the block. It does not splice — `regions.append` does that — and it
does not know what an item ball is beyond how one is spelled.

**Every rule here was measured against all 178 vanilla item balls, and the
reason to measure rather than reason is that two of the three name shapes have
an irregularity a sensible guess gets wrong.**

*The label* is `<map file stem><item, camel-cased>` — `Route29Potion`,
`BurnedTowerB1FTMEndure`. 178 of 178, exactly. But :func:`camel` cannot just
title-case the underscore-separated parts, because `HP_UP` is `HPUp` and not
`HpUp`, and `TM_ENDURE` is `TMEndure` and not `TmEndure`. Four short words stay
uppercase and the rest are capitalised; the count drops below 178 if any of the
four is left out, which is how the set was found and how it stays honest.

*The const* is prefixed with the **map file's stem, upper-cased** — `Route29`
gives `ROUTE29_POKE_BALL` — and not with the map constant, which for that same
map is `ROUTE_29`. The two differ by an underscore in exactly the maps whose
names end in a number, which is most of the routes. 1466 of the 1466 object
consts in the tree are stem-prefixed; the first version of this module used the
map constant, and the symptom was not an error. It was a `ROUTE_29_POKE_BALL`
sitting under the `ROUTE29_POKE_BALL` already there, past a uniqueness check
that had compared against the wrong name and found no clash — the second ball
on the map declared as if it were the first. Found by reading a generated diff.

Then `_POKE_BALL2` and up, with the first one **unnumbered**: 33 maps have a
bare `POKE_BALL`, and the maps with several start at `POKE_BALL1`. So the
convention for a map that already has one ball would be to renumber its bare
const to `POKE_BALL1` and add `POKE_BALL2`. :func:`object_const` does not do
that. The const is the name every script on that map addresses the object by —
`disappear ROUTE29_POKE_BALL` — so renumbering to satisfy a naming habit would
rewrite identifiers across the repo to make one new ball look tidy. It takes
the first free name instead and leaves what is there alone.

*The flag* is `EVENT_<MAP>_<ITEM>`, which is 161 of 178. The other 17 are the
Ruins of Alph item rooms, named for the story (`EVENT_PICKED_UP_GOLD_BERRY_
FROM_HO_OH_ITEM_ROOM`) rather than for the pickup. So this is a default and not
a rule, and the form leaves the box editable.
"""

from __future__ import annotations

import re

INDENT = "\t"

#: A label at column zero — what `unique_label` must not collide with. Local
#: labels (`.AfterScript`) are namespaced under the block above them and are
#: deliberately not collected: two blocks may each have a `.Done`.
_LABEL = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):")

#: Words that stay upper-case through :func:`camel`. Not a style choice — with
#: any one of them removed, the measured label rule stops reproducing all 178
#: vanilla item-ball labels. `HP_UP` is `HPUp`; `PP_UP` is `PPUp`; every TM and
#: HM is `TMSnore`, `HMWaterfall`.
ACRONYMS = frozenset({"TM", "HM", "HP", "PP"})


class BlockError(RuntimeError):
    """A block cannot be written under a name that is safe to write it under."""


def camel(name: str) -> str:
    """`HYPER_POTION` -> `HyperPotion`, `HP_UP` -> `HPUp`.

    The acronym set is what makes this reproduce the tree rather than merely
    resemble it — see :data:`ACRONYMS`.
    """
    return "".join(p if p in ACRONYMS else p.capitalize()
                   for p in name.split("_") if p)


def plain_camel(name: str) -> str:
    """`FULL_HEAL` -> `FullHeal`, `PP_UP` -> `PpUp` — title-case, acronyms and all.

    The sibling of :func:`camel`, and it exists because the two disagree in the
    tree. An item ball's label writes `PP_UP` as `PPUp` (see :data:`ACRONYMS`),
    but a hidden item's label writes the same item `PpUp` — `CeladonCityHiddenPpUp`
    and `Route45HiddenPpUp`, the only two acronym items among the hidden-item
    labels, and both plain. So a hidden item cannot borrow :func:`camel`: reusing
    it would spell a `PPUp` that no `hiddenitem` block in the tree contains. Two
    features, written by different hands, that never agreed on the casing — and
    the label rule for each is measured against its own, not reasoned from one.
    """
    return "".join(p.capitalize() for p in name.split("_") if p)


def labels(text: str) -> set[str]:
    """Every top-level label in one file."""
    return {m.group(1) for line in text.split("\n") if (m := _LABEL.match(line))}


def unique_label(text: str, wanted: str) -> str:
    """`wanted`, or `wanted2`, `wanted3`… — the first not already in the file.

    Two item balls holding the same item on the same map is not a mistake, and
    it is not rare: Route 45 has four, and the Ruins of Alph item rooms are
    nothing but repeats. The collision this suffix avoids is real and silent in
    the other direction — rgbds takes the *second* definition of a label as a
    redefinition error, so a duplicate would at least fail the build, but it
    would fail it in a file the user did not think they had broken.
    """
    if not _LABEL.match(f"{wanted}:"):
        raise BlockError(f"{wanted!r} is not a label a block can be given")
    taken = labels(text)
    if wanted not in taken:
        return wanted
    return next(f"{wanted}{n}" for n in range(2, len(taken) + 3)
                if f"{wanted}{n}" not in taken)


def object_const(existing: list[str], label: str, what: str) -> str:
    """The `object_const_def` name for a new object: `<LABEL>_<WHAT>`, then
    `<LABEL>_<WHAT>2` and up.

    `label` is the map file's stem — `Route29`, not `ROUTE_29`. Passing the map
    *constant* here is the mistake this function's docstring in the module
    header describes, and it is a mistake with no error attached: it produces a
    name that is unique because it is wrong.

    Takes the names already declared rather than reading them, so the caller
    that already parsed the block does not parse it twice — and so the number
    this picks is checked against what is really in the file, not against how
    many balls the map is thought to have.
    """
    taken = set(existing)
    base = f"{label.upper()}_{what}"

    # "The first name not taken" is not the rule, and Elm's Lab is why: it
    # declares POKE_BALL1, POKE_BALL2 and POKE_BALL3 and no bare POKE_BALL, so
    # the unnumbered name is free and picking it puts a fourth ball at the head
    # of a series it belongs at the end of. The unnumbered name means "the only
    # one" — it is available only when there is no series at all.
    used = {1} if base in taken else set()
    used |= {int(n.removeprefix(base)) for n in taken
             if n.startswith(base) and n.removeprefix(base).isdigit()}
    if not used:
        return base
    return next(f"{base}{n}" for n in range(2, max(used) + 2)
                if n not in used)


def flag_name(map_const: str, item: str, taken: set[str] = frozenset()) -> str:
    """`EVENT_ROUTE_29_POTION`, or `…_POTION_2` if that is spoken for.

    A default the form may overwrite — 17 of the 178 real ones are named for a
    story beat instead. See the module docstring.

    The suffix exists because the default collides in exactly one situation:
    the map already has a ball holding this item. No vanilla map does, so the
    tree offers no precedent — but the semantics are not in doubt. The flag is
    what the engine checks to decide whether to draw the ball at all, so two
    balls sharing one would vanish together the moment either was picked up,
    and the second would never be collectable. A caller that *asks* for an
    existing flag by name gets it; a caller that merely did not type one must
    not be handed that quietly.
    """
    base = f"EVENT_{map_const}_{item}"
    if base not in taken:
        return base
    return next(f"{base}_{n}" for n in range(2, len(taken) + 3)
                if f"{base}_{n}" not in taken)


def itemball(label: str, item: str, quantity: int = 1) -> list[str]:
    """The whole block a `OBJECTTYPE_ITEMBALL` object points at.

    Two lines, and 178 of the 178 in the tree are exactly this shape — a label
    and one `itemball`, with nothing before it and nothing after it. There is
    no script here to run and no text to say, which is why the item ball is the
    block worth crossing the seam first: everything hard about it is the three
    names, and the body is a macro call.

    The quantity is written only when it is not one. `macros/scripts/maps.asm`
    makes `itemball POTION` expand to `itemball POTION, 1`, so the two spell
    the same two bytes — and no item ball in the tree writes the second
    argument, so writing `, 1` on every new one would make every ball this tool
    adds visibly not match the 178 beside it.
    """
    if quantity < 1:
        raise BlockError(
            f"an item ball holds at least one of something, not {quantity}")
    if quantity > 99:
        # The macro emits the count as one byte and the engine hands it to the
        # bag, which caps a stack at 99. A larger number assembles.
        raise BlockError(
            f"{quantity} is more than a bag slot holds — the count is one byte "
            "and the bag caps a stack at 99")
    args = item if quantity == 1 else f"{item}, {quantity}"
    return [f"{label}:", f"{INDENT}itemball {args}"]


def fruittree(label: str, tree_id: str) -> list[str]:
    """The whole block a fruit-tree object points at: a label and one
    `fruittree` naming the tree's id.

    Two lines, exactly like an item ball, and for the same reason it is worth
    crossing the seam early — the body is a macro call and everything hard is in
    the names. The one difference is where the hard part lives: an item ball's
    three names are all in the map file, but a fruit tree's `tree_id` is a
    `FRUITTREE_` constant that indexes a table in a *different* file, so this
    formatter only spells the reference and `wiring/fruittrees.py` owns making
    the reference resolve.
    """
    return [f"{label}:", f"{INDENT}fruittree {tree_id}"]


def dialogue_body(pages: list[list[str]]) -> list[str]:
    """Dialogue as the family's text engine reads it: `text` opens the first
    box, `line` is its second row and `cont` each row after, `para` opens a
    fresh box, and `done` ends the whole thing.

    The family opener is `text` where prism's is `ctxt` — the one thing that
    keeps this from being `scaffold._text_body`, and the reason a trainer block
    cannot borrow prism's dialogue formatter. A blank line is written before
    each fresh `para` box the way both family trees space their paragraphs.
    """
    if not pages or not any(pages):
        raise BlockError("a trainer with nothing to say — dialogue needs a line")
    out: list[str] = []
    for p, lines in enumerate(pages):
        if not lines:
            raise BlockError("a textbox with no lines in it")
        for i, line in enumerate(lines):
            if '"' in line:
                # rgbasm ends the string at the first unescaped quote, so a line
                # carrying one would spill into the next argument and the map
                # would not assemble. Refuse it here rather than write it.
                raise BlockError(
                    f"{line!r} has a double-quote in it, which would close the "
                    "string early — the map would not assemble")
            if p > 0 and i == 0:
                out.append("")
            macro = ("text" if p == 0 else "para") if i == 0 else \
                    ("line" if i == 1 else "cont")
            out.append(f'{INDENT}{macro} "{line}"')
    out.append(f"{INDENT}done")
    return out


def trainer_block(label: str, cls: str, party: str, flag: str, *,
                  seen_label: str, defeated_label: str, after_label: str,
                  seen: list[list[str]], defeated: list[list[str]],
                  after: list[list[str]]) -> list[str]:
    """The whole of a vanilla `OBJECTTYPE_TRAINER` block, the native way.

    333 of 333 pokecrystal trainers name their seen and beaten texts as
    **global** labels and hang a local `.AfterScript` off the seventh macro
    argument, whose 291-of-331 body is the six-line post-battle one-liner below.
    Emitting local `.SeenText` labels instead — the shape polished uses — would
    make every trainer this writes the first of its kind in the tree, the same
    "visibly not one of the 333" tell the item ball's `, 1` and the `PPUp`
    casing exist to avoid. So the three texts are global blocks the caller has
    minted unique names for, and this formats them beside the script.

    The loss text (the macro's sixth argument, shown when the *player* loses) is
    `0` in all 333 — the engine has a default — and the family form does not ask
    for one, so it is written literally.
    """
    return [
        f"{label}:",
        f"{INDENT}trainer {cls}, {party}, {flag}, {seen_label}, "
        f"{defeated_label}, 0, .AfterScript",
        "",
        ".AfterScript:",
        f"{INDENT}endifjustbattled",
        f"{INDENT}opentext",
        f"{INDENT}writetext {after_label}",
        f"{INDENT}waitbutton",
        f"{INDENT}closetext",
        f"{INDENT}end",
        "",
        f"{seen_label}:", *dialogue_body(seen),
        "",
        f"{defeated_label}:", *dialogue_body(defeated),
        "",
        f"{after_label}:", *dialogue_body(after),
    ]


def generictrainer_block(label: str, cls: str, party: str, flag: str, *,
                         seen: list[list[str]], defeated: list[list[str]],
                         after: list[list[str]]) -> list[str]:
    """The whole of a polished `OBJECTTYPE_GENERICTRAINER` block, self-contained.

    The shape 593 of 593 polished generic trainers take, and the one prism's
    `scaffold._trainer_block` renders identically: the macro names two local
    texts, the talk-again text falls through directly beneath it, and the seen
    and beaten texts follow as local labels. Polished genuinely writes local
    labels here (190 of the 593), so unlike vanilla the self-contained block is
    a shape already in its tree — which is why the two dialects fork rather than
    sharing one formatter.
    """
    return [
        f"{label}:",
        f"{INDENT}generictrainer {cls}, {party}, {flag}, .SeenText, .BeatenText",
        "",
        *dialogue_body(after),
        "",
        ".SeenText:", *dialogue_body(seen),
        "",
        ".BeatenText:", *dialogue_body(defeated),
    ]


def hiddenitem(label: str, item: str, flag: str) -> list[str]:
    """The whole block a `BGEVENT_ITEM` sign points at: a label and one
    `hiddenitem` naming the item and the flag that remembers it was taken.

    Two lines, like an item ball — but the flag lives *here*, in the block, and
    not on the entry line the way a ball's does. A ball is an `object_event`
    whose last argument is its flag; a hidden item is a `bg_event` with no flag
    column of its own, so the byte that gates it sits inside `hiddenitem`
    instead. That is why this adder allocates a flag like the item ball does yet
    writes it into the body rather than the line.

    The argument order is the whole reason a round-trip guards this writer. The
    macro is `dwb \\2, \\1` — flag word then item byte, the two *transposed* on
    the way to the ROM — but the source line is `hiddenitem ITEM, FLAG`,
    item first. Copying the byte order into the source would write
    `hiddenitem FLAG, ITEM` on every one, which assembles (both are constants)
    and hands the engine an item id where the flag belongs. 85 lines in the tree
    are `item, flag`; this writes the 86th the same way.
    """
    return [f"{label}:", f"{INDENT}hiddenitem {item}, {flag}"]
