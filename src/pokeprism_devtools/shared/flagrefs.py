"""Every reference to every event flag — and, crucially, what kind of reference.

A flag is not just "used" or "unused". The distinction that matters is between
the code that **owns** it and the code that **reads** it::

    person_event …, PERSONTYPE_ITEMBALL, 1, ULTRA_BALL, EVENT_X   owner: picking
                                                                  it up sets X
    trainer EVENT_X, SAGE, 4, …                                   owner: beating
                                                                  him sets X
    <hidden item record>  dw EVENT_X                              owner
    setevent EVENT_X / clearevent EVENT_X                         owner (a script
                                                                  writes it)

    person_event …, PERSONTYPE_TEXT, 0, Foo, EVENT_X              reader: this NPC
                                                                  only appears if X
    checkevent EVENT_X                                            reader

A flag having many *readers* is completely normal — that is what a flag is for.
A flag having two *owners* is the suspicious thing: two item balls that both set
the same flag mean picking up one makes the other vanish, and nothing about that
fails to assemble.

So this module tags each reference, and the flag rules are written in terms of
owners and readers rather than raw text hits.

The blind spot this replaces: the old rules read only the four counted lists in
a map's event header. That misses the ~660 script-level ``checkevent`` /
``setevent`` references, every trainer's flag (which is *not* in its
person_event — that argument says -1 — but in the ``trainer`` macro in its script
block), and every hidden item's (which lives in the record the signpost points
at). Roughly speaking, it missed most of them.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

#: A reference that *writes* the flag, or whose existence the flag is the record
#: of. Two of these on one flag is worth a second look.
OWNER = "owner"
#: A reference that only *reads* the flag to decide something. Any number is fine.
READER = "reader"
#: A mention this parser cannot classify — an engine `ld de, EVENT_X` handed to
#: EventFlagAction, whose mode byte decides whether it sets or tests the flag.
#: Callers asking "does anything set this?" must treat UNKNOWN as "possibly yes",
#: because the alternative is calling a live flag dead.
UNKNOWN = "unknown"

#: Script commands, and which side they fall on. `checkcode` and the `seteventvar`
#: family take a flag as a value; treat them as readers — they don't own it.
_COMMANDS = {
    "setevent": OWNER,
    "clearevent": OWNER,
    "setflag": OWNER,
    "clearflag": OWNER,
    "checkevent": READER,
    "checkflag": READER,
    "seteventvar": READER,
    "seteventvartovalue": READER,
    "eventflagchangeblock": READER,
}

#: The `trainer` macro's first argument is the flag that remembers you beat him.
_TRAINER_RE = re.compile(r"^\s*trainer\s+(EVENT_\w+)\s*,")
#: A hidden-item record is `dw EVENT_X` followed by `db <ITEM>`. The follower is
#: what distinguishes it from a table of flags, which looks identical on one line.
_DW_RE = re.compile(r"^\s*dw\s+(EVENT_\w+)\s*(?:;.*)?$")
_ITEM_FOLLOWS_RE = re.compile(r"^\s*db\s+[A-Z_][A-Z0-9_]*\s*(?:;.*)?$")
_COMMAND_RE = re.compile(r"^\s*(\w+)\s+(EVENT_\w+)")
_EVENT_RE = re.compile(r"\bEVENT_\w+\b")

_PERSON_RE = re.compile(r"^\s*person_event\s+(.*?)\s*(?:;.*)?$")

#: A flag argument is an *expression*, not just a name: `EVENT_FOO | $8000` sets
#: a high bit alongside the flag. So a name is extracted from the argument rather
#: than the argument being taken as the name.
#:
#: And a name can be *built* at assembly time — `dw EVENT_ADOPTED_\1` inside a
#: macro constructs one from the macro's argument. No text scan can see the
#: resulting reference, so the literal prefix is recorded and every flag starting
#: with it is treated as referenced. Getting this wrong means calling a live flag
#: dead, which is the one mistake that matters here.
_CONCAT_RE = re.compile(r"\b(EVENT_\w*)\\")

#: person_event types whose flag is what the object *creates* when triggered,
#: rather than a condition on its appearing. An item ball's flag is the record
#: that it has been taken.
_OWNING_PERSONTYPES = ("PERSONTYPE_ITEMBALL", "PERSONTYPE_TMHMBALL")

_DECLARATION = "constants/event_flags.asm"


@dataclass(frozen=True)
class FlagRef:
    flag: str
    role: str            # OWNER | READER | UNKNOWN
    how: str             # "person_event (…)" | "trainer" | "item record" | "setevent" | …
    path: str            # repo-relative
    line: int            # 1-based
    #: Only meaningful on a person_event gate. The `| $8000` bit inverts the test
    #: (engine/objects.asm: `res 7, d` … `xor b`), and it inverts the *meaning* of
    #: the gate: normally an object is visible until its flag is set, and with
    #: this bit it is invisible until its flag is set.
    inverted: bool = False


@dataclass(frozen=True)
class Index:
    refs: dict[str, list[FlagRef]]
    #: Literal prefixes of flag names *built* by macro concatenation. Any declared
    #: flag starting with one of these is referenced in a way no text scan can
    #: see, so it must never be reported as unused.
    built_prefixes: frozenset[str]

    def get(self, flag: str) -> list[FlagRef]:
        return self.refs.get(flag, [])

    def is_referenced(self, flag: str) -> bool:
        """Including the references a text scan cannot see."""
        return flag in self.refs or any(flag.startswith(p) for p in self.built_prefixes)


def index(root: Path) -> Index:
    """Every reference to every flag, anywhere in the repo's asm.

    The declaration in constants/event_flags.asm is not a reference: it is the
    thing being referenced.
    """
    out: dict[str, list[FlagRef]] = defaultdict(list)
    built: set[str] = set()

    for path in sorted(root.rglob("*.asm")):
        rel = path.relative_to(root).as_posix()
        if rel == _DECLARATION:
            continue
        refs, prefixes = _refs_in(path, rel)
        for ref in refs:
            out[ref.flag].append(ref)
        built |= prefixes

    return Index(dict(out), frozenset(built))


def _refs_in(path: Path, rel: str) -> tuple[list[FlagRef], set[str]]:
    refs: list[FlagRef] = []
    built: set[str] = set()
    lines = path.read_text().split("\n")

    for i, raw in enumerate(lines, start=1):
        line = raw.split(";")[0]
        if "EVENT_" not in line:
            continue

        # `EVENT_ADOPTED_\1` — a name assembled from a macro argument, so the
        # real reference never appears as text anywhere.
        if concat := _CONCAT_RE.findall(line):
            built |= set(concat)
            continue

        if m := _PERSON_RE.match(line):
            refs += _person_refs(m.group(1), rel, i)
            continue
        if m := _TRAINER_RE.match(line):
            refs.append(FlagRef(m.group(1), OWNER, "trainer", rel, i))
            continue
        if m := _DW_RE.match(line):
            # `dw EVENT_X` on its own means little. It is a hidden-item record
            # only when a `db <ITEM>` follows it; otherwise it is a table entry.
            # EagulouGymB1F keeps an array of its three trainers' flags exactly
            # this way, and reading those as items would invent three item balls.
            nxt = lines[i].split(";")[0] if i < len(lines) else ""
            if _ITEM_FOLLOWS_RE.match(nxt):
                refs.append(FlagRef(m.group(1), OWNER, "item record", rel, i))
            else:
                refs.append(FlagRef(m.group(1), READER, "table entry", rel, i))
            continue
        if (m := _COMMAND_RE.match(line)) and (role := _COMMANDS.get(m.group(1))):
            refs.append(FlagRef(m.group(2), role, m.group(1), rel, i))
            continue

        # Anything else naming a flag — engine code, expressions, tables. We
        # can't tell a set from a test here, so we don't pretend to.
        for name in _EVENT_RE.findall(line):
            refs.append(FlagRef(name, UNKNOWN, "reference", rel, i))
    return refs, built


def _person_refs(args: str, rel: str, line: int) -> list[FlagRef]:
    """A person_event's flag is its *last* argument in every tail shape.

    For most types it gates the object's appearance — a reader. For an item ball
    it is the record of having taken it, which the object writes: an owner. A
    trainer's person_event carries -1; his real flag is in the `trainer` macro.

    The argument is an *expression*: `EVENT_FOO | $8000` carries a bit alongside
    the flag, so the name is extracted from it rather than taken whole.
    """
    parts = [a.strip() for a in args.split(",")]
    if not parts:
        return []

    names = _EVENT_RE.findall(parts[-1])
    if not names:
        return []
    persontype = parts[9] if len(parts) > 9 else ""
    role = OWNER if persontype in _OWNING_PERSONTYPES else READER
    inverted = "$8000" in parts[-1]
    return [FlagRef(name, role, f"person_event ({persontype})", rel, line, inverted)
            for name in names]


def owners(refs: list[FlagRef]) -> list[FlagRef]:
    return [r for r in refs if r.role == OWNER]


def readers(refs: list[FlagRef]) -> list[FlagRef]:
    return [r for r in refs if r.role == READER]


def maybe_set(refs: list[FlagRef]) -> bool:
    """Whether *anything* might set this flag.

    True for an explicit owner, and also for any reference this parser could not
    classify — engine code that loads the flag into `de` and hands it to
    EventFlagAction may be setting it or testing it, and there is no way to tell
    from the text. Erring towards "it is set" keeps the never-set rule from
    reporting live flags.
    """
    return any(r.role in (OWNER, UNKNOWN) for r in refs)
