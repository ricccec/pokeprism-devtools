"""Rules about the data a map hangs off itself: block data, trainers, wild mons.

Each of these lives in a *different file* from the map, joined only by a name or
an index — which is exactly why they drift apart without the build noticing.
"""

from __future__ import annotations

import re

from ..shared import mapsource, trainerparty, wilddata
from .context import LintContext
from .diagnostics import Diagnostic, Severity

_TRAINER_RE = re.compile(r"^\s*trainer\s+(\w+)\s*,\s*(\w+)\s*,\s*(\w+)\s*,")
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

def trainer_party(ctx: LintContext) -> list[Diagnostic]:
    """`trainer FLAG, CLASS, party_id, …` — party_id is a 1-based index into that
    class's group.

    The class resolves to its group through ``TrainerGroups`` in
    trainers/trainer_pointers.asm, a table the engine indexes by class id. Point
    the index past the end of the group it lands in and the game reads whatever
    follows as a Pokémon party.
    """
    out = []
    for const, info in sorted(ctx.map_infos.items()):
        path = ctx.rel(info.path)
        for i, line in enumerate(info.path.read_text().split("\n"), start=1):
            m = _TRAINER_RE.match(line)
            if not m:
                continue
            cls, party = m.group(2), m.group(3)
            if not party.isdigit():
                continue            # cited by const (RIVAL1_3) — not ours to resolve

            group = ctx.trainer_groups.get(cls)
            if group is None:
                continue            # unbacked class — trainer_class reports that
            if not 1 <= int(party) <= group.count:
                out.append(Diagnostic(
                    "trainer-party", Severity.ERROR, path, i,
                    f"trainer uses {cls} party #{party}, but {group.label} has "
                    f"{group.count} part{'y' if group.count == 1 else 'ies'} "
                    f"(valid: 1-{group.count})",
                ))
    return out


def trainer_class(ctx: LintContext) -> list[Diagnostic]:
    """A map may only battle a trainer class that has parties behind it.

    ``TrainerGroups`` is indexed by class id with no bounds check, so a class
    whose slot is ``dw NULL`` — or that has no slot at all, because the table is
    shorter than the enum — yields a garbage party pointer. It assembles, and it
    is only visible when the battle starts.
    """
    unbacked = trainerparty.unbacked_classes(ctx.root)
    out = []
    for const, info in sorted(ctx.map_infos.items()):
        path = ctx.rel(info.path)
        for i, line in enumerate(info.path.read_text().split("\n"), start=1):
            m = _TRAINER_RE.match(line)
            if m and (why := unbacked.get(m.group(2))):
                out.append(Diagnostic(
                    "trainer-class", Severity.ERROR, path, i,
                    f"trainer class {m.group(2)} {why}",
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


def wild_rate(ctx: LintContext) -> list[Diagnostic]:
    """An encounter rate should be written `N percent`, not as a bare byte.

    `percent` is `EQUS "* $ff / 100"` (macros.asm): the engine compares a random
    byte against the rate, so the scale is 255, not 100. Write `db 3` where you
    meant `3 percent` and you get 3/255 = 1.2% instead of 2.7% — encounters that
    are silently less than half as frequent as the number reads.
    """
    out = []
    for path in sorted((ctx.root / "data" / "wild").glob("*.asm")):
        if path.stem == "fish":
            continue
        region, _, kind = path.stem.rpartition("_")
        if kind not in wilddata.SLOTS:
            continue
        try:
            table = wilddata.load(ctx.root, region, kind)
        except wilddata.WildDataError:
            continue                    # a malformed table is blk_size's kind of problem

        for block in table.blocks:
            if not block.raw_rates:
                continue
            shown = ", ".join(str(r) for r in block.rates)
            actual = block.rate_bytes[0] * 100 / 255
            out.append(Diagnostic(
                "wild-rate", Severity.WARNING, ctx.rel(path), block.start + 1,
                f"{block.map_const}'s encounter rate is `db {shown}` — a bare byte, so "
                f"it means {actual:.1f}%, not {block.rates[0]}%. Every other block in "
                f"the repo writes `{block.rates[0]} percent` (which is byte "
                f"{block.rates[0] * wilddata.RATE_SCALE // 100})",
            ))
    return out


ALL = (blk_size, trainer_party, trainer_class, wild_region, wild_rate)
