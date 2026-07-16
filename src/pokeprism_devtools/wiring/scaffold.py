"""Adding *content* to a map: NPCs, trainers, signs — the things that talk.

The things that are not people are next door in :mod:`.props`. They build on the
machinery here (:class:`MapCtx`, :func:`allocate_flag`), and they are a separate
module because what makes a prop hard is not the wiring: it is that the engine
reads the same two macro arguments four different ways.

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

#: The four signposts that read only when you're facing them. They are *scripts*,
#: not text — see :func:`add_signpost`.
FACINGS = ("SIGNPOST_UP", "SIGNPOST_DOWN", "SIGNPOST_LEFT", "SIGNPOST_RIGHT")

_STILL = "SPRITEMOVEDATA_STANDING_DOWN"

INDENT = "\t"


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
        require(root, "sprite", self.sprite, frozenset(spritesets.sprite_ids(root)))
        require(root, "movement", self.movement, frozenset(spritesets.movedata_ids(root)))
        require(root, "palette", self.palette,
                 consts.with_prefix(root, consts.SPRITES, "PAL_OW_"))


def require(root: Path, kind: str, name: str, known: frozenset[str]) -> None:
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
    ctx = MapCtx(root, map_const)
    # `<Map>_NPC_<n>`, the convention this fork's own maps follow (MtEmber_NPC_1,
    # EagulouCity_NPC_2) and the same numbered shape a trainer's label gets — not
    # the concatenated `<Map>NPC` of the vanilla maps we inherited.
    label = label or ctx.unique_label("NPC", numbered=True)
    edits: list[Edit] = []

    flag_name = None
    if flag:
        flag_name, flag_edit = allocate_flag(root, flag)
        edits.append(flag_edit)

    ctx.add_script(label, _text_block(label, pages))
    # TEXTFP, not TEXT: it runs `jumptextfaceplayer` (engine/events.asm:540), so the
    # NPC turns to face you before it speaks. That is what a person does when you
    # talk to them, and it is what all but a handful of this repo's NPCs are.
    ctx.add_object(obj, "PERSONTYPE_TEXTFP", sight, label, flag_name or ALWAYS)
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
    ctx = MapCtx(root, map_const)
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
    flag_name, flag_edit = allocate_flag(root, flag or ctx.flag_name("TRAINER", numbered=True))
    edits.append(flag_edit)

    ctx.add_script(label, _trainer_block(label, flag_name, cls, party,
                                         seen, defeated, after))
    ctx.add_object(obj, "PERSONTYPE_GENERICTRAINER", sight, label, ALWAYS)
    edits.append(ctx.to_edit(f"{cls} {label} at ({obj.y}, {obj.x})"))

    return Scaffold(f"{cls} #{party} as {label} in {map_const}",
                    edits, flag_name, label, party)


def add_signpost(root: Path, map_const: str, y: int, x: int,
                 pages: list[list[str]], *, label: str | None = None,
                 facing: str | None = None) -> Scaffold:
    """A sign you read. No flag — a sign is always there.

    Two shapes, and which one is right depends on the signpost type, because the
    engine treats the pointer differently:

    `SIGNPOST_TEXT` jumps straight into a **text** block (`engine/events.asm:663`
    stuffs the pointer into a synthesised `jumptext`). That is the plain sign, and
    it is what all 71 of this repo's gym and town signs are.

    `SIGNPOST_UP` / `DOWN` / `LEFT` / `RIGHT` only read when you're facing them,
    and all four fall through to `.read`, which **calls a script**. Point one at a
    bare text block and the engine will execute your prose as bytecode. So a
    facing sign gets a one-line script that jumps to its own text.
    """
    ctx = MapCtx(root, map_const)
    label = label or ctx.unique_label("Sign")

    if facing is None:
        kind, block = "SIGNPOST_TEXT", _text_block(label, pages)
    else:
        kind = f"SIGNPOST_{facing.upper()}"
        if kind not in FACINGS:
            raise ScaffoldError(
                f"a sign faces {', '.join(f.removeprefix('SIGNPOST_').lower() for f in FACINGS)}"
                f" — or nothing at all, and then it reads from any side. Not {facing!r}."
            )
        block = [f"{label}:", f"{INDENT}jumptext .text", "", ".text",
                 *_text_body(pages)]

    ctx.add_script(label, block)
    ctx.add_bg_event([str(y), str(x), kind, label])

    return Scaffold(
        f"sign {label} at ({y}, {x}) in {map_const}",
        [ctx.to_edit(f"sign {label} at ({y}, {x})")],
        label=label,
    )


# --------------------------------------------------------------------------- #
# the map file, mid-edit                                                      #
# --------------------------------------------------------------------------- #

class MapCtx:
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

    def add_object(self, obj: Object, persontype: str, param: str | int,
                   pointer: str, flag: str) -> None:
        """One person_event. `param` is the macro's 11th argument, and what it
        means is decided by the persontype: sight range for a person, quantity for
        an item ball, the item itself for a TM ball, an ignored `0` for a tree.
        The macro has one slot; the engine reads four different things out of it.
        """
        self.header.add_entry(eh.ListKind.OBJECT_EVENTS, [
            obj.sprite, str(obj.y), str(obj.x), obj.movement,
            str(obj.radius_y), str(obj.radius_x), str(obj.hour), str(obj.daytime),
            obj.palette_arg(), persontype, str(param), pointer, flag,
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
        if p > 0:
            # A blank line before every `para`, the way this fork's own maps space
            # their paragraphs (MtEmberWest.asm): a `para` opens a fresh textbox,
            # and the empty line makes that break legible in the source.
            out.append("")
        for i, line in enumerate(lines):
            macro = ("ctxt" if p == 0 else "para") if i == 0 else ("line" if i == 1 else "cont")
            out.append(f'{INDENT}{macro} "{_escape(line)}"')
    out.append(f"{INDENT}done")
    return out


def _trainer_block(label: str, flag: str, cls: str, party: int,
                   seen: list[list[str]], defeated: list[list[str]],
                   after: list[list[str]]) -> list[str]:
    """The shape every generic trainer in the repo has: the macro, the
    talk-again text falling through directly beneath it, then the two texts the
    macro points at, as local labels."""
    return [
        f"{label}:",
        f"{INDENT}trainer {flag}, {cls}, {party}, .before_battle_text, .defeated_text",
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


def camel(const: str) -> str:
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
        require(root, "species", mon.species, species)
        if mon.item:
            require(root, "held item", mon.item, items)
        for move in mon.moves:
            require(root, "move", move, moves)


def allocate_flag(root: Path, name: str) -> tuple[str, Edit]:
    flags = eventflags.load(root)
    flag = flags.allocate(name)
    return flag.name, flags.to_edit(root, f"{name} = {flag.value}")
