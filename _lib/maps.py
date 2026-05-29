"""Parser for `constants/map_dimension_constants.asm`.

(Despite the name, `map_constants.asm` is mostly *not* about individual maps
— it INCLUDEs `map_dimension_constants.asm` for that. This parser targets
the actual file with the `mapgroup` lines.)

Maps in pokeprism are identified by a (group, map_id) pair, not a single ID.
The constants file uses two custom macros (`macros/map.asm:155-165`) on top
of the regular `const_def`/`const`/`enum` machinery:

    newgroup [; comment]
        ; const_value = const_value + 1
        ; enum_start 1
        ; → bumps the group counter, resets the within-group enum

    mapgroup NAME, H, W
        ; GROUP_NAME EQU const_value
        ; enum MAP_NAME             ; assigns __enum__, then __enum__ += 1
        ; NAME_HEIGHT EQU H
        ; NAME_WIDTH  EQU W

So a single `mapgroup CAPER_RIDGE, 9, 20` after one `newgroup` produces:
    GROUP_CAPER_RIDGE = 1
    MAP_CAPER_RIDGE   = 1
    CAPER_RIDGE_HEIGHT = 9
    CAPER_RIDGE_WIDTH  = 20

This parser ignores everything else in the file (the `const_def`/`const`
blocks for spawns, signposts, etc. — those are handled by the generic
constants parser).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MapDef:
    name: str       # bare name (e.g. "CAPER_RIDGE")
    group: int      # group ID (= GROUP_<name>)
    map_id: int     # within-group enum (= MAP_<name>)
    height: int
    width: int


_NEWGROUP_RE = re.compile(r"^\s*newgroup\b")
_MAPGROUP_RE = re.compile(
    r"^\s*mapgroup\s+([A-Za-z_][A-Za-z0-9_]*)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*$"
)


def parse_maps(path: Path) -> list[MapDef]:
    """Walk map_constants.asm and return one MapDef per `mapgroup` line."""
    out: list[MapDef] = []
    group_counter = 0
    enum_counter = 1  # not used until first newgroup, but safe default

    with path.open("r", encoding="utf-8") as f:
        for raw in f:
            line = _strip_comment(raw)
            if not line.strip():
                continue

            if _NEWGROUP_RE.match(line):
                group_counter += 1
                enum_counter = 1
                continue

            m = _MAPGROUP_RE.match(line)
            if m:
                name, height, width = m.group(1), int(m.group(2)), int(m.group(3))
                out.append(
                    MapDef(
                        name=name,
                        group=group_counter,
                        map_id=enum_counter,
                        height=height,
                        width=width,
                    )
                )
                enum_counter += 1
                continue

    return out


def _strip_comment(line: str) -> str:
    semi = line.find(";")
    return line if semi < 0 else line[:semi]
