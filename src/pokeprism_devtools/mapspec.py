"""The description of a new map to wire in, plus the derived section names.

A map carries two names: a CamelCase *label* used for asm labels, INCLUDE/INCBIN
filenames and section names (``MtEmberSmallRoom``), and a SCREAMING_SNAKE
*const* used for the ``MAP_``/``GROUP_`` enum and the dimension macro
(``MT_EMBER_SMALL_ROOM``). They are not mechanically interconvertible
(``MtEmber`` → ``MT_EMBER``? ``MTEMBER``?), so both are carried explicitly.

The spec covers only the *wiring* fields — the ``map_header`` /
``map_header_2`` arguments, dimensions, group, and the paths to the
already-authored script ``.asm`` and ``.blk``. It does not author map content.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class MapSpec:
    label: str                  # "MtEmberSmallRoom"
    const: str                  # "MT_EMBER_SMALL_ROOM"
    group: int                  # existing group number to append into
    height: int
    width: int

    # primary header — map_header label, tileset, permission, landmark, music,
    #                   phone_service_flag, time_of_day/palette, fishing_group
    tileset: str
    permission: str
    landmark: str
    music: str
    palette: str
    fishgroup: str
    phone: int = 0

    # secondary header — map_header_2 label, const, border_block, conn_flags
    border_block: str = "0"
    conn_flags: str = "0"
    connections: list[str] = field(default_factory=list)

    # already-authored content, paths relative to the repo root
    script_asm: str = ""
    blk: str = ""

    @property
    def blk_lz(self) -> str:
        return f"{self.blk}.lz"

    @property
    def section_blockdata(self) -> str:
        return f"Map block data {self.label}"

    @property
    def section_script(self) -> str:
        return f"Map Scripts {self.label}"

    @property
    def section_secondary(self) -> str:
        return f"Second Map Header {self.label}"

    def validate(self, root: Path) -> list[str]:
        """Return a list of human-readable problems (empty == OK)."""
        problems: list[str] = []
        if not self.label or not self.label[0].isupper():
            problems.append(f"label '{self.label}' should be CamelCase")
        if self.const != self.const.upper():
            problems.append(f"const '{self.const}' should be SCREAMING_SNAKE_CASE")
        if self.group < 1:
            problems.append(f"group must be >= 1, got {self.group}")
        if not (0 < self.width < 256 and 0 < self.height < 256):
            problems.append(f"dimensions {self.height}x{self.width} out of range")
        if not self.script_asm:
            problems.append("script_asm path is required")
        elif not (root / self.script_asm).exists():
            problems.append(f"script asm not found: {self.script_asm}")
        if not self.blk:
            problems.append("blk path is required")
        elif not (root / self.blk).exists():
            problems.append(f"blk file not found: {self.blk}")
        return problems

    @classmethod
    def from_toml(cls, path: Path) -> "MapSpec":
        with path.open("rb") as f:
            data = tomllib.load(f)
        known = cls.__dataclass_fields__.keys()
        unknown = set(data) - set(known)
        if unknown:
            raise ValueError(f"{path.name}: unknown keys {sorted(unknown)}")
        return cls(**data)
