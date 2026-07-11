"""Adding *content* to a map: NPCs, trainers, item balls, hidden items.

Each of these is one conceptual thing — "put a Sage here who battles you" — that
the source spreads across three or four files with nothing but a name to hold
them together:

    maps/<Map>.asm            the person_event, and the text it points at
    constants/event_flags.asm the flag that remembers you beat him
    trainers/groups/sage.asm  the party, referenced by *position*

Get any one of them wrong and it still assembles. A trainer with no flag is
re-battleable forever; a flag allocated by hand in the middle of the enum
invalidates every save; a party index off by one battles somebody else's team.

So a scaffold here is all-or-nothing: it produces the full set of :class:`Edit`s
across every file involved, and the caller applies them together or not at all.
Nothing is written until it does.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ..shared import consts, eventheader as eh, eventflags, mapsource, spritesets, trainerparty
from ..shared.edits import Edit

#: Bit 3 of the person_event palette nibble is OAM_PRIORITY (gbhw.asm) — the
#: object draws *behind* BG tiles, which is how NPCs stand in doorways or behind
#: counters. It's why the source is full of `8 + PAL_OW_BLUE`.
BEHIND_BG = 8

#: What an object with no schedule carries in the two clock fields.
ANY_TIME = -1

#: person_event's event-flag argument when the object is always present.
ALWAYS = "-1"

_STILL = "SPRITEMOVEDATA_STANDING_DOWN"
_ITEM_MOVEMENT = "SPRITEMOVEDATA_ITEM_TREE"
_ITEM_SPRITE = "SPRITE_POKE_BALL"

_INDENT = "\t"


class ScaffoldError(RuntimeError):
    pass


@dataclass(frozen=True)
class Object:
    """The half of a person_event that describes a body in the world, as opposed
    to what it *does* (which is the persontype and the pointer)."""
    sprite: str
    y: int
    x: int
    movement: str = _STILL
    palette: str = "PAL_OW_RED"
    radius_y: int = 0
    radius_x: int = 0
    hour: int = ANY_TIME
    daytime: int = ANY_TIME
    behind_bg: bool = False

    def palette_arg(self) -> str:
        return f"{BEHIND_BG} + {self.palette}" if self.behind_bg else self.palette

    def check(self, root: Path) -> None:
        """Every constant this object will emit must actually exist."""
        _require(root, "sprite", self.sprite, frozenset(spritesets.sprite_ids(root)))
        _require(root, "movement", self.movement, frozenset(spritesets.movedata_ids(root)))
        _require(root, "palette", self.palette,
                 consts.with_prefix(root, consts.SPRITES, "PAL_OW_"))


def _require(root: Path, kind: str, name: str, known: frozenset[str]) -> None:
    if name not in known:
        raise ScaffoldError(_unknown(kind, name, known))


def _unknown(kind: str, name: str, known: frozenset[str]) -> str:
    near = consts.suggest(name, known)
    hint = f" Did you mean {' or '.join(near)}?" if near else ""
    article = "an" if kind[0] in "aeiou" else "a"
    return f"{name} is not {article} {kind} in this repo ({len(known)} exist).{hint}"


@dataclass
class Scaffold:
    """Everything one addition touches. Apply the edits together or not at all."""
    summary: str
    edits: list[Edit] = field(default_factory=list)
    flag: str | None = None          # the event flag it allocated, if any
    label: str | None = None         # the script/text label it defined, if any
    party: int | None = None         # the trainer party index it settled on

    @property
    def changes(self) -> list[Edit]:
        return [e for e in self.edits if e.changed]


# --------------------------------------------------------------------------- #
# the four scaffolds                                                          #
# --------------------------------------------------------------------------- #

def add_npc(root: Path, map_const: str, obj: Object, pages: list[list[str]], *,
            label: str | None = None, flag: str | None = None,
            sight: int = 0) -> Scaffold:
    """An NPC who says something when you talk to it.

    `pages` is the dialogue, one list of screen lines per textbox. `flag` gates
    the NPC's *existence* — with one, it only appears once the flag is set; the
    default is an NPC that is always there.
    """
    obj.check(root)
    ctx = _MapCtx(root, map_const)
    label = label or ctx.unique_label("NPC")
    edits: list[Edit] = []

    flag_name = None
    if flag:
        flag_name, flag_edit = _allocate(root, flag)
        edits.append(flag_edit)

    ctx.add_script(label, _text_block(label, pages))
    ctx.add_object(obj, "PERSONTYPE_TEXT", sight, label, flag_name or ALWAYS)
    edits.append(ctx.to_edit(f"NPC {label} at ({obj.y}, {obj.x})"))

    return Scaffold(f"NPC {label} in {map_const}", edits, flag_name, label)


def add_trainer(root: Path, map_const: str, obj: Object, cls: str, *,
                seen: list[list[str]], defeated: list[list[str]],
                after: list[list[str]], party: int | None = None,
                new_party: tuple[str, list[trainerparty.Mon], str] | None = None,
                label: str | None = None, flag: str | None = None,
                sight: int = 1) -> Scaffold:
    """A trainer who spots you, battles, and can be talked to afterwards.

    Give either `party` (an existing 1-based index in `cls`'s group) or
    `new_party` as ``(name, mons, kind)`` to append one — appending is safe,
    inserting is not, so that is the only way a new party can be made.

    Three texts, all required, because the engine reads all three: what he says
    when he spots you (`seen`), when you win (`defeated`), and when you talk to
    him again afterwards (`after` — the text that falls through after the macro).

    `sight` is how many tiles away he notices you. Above 1 he *walks* to you, so
    his sprite must have walk frames loaded — see maplint's `sprite-vram`.
    """
    if (party is None) == (new_party is None):
        raise ScaffoldError("give exactly one of party= (reuse) or new_party= (append)")

    obj.check(root)
    ctx = _MapCtx(root, map_const)
    edits: list[Edit] = []

    try:
        group = trainerparty.group_for(root, cls)
        if new_party is not None:
            name, mons, kind = new_party
            _check_mons(root, mons)
            party = group.add_party(name, mons, kind).index
            edits.append(group.to_edit(root, f"{cls} party #{party}: {name}"))
    except trainerparty.TrainerPartyError as e:
        raise ScaffoldError(str(e)) from e

    if new_party is None and not 1 <= party <= group.count:
        raise ScaffoldError(
            f"{cls} party #{party} doesn't exist — {group.label} has {group.count}. "
            f"Pass new_party= to append one."
        )

    label = label or ctx.unique_label("Trainer", numbered=True)
    flag_name, flag_edit = _allocate(root, flag or ctx.flag_name("TRAINER", numbered=True))
    edits.append(flag_edit)

    ctx.add_script(label, _trainer_block(label, flag_name, cls, party,
                                         seen, defeated, after))
    ctx.add_object(obj, "PERSONTYPE_GENERICTRAINER", sight, label, ALWAYS)
    edits.append(ctx.to_edit(f"{cls} {label} at ({obj.y}, {obj.x})"))

    return Scaffold(f"{cls} #{party} as {label} in {map_const}",
                    edits, flag_name, label, party)


def add_itemball(root: Path, map_const: str, y: int, x: int, item: str, *,
                 flag: str | None = None, sprite: str = _ITEM_SPRITE,
                 palette: str = "PAL_OW_RED") -> Scaffold:
    """A Poké Ball on the ground. The item const goes where a script pointer
    normally would — PERSONTYPE_ITEMBALL reads that argument as an item id."""
    obj = Object(sprite=sprite, y=y, x=x, movement=_ITEM_MOVEMENT, palette=palette)
    obj.check(root)
    _require(root, "item", item, consts.names(root, consts.ITEMS))

    ctx = _MapCtx(root, map_const)
    flag_name, flag_edit = _allocate(root, flag or ctx.flag_name(f"ITEM_{item}"))
    ctx.add_object(obj, "PERSONTYPE_ITEMBALL", 1, item, flag_name)

    return Scaffold(
        f"{item} at ({y}, {x}) in {map_const}",
        [flag_edit, ctx.to_edit(f"{item} itemball at ({y}, {x})")],
        flag_name,
    )


def add_hidden_item(root: Path, map_const: str, y: int, x: int, item: str, *,
                    flag: str | None = None, label: str | None = None) -> Scaffold:
    """An item hidden in the scenery, found with the Itemfinder.

    A SIGNPOST_ITEM points at a two-line record — the flag, then the item — which
    is why this one needs a label as well as a flag.
    """
    _require(root, "item", item, consts.names(root, consts.ITEMS))
    ctx = _MapCtx(root, map_const)
    label = label or ctx.unique_label(_camel(item))
    flag_name, flag_edit = _allocate(root, flag or ctx.flag_name(f"HIDDENITEM_{item}"))

    ctx.add_script(label, [f"{label}:", f"{_INDENT}dw {flag_name}", f"{_INDENT}db {item}"])
    ctx.add_bg_event([str(y), str(x), "SIGNPOST_ITEM", label])

    return Scaffold(
        f"hidden {item} at ({y}, {x}) in {map_const}",
        [flag_edit, ctx.to_edit(f"hidden {item} at ({y}, {x})")],
        flag_name, label,
    )


# --------------------------------------------------------------------------- #
# the map file, mid-edit                                                      #
# --------------------------------------------------------------------------- #

class _MapCtx:
    """A map's asm held open across several splices, so one Edit carries them all.

    Script and text blocks go *above* the ``X_MapEventHeader::`` line, which is
    where every map in the repo keeps them, and the event-header lists are
    spliced through :mod:`.eventheader` so the count bytes stay honest.
    """

    def __init__(self, root: Path, map_const: str) -> None:
        self.root = root
        self.const = map_const

        label = {c: l for l, c in mapsource.header_pairs(root)}.get(map_const)
        if label is None:
            raise ScaffoldError(f"{map_const} has no map_header_2 — wire the map first")
        self.map_label = label

        self.path = root / "maps" / f"{label}.asm"
        if not self.path.exists():
            raise ScaffoldError(f"{map_const} has no script file at maps/{label}.asm")

        try:
            self.header = eh.parse_map(self.path)
        except eh.UnparseableHeader as e:
            raise ScaffoldError(f"can't manage {map_const}: {e}") from e

        self._original = self.path.read_text()

    # -- naming ------------------------------------------------------------- #
    def unique_label(self, kind: str, *, numbered: bool = False) -> str:
        """`<Map><Kind>`, or `<Map>_<Kind>_<n>` — never one that already exists."""
        if numbered:
            base = f"{self.map_label}_{kind}"
            return f"{base}_{self._next_ordinal(base)}"

        candidate = f"{self.map_label}{kind}"
        if not self._defines(candidate):
            return candidate
        n = 2
        while self._defines(f"{candidate}{n}"):
            n += 1
        return f"{candidate}{n}"

    def flag_name(self, kind: str, *, numbered: bool = False) -> str:
        """`EVENT_<MAP>_<KIND>`, the convention the repo already follows."""
        base = f"EVENT_{self.const}_{kind}"
        if numbered:
            return f"{base}_{self._next_ordinal(base)}"
        flags = eventflags.load(self.root).by_name
        if base not in flags:
            return base
        n = 2
        while f"{base}_{n}" in flags:
            n += 1
        return f"{base}_{n}"

    def _next_ordinal(self, base: str) -> int:
        """1 past the highest `<base>_<n>` in the map (and, for flags, the enum)."""
        used = {int(m.group(1))
                for m in re.finditer(rf"{re.escape(base)}_(\d+)\b", self._text())}
        if base.startswith("EVENT_"):
            used |= {int(m.group(1)) for name in eventflags.load(self.root).by_name
                     if (m := re.fullmatch(rf"{re.escape(base)}_(\d+)", name))}
        return max(used, default=0) + 1

    def _defines(self, label: str) -> bool:
        return re.search(rf"^{re.escape(label)}:", self._text(), re.M) is not None

    def _text(self) -> str:
        return self.header.to_text()

    # -- splices ------------------------------------------------------------ #
    def add_script(self, label: str, block: list[str]) -> None:
        """Put a script/text block above the event header."""
        if self._defines(label):
            raise ScaffoldError(f"maps/{self.map_label}.asm already defines {label}")
        at = self.header.header_lineno
        self.header.lines[at:at] = [*block, ""]
        self.header.reparse()

    def add_object(self, obj: Object, persontype: str, sight: int,
                   pointer: str, flag: str) -> None:
        self.header.add_entry(eh.ListKind.OBJECT_EVENTS, [
            obj.sprite, str(obj.y), str(obj.x), obj.movement,
            str(obj.radius_y), str(obj.radius_x), str(obj.hour), str(obj.daytime),
            obj.palette_arg(), persontype, str(sight), pointer, flag,
        ])

    def add_bg_event(self, args: list[str]) -> None:
        self.header.add_entry(eh.ListKind.BG_EVENTS, args)

    def to_edit(self, detail: str) -> Edit:
        rel = f"maps/{self.map_label}.asm"
        text = self._text()
        return Edit(rel, text != self._original, detail, text, base=self._original)


# --------------------------------------------------------------------------- #
# rendering                                                                   #
# --------------------------------------------------------------------------- #

def _text_block(label: str, pages: list[list[str]]) -> list[str]:
    return [f"{label}:", *_text_body(pages)]


def _text_body(pages: list[list[str]]) -> list[str]:
    """Dialogue as the text engine reads it.

    A page is one textbox: `ctxt` opens it, `line` is the second row, and each
    further `cont` scrolls one more row into view. `para` opens a fresh box, and
    `done` ends the whole thing.
    """
    if not pages or not any(pages):
        raise ScaffoldError("dialogue needs at least one line")

    out: list[str] = []
    for p, lines in enumerate(pages):
        if not lines:
            raise ScaffoldError("a textbox with no lines in it")
        for i, line in enumerate(lines):
            macro = ("ctxt" if p == 0 else "para") if i == 0 else ("line" if i == 1 else "cont")
            out.append(f'{_INDENT}{macro} "{_escape(line)}"')
    out.append(f"{_INDENT}done")
    return out


def _trainer_block(label: str, flag: str, cls: str, party: int,
                   seen: list[list[str]], defeated: list[list[str]],
                   after: list[list[str]]) -> list[str]:
    """The shape every generic trainer in the repo has: the macro, the
    talk-again text falling through directly beneath it, then the two texts the
    macro points at, as local labels."""
    return [
        f"{label}:",
        f"{_INDENT}trainer {flag}, {cls}, {party}, .before_battle_text, .defeated_text",
        "",
        *_text_body(after),
        "",
        ".before_battle_text",
        *_text_body(seen),
        "",
        ".defeated_text",
        *_text_body(defeated),
    ]


def _escape(line: str) -> str:
    if '"' in line:
        raise ScaffoldError(f'a double quote can\'t appear in dialogue: {line!r}')
    return line


def _camel(const: str) -> str:
    return "".join(part.capitalize() for part in const.split("_"))


def _check_mons(root: Path, mons: list[trainerparty.Mon]) -> None:
    """A party's species, held items and moves must all exist.

    This fork carries its own dex — most of Kanto is gone — so a species name
    remembered from vanilla Crystal is a genuinely easy mistake, and rgbds only
    catches it when the whole ROM links.
    """
    species = consts.names(root, consts.SPECIES)
    items = consts.names(root, consts.ITEMS)
    moves = consts.names(root, consts.MOVES)

    for mon in mons:
        _require(root, "species", mon.species, species)
        if mon.item:
            _require(root, "held item", mon.item, items)
        for move in mon.moves:
            _require(root, "move", move, moves)


def _allocate(root: Path, name: str) -> tuple[str, Edit]:
    flags = eventflags.load(root)
    flag = flags.allocate(name)
    return flag.name, flags.to_edit(root, f"{name} = {flag.value}")
