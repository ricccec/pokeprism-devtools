"""Model of ``data/wild/<region>_{grass,water}.asm`` — a map's wild encounters.

A ``wildmap`` block is a fixed-size record, and the engine reads it positionally::

    wildmap ACQUA_START          ; db group, id
    db 2 percent, 2 percent, 2 percent    ; encounter rate, one per time of day
    ; morn
    db 2, SHINX                  ; NUM_GRASSMON (7) slots, each `db level, species`
    ...  x7
    ; day
    ...  x7
    ; nite
    ...  x7

Water is the same with one rate and NUM_WATERMON (3) slots. The slot counts are
not negotiable — ``GRASS_WILDDATA_LENGTH`` is baked into the table stride, so a
block with six grass slots doesn't shift *its* map's encounters, it shifts every
map after it in the file.

**Which file a block goes in is decided by the map's landmark**, not by its name
or its group: ``RegionCheck`` picks the table from the landmark alone (see
:mod:`.landmarks`). File a block under the wrong region and the engine looks the
map up in a table that doesn't contain it, finds nothing, and the grass is
simply empty — no error, anywhere. So :func:`table_for` resolves the region
rather than letting a caller name it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import landmarks
from ...shared.edits import Edit

_DIR = "data/wild"

GRASS, WATER = "grass", "water"

#: NUM_GRASSMON / NUM_WATERMON in constants/pokemon_data_constants.asm.
SLOTS = {GRASS: 7, WATER: 3}

#: A grass block carries one encounter rate and one slot table per time of day;
#: water has a single unnamed one.
TIMES = {GRASS: ("morn", "day", "nite"), WATER: ("",)}

_INDENT = "\t"

_WILDMAP_RE = re.compile(r"^\s*wildmap\s+(\w+)\s*(?:;.*)?$")
_END_RE = re.compile(r"^\s*endwildmap\s*(?:;.*)?$")
_RATES_RE = re.compile(r"^\s*db\s+(.+?)\s*(?:;.*)?$")
_MON_RE = re.compile(r"^\s*db\s+(\d+)\s*,\s*(\w+)\s*(?:;.*)?$")
_RATE_RE = re.compile(r"^(\d+)(\s+percent)?$")

#: `percent EQUS "* $ff / 100"` (macros.asm) — the rate byte the engine compares a
#: random number against is a fraction of 255, not of 100. So `3 percent` is byte
#: 7, and a bare `db 3` is byte 3, i.e. 1.2%.
RATE_SCALE = 0xFF


class WildDataError(RuntimeError):
    pass


@dataclass(frozen=True)
class Encounter:
    level: int
    species: str


@dataclass
class WildBlock:
    map_const: str
    rates: list[int]                                  # one per time of day, as written
    mons: dict[str, list[Encounter]] = field(default_factory=dict)
    start: int = 0                                    # 0-based `wildmap` line
    end: int = 0                                      # 0-based last line of the block
    #: True when the rates were written as bare bytes (`db 3`) rather than
    #: `3 percent`. They then mean 3/255, not 3/100 — see RATE_SCALE.
    raw_rates: bool = False

    @property
    def rate_bytes(self) -> list[int]:
        """What the engine actually compares against, whichever way it was written."""
        if self.raw_rates:
            return list(self.rates)
        return [r * RATE_SCALE // 100 for r in self.rates]


@dataclass
class WildTable:
    path: Path
    region: str
    kind: str                                         # GRASS | WATER
    lines: list[str]
    blocks: list[WildBlock] = field(default_factory=list)

    @property
    def times(self) -> tuple[str, ...]:
        return TIMES[self.kind]

    @property
    def slots(self) -> int:
        return SLOTS[self.kind]

    def find(self, map_const: str) -> WildBlock | None:
        return next((b for b in self.blocks if b.map_const == map_const), None)

    def to_text(self) -> str:
        return "\n".join(self.lines)

    # -- write -------------------------------------------------------------- #
    def set_block(self, map_const: str, rates: list[int],
                  mons: dict[str, list[Encounter]]) -> WildBlock:
        """Give `map_const` these encounters, replacing its block if it has one.

        Every time of day must be filled to exactly `slots` entries: the record
        is fixed-size, and a short one shifts every map below it in the table.
        """
        self._check(map_const, rates, mons)
        block = _render(self.kind, map_const, rates, mons)

        existing = self.find(map_const)
        if existing:
            self.lines[existing.start:existing.end + 1] = block
        else:
            self.lines[self._append_at():self._append_at()] = [*block, ""]

        self._reparse()
        return self.find(map_const)                   # type: ignore[return-value]

    def _check(self, map_const: str, rates: list[int],
               mons: dict[str, list[Encounter]]) -> None:
        if len(rates) != len(self.times):
            raise WildDataError(
                f"{self.kind} needs {len(self.times)} encounter rate(s) "
                f"({', '.join(t or 'all day' for t in self.times)}), got {len(rates)}"
            )
        for rate in rates:
            if not 0 <= rate <= 100:
                raise WildDataError(f"encounter rate {rate} is not a percentage")
        for time in self.times:
            got = mons.get(time, [])
            if len(got) != self.slots:
                label = f"{time} " if time else ""
                raise WildDataError(
                    f"{map_const}: {self.kind} needs exactly {self.slots} "
                    f"{label}slots, got {len(got)} — the record is fixed-size, and a "
                    f"short one shifts every map below it in {self.path.name}"
                )

    def _append_at(self) -> int:
        """Where a new block goes: after the last one, before `endwildmap`."""
        for i, line in enumerate(self.lines):
            if _END_RE.match(line):
                return i
        raise WildDataError(f"{self.path}: no `endwildmap` — can't tell where the table ends")

    def _reparse(self) -> None:
        self.blocks = _parse_blocks(self.path, self.lines, self.kind)

    def to_edit(self, root: Path, detail: str) -> Edit:
        rel = str(self.path.relative_to(root))
        text = self.to_text()
        base = self.path.read_text()
        changed = text != base
        return Edit(rel, changed, detail, text if changed else "", base=base)


def _render(kind: str, map_const: str, rates: list[int],
            mons: dict[str, list[Encounter]]) -> list[str]:
    rate_expr = ", ".join(f"{r} percent" for r in rates)
    out = [f"{_INDENT}wildmap {map_const}", f"{_INDENT}db {rate_expr}"]
    for time in TIMES[kind]:
        if time:
            out.append(f"{_INDENT}; {time}")
        out += [f"{_INDENT}db {e.level}, {e.species}" for e in mons[time]]
    return out


# --------------------------------------------------------------------------- #
# loading                                                                     #
# --------------------------------------------------------------------------- #

def table_for(root: Path, map_const: str, kind: str) -> WildTable:
    """The `kind` table `map_const`'s encounters belong in — resolved through its
    landmark, because that is what the engine does."""
    if kind not in SLOTS:
        raise WildDataError(f"{kind!r} is not a wild table ({GRASS} or {WATER})")

    region = landmarks.region_of_map(root, map_const)
    if region is None:
        raise WildDataError(
            f"can't tell which region {map_const} is in — it has no map_header, or "
            f"its landmark sits before the first `region_def` in "
            f"constants/landmark_constants.asm"
        )
    return load(root, region, kind)


def load(root: Path, region: str, kind: str) -> WildTable:
    path = root / _DIR / f"{region}_{kind}.asm"
    if not path.exists():
        raise WildDataError(f"{path} not found — {region} has no {kind} table")

    lines = path.read_text().split("\n")
    table = WildTable(path=path, region=region, kind=kind, lines=lines)
    table.blocks = _parse_blocks(path, lines, kind)
    return table


def _parse_blocks(path: Path, lines: list[str], kind: str) -> list[WildBlock]:
    """Every `wildmap` block, read positionally — which is how the engine reads
    them. The `; morn` comments are decoration; the slot *counts* carry the
    meaning, so this splits on those and would notice a block of the wrong size.
    """
    times, slots = TIMES[kind], SLOTS[kind]
    starts = [i for i, ln in enumerate(lines) if _WILDMAP_RE.match(ln)]
    blocks: list[WildBlock] = []

    for n, start in enumerate(starts):
        stop = starts[n + 1] if n + 1 < len(starts) else len(lines)
        const = _WILDMAP_RE.match(lines[start]).group(1)     # type: ignore[union-attr]

        rates: list[int] = []
        raw = False
        mons: list[Encounter] = []
        last = start
        for i in range(start + 1, stop):
            line = lines[i]
            if m := _MON_RE.match(line):
                mons.append(Encounter(int(m.group(1)), m.group(2)))
                last = i
            elif not rates and (m := _RATES_RE.match(line)):
                rates, raw = _rates(path, i, m.group(1))
                last = i

        expected = slots * len(times)
        if len(mons) != expected:
            raise WildDataError(
                f"{path}:{start + 1}: {const}'s block has {len(mons)} encounter slots, "
                f"but a {kind} record is exactly {expected} — the table is read at a "
                f"fixed stride, so this shifts every map below it"
            )
        blocks.append(WildBlock(
            map_const=const, rates=rates, raw_rates=raw, start=start, end=last,
            mons={t: mons[j * slots:(j + 1) * slots] for j, t in enumerate(times)},
        ))
    return blocks


def _rates(path: Path, i: int, expr: str) -> tuple[list[int], bool]:
    """The rates, and whether they were written as bare bytes rather than
    `N percent` — which changes what they mean by a factor of 2.55."""
    out: list[int] = []
    percent: list[bool] = []
    for part in expr.split(","):
        m = _RATE_RE.match(part.strip())
        if not m:
            raise WildDataError(
                f"{path}:{i + 1}: {part.strip()!r} is not an encounter rate "
                f"(`N percent`, or a bare byte)"
            )
        out.append(int(m.group(1)))
        percent.append(bool(m.group(2)))

    if any(percent) and not all(percent):
        raise WildDataError(f"{path}:{i + 1}: some rates say `percent` and some don't")
    return out, not any(percent)
