"""How wide a line of dialogue actually is, and what box it has to fit in.

Three things have to be true at once for a line of text to be safe, and none of
them is checkable by eye:

**The text engine is fixed-width.** ``_PlaceString`` (home/text.asm) does
``ld [hli], a`` — one 8x8 tile per byte, no kerning. So a "line" is a count of
charmap tokens, not of pixels and not of Python characters. (pokeprism *has* a
proportional font — engine/vwf.asm — but nothing in the dialogue path calls it.
It draws the trainer card, the treasure bag, the intro and the landmark signs.
Measuring dialogue with it would be measuring the wrong engine.)

**Control codes expand.** ``#`` is one byte in the source and prints ``Poké`` —
four tiles. So ``"#mon Center near"`` is sixteen characters, and nineteen tiles,
and one tile too wide for the box. That is a real bug in Route77Pokecenter, and
it is invisible unless you expand. The expansions are read out of home/text.asm
(the jumptable's comments name the token, ``print_name`` names the buffer, and
the buffer is a ``db "…@"``), never reproduced here: a fork that redefines
``<TRNER>`` gets the new width for free.

**There are two boxes, and which one you're in isn't a property of the text.**
NPC dialogue lands in the speech box: 18 columns, two rows. A signpost gets a
full-screen window: 17 columns, rows 7 to 16, because its body starts at
``hlcoord 2, 7`` (engine/signpost.asm). The corpus confirms the split cleanly —
``line``/``para``/``cont`` appear *only* in speech text and ``next``/``nl``
*only* in sign text, 453 maps, no exceptions. Lint sign text against the speech
box and you invent a hundred findings; lint it against nothing and you miss the
real ones.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from . import charmap

_TEXT_ASM = "home/text.asm"
_SIGNPOST_ASM = "engine/signpost.asm"
_TEXT_MACROS = "macros/text.asm"
_MISC = "constants/misc_constants.asm"

# --- what a control code does to the cursor --------------------------------- #
# Read off TextControlCodeJumptable's handlers (home/text.asm). These are engine
# semantics, not text that can be parsed: `LineChar` does an *absolute*
# `hlcoord TEXTBOX_INNERX, TEXTBOX_INNERY + 2`, while `NextLineChar` does a
# *relative* `add hl, SCREEN_WIDTH * 2` from wherever the last line began. They
# are not interchangeable, and the difference is the whole reason `next` is safe
# in a tall signpost and would walk off the bottom of a speech box.
LINE_ABS = "line"        # <LINE>    -> the box's second row, absolutely
DOWN_2 = "down2"         # <NEXT>    -> two rows below the last line's start
DOWN_1 = "down1"         # <LNBRK>   -> one row below it
SCROLL = "scroll"        # <CONT>, <SCROLL> -> scroll up; the last row is free again
NEW_BOX = "newbox"       # <PARA>    -> clear the box, back to the first row
END = "end"              # <DONE>, <SDONE>, <PROMPT>, @

_ACTIONS = {
    "<LINE>": LINE_ABS, "<NEXT>": DOWN_2, "<LNBRK>": DOWN_1,
    "<CONT>": SCROLL, "<SCROLL>": SCROLL, "<PARA>": NEW_BOX,
    "<DONE>": END, "<SDONE>": END, "<PROMPT>": END, "@": END,
}

#: WRAM buffer -> the constant bounding what can be in it. The engine can only
#: tell us a buffer is variable; how long its *content* can get is semantic, so
#: the mapping is declared and the numbers are read from source.
#: wMonOrItemNameBuffer holds a species name (11) or an item name (13) — the
#: longer one is the bound.
_BUFFER_BOUNDS = {
    "wPlayerName": "PLAYER_NAME_LENGTH",
    "wRivalName": "PLAYER_NAME_LENGTH",
    "wEnemyMonNick": "PKMN_NAME_LENGTH",
    "wBattleMonNick": "PKMN_NAME_LENGTH",
    "wMonOrItemNameBuffer": "ITEM_NAME_LENGTH",
}

#: The general-purpose buffers. Whatever a script last put there — a score, a
#: number, a name — so there is no bound to be had from the text, and pretending
#: otherwise turns `"Rounds won:   <STRBF3>"` into a 26-tile overflow that never
#: happens. They are excluded from the width, and reported separately.
UNBOUNDED = ("wStringBuffer1", "wStringBuffer2", "wStringBuffer3", "wStringBuffer4")

_EQU_RE = re.compile(r"^\s*(\w+)\s+EQU\s+(.+?)\s*(?:;.*)?$")
_JUMP_RE = re.compile(r'^\s*dw\s+(\w+)\s*;\s*"(.*)"\s*$')
_PRINT_NAME_RE = re.compile(r"^(\w+):+\s*print_name\s+(\w+)\s*(?:;.*)?$")
_ROM_STR_RE = re.compile(r'^(\w+)::?\s+db\s+"((?:[^"\\]|\\.)*)"')
_HLCOORD_RE = re.compile(r"^\s*hlcoord\s+(\d+)\s*,\s*(\d+)")
_MACRO_EQUS_RE = re.compile(r'^(\w+)\s+EQUS\s+"dtxt\s+\\"(<\w+>)\\"')


@dataclass(frozen=True)
class Box:
    """A place text gets drawn, and the shape of it."""
    name: str
    cols: int            # tiles per line
    first_row: int       # where `text`/`ctxt`/`para` start
    last_row: int        # the last row inside the border
    second_row: int      # where <LINE> lands, absolutely

    def rows_for(self, action: str, row: int) -> int:
        if action == LINE_ABS:
            return self.second_row
        if action == DOWN_2:
            return row + 2
        if action == DOWN_1:
            return row + 1
        if action == NEW_BOX:
            return self.first_row
        return row


@dataclass(frozen=True)
class Metrics:
    """Every token's cost in tiles, and what the control codes do."""
    #: token -> tiles it prints. Literals are 1; `#` is 4.
    width: dict[str, int]
    #: token -> the most tiles its buffer can print (`<PLAYER>` -> 7).
    bound: dict[str, int]
    #: tokens whose content cannot be bounded from the text at all.
    unbounded: frozenset[str]
    #: token -> what it does to the cursor.
    action: dict[str, str]
    #: source macro (`line`, `para`, …) -> the token it emits.
    macro_token: dict[str, str]

    def tiles(self, root: Path, text: str) -> tuple[int, int, list[str], list[str]]:
        """(determinate tiles, extra tiles at the buffers' bound, unbounded
        tokens present, tokens with no charmap entry)."""
        det = bnd = 0
        unb: list[str] = []
        unknown: list[str] = []
        for tok in charmap.tokenize(root, text):
            if tok in self.action:
                break                      # `@` and friends terminate the string
            if tok in self.unbounded:
                unb.append(tok)
            elif tok in self.bound:
                bnd += self.bound[tok]
            elif tok in self.width:
                det += self.width[tok]
            else:
                unknown.append(tok)
                det += 1
        return det, bnd, unb, unknown


def _equs(root: Path, rel: str, known: dict[str, int]) -> dict[str, int]:
    """`NAME EQU <arithmetic>` lines, resolved against what's known so far."""
    out = dict(known)
    for line in (root / rel).read_text().split("\n"):
        m = _EQU_RE.match(line)
        if not m:
            continue
        name, expr = m.group(1), m.group(2)
        try:
            out[name] = int(eval(expr, {"__builtins__": {}}, out))   # noqa: S307
        except Exception:
            continue          # symbolic or non-arithmetic; nothing here needs it
    return out


@lru_cache(maxsize=4)
def boxes(root: Path) -> dict[str, Box]:
    """The two boxes map text can land in, measured from the engine.

    The speech box falls straight out of home/text.asm's EQUs. The signpost is a
    full-screen window — its border is the screen edge by construction — so all
    that has to be read is where the body starts, which is the `hlcoord` before
    the `FarPlaceText` in `SignpostFront`.
    """
    syms = _equs(root, _MISC, {})
    syms = _equs(root, _TEXT_ASM, syms)

    inner_w = syms["TEXTBOX_INNERW"]
    inner_y = syms["TEXTBOX_INNERY"]
    speech = Box("speech textbox", cols=inner_w, first_row=inner_y,
                 last_row=inner_y + 2, second_row=inner_y + 2)

    x, y = _signpost_origin(root)
    screen_w, screen_h = syms["SCREEN_WIDTH"], syms["SCREEN_HEIGHT"]
    sign = Box("signpost", cols=(screen_w - 1) - x, first_row=y,
               last_row=(screen_h - 1) - 1, second_row=y + 2)

    return {"speech": speech, "sign": sign}


def _signpost_origin(root: Path) -> tuple[int, int]:
    """Where a signpost's *body* text starts: the `hlcoord` before FarPlaceText."""
    last: tuple[int, int] | None = None
    for line in (root / _SIGNPOST_ASM).read_text().split("\n"):
        if m := _HLCOORD_RE.match(line):
            last = (int(m.group(1)), int(m.group(2)))
        elif "FarPlaceText" in line and last:
            return last
    raise ValueError(f"no `hlcoord` before FarPlaceText in {_SIGNPOST_ASM}")


@lru_cache(maxsize=4)
def metrics(root: Path) -> Metrics:
    """Token widths, read out of the engine rather than reproduced.

    Three hops, all in home/text.asm: the jumptable's comment names the token,
    `print_name` names the buffer it prints, and a ROM buffer is a `db "…@"` we
    can measure. A buffer in WRAM has no width until runtime, so it is bounded
    (`<PLAYER>` by the naming screen) or declared unbounded (`<STRBF1>`).
    """
    src = (root / _TEXT_ASM).read_text().split("\n")

    token_of: dict[str, str] = {}       # handler -> token
    in_table = False
    for line in src:
        if line.startswith("TextControlCodeJumptable"):
            in_table = True
            continue
        if in_table:
            if m := _JUMP_RE.match(line):
                token_of[m.group(1)] = m.group(2)
            elif line.strip() and not line.strip().startswith(";"):
                break

    prints: dict[str, str] = {}          # handler -> buffer it prints
    rom: dict[str, str] = {}             # ROM label -> its string
    for line in src:
        if m := _PRINT_NAME_RE.match(line):
            prints[m.group(1)] = m.group(2)
        elif m := _ROM_STR_RE.match(line):
            rom[m.group(1)] = m.group(2)

    consts = _equs(root, _MISC, {})
    width = {t: 1 for t in charmap.tokens(root)}
    bound: dict[str, int] = {}
    unbounded: set[str] = set()
    action: dict[str, str] = {}

    for handler, token in token_of.items():
        if token in _ACTIONS:
            action[token] = _ACTIONS[token]
            width.pop(token, None)
            continue
        buf = prints.get(handler)
        if buf is None:
            continue                     # a routine we can't measure; leave it 1
        if buf in rom:
            width[token] = _rom_width(root, rom[buf])
        elif buf in UNBOUNDED:
            unbounded.add(token)
            width.pop(token, None)
        elif buf in _BUFFER_BOUNDS:
            # the length constants count the terminator; the printed name doesn't
            bound[token] = consts[_BUFFER_BOUNDS[buf]] - 1
            width.pop(token, None)

    for token, act in _ACTIONS.items():  # `@` is in the charmap, not the jumptable
        action.setdefault(token, act)
        width.pop(token, None)

    return Metrics(width, bound, frozenset(unbounded), action, _macro_tokens(root))


def _rom_width(root: Path, text: str) -> int:
    """Tiles a ROM expansion prints.

    Every token in one of these is a plain glyph — `"Poké@"` is four, `"<PK><MN>@"`
    is two, since `<PK>` and `<MN>` are single tiles in the font — so counting
    tokens up to the terminator is the whole job. If a fork ever wrote a control
    code *into* an expansion it would need to recurse; none does, and `text_unknown`
    would surface it.
    """
    n = 0
    for tok in charmap.tokenize(root, text):
        if tok == charmap.TERMINATOR:
            break
        n += 1
    return n


@lru_cache(maxsize=4)
def _macro_tokens(root: Path) -> dict[str, str]:
    """`line EQUS "dtxt \\"<LINE>\\","` -> {"line": "<LINE>"}, from macros/text.asm."""
    out: dict[str, str] = {}
    for line in (root / _TEXT_MACROS).read_text().split("\n"):
        if m := _MACRO_EQUS_RE.match(line):
            out[m.group(1)] = m.group(2)
    return out
