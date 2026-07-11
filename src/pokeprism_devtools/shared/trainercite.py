"""Who battles which party — every reference, from every direction.

A party has no name the assembler can see. It is reached by *ordinal*, and there
are two macros that do the reaching:

    trainer     EVENT_FOO, YOUNGSTER, 3, .seen, .beaten    ; a person_event's trainer
    loadtrainer BUGSY, BUGSY_GYM                           ; a scripted battle

and the ordinal itself comes two ways: written out (``3``), or as a constant
declared by the ``trainerclass`` enum::

    trainerclass RIVAL1
    const RIVAL1_1        ; = 1, because `trainerclass` resets const_value
    const RIVAL1_2        ; = 2

Miss any one of those four combinations and you will conclude a party is dead
when it is not. That is not hypothetical: 63 of pokeprism's 352 parties have no
``trainer`` macro pointing at them, and they include Bugsy, Blue and every gym
leader — all reached by ``loadtrainer``, most of them by named const.

So this module exists to be *exhaustive*, and anything that wants to know
whether a party is safe to touch must ask it rather than grep.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import trainerparty as tp

_CLASSES = "constants/trainer_constants.asm"

#: `trainer FLAG, CLASS, ordinal, …` — the party a person_event battles.
_TRAINER_RE = re.compile(r"^\s*trainer\s+(\w+)\s*,\s*(\w+)\s*,\s*(\w+)\s*,")
#: `loadtrainer CLASS, ordinal` — a battle a script starts.
_LOADTRAINER_RE = re.compile(r"^\s*loadtrainer\s+(\w+)\s*,\s*(\w+)")

_TRAINERCLASS_RE = re.compile(r"^\s*trainerclass\s+(\w+)")
_CONST_RE = re.compile(r"^\s*const\s+(\w+)\s*(?:;.*)?$")
#: The class enum ends where the file starts a fresh counter. Everything after
#: `trainerclass CAL` is `const_def` + the AI-flag enum — consts that have
#: nothing to do with parties, and would otherwise be read as CAL's.
_COUNTER_RESET_RE = re.compile(r"^\s*(const_def\b|const_value\s*=)")

#: The id-0 class. `trainerclass TRAINER_NONE` is followed by `const
#: PHONECONTACT_*` — phone contacts parked in the class-0 slot, not parties.
_NO_CLASS = "TRAINER_NONE"


#: Where a citation came from. `symbol` means a party-ordinal const was *named*
#: somewhere outside the enum that declares it — `ld a, ARCADEPC_TRAINER` in
#: event/battle_arcade.asm, say. The engine reaches parties that way too, and a
#: tool that only reads the two macros would call that party dead.
TRAINER, LOADTRAINER, SYMBOL = "trainer", "loadtrainer", "symbol"


@dataclass(frozen=True)
class Citation:
    """One reference to one party."""
    cls: str             # trainer class const
    party: int           # 1-based ordinal
    macro: str           # TRAINER | LOADTRAINER | SYMBOL
    path: str            # repo-relative
    line: int            # 1-based
    written: str         # how the ordinal was written — "3" or "RIVAL1_3"


def party_consts(root: Path) -> dict[str, tuple[str, int]]:
    """Party-ordinal const -> (class, ordinal).

    ``trainerclass`` (macros/trainer.asm) enums the class *and* resets
    ``const_value`` to 1, so each `const` beneath one is that class's next party
    ordinal. Two kinds of const must not be swept up: TRAINER_NONE's, which are
    phone contacts parked in the class-0 slot, and everything past the enum's
    end, where the file opens a fresh ``const_def`` for the AI flags.
    """
    out: dict[str, tuple[str, int]] = {}
    cls: str | None = None
    ordinal = 1

    for line in _lines(root / _CLASSES):
        if m := _TRAINERCLASS_RE.match(line):
            cls, ordinal = m.group(1), 1
        elif _COUNTER_RESET_RE.match(line):
            cls = None                  # the class enum is over
        elif (m := _CONST_RE.match(line)) and cls and cls != _NO_CLASS:
            out[m.group(1)] = (cls, ordinal)
            ordinal += 1
    return out


@dataclass
class Citations:
    """Every party citation in the repo, kept **per file**.

    Same reasoning as :class:`..flagrefs.Index`: the whole-repo scan below is the
    single most expensive thing the linter does, and an edit only ever touches
    one file. So the per-file lists are the state and :meth:`reindex` rescans
    exactly one of them.
    """
    #: Party-ordinal const -> (class, ordinal). Declared in one file; if *that*
    #: file changes, every citation must be re-resolved, so rebuild from scratch.
    #: Party-ordinal const -> (class, ordinal). Declared in one file; if *that*
    #: file changes every citation must be re-resolved, so rebuild from scratch.
    consts: dict[str, tuple[str, int]]
    by_file: dict[str, list[Citation]] = field(default_factory=dict)
    _merged: dict[tuple[str, int], list[Citation]] | None = None
    _wanted: re.Pattern | None = None

    def all(self) -> dict[tuple[str, int], list[Citation]]:
        """Keyed by (class, ordinal)."""
        if self._merged is None:
            out: dict[tuple[str, int], list[Citation]] = {}
            for cites in self.by_file.values():
                for cite in cites:
                    out.setdefault((cite.cls, cite.party), []).append(cite)
            self._merged = out
        return self._merged

    def reindex(self, root: Path, rel: str) -> None:
        """Re-read one file. The merged view rebuilds itself on next use."""
        if rel == _CLASSES:
            return
        path = root / rel
        if path.is_file():
            self.by_file[rel] = self.scan(path, rel)
        else:
            self.by_file.pop(rel, None)
        self._merged = None

    def scan(self, path: Path, rel: str) -> list[Citation]:
        """One file's citations.

        A map reaches a party through the two macros. Everything *else* reaches it
        by naming the ordinal const directly — ``event/battle_arcade.asm`` says
        ``ld a, ARCADEPC_TRAINER`` and loads that party, and there is no reason to
        think it is the only place. So outside maps/, any file that so much as
        *mentions* a party's const is treated as reaching it: a reference this
        tool can't follow is still a reference, and the conservative reading is
        the only safe one when the alternative is calling a live trainer dead.

        A reference whose ordinal is a const this repo doesn't declare is dropped
        — it cannot be resolved to a party, and guessing would be worse than
        silence.
        """
        lines = path.read_text().split("\n")
        out: list[Citation] = []

        if rel.startswith("maps/"):
            # Note this runs even with no party-ordinal consts declared: a macro
            # citing its ordinal as a plain `3` resolves without them.
            for i, line in enumerate(lines, start=1):
                if m := _TRAINER_RE.match(line):
                    cls, written, macro = m.group(2), m.group(3), TRAINER
                elif m := _LOADTRAINER_RE.match(line):
                    cls, written, macro = m.group(1), m.group(2), LOADTRAINER
                else:
                    continue
                ordinal = _ordinal(written, cls, self.consts)
                if ordinal is not None:
                    out.append(Citation(cls, ordinal, macro, rel, i, written))
            return out

        if not self.consts:
            return []                    # nothing for the symbol scan to look for
        if self._wanted is None:
            self._wanted = re.compile(
                r"\b(" + "|".join(map(re.escape, self.consts)) + r")\b")
        for i, line in enumerate(lines, start=1):
            for name in self._wanted.findall(line.split(";")[0]):
                cls, ordinal = self.consts[name]
                out.append(Citation(cls, ordinal, SYMBOL, rel, i, name))
        return out


def index(root: Path) -> Citations:
    cites = Citations(party_consts(root))
    for path in sorted(root.rglob("*.asm")):
        rel = path.relative_to(root).as_posix()
        if rel != _CLASSES:              # the enum declaring them, not a use
            cites.by_file[rel] = cites.scan(path, rel)
    return cites


def citations(root: Path) -> dict[tuple[str, int], list[Citation]]:
    """Every reference to every party, keyed by (class, ordinal)."""
    return index(root).all()


def _ordinal(written: str, cls: str, consts: dict[str, tuple[str, int]]) -> int | None:
    if written.isdigit():
        return int(written)
    entry = consts.get(written)
    # The const must belong to the class it's cited with; one that doesn't is a
    # bug of a different kind, and not ours to resolve.
    return entry[1] if entry and entry[0] == cls else None


def orphans(root: Path, cites: Citations | None = None) -> list[tuple[str, tp.Party]]:
    """Parties nothing references, as (group label, party).

    Dead weight rather than a defect: the bytes ship, the game is fine. But an
    orphan is usually the residue of a trainer someone deleted from a map and
    left behind here, and it is the one party that *would* be safe to remove.

    Pass `cites` to reuse an index that is already warm — building one scans every
    asm file in the repo, and a long-lived caller (the studio) keeps one alive and
    reindexes the single file it just wrote.
    """
    cited = (cites or index(root)).all()
    groups = tp.load(root)
    mapping = tp.class_groups(root)

    # A group can be reached through more than one class; a party is an orphan
    # only if no class that reaches its group cites it.
    classes_of: dict[str, list[str]] = {}
    for cls, label in mapping.items():
        if label:
            classes_of.setdefault(label, []).append(cls)

    out = []
    for label, group in sorted(groups.items()):
        for party in group.parties:
            if not any((cls, party.index) in cited for cls in classes_of.get(label, [])):
                out.append((label, party))
    return out


def _lines(path: Path) -> list[str]:
    return path.read_text().split("\n") if path.exists() else []
