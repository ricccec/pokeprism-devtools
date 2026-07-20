"""Deleting a warp, and the repo-wide renumber that has to travel with it.

A warp destination is a **1-based index into the destination map's own warp
list**. A warp is therefore not an identity, it is a *position*: take one out and
every warp below it in that map slides up by one, and every reference in the repo
that counted past the hole now counts one too many. That is why adding a warp is
safe (append, and nothing moves) and deleting one is not.

The rule is dialect-free. For a deleted warp #k of map M, every reference to M's
warps in the repo:

    n > k    ->  n - 1        the warp it aimed at slid up
    n == k   ->  it aimed at the warp that is gone
    n < k    ->  untouched
    n < 1    ->  untouched — a *dynamic* warp, filled in at runtime

The **grammar** is not dialect-free, so it crosses the seam as data. Prism writes
``warp_def y, x, n, MAP``; the pokecrystal family writes ``warp_event x, y, MAP,
n`` — the argument seats move and the coordinates turn. Which macros index a
warp, which seat holds the number, which holds the map, and how a door to nowhere
is spelled are all a :class:`WarpGrammar` the *adapter* declares. This module
holds the rule and the repo scan and knows no hack's name.

What a grammar has to get right
-------------------------------
**The macro list is the whole surface, and that is a claim per tree.** Surveying
the three trees found four macros, not the two prism needs:

    warp_def / warp_event   a door on some map that arrives on M's warp n
    warpmod  n, MAP         a script re-pointing a dynamic warp at runtime
    elevfloor FLOOR, n, MAP an elevator's floor list (the family; not prism)
    digmod   n, MAP         Dig's exit (polished only; not vanilla, not prism)

**A door macro can be sent nowhere; the others cannot.** ``door=True`` marks the
macro that spells an entry in a map's own warp list — the only one with anywhere
to go when its destination is deleted. A ``warpmod``, ``elevfloor`` or ``digmod``
aimed at the deleted warp is refused: there is no dummy form of any of them, and
quietly leaving one aimed at whatever slid into the slot is worse than saying no.

**The dead-door spelling must be found, not assumed.** Prism has a
``dummy_warp y, x`` macro; the family has no such macro, and stopping there
would have been the wrong answer — both family trees ``DEF GROUP_NONE`` and
``DEF MAP_NONE`` to 0, so ``warp_event x, y, NONE, -1`` assembles to exactly
the bytes ``dummy_warp`` does. Each dialect spells the same door in its own
vocabulary, which is why :class:`DeadDoor` describes a *rewrite* (keep these
seats, append these literals) rather than a macro name. What "nowhere" is
actually worth is written down on that class, and it is less than it sounds.

A grammar may still set ``dead_door=None``, and then a door aimed at the
deleted warp refuses instead — the deletion names the doors and the human
repoints them first. No tree needs that today; it is the honest behaviour for
one that has no spelling, rather than an invented idiom.

**It refuses rather than guess.** A warp number it cannot read as a number is a
reference it cannot renumber, so the whole deletion is refused, naming the line.

Blind tables
------------
Polished keeps hidden-grotto return warps in ``data/`` as bare numbers with *no
map on the line* — the map is only inferable from the naming convention on a
constant in another file. A scan keyed by map const cannot see them, and this
module will not infer a map from a name. A grammar declares such a file as a
:class:`BlindTable` and every deletion on that tree carries a warning naming it.
Saying "there is a place I cannot check, and here it is" beats both silence and a
guess.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ..shared.constants import as_int
from ..shared.edits import Edit


@dataclass(frozen=True)
class WarpMacro:
    """One macro that names a warp by position, and where in it to look."""
    name: str
    #: Which argument seat holds the warp number.
    at: int
    #: Which seat holds the map the number counts into.
    at_map: int
    #: True for the macro that spells an entry in a map's own warp list — the
    #: only kind with anywhere to go when its destination is deleted.
    door: bool = False


@dataclass(frozen=True)
class DeadDoor:
    """How this dialect spells a door whose destination has been deleted.

    ``keeps`` names which seats of the door macro carry over, in order, and
    ``extra`` the literal arguments written after them. The two dialects need
    both halves because one swaps the macro and the other swaps the arguments:

        prism   warp_def y, x, n, MAP  ->  dummy_warp y, x
                                          keeps=(0, 1)
        family  warp_event x, y, MAP, n -> warp_event x, y, NONE, -1
                                          keeps=(0, 1), extra=("NONE", "-1")

    Those two assemble to the same five bytes. The door is still a door and
    still in the same place — it keeps its position in its own map's warp
    list, which is the whole point of not deleting the line.

    **What "nowhere" actually means here, which is not what it sounds like.**
    ``CopyWarpData`` (pokecrystal ``home/map.asm:331``, prism
    ``home/map.asm:172`` — the same code) reads the warp number, and *if it is
    -1* repoints ``hl`` at ``wBackupWarpNumber`` and takes the number, the
    group **and** the map from there. So the destination written on a -1 warp
    is never read: prism's ``dummy_warp`` trailing ``0, 0`` is dead bytes, not
    "group 0, map 0". A dead door does not lead nowhere — it lands on whatever
    the backup warp last held, which is unpredictable but does not crash.

    Neither dialect can express a true nowhere; the engine has no encoding for
    it. This is a door the human is told to go and fix, and the warning says
    so. It is recorded here because the alternative is a comment that claims a
    safety the engine does not provide.
    """
    macro: str
    keeps: tuple[int, ...]
    extra: tuple[str, ...] = ()

    @property
    def shown(self) -> str:
        """The spelling, for a warning that has to name it."""
        return f"{self.macro} …, {', '.join(self.extra)}" if self.extra \
            else self.macro


@dataclass(frozen=True)
class BlindTable:
    """A file holding warp numbers whose map is not on the line. Declared so it
    can be named in a warning, never read: inferring the map would be a guess."""
    rel: str
    why: str


@dataclass(frozen=True)
class WarpGrammar:
    """Everything about warp references that differs between trees."""
    macros: tuple[WarpMacro, ...]
    #: None where the dialect has no way to spell a dead door — then a door
    #: aimed at the deleted warp refuses instead of being rewritten.
    dead_door: DeadDoor | None
    blind: tuple[BlindTable, ...] = ()

    def door_macro(self) -> WarpMacro:
        return next(m for m in self.macros if m.door)


#: Where the build's own copies live. Renumbering those would be renumbering the
#: output, which `make` is about to overwrite anyway.
_SKIP = ("build/",)


class WarpDelError(RuntimeError):
    pass


@dataclass
class Deletion:
    summary: str
    edits: list[Edit] = field(default_factory=list)
    #: How many warps elsewhere counted past the hole and were pulled back one.
    renumbered: int = 0
    #: Doors that led to the deleted warp and now lead nowhere, by name.
    nowhere: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def changes(self) -> list[Edit]:
        return [e for e in self.edits if e.changed]


def delete_warp(root: Path, map_const: str, index: int, grammar: WarpGrammar,
                *, own_rel: str, spliced: str, where: str = "") -> Deletion:
    """Fix the whole repo behind warp #(index+1) of `map_const`, just removed.

    The caller has already taken the entry out of the map's own file — that
    splice is the adapter's, because only the adapter can parse its own dialect's
    event block — and hands the result in as `spliced`. Everything after it is
    the same for every tree, and is this module's.

    Nothing is written: the repo is read as it stands, every question about it is
    settled, and the answer comes back as :class:`Edit` previews. A refusal
    therefore happens while nothing has moved.
    """
    k = index + 1
    sources = _sources(root)
    refs = _refs(sources, map_const, grammar)
    _refuse(refs, k, map_const, grammar)

    # The map's own file takes both changes — the removal and, if it warps to
    # itself, the renumber — and an Edit carries the *whole* file, so they have
    # to be composed in one buffer or the second silently drops the first.
    done = {own_rel: spliced}

    edits: list[Edit] = []
    moved = 0
    nowhere: list[str] = []
    for rel in sorted({ref.rel for ref in refs} | {own_rel}):
        was = sources[rel]
        text, fixed, dead = _renumber(done.get(rel, was), map_const, k, grammar)
        moved += fixed
        nowhere += [f"{rel}:{n}" for n in dead]
        edits.append(Edit(rel, text != was, _detail(rel, own_rel, k, fixed, len(dead)),
                          text, base=was))

    warnings = []
    if moved:
        warnings.append(
            f"{moved} warp{'s' if moved != 1 else ''} elsewhere counted past #{k} "
            f"and {'have' if moved != 1 else 'has'} been renumbered.")
    for door in nowhere:
        warnings.append(
            f"{door} led to this warp and is now a `{grammar.dead_door.shown}` — a "
            f"door to nowhere. Walking into it lands on whatever the backup warp "
            f"last held, so it is a real loose end: nothing else moved, and it "
            f"wants a destination as soon as you know what it should be.")
    for table in grammar.blind:
        warnings.append(
            f"{table.rel} holds warp numbers with no map on the line ({table.why}), "
            f"so this scan could not check it. If {map_const} is named there, its "
            f"numbers past #{k} are now off by one — check it by hand.")

    return Deletion(f"removed warp #{k} of {map_const}{f' at {where}' if where else ''}",
                    edits, moved, nowhere, warnings)


def _detail(rel: str, own: str, k: int, fixed: int, dead: int) -> str:
    bits = []
    if rel == own:
        bits.append(f"removed warp #{k}")
    if fixed:
        bits.append(f"renumbered {fixed} warp{'s' if fixed != 1 else ''}")
    if dead:
        bits.append(f"{dead} door{'s' if dead != 1 else ''} to nowhere")
    return "; ".join(bits) or "unchanged"


# --------------------------------------------------------------------------- #
# reading the repo                                                            #
# --------------------------------------------------------------------------- #

def _sources(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for path in sorted(root.rglob("*.asm")):
        rel = path.relative_to(root).as_posix()
        if not rel.startswith(_SKIP):
            out[rel] = path.read_text()
    return out


@dataclass(frozen=True)
class _Ref:
    """One line, somewhere in the repo, that names a warp of the map in question."""
    rel: str
    lineno: int          # 0-based
    macro: WarpMacro
    n: int | None        # the warp number it names, or None if unreadable
    raw: str

    def where(self) -> str:
        return f"{self.rel}:{self.lineno + 1}: {self.raw.strip()}"


def _refs(sources: dict[str, str], const: str,
          grammar: WarpGrammar) -> list[_Ref]:
    refs: list[_Ref] = []
    for rel, text in sources.items():
        for i, line in enumerate(text.split("\n")):
            hit = _match(line, const, grammar)
            if hit is None:
                continue
            macro, _, args = hit
            refs.append(_Ref(rel, i, macro, as_int(args[macro.at].strip()), line))
    return refs


_PATTERNS: dict[str, re.Pattern] = {}


def _pattern(macro: str) -> re.Pattern:
    if macro not in _PATTERNS:
        _PATTERNS[macro] = re.compile(
            rf"^(?P<head>\s*{re.escape(macro)}\s+)(?P<args>.*\S)(?P<tail>\s*)$")
    return _PATTERNS[macro]


def _match(line: str, const: str, grammar: WarpGrammar):
    """The warp macro on this line, if it names `const`'s warps.

    Returns (WarpMacro, match, args). These macros take no strings, so the first
    `;` is always the start of a comment and nothing else.
    """
    code = line.split(";", 1)[0]
    for macro in grammar.macros:
        m = _pattern(macro.name).match(code)
        if not m:
            continue
        args = m.group("args").split(",")
        if (len(args) <= max(macro.at, macro.at_map)
                or args[macro.at_map].strip() != const):
            return None
        return macro, m, args
    return None


def _refuse(refs: list[_Ref], k: int, const: str, grammar: WarpGrammar) -> None:
    """Everything this module will not do, decided before it has done anything."""
    blind = [r.where() for r in refs if r.n is None]
    if blind:
        raise WarpDelError(
            f"{len(blind)} reference{'s' if len(blind) != 1 else ''} to {const}'s "
            f"warps write the warp number as something that cannot be read as a "
            f"number, so it cannot be renumbered. Deleting a warp would silently "
            f"repoint {'them' if len(blind) != 1 else 'it'}:\n  "
            + "\n  ".join(blind[:6]))

    # A macro that is not a door has nowhere to be sent: there is no dummy form
    # of a warpmod, an elevfloor or a digmod.
    stuck = [r for r in refs if not r.macro.door and r.n == k]
    if stuck:
        names = sorted({r.macro.name for r in stuck})
        raise WarpDelError(
            f"warp #{k} of {const} is the warp {len(stuck)} "
            f"`{'`/`'.join(names)}` "
            f"{'calls' if len(stuck) != 1 else 'call'} "
            f"{'point' if len(stuck) != 1 else 'points'} at, and there is no dummy "
            f"form of {'those' if len(names) != 1 else 'that'}. Rewrite "
            f"{'them' if len(stuck) != 1 else 'it'} first:\n  "
            + "\n  ".join(r.where() for r in stuck[:6]))

    # A door aimed at the deleted warp, in a dialect with no way to spell a dead
    # door. The rewrite prism does is simply not available here.
    if grammar.dead_door is None:
        doors = [r for r in refs if r.macro.door and r.n == k]
        if doors:
            raise WarpDelError(
                f"{len(doors)} door{'s' if len(doors) != 1 else ''} in this repo "
                f"lead{'' if len(doors) != 1 else 's'} to warp #{k} of {const}, and "
                f"this dialect has no way to spell a door to nowhere — its bare "
                f"`-1` means a *dynamic* warp the engine fills in at runtime, not a "
                f"dead one, so writing that would send the player somewhere "
                f"unpredictable instead of nowhere. Give "
                f"{'them' if len(doors) != 1 else 'it'} a new destination first:\n  "
                + "\n  ".join(r.where() for r in doors[:6]))


# --------------------------------------------------------------------------- #
# rewriting                                                                   #
# --------------------------------------------------------------------------- #

def _renumber(text: str, const: str, k: int,
              grammar: WarpGrammar) -> tuple[str, int, list[int]]:
    """Every reference to `const`'s warps in one file, after warp #k has gone.

    Re-scans the text it is given rather than trusting line numbers taken before
    the removal, so it does not matter whether the map's own entry has already
    been spliced out from under it.
    """
    lines = text.split("\n")
    fixed = 0
    dead: list[int] = []

    for i, line in enumerate(lines):
        hit = _match(line, const, grammar)
        if hit is None:
            continue
        macro, m, args = hit
        n = as_int(args[macro.at].strip())

        # A negative number is a dynamic warp the engine fills in, and 0 is not a
        # position in a 1-based list. Neither is ours to move. An unreadable one
        # never gets here — `_refuse` has already stopped the whole deletion.
        if n is None or n < 1 or n < k:
            continue

        if n > k:
            lines[i] = _swap(m, line, args, macro.at, str(n - 1))
            fixed += 1
        elif macro.door:
            # `n == k` on a door, in a dialect that can spell one — a grammar
            # without a `dead_door` refused this whole deletion above.
            lines[i] = _to_nowhere(m, line, args, grammar.dead_door, macro.name)
            dead.append(i + 1)
        # `n == k` on a non-door cannot happen: `_refuse` raised on it.

    return "\n".join(lines), fixed, dead


def _swap(m: re.Match, line: str, args: list[str], at: int, value: str) -> str:
    """Rewrite one argument and not one other character of the line.

    Two thirds of prism's warps write their coordinates in rgbasm hex, and an
    argument nobody changed comes back exactly as it was written — the same rule
    the editors rest on. So the argument's own surrounding whitespace is kept and
    only the token inside it is replaced.
    """
    old = args[at]
    out = list(args)
    out[at] = old.replace(old.strip(), value, 1)
    return f"{m.group('head')}{','.join(out)}{m.group('tail')}{_comment(line)}"


def _to_nowhere(m: re.Match, line: str, args: list[str], dead: DeadDoor,
                was: str) -> str:
    """A door whose destination has just been deleted, spelled the way this
    dialect spells one.

    The kept arguments come across **verbatim, spacing and all** — the same
    rule :func:`_swap` rests on, for the same reason. It matters more here than
    it looks: the family right-aligns its coordinates to two columns, so a
    stripped argument would leave a ragged line in a padded list, while prism's
    ``dummy_warp`` inherits the alignment of the ``warp_def`` it replaces.
    Neither dialect needs to be named to get its own house style back.
    """
    head = m.group("head")
    indent = head[:len(head) - len(head.lstrip())]
    # The gap between macro and first argument is part of the alignment and
    # was swallowed by the head, so it is put back rather than guessed at.
    gap = head.lstrip()[len(was):]
    kept = [args[i] for i in dead.keeps] + [f" {e}" for e in dead.extra]
    return (f"{indent}{dead.macro}{gap}{','.join(kept)}"
            f"{m.group('tail')}{_comment(line)}")


def _comment(line: str) -> str:
    i = line.find(";")
    return "" if i < 0 else line[i:]
