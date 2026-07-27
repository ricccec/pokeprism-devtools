"""Vanilla's map file, read from the tail.

pokecrystal writes a map file top-down: `<Label>_MapScripts:` first, the
scripts and dialogue in the middle, and `<Label>_MapEvents:` last — the four
`def_*` lists whose macros self-count, so no row here can ever be
`undeclared`. That anchor at the tail is also what tells the mount this tree
is vanilla and not polished, whose event block opens the file.

Two turns happen at this boundary and nowhere above it:

* **Coordinates are written (x, y)** in every event macro, and cross the seam
  as `(y, x)` — the way `shared.coords.Tile` says. Skip the turn and every
  object on the grid reflects across the diagonal.
* **Classification is a walk, not a field.** An `object_event` says
  `OBJECTTYPE_SCRIPT` about a mart clerk and a fruit tree alike; what makes
  the tree a thing-on-the-floor is the `fruittree` macro in the block its
  pointer names. So the six-list carve-up here reads the pointed-at block:
  `trainer` lines carry the class, party and flag a trainer's own event
  doesn't; `itemball` carries the item; `hiddenitem` carries what a
  `BGEVENT_ITEM` sign is actually hiding.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ...shared import coords
from ...shared.coords import Tile
from ...studio import panels
from . import dialogue

_TOP_LABEL = re.compile(r"^(\w+):{1,2}")
_LOCAL_LABEL = re.compile(r"^(\.\w+):{1,2}")


@dataclass(frozen=True)
class Block:
    """One labelled run of lines: a script, a text, a movement."""
    label: str          # `.Script` for locals, bare for top-level
    owner: str          # the enclosing top-level label; == label at top level
    lineno: int
    lines: list[str]


@dataclass(frozen=True)
class MapSource:
    """One map file, carved the way vanilla writes it. Event entries are kept
    as their raw comma-split args — the (x, y) turn happens in :func:`tables`,
    at the seam, not here."""
    warp_events: list[list[str]] = field(default_factory=list)
    coord_events: list[list[str]] = field(default_factory=list)
    bg_events: list[list[str]] = field(default_factory=list)
    object_events: list[list[str]] = field(default_factory=list)
    #: `object_const_def` names, in object order — the names scripts address
    #: objects by, and so the natural handle when the list lines up.
    names: list[str] = field(default_factory=list)
    blocks: dict[str, Block] = field(default_factory=dict)
    #: The map's dialogue, from the one parse in :mod:`.dialogue`. Carried here
    #: rather than read again because this function already has the file's lines
    #: in hand — and because a second reading of the same words is exactly the
    #: drift that made the reword form unsafe to write in the first place.
    texts: tuple[dialogue.Block, ...] = ()


_EVENT_MACROS = ("warp_event", "coord_event", "bg_event", "object_event")


def parse(path: Path, anchor: str = "_MapEvents",
          expand: dict[str, Callable[[list[str]], list[str]]] | None = None
          ) -> MapSource:
    """Read one map file whole. Raises :class:`panels.Unreadable` when the
    file is missing or lacks the family anchor — a file this adapter cannot
    honestly call one of its maps. `anchor` is the one structural difference
    inside the family: vanilla's `_MapEvents` tail, polished's
    `_MapScriptHeader` head. The carving is otherwise identical, which is why
    the polished adapter imports this function instead of forking it.

    `expand` is the second fork, and it is polished's alone: a map of a
    convenience macro to the function that turns its args into the
    ``object_event`` args it assembles to. Vanilla passes none — it writes no
    shorthand — and polished passes `..polished.shorthand.SHORTHANDS`, so an
    ``itemball_event`` or a ``fruittree_event`` lands in ``object_events`` at its
    file position, counted in the same engine order the object consts number by.
    Without it the seven-hundred-odd shorthands in the tree are silently dropped,
    which is exactly what they were until this argument existed."""
    expand = expand or {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise panels.Unreadable(f"{path} does not exist.") from exc

    src = MapSource(texts=tuple(dialogue.parse_source(lines)))
    owner = ""
    current: Block | None = None
    in_consts = False
    seen_anchor = False

    for lineno, raw in enumerate(lines, start=1):
        stripped = raw.split(";")[0].strip()

        if m := _TOP_LABEL.match(raw):
            owner = m.group(1)
            if owner.endswith(anchor):
                seen_anchor = True
            current = src.blocks.setdefault(
                owner, Block(owner, owner, lineno, []))
            continue
        if m := _LOCAL_LABEL.match(raw.strip()):
            name = m.group(1)
            current = src.blocks.setdefault(
                owner + name, Block(name, owner, lineno, []))
            continue

        if current is not None and stripped:
            current.lines.append(stripped)

        word, _, rest = stripped.partition(" ")
        if word == "object_const_def":
            in_consts = True
            continue
        if in_consts:
            if word == "const":
                src.names.append(rest.strip())
                continue
            if stripped:
                in_consts = False
        if word in _EVENT_MACROS:
            args = [a.strip() for a in rest.split(",")]
            getattr(src, word + "s").append(args)
        elif word in expand:
            # A convenience macro that assembles to one object_event: expand it
            # in place so the object list stays in engine order — the order the
            # object consts are numbered by, and the reason a skipped shorthand
            # would slide every later const onto the wrong object.
            args = [a.strip() for a in rest.split(",")]
            src.object_events.append(expand[word](args))

    if not seen_anchor:
        raise panels.Unreadable(
            f"{path} has no {anchor} block — the anchor every map file in "
            "this dialect carries.")
    return src


# --------------------------------------------------------------------------- #
# the six lists                                                               #
# --------------------------------------------------------------------------- #

def tables(path: Path) -> panels.MapTables:
    """One map's events, carved into the six lists the tabs draw — and the
    same objects again as grid glyphs, from the one enumeration."""
    src = parse(path)
    marks: dict[Tile, str] = {}
    named = len(src.names) == len(src.object_events)

    warps = []
    for i, args in enumerate(src.warp_events):
        y, x = yx(args)
        mark(marks, y, x, coords.WARP)
        warps.append(panels.Warp(
            handle=("warp", i), index=i, y=y, x=x,
            to_map=arg(args, 2), their_warp=arg(args, 3)))

    triggers = []
    for i, args in enumerate(src.coord_events):
        y, x = yx(args)
        mark(marks, y, x, coords.TRIGGER)
        triggers.append(panels.Trigger(
            handle=("coord", i), index=i, y=y, x=x,
            scene=arg(args, 2), runs=arg(args, 3)))

    signs: list[panels.Signpost] = []
    props: list[panels.Prop] = []
    for i, args in enumerate(src.bg_events):
        y, x = yx(args)
        mark(marks, y, x, coords.SIGN)
        kind, target = arg(args, 2), arg(args, 3)
        if kind == "BGEVENT_ITEM":
            # What the sign hides is on the `hiddenitem ITEM, FLAG` line in
            # the block it points at. It goes on the Objects tab: it is a
            # thing on the floor, however the engine files it.
            hidden = macro_args(src, target, "hiddenitem")
            props.append(panels.Prop(
                handle=("bg", i), index=i, y=y, x=x, kind="hidden",
                what=arg(hidden, 0), qty="", flag=arg(hidden, 1)))
        else:
            signs.append(panels.Signpost(
                handle=("bg", i), index=i, y=y, x=x,
                kind=kind.removeprefix("BGEVENT_"), points_at=target))

    npcs: list[panels.Npc] = []
    trainers: list[panels.Trainer] = []
    says = first_words(src)
    for i, args in enumerate(src.object_events):
        if len(args) < 13:
            continue
        y, x = yx(args)
        handle = src.names[i] if named else ("object", i)
        sprite = args[2].removeprefix("SPRITE_")
        objtype, sight, script, flag = args[9], args[10], args[11], args[12]

        if objtype == "OBJECTTYPE_TRAINER":
            # The flag that remembers you beat a trainer lives on the
            # `trainer CLASS, PARTY, FLAG, …` line, not on the object_event —
            # whose own flag says when he is on the map at all.
            t = macro_args(src, script, "trainer")
            mark(marks, y, x, coords.TRAINER)
            trainers.append(panels.Trainer(
                handle=handle, index=i, y=y, x=x, sprite=sprite,
                cls=arg(t, 0), party=arg(t, 1), sight=sight,
                flag=arg(t, 2)))
        elif objtype == "OBJECTTYPE_ITEMBALL":
            ball = macro_args(src, script, "itemball")
            mark(marks, y, x, coords.ITEM)
            props.append(panels.Prop(
                handle=handle, index=i, y=y, x=x, kind="itemball",
                what=arg(ball, 0) or script, qty=arg(ball, 1), flag=flag))
        elif tree := macro_args(src, script, "fruittree"):
            mark(marks, y, x, coords.ITEM)
            props.append(panels.Prop(
                handle=handle, index=i, y=y, x=x, kind="fruittree",
                what=arg(tree, 0), qty="", flag=flag))
        else:
            mark(marks, y, x, coords.PERSON)
            npcs.append(panels.Npc(
                handle=handle, index=i, y=y, x=x, sprite=sprite,
                movement=args[3].removeprefix("SPRITEMOVEDATA_"),
                says=says.get(script, script), flag=flag))

    return panels.MapTables(npcs=npcs, trainers=trainers, props=props,
                            signposts=signs, warps=warps, triggers=triggers,
                            marks=marks)


# --------------------------------------------------------------------------- #
# the words                                                                   #
# --------------------------------------------------------------------------- #

def texts(path: Path) -> list[panels.TextRef]:
    """Every text block in one map, as prose. Vanilla draws signs and speech
    in the same box, so everything is "speech" here."""
    return refs(parse(path))


def refs(src: MapSource) -> list[panels.TextRef]:
    """The map's dialogue in the seam's record — shared with polished, which
    parses with its own anchor and then has the identical question to answer.

    A block with nothing to say is dropped: `.dialogue` keeps a box whose only
    command draws no string, because the writer has to see one to refuse it, and
    there is no point offering to reword a block with no words in it.
    """
    return [panels.TextRef(label=b.label, owner=b.owner, lineno=b.lineno,
                           prose=b.prose, box="speech")
            for b in src.texts if b.prose.strip()]


def first_words(src: MapSource) -> dict[str, str]:
    """`script label -> the first words it shows`, so an NPC's row can say
    what he says instead of the name of the block that says it. The walk is
    one hop: a script that `jumptext`s or `writetext`s a label shows that
    label's text; a pointer straight at a text block shows its own.

    Keyed the way `src.blocks` is — a local block under its owner — because
    that is the name an `object_event` points at.
    """
    first: dict[str, str] = {}
    for b in src.texts:
        name = b.owner + b.label if b.label.startswith(".") else b.label
        if name in first:
            continue        # a label with two boxes still opens with the first
        if words := next((ln for ln in b.prose.split("\n") if ln.strip()), ""):
            first[name] = words[:40]
    out: dict[str, str] = dict(first)
    hop = re.compile(r"^(?:jumptextfaceplayer|jumptext|writetext)\s+(\S+)")
    for name, b in src.blocks.items():
        if name in out:
            continue
        for ln in b.lines:
            if (m := hop.match(ln)) and m.group(1) in first:
                out[name] = first[m.group(1)]
                break
    return out


# --------------------------------------------------------------------------- #
# small readings                                                              #
# --------------------------------------------------------------------------- #

def yx(args: list[str]) -> tuple[int | None, int | None]:
    """The (x, y) the macro wrote, turned around. An expression instead of a
    number leaves the axis None: the row exists, the grid can't point at it."""
    return to_int(arg(args, 1)), to_int(arg(args, 0))


def to_int(s: str) -> int | None:
    try:
        return int(s, 0)
    except ValueError:
        return None


def arg(args: list[str] | None, i: int) -> str:
    return args[i] if args and len(args) > i else ""


def mark(marks: dict[Tile, str], y: int | None, x: int | None,
          glyph: str) -> None:
    if y is not None and x is not None:
        marks[Tile(y=y, x=x)] = glyph


def macro_args(src: MapSource, label: str, macro: str) -> list[str] | None:
    """The comma-split args of the first `macro` line in the block `label`
    names, or None — a pointer at nothing readable classifies as nothing."""
    b = src.blocks.get(label)
    if b is None:
        return None
    for ln in b.lines:
        word, _, rest = ln.partition(" ")
        if word == macro:
            return [a.strip() for a in rest.split(",")]
    return None
