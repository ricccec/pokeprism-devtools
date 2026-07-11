"""Rules about the data a map hangs off itself: block data, trainers, wild mons.

Each of these lives in a *different file* from the map, joined only by a name or
an index — which is exactly why they drift apart without the build noticing.
"""

from __future__ import annotations

import re

from ..shared import mapsource
from .context import LintContext
from .diagnostics import Diagnostic, Severity

_TRAINER_RE = re.compile(r"^\s*trainer\s+(\w+)\s*,\s*(\w+)\s*,\s*(\d+)\s*,")
_GROUP_LABEL_RE = re.compile(r"^(\w+)Group:")
_PARTY_NAME_RE = re.compile(r'^\s*db\s+"[^"]*@"')
_WILDMAP_RE = re.compile(r"^\s*wildmap\s+(\w+)")


def blk_size(ctx: LintContext) -> list[Diagnostic]:
    """A map's block-data file must be exactly width × height bytes.

    The engine reads `height` rows of `width` blocks straight out of the file.
    Too small and it reads past the end; too large and the map was authored at
    different dimensions than it now declares — the leftovers are dropped, and
    if the *width* is what changed, every row lands shifted.
    """
    out = []
    for const, info in sorted(ctx.map_infos.items()):
        mapdef = ctx.map_defs.get(const)
        blk = mapsource.blk_path(ctx.root, info.label)
        if mapdef is None or blk is None:
            continue
        path = ctx.root / blk
        if not path.exists():
            continue

        actual = path.stat().st_size
        expected = mapdef.width * mapdef.height
        if actual == expected:
            continue

        where = ctx.rel(info.path)
        if actual < expected:
            out.append(Diagnostic(
                "blk-size", Severity.ERROR, where, 0,
                f"{blk} is {actual} bytes but {const} declares {mapdef.width}x"
                f"{mapdef.height} = {expected} — the engine reads {expected - actual} "
                f"bytes past the end of the file",
            ))
        else:
            out.append(Diagnostic(
                "blk-size", Severity.WARNING, where, 0,
                f"{blk} is {actual} bytes but {const} declares {mapdef.width}x"
                f"{mapdef.height} = {expected} — {actual - expected} trailing bytes are "
                f"ignored, so the map and its block data were authored at different "
                f"sizes",
            ))
    return out


# --------------------------------------------------------------------------- #
# trainers                                                                    #
# --------------------------------------------------------------------------- #

def _trainer_groups(ctx: LintContext) -> dict[str, tuple[str, int]]:
    """Trainer class -> (group label, number of parties in it).

    Parties are stored **positionally** in trainers/groups/<class>.asm: the map
    refers to one by a 1-based index, so the only thing tying them together is
    counting. Classes are matched to their group by name, normalised — the enum
    that formally links them is built from custom `enum`/`trainerclass` macros
    this parser doesn't model, and a name we can't resolve is skipped rather
    than guessed at.
    """
    groups: dict[str, tuple[str, int]] = {}
    for path in sorted((ctx.root / "trainers" / "groups").glob("*.asm")):
        label: str | None = None
        parties = 0
        for line in path.read_text().split("\n"):
            m = _GROUP_LABEL_RE.match(line)
            if m:
                if label:
                    groups[_normalise(label)] = (label, parties)
                label, parties = m.group(1), 0
                continue
            if label and _PARTY_NAME_RE.match(line):
                parties += 1        # each party opens with its trainer's name
        if label:
            groups[_normalise(label)] = (label, parties)
    return groups


def _normalise(name: str) -> str:
    return name.replace("_", "").lower()


def trainer_party(ctx: LintContext) -> list[Diagnostic]:
    """`trainer FLAG, CLASS, party_id, …` — party_id is a 1-based index into
    that class's group file. Point it past the end and the game reads whatever
    follows as a Pokémon party."""
    groups = _trainer_groups(ctx)
    out = []
    for const, info in sorted(ctx.map_infos.items()):
        path = ctx.rel(info.path)
        for i, line in enumerate(info.path.read_text().split("\n"), start=1):
            m = _TRAINER_RE.match(line)
            if not m:
                continue
            cls, party = m.group(2), int(m.group(3))

            entry = groups.get(_normalise(cls))
            if entry is None:
                continue            # class we can't resolve to a group — say nothing
            label, count = entry
            if not 1 <= party <= count:
                out.append(Diagnostic(
                    "trainer-party", Severity.ERROR, path, i,
                    f"trainer uses {cls} party #{party}, but {label} has {count} "
                    f"part{'y' if count == 1 else 'ies'} (valid: 1-{count})",
                ))
    return out


# --------------------------------------------------------------------------- #
# wild data                                                                   #
# --------------------------------------------------------------------------- #

def wild_region(ctx: LintContext) -> list[Diagnostic]:
    """A map's `wildmap` block must live in the wild file for the map's region.

    At runtime `RegionCheck` (engine/landmarks.asm) picks the wild table purely
    from the map's *landmark*. Put the block in the wrong region's file and the
    engine consults a table that doesn't contain the map — so the grass is
    simply empty. Nothing errors.
    """
    regions = ctx.landmark_regions
    out = []
    for path in sorted((ctx.root / "data" / "wild").glob("*.asm")):
        region = path.stem.rsplit("_", 1)[0]
        if region == "swarm" or path.stem == "fish":
            continue                # swarm tables are keyed differently
        rel = ctx.rel(path)

        for i, line in enumerate(path.read_text().split("\n"), start=1):
            m = _WILDMAP_RE.match(line)
            if not m:
                continue
            const = m.group(1)
            expected = ctx.region_of(const)
            if expected is None or expected == region:
                continue
            landmark = ctx.primary_headers[const].landmark if const in ctx.primary_headers else "?"
            out.append(Diagnostic(
                "wild-region", Severity.ERROR, rel, i,
                f"{const}'s wild data is in the {region} table, but its landmark "
                f"({landmark}) puts it in {expected} — RegionCheck will look it up in "
                f"{expected}_{path.stem.rsplit('_', 1)[1]}.asm and find nothing, so the "
                f"map has no encounters",
            ))
    return out


ALL = (blk_size, trainer_party, wild_region)
