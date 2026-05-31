"""Parsers + formulas for pokemon species data.

Three small parsers (`data/base_stats/*.asm`, `data/movesets/*.asm`,
`battle/moves/moves.asm`) plus the stat / experience formulas the game
uses on the fly. Used by `prism-dev` to synthesize PartyMon structs from
just `(species, level)`.

Formula sources (line numbers in pokeprism, not this repo):
- Stat calc: `engine/move_mon.asm:1355-1513` (CalcPkmnStatC).
- Exp at level: `engine/experience.asm:40-172` + GrowthRates table at :208.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BaseStats:
    species: str
    hp: int
    atk: int
    def_: int
    spd: int
    sat: int
    sdf: int
    growth_rate: str  # "MEDIUM_FAST", "MEDIUM_SLOW", "FAST", "SLOW",
                      # "SLIGHTLY_FAST", "SLIGHTLY_SLOW", "ERRATIC", "FLUCTUATING"


@dataclass
class Learnset:
    species: str
    level_moves: list[tuple[int, str]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# base_stats/*.asm
# ---------------------------------------------------------------------------

_GROWTH_RATE_NAMES = {
    "MEDIUM_FAST", "SLIGHTLY_FAST", "SLIGHTLY_SLOW", "MEDIUM_SLOW",
    "FAST", "SLOW", "ERRATIC", "FLUCTUATING",
}


def parse_base_stats(root: Path) -> dict[str, BaseStats]:
    """Parse `data/base_stats/*.asm` → {species_name: BaseStats}."""
    out: dict[str, BaseStats] = {}
    for path in sorted((root / "data" / "base_stats").glob("*.asm")):
        bs = _parse_one_base_stats(path)
        if bs is not None:
            out[bs.species] = bs
    return out


def _parse_one_base_stats(path: Path) -> BaseStats | None:
    species = None
    base_six: list[int] | None = None
    growth: str | None = None
    for line in path.read_text().splitlines():
        line = _strip_comment(line).strip()
        if not line:
            continue
        if not line.startswith("db") and not line.startswith("dn"):
            continue
        if species is None:
            # first db: species id
            m = re.match(r"db\s+([A-Z_][A-Z0-9_]*)\s*$", line)
            if m:
                species = m.group(1)
                continue
        if base_six is None and line.startswith("db"):
            # second db: the six base stats
            parts = [p.strip() for p in line[2:].split(",")]
            if len(parts) == 6 and all(p.isdigit() for p in parts):
                base_six = [int(p) for p in parts]
                continue
        # Growth rate is a `db NAME` line where NAME is one of the 8 known.
        m = re.match(r"db\s+([A-Z_][A-Z0-9_]*)\b", line)
        if m and m.group(1) in _GROWTH_RATE_NAMES:
            growth = m.group(1)
            break
    if species is None or base_six is None or growth is None:
        return None
    return BaseStats(
        species=species,
        hp=base_six[0], atk=base_six[1], def_=base_six[2],
        spd=base_six[3], sat=base_six[4], sdf=base_six[5],
        growth_rate=growth,
    )


# ---------------------------------------------------------------------------
# movesets/*.asm  +  evos_attacks_pointers.asm
# ---------------------------------------------------------------------------

def parse_movesets(root: Path, species_in_order: list[str]) -> dict[str, Learnset]:
    """Parse `data/movesets/*.asm` keyed by species name.

    `species_in_order` is the species list in dex-id order, used to map
    the `EvosAttacksPointers` table entries (`dw XxxEvosAttacks`) onto
    species names.
    """
    label_to_species = _build_label_to_species_map(
        root / "data" / "evos_attacks_pointers.asm", species_in_order
    )
    out: dict[str, Learnset] = {}
    for path in sorted((root / "data" / "movesets").glob("*.asm")):
        ls = _parse_one_moveset(path, label_to_species)
        if ls is not None:
            out[ls.species] = ls
    return out


def _build_label_to_species_map(
    pointers_asm: Path, species_in_order: list[str]
) -> dict[str, str]:
    out: dict[str, str] = {}
    if not pointers_asm.exists():
        return out
    idx = 0
    for line in pointers_asm.read_text().splitlines():
        line = _strip_comment(line).strip()
        m = re.match(r"dw\s+([A-Za-z_][A-Za-z0-9_]*)\s*$", line)
        if m and idx < len(species_in_order):
            out[m.group(1)] = species_in_order[idx]
            idx += 1
    return out


def _parse_one_moveset(
    path: Path, label_to_species: dict[str, str]
) -> Learnset | None:
    text = path.read_text()
    m = re.search(r"^([A-Za-z_][A-Za-z0-9_]*):", text, re.MULTILINE)
    if not m:
        return None
    species = label_to_species.get(m.group(1))
    if species is None:
        return None

    # After the label come evolution lines (`db EVOLVE_*, ...`) terminated
    # by a `db 0`, followed by `db level, MOVE` pairs terminated by another
    # `db 0`. We only want the moves.
    in_moves = False
    moves: list[tuple[int, str]] = []
    for line in text.splitlines():
        line = _strip_comment(line).strip()
        if not line.startswith("db"):
            continue
        body = line[2:].strip()
        if body == "0":
            if in_moves:
                break
            in_moves = True
            continue
        if not in_moves:
            continue
        parts = [p.strip() for p in body.split(",")]
        if len(parts) == 2 and parts[0].isdigit():
            moves.append((int(parts[0]), parts[1]))
    return Learnset(species=species, level_moves=moves)


# ---------------------------------------------------------------------------
# battle/moves/moves.asm
# ---------------------------------------------------------------------------

def parse_move_pp(root: Path) -> dict[str, int]:
    """Parse `battle/moves/moves.asm` → {MOVE_NAME: PP}.

    Each move is a `move NAME, EFFECT, POWER, TYPE, CATEGORY, ACC, PP, EFFECT_CHANCE`
    macro invocation. PP is the 7th field.
    """
    path = root / "battle" / "moves" / "moves.asm"
    out: dict[str, int] = {}
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        line = _strip_comment(line).strip()
        if not line.startswith("move "):
            continue
        parts = [p.strip() for p in line[5:].split(",")]
        if len(parts) < 7:
            continue
        name = parts[0]
        try:
            pp = int(parts[6])
        except ValueError:
            continue
        out[name] = pp
    return out


# ---------------------------------------------------------------------------
# Formulas
# ---------------------------------------------------------------------------

# (a, b, c, d, e) such that exp = (a*n³)/b + c*n² + d*n - e, max 0.
# Lifted from `GrowthRates` in engine/experience.asm:208.
_GROWTH_COEFFS: dict[str, tuple[int, int, int, int, int]] = {
    "MEDIUM_FAST":   (1, 1,   0,   0,   0),
    "SLIGHTLY_FAST": (3, 4,  10,   0,  30),
    "SLIGHTLY_SLOW": (3, 4,  20,   0,  70),
    "MEDIUM_SLOW":   (6, 5, -15, 100, 140),
    "FAST":          (4, 5,   0,   0,   0),
    "SLOW":          (5, 4,   0,   0,   0),
}


def exp_at_level(growth_rate: str, level: int) -> int:
    if level < 2:
        return 0
    n = level
    if growth_rate == "ERRATIC":
        return _erratic_exp(n)
    if growth_rate == "FLUCTUATING":
        return _fluctuating_exp(n)
    coeffs = _GROWTH_COEFFS.get(growth_rate)
    if coeffs is None:
        raise ValueError(f"unknown growth rate: {growth_rate!r}")
    a, b, c, d, e = coeffs
    cubic = (a * n * n * n) // b
    return max(0, cubic + c * n * n + d * n - e)


def _erratic_exp(n: int) -> int:
    # See engine/experience.asm:244 (ErraticGrowth).
    cube = n * n * n
    if n < 51:
        return (cube * (100 - n)) // 50
    if n < 69:
        return (cube * (150 - n)) // 100
    if n < 99:
        return (cube * ((1911 - 10 * n) // 3)) // 500
    return (cube * (160 - n)) // 100


def _fluctuating_exp(n: int) -> int:
    # See engine/experience.asm:215 (FluctuatingGrowth).
    cube = n * n * n
    if n < 16:
        return (cube * (((n + 1) // 3) + 24)) // 50
    if n < 37:
        return (cube * (n + 14)) // 50
    return (cube * ((n // 2) + 32)) // 50


def calc_stat(base: int, dv: int, stat_exp: int, level: int, *, is_hp: bool) -> int:
    """Compute one stat (HP if `is_hp`, otherwise Atk/Def/Spd/SpA/SpD).

    `stat_exp` is the 2-byte StatExp value (0..65535). The game uses
    `floor(sqrt(stat_exp)) // 4` as the EV-equivalent.
    """
    inner = 2 * base + dv + (math.isqrt(max(0, stat_exp)) // 4)
    val = (inner * level) // 100
    val += (level + 10) if is_hp else 5
    return min(val, 999)


def hp_dv(atk_dv: int, def_dv: int, spd_dv: int, spc_dv: int) -> int:
    """Gen 2 HP DV is the bit-0 of the other four DVs concatenated."""
    return (
        ((atk_dv & 1) << 3)
        | ((def_dv & 1) << 2)
        | ((spd_dv & 1) << 1)
        | (spc_dv & 1)
    )


def default_moves_for_level(learnset: Learnset, level: int) -> list[str]:
    """The last 4 moves learnable at or below `level`. Mirrors what the
    in-game level-up loop leaves the mon with after CALL FillMoves."""
    eligible = [m for (lvl, m) in learnset.level_moves if lvl <= level]
    return eligible[-4:] if eligible else []


def _strip_comment(line: str) -> str:
    semi = line.find(";")
    return line if semi < 0 else line[:semi]
