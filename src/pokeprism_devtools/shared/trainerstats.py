"""What a trainer of this class usually looks like — counted, not guessed.

Adding a trainer means answering four questions, and two of them have the same
answer nearly every time: a `BUG_CATCHER` is a `SPRITE_BUG_CATCHER` in
`PAL_OW_BLUE`, in seven of this repo's ten. Making you type that is making you
look it up, and the place you would look it up is this repo. So the form fills it
in from the mode of what is already there, and you type over it when you mean
something else.

The reason it is *counted* rather than derived from the class name: **the name
lies, for 17 of the 43 classes that have a trainer on any map.** A `SKIER` is a
`SPRITE_BUENA`, all three of them. A `MEDIUM` is a `SPRITE_GRANNY`. A
`BLACKBELT_T` is a `SPRITE_BLACK_BELT` — the underscore moves. Mangling the class
into a sprite name would be right often enough to be trusted and wrong 40% of the
time, which is the worst thing a default can be.

And the palette is a property of the *class*, not of the sprite: the same
`SPRITE_LASS` appears in `PAL_OW_RED` and in `PAL_OW_BLUE`, and only counting can
tell you which a LASS usually gets.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

#: A trainer's `person_event`, of either persontype — `GENERICTRAINER` differs
#: only in that the engine gives it no phone number, and it wears the same
#: clothes. Groups 2..8 are y, x, movement, the two radii and the two clock
#: fields; none of them says anything about a class.
_PERSON_RE = re.compile(
    r"^\s*person_event\s+(?P<sprite>\w+)\s*,"
    r"(?:[^,]*,){7}"
    r"(?P<palette>[^,]*),"
    r"\s*PERSONTYPE_(?:GENERIC)?TRAINER\s*,"
    r"[^,]*,\s*(?P<pointer>[\w.]+)\s*,"
)
#: `trainer EVENT_FOO, YOUNGSTER, 3, .seen, .beaten` — inside the script block
#: the person_event points at. The class is not on the person_event at all.
_TRAINER_RE = re.compile(r"^\s*trainer\s+\w+\s*,\s*(\w+)\s*,")
_LABEL_RE = re.compile(r"^([A-Za-z_]\w*):")
#: The palette argument is not always a palette. It carries the behind-background
#: bit (`8 + PAL_OW_BLUE`), and a handful of objects give a bare number. The bit
#: is a property of the *object* — whether it stands behind a tree — so it has no
#: business in a class default, and a bare number names no constant we could
#: offer. Take the name when there is one, and count nothing when there isn't.
_PALETTE_RE = re.compile(r"\bPAL_OW_\w+")


@dataclass(frozen=True)
class Appearance:
    """One trainer on one map: the class it battles as, and what it wears there.

    `palette` is `None` when the person_event carries no `PAL_OW_*` name — a bare
    number, say. `map` is the file stem (``Route55``) and `line` is 1-based, so a
    caller can point an editor or a diagnostic straight at the person_event.
    """
    cls: str
    sprite: str
    palette: str | None
    map: str
    line: int


@lru_cache(maxsize=4)
def appearances(root: Path) -> tuple[Appearance, ...]:
    """Every trainer person_event in the repo, resolved to its class.

    The one parse the rest of this module is built on. A map keeps its scripts
    above its event header, so a single pass collects both halves: which class
    each script block battles as (`trainer FLAG, CLASS, …`), and which sprite the
    person_event pointing at that block wears. A person_event whose pointer names
    no script block here — a plain NPC, or a `loadtrainer` battle with no
    `trainer` macro — resolves to no class and is left out.
    """
    out: list[Appearance] = []
    for path in sorted((root / "maps").glob("*.asm")):
        try:
            lines = path.read_text(errors="replace").split("\n")
        except OSError:
            continue

        classes: dict[str, str] = {}
        people: list[tuple[str, str | None, str, int]] = []
        label = ""
        for i, line in enumerate(lines, start=1):
            if m := _LABEL_RE.match(line):
                label = m.group(1)
            elif m := _TRAINER_RE.match(line):
                if label:
                    classes[label] = m.group(1)
            elif m := _PERSON_RE.match(line):
                pal = _PALETTE_RE.search(m["palette"])
                people.append((m["sprite"], pal.group(0) if pal else None,
                               m["pointer"], i))

        for sprite, palette, pointer, lineno in people:
            if cls := classes.get(pointer):
                out.append(Appearance(cls, sprite, palette, path.stem, lineno))
    return tuple(out)


@lru_cache(maxsize=4)
def _counts(root: Path) -> dict[str, Counter[tuple[str, str | None]]]:
    """class -> how often each (sprite, palette) pair is worn by it.

    A bare-palette trainer still *wears the sprite*, so it counts toward
    who-wears-what (:func:`classes_for`); it just says nothing about the palette
    a class prefers, so :func:`defaults` skips it when choosing one.
    """
    out: dict[str, Counter[tuple[str, str | None]]] = {}
    for a in appearances(root):
        out.setdefault(a.cls, Counter())[(a.sprite, a.palette)] += 1
    return out


def defaults(root: Path, cls: str) -> dict[str, str]:
    """The sprite and palette this class wears most often. `{}` if it wears none.

    Empty is the honest answer for a class with no trainer on any map — a gym
    leader reached only by `loadtrainer`, say. The form then leaves its fields as
    they were, rather than inventing a look for a character that has never
    appeared.
    """
    counts = _counts(root).get(cls)
    if not counts:
        return {}
    # The modal sprite, over every appearance — a bare-palette trainer wears a
    # sprite as surely as any other.
    sprites: Counter[str] = Counter()
    for (sprite, _pal), n in counts.items():
        sprites[sprite] += n
    sprite = sprites.most_common(1)[0][0]
    out = {"sprite": sprite}
    # The palette that sprite wears most often, ignoring the appearances that
    # named none: a class with only bare-palette trainers offers its sprite and
    # leaves the palette field as it was, rather than inventing PAL_OW_RED.
    palettes: Counter[str] = Counter()
    for (spr, pal), n in counts.items():
        if spr == sprite and pal is not None:
            palettes[pal] += n
    if palettes:
        out["palette"] = palettes.most_common(1)[0][0]
    return out


def classes_for(root: Path, sprite: str) -> list[str]:
    """Every class that wears this sprite anywhere in the repo, most-common
    first — the reverse of :func:`defaults`. Empty for a sprite no trainer
    wears: an NPC-only sprite, or one nothing has been given yet.

    Counts *appearances*, not classes: a class that wears this sprite in six
    towns outranks one that wears it once, regardless of what else either of
    them also wears.
    """
    totals: Counter[str] = Counter()
    for cls, worn in _counts(root).items():
        n = sum(count for (spr, _pal), count in worn.items() if spr == sprite)
        if n:
            totals[cls] = n
    return [cls for cls, _ in totals.most_common()]


def rosters(root: Path, cls: str) -> list[str]:
    """Every existing party of a class, one line each: `3  Joey — RATTATA 4`.

    The index leads, because the index is the only part of this the assembler
    sees: it is what goes into the `trainer` macro. Everything after it is there
    so you can tell which party you are pointing at, a party having no name the
    engine can read.
    """
    from . import trainerparty

    try:
        group = trainerparty.group_for(root, cls)
    except trainerparty.TrainerPartyError:
        return []
    return [
        f"{p.index}  {p.name} — "
        + (", ".join(f"{m.species} {m.level}" for m in p.mons) or "no Pokémon")
        for p in group.parties
    ]
