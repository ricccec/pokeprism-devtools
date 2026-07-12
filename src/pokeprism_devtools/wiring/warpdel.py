"""Deleting a warp, and the repo-wide renumber that has to travel with it.

``warp_def y, x, warp_to, MAP`` — ``warp_to`` is a **1-based index into MAP's own
warp list**. A warp is therefore not an identity, it is a *position*: take one
out and every warp below it in that map slides up by one, and every reference in
the repo that counted past the hole now counts one too many. That is why adding
a warp is safe (append, and nothing moves) and deleting one is not.

Exactly two things in this repo index a warp by number, and both are handled:

    warp_def y, x, n, M     a door on some map that arrives on M's warp n
    warpmod  n, M           a script re-pointing a `dummy_warp` at runtime

Nothing else does. No other macro in ``macros/`` takes a warp id, and ``data/``
does not mention warps at all — so the two patterns below are the whole surface,
and a scan of them is exhaustive. The rule, for a deleted warp #k of map M:

    n > k    ->  n - 1        the warp it aimed at slid up
    n == k   ->  it aimed at the warp that is gone: the door now leads nowhere
    n < k    ->  untouched
    n == -1  ->  untouched — a *dynamic* warp, filled in at runtime

A door that led to the deleted warp becomes a ``dummy_warp y, x``. Not a deleted
line: deleting it would renumber *that* map's warps and cascade the whole problem
outward, one map at a time, until the repo stopped assembling. ``dummy_warp``
keeps every index on every map exactly where it was and costs one dead door,
which the caller is told about by name so a human can go and decide what it
should really do.

**`dummy_warp`, and never a bare `-1`.** They both assemble to a -1 warp number,
which is why it is tempting to treat them alike, and they are not alike:
``dummy_warp`` emits ``db -1, 0, 0`` — group 0, map 0, *nowhere*. A
``warp_def y, x, -1, M`` keeps a real destination map and lets ``CopyWarpData``
substitute ``wBackupWarpNumber``, so a -1 warp on a map nobody ran ``warpmod``
for drops the player somewhere unpredictable. Two of those exist here on purpose
(PokecenterBackroom). This module leaves them alone and never writes a new one.

**It refuses rather than guess.** A ``warp_to`` it cannot read as a number is a
reference it cannot renumber, so the whole deletion is refused, naming the line.
Likewise a ``warpmod`` that pointed *at* the warp being deleted: there is no
dummy form of a warpmod, and quietly leaving it aimed at whatever slid into the
slot is worse than saying no.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ..shared import eventheader as eh, mapsource
from ..shared.edits import Edit
from ..shared.eventheader import ListKind

#: Which argument holds the warp number, and which holds the map, in each macro.
_WARP_TO, _WARP_MAP = 2, 3
_MOD_TO, _MOD_MAP = 0, 1

_WARP_RE = re.compile(r"^(?P<head>\s*warp_def\s+)(?P<args>.*\S)(?P<tail>\s*)$")
_MOD_RE = re.compile(r"^(?P<head>\s*warpmod\s+)(?P<args>.*\S)(?P<tail>\s*)$")

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


def delete_warp(root: Path, map_const: str, index: int) -> Deletion:
    """Take warp #(index+1) out of `map_const`, and fix the whole repo behind it."""
    label = {c: l for l, c in mapsource.header_pairs(root)}.get(map_const)
    if label is None:
        raise WarpDelError(f"{map_const} is not a wired map")

    path = root / "maps" / f"{label}.asm"
    try:
        header = eh.parse_map(path)
    except (eh.UnparseableHeader, FileNotFoundError) as exc:
        raise WarpDelError(f"{map_const}'s event header can't be read, so its "
                           f"warps can't be counted: {exc}") from exc

    warps = header.warps
    if not 0 <= index < len(warps):
        raise WarpDelError(
            f"{map_const} has {len(warps)} warp{'s' if len(warps) != 1 else ''}, "
            f"so there is no warp #{index + 1} to delete")

    k = index + 1
    gone = warps[index]

    # Read the repo as it stands, and settle every question about it, before
    # anything is rewritten. A refusal has to happen while nothing has moved.
    sources = _sources(root)
    refs = _refs(sources, map_const)
    _refuse(refs, k, map_const)

    rel = f"maps/{label}.asm"
    header.remove_entry(ListKind.WARPS, index)

    # The map's own file takes both changes — the removal and, if it warps to
    # itself, the renumber — and an Edit carries the *whole* file, so they have
    # to be composed in one buffer or the second silently drops the first.
    done = {rel: header.to_text()}

    edits: list[Edit] = []
    moved = 0
    nowhere: list[str] = []
    for r in sorted({ref.rel for ref in refs} | {rel}):
        was = sources[r]
        text, fixed, dead = _renumber(done.get(r, was), map_const, k)
        moved += fixed
        nowhere += [f"{r}:{n}" for n in dead]
        edits.append(Edit(r, text != was, _detail(r, rel, k, fixed, len(dead)),
                          text, base=was))

    warnings = []
    if moved:
        warnings.append(
            f"{moved} warp{'s' if moved != 1 else ''} elsewhere counted past #{k} "
            f"and {'have' if moved != 1 else 'has'} been renumbered.")
    for door in nowhere:
        warnings.append(f"{door} led to this warp and is now a `dummy_warp` — a "
                        f"door to nowhere. Nothing else moved; go and give it a "
                        f"destination when you know what it should be.")

    y, x = gone.coords
    return Deletion(f"removed warp #{k} of {map_const} at ({y}, {x})",
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
    macro: str           # warp_def | warpmod
    n: int | None        # the warp number it names, or None if unreadable
    raw: str

    def where(self) -> str:
        return f"{self.rel}:{self.lineno + 1}: {self.raw.strip()}"


def _refs(sources: dict[str, str], const: str) -> list[_Ref]:
    refs: list[_Ref] = []
    for rel, text in sources.items():
        for i, line in enumerate(text.split("\n")):
            hit = _match(line, const)
            if hit is None:
                continue
            macro, _, args, at, _ = hit
            refs.append(_Ref(rel, i, macro, eh.as_int(args[at].strip()), line))
    return refs


def _match(line: str, const: str):
    """The warp macro on this line, if it names `const`'s warps.

    Returns (macro, match, args, warp-arg, map-arg). The macros take no strings,
    so the first `;` is always the start of a comment and nothing else.
    """
    code = line.split(";", 1)[0]
    for macro, pattern, at, at_map in (("warp_def", _WARP_RE, _WARP_TO, _WARP_MAP),
                                       ("warpmod", _MOD_RE, _MOD_TO, _MOD_MAP)):
        m = pattern.match(code)
        if not m:
            continue
        args = m.group("args").split(",")
        if len(args) <= max(at, at_map) or args[at_map].strip() != const:
            return None
        return macro, m, args, at, at_map
    return None


def _refuse(refs: list[_Ref], k: int, const: str) -> None:
    """Everything this module will not do, decided before it has done anything."""
    blind = [r.where() for r in refs if r.n is None]
    if blind:
        raise WarpDelError(
            f"{len(blind)} reference{'s' if len(blind) != 1 else ''} to {const}'s "
            f"warps write the warp number as something that cannot be read as a "
            f"number, so it cannot be renumbered. Deleting a warp would silently "
            f"repoint {'them' if len(blind) != 1 else 'it'}:\n  "
            + "\n  ".join(blind[:6]))

    stuck = [r.where() for r in refs if r.macro == "warpmod" and r.n == k]
    if stuck:
        raise WarpDelError(
            f"warp #{k} of {const} is the warp {len(stuck)} `warpmod` "
            f"{'calls' if len(stuck) != 1 else 'call'} re-point{'' if len(stuck) != 1 else 's'} "
            f"a door at, and there is no such thing as a dummy warpmod. Rewrite "
            f"{'them' if len(stuck) != 1 else 'it'} first:\n  " + "\n  ".join(stuck[:6]))


# --------------------------------------------------------------------------- #
# rewriting                                                                   #
# --------------------------------------------------------------------------- #

def _renumber(text: str, const: str, k: int) -> tuple[str, int, list[int]]:
    """Every reference to `const`'s warps in one file, after warp #k has gone.

    Re-scans the text it is given rather than trusting line numbers taken before
    the removal, so it does not matter whether the map's own entry has already
    been spliced out from under it.
    """
    lines = text.split("\n")
    fixed = 0
    dead: list[int] = []

    for i, line in enumerate(lines):
        hit = _match(line, const)
        if hit is None:
            continue
        macro, m, args, at, _ = hit
        n = eh.as_int(args[at].strip())

        # A negative number is a dynamic warp the engine fills in, and 0 is not a
        # position in a 1-based list. Neither is ours to move. An unreadable one
        # never gets here — `_refuse` has already stopped the whole deletion.
        if n is None or n < 1 or n < k:
            continue

        if n > k:
            lines[i] = _swap(m, line, args, at, str(n - 1))
            fixed += 1
        elif macro == "warp_def":
            lines[i] = _to_nowhere(m, line, args)
            dead.append(i + 1)
        # `n == k` on a warpmod cannot happen: `_refuse` raised on it.

    return "\n".join(lines), fixed, dead


def _swap(m: re.Match, line: str, args: list[str], at: int, value: str) -> str:
    """Rewrite one argument and not one other character of the line.

    Two thirds of this repo's warps write their coordinates in rgbasm hex, and an
    argument nobody changed comes back exactly as it was written — the same rule
    the editors rest on. So the argument's own surrounding whitespace is kept and
    only the token inside it is replaced.
    """
    old = args[at]
    out = list(args)
    out[at] = old.replace(old.strip(), value, 1)
    return f"{m.group('head')}{','.join(out)}{m.group('tail')}{_comment(line)}"


def _to_nowhere(m: re.Match, line: str, args: list[str]) -> str:
    """A `warp_def` whose destination has just been deleted, as a `dummy_warp`.

    The coordinates come across verbatim: the door is still a door, it is still in
    the same place, and it still holds its position in its map's warp list — which
    is the whole point of not deleting the line.
    """
    indent = m.group("head")[:len(m.group("head")) - len(m.group("head").lstrip())]
    y, x = args[0].strip(), args[1].strip()
    return f"{indent}dummy_warp {y}, {x}{m.group('tail')}{_comment(line)}"


def _comment(line: str) -> str:
    i = line.find(";")
    return "" if i < 0 else line[i:]
