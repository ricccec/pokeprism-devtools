"""Polished's convenience object macros, expanded to the ``object_event`` each
one assembles into.

`macros/scripts/maps.asm` defines ten shorthands that stand in for an
``object_event`` — three item-ball kinds, a fruit tree, a cuttable tree, the two
boulder kinds, a wild Pokémon, a Poké Center nurse and a mart clerk. Each is one
line the assembler pastes a full ``object_event`` in place of, so the ROM has one
more object than the source has ``object_event`` lines. Vanilla writes none of
them; polished writes 657 across the tree, and two readers went blind to every
one: :func:`..vanilla.events.parse` collected only the four ``def_*`` macros, and
:func:`..vanilla.eventblock._entries_after` learned to *skip* the shorthands so
its object count still matched the first reader's. Both agreed — on a count that
was wrong by 657.

This module is the vocabulary that opens that eye. ``SHORTHANDS[macro](args)``
turns a shorthand's own arguments into the ``object_event`` argument list it
expands to, in polished's twelve/thirteen-column layout, so
:func:`..events.tables` classifies and places the object exactly as if it had
been written out long. Every expansion here is *transcribed* from the macro body
it mirrors — checkable against `maps.asm` slot for slot — rather than reasoned
about, because a plausible-looking guess at one column is the failure the whole
seam is organised against, and these lines feed the same classifier the long
form does.

The variadic macros (``fruittree_event``, the two boulders, ``pokemon_event``)
choose a form by argument count exactly as the ``if _NARG ==`` in the macro does.
The arithmetic columns a shorthand computes (``\\3 - 1``, ``(1 << \\6)``) are
emitted as the literal expression the source would: the reader reads none of
those slots, but writing the true expression keeps the transcription honest and
auditable against the macro.
"""

from __future__ import annotations

from typing import Callable

Expand = Callable[[list[str]], list[str]]


def _ball(palette: str, playerevent: str) -> Expand:
    """The three item balls differ only in palette and PLAYEREVENT_*: a red
    ordinary ball with a quantity, a green key item and a yellow TM/HM without
    one — the last two assert four args (no count), the first takes five."""
    def expand(a: list[str]) -> list[str]:
        # a: x, y, item, [quantity,] flag
        out = [a[0], a[1], "SPRITE_BALL_CUT_TREE", "SPRITEMOVEDATA_STANDING_DOWN",
               "0", "0", "-1", palette, "OBJECTTYPE_ITEMBALL", playerevent]
        out.extend(a[2:])
        return out
    return expand


def _cuttree(a: list[str]) -> list[str]:
    # a: x, y, flag
    return [a[0], a[1], "SPRITE_BALL_CUT_TREE", "SPRITEMOVEDATA_CUTTABLE_TREE",
            "0", "0", "-1", "0", "OBJECTTYPE_COMMAND", "jumpstd", "cuttree", a[2]]


def _fruittree(a: list[str]) -> list[str]:
    # a: x, y, tree, item, palette[, bit, flag]
    if len(a) == 5:
        return [a[0], a[1], "SPRITE_BLANK_FRUIT", "SPRITEMOVEDATA_FRUIT",
                "0", f"{a[2]} - 1", "-1", a[4], "OBJECTTYPE_COMMAND",
                "fruittree", a[2], a[3], "-1"]
    return [a[0], a[1], "SPRITE_BLANK_FRUIT", "SPRITEMOVEDATA_FRUIT",
            "0", f"{a[2]} - 1", f"(1 << {a[5]})", a[4], "OBJECTTYPE_COMMAND",
            "fruittree", a[2], a[3], a[6]]


def _boulder(movement: str, command: str) -> Expand:
    """Strength and smash boulders share a sprite and a `jumpstd` command,
    differing in movement, command and — the reason they are one helper — the
    optional trailing flag that defaults to ``-1`` when absent. Smash carries an
    extra ``0`` column the strength boulder does not."""
    tail = ["0"] if command == "smashrock" else []

    def expand(a: list[str]) -> list[str]:
        # a: x, y[, flag]
        flag = a[2] if len(a) == 3 else "-1"
        return [a[0], a[1], "SPRITE_BOULDER_ROCK", movement, "0", "0", "-1", "0",
                "OBJECTTYPE_COMMAND", "jumpstd", command, *tail, flag]
    return expand


def _pokemon(a: list[str]) -> list[str]:
    # a: x, y, level, movement, palette, time, script, flag  (formless, 8 args)
    #    x, y, level, form, movement, palette, time, script, flag  (formed, 9)
    if len(a) == 8:
        return [a[0], a[1], "SPRITE_MON_ICON", a[3], "0", a[2], a[4], a[5],
                "OBJECTTYPE_POKEMON", "NO_FORM", a[6], a[7]]
    return [a[0], a[1], "SPRITE_MON_ICON", a[4], "0", a[2], a[5], a[6],
            "OBJECTTYPE_POKEMON", a[3], a[7], a[8]]


def _pc_nurse(a: list[str]) -> list[str]:
    # a: x, y
    return [a[0], a[1], "SPRITE_BOWING_NURSE", "SPRITEMOVEDATA_STANDING_DOWN",
            "0", "0", "-1", "0", "OBJECTTYPE_COMMAND", "jumpstd",
            "pokecenternurse", "-1"]


def _mart_clerk(a: list[str]) -> list[str]:
    # a: x, y, mart, dialog
    return [a[0], a[1], "SPRITE_CLERK", "SPRITEMOVEDATA_STANDING_RIGHT",
            "0", "0", "-1", "0", "OBJECTTYPE_COMMAND", "pokemart", a[2], a[3], "-1"]


#: Macro name -> the expander that turns its args into an ``object_event``'s.
#: These are the ten words :func:`..events.tables` must count as objects; the
#: keys are also the set :func:`..vanilla.eventblock._entries_after` recognises
#: as object entries rather than block-enders.
SHORTHANDS: dict[str, Expand] = {
    "itemball_event": _ball("PAL_NPC_ENV_RED", "PLAYEREVENT_ITEMBALL"),
    "keyitemball_event": _ball("PAL_NPC_ENV_GREEN", "PLAYEREVENT_KEYITEMBALL"),
    "tmhmball_event": _ball("PAL_NPC_ENV_YELLOW", "PLAYEREVENT_TMHMBALL"),
    "cuttree_event": _cuttree,
    "fruittree_event": _fruittree,
    "strengthboulder_event": _boulder("SPRITEMOVEDATA_STRENGTH_BOULDER",
                                      "strengthboulder"),
    "smashrock_event": _boulder("SPRITEMOVEDATA_SMASHABLE_ROCK", "smashrock"),
    "pokemon_event": _pokemon,
    "pc_nurse_event": _pc_nurse,
    "mart_clerk_event": _mart_clerk,
}
