"""Parser for RGBDS .map link-map files."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


REGION_CAPACITY: dict[str, int] = {
    "ROM0": 16_384,
    "ROMX": 16_384,
    "VRAM": 8_192,
    "SRAM": 8_192,
    "WRAM0": 4_096,
    "WRAMX": 4_096,
    "HRAM": 127,
}

_RE_BANK = re.compile(r"^(\w+) bank #(\d+):$")
_RE_SECTION = re.compile(
    r'^\s+SECTION: \$([0-9a-fA-F]+)-\$([0-9a-fA-F]+)'
    r' \(\$[0-9a-fA-F]+ bytes\) \["(.+)"\]$'
)
_RE_TOTAL_EMPTY = re.compile(r"^\s+TOTAL EMPTY: \$([0-9a-fA-F]+) bytes?$")


@dataclass(frozen=True)
class Section:
    name: str
    region: str
    bank: int
    start: int
    end: int
    size: int


@dataclass
class Bank:
    region: str
    number: int
    capacity: int
    used: int
    free: int
    sections: list[Section] = field(default_factory=list)

    @property
    def utilization(self) -> float:
        return self.used / self.capacity if self.capacity else 0.0


class MapFile:
    def __init__(self, banks: dict[tuple[str, int], Bank]) -> None:
        self.banks = banks

    @classmethod
    def parse(cls, path: Path) -> "MapFile":
        banks: dict[tuple[str, int], Bank] = {}
        cur_region: str | None = None
        cur_number: int | None = None
        cur_sections: list[Section] = []

        with path.open("r", encoding="utf-8") as f:
            for lineno, raw in enumerate(f, 1):
                line = raw.rstrip("\n")

                m = _RE_BANK.match(line)
                if m:
                    cur_region = m.group(1)
                    cur_number = int(m.group(2))
                    cur_sections = []
                    continue

                if cur_region is None:
                    continue

                m = _RE_SECTION.match(line)
                if m:
                    start = int(m.group(1), 16)
                    end = int(m.group(2), 16)
                    cur_sections.append(Section(
                        name=m.group(3),
                        region=cur_region,
                        bank=cur_number,
                        start=start,
                        end=end,
                        size=end - start + 1,
                    ))
                    continue

                m = _RE_TOTAL_EMPTY.match(line)
                if m:
                    total_empty = int(m.group(1), 16)
                    capacity = REGION_CAPACITY.get(cur_region, 0)
                    used = sum(s.size for s in cur_sections)
                    if capacity and capacity - used != total_empty:
                        raise ValueError(
                            f"{path.name}:{lineno}: {cur_region} bank #{cur_number}: "
                            f"expected free={total_empty:#x} but computed {capacity - used:#x}"
                        )
                    banks[(cur_region, cur_number)] = Bank(
                        region=cur_region,
                        number=cur_number,
                        capacity=capacity,
                        used=used,
                        free=total_empty,
                        sections=list(cur_sections),
                    )
                    cur_region = None
                    cur_number = None
                    cur_sections = []

        return cls(banks)

    def fill_rom_banks(self, total_banks: int) -> None:
        """Add empty ROMX bank entries for banks the cartridge contains but the
        linker never assigned, so they're absent from the .map (trailing $ff
        padding that rgbfix appends to reach a valid ROM size).

        `total_banks` is the cartridge's full bank count *including* bank 0, so
        ROMX banks run 1..total_banks-1. No-op for banks already present.
        """
        cap = REGION_CAPACITY["ROMX"]
        for n in range(1, total_banks):
            if ("ROMX", n) in self.banks or ("ROM0", n) in self.banks:
                continue
            self.banks[("ROMX", n)] = Bank(
                region="ROMX", number=n, capacity=cap, used=0, free=cap,
            )

    def rom_banks(self) -> list[Bank]:
        result = [b for b in self.banks.values() if b.region in ("ROM0", "ROMX")]
        return sorted(result, key=lambda b: (0 if b.region == "ROM0" else 1, b.number))

    def banks_by_region(self, region: str) -> list[Bank]:
        r = region.upper()
        return sorted(
            [b for b in self.banks.values() if b.region == r],
            key=lambda b: b.number,
        )

    def all_sections(self) -> list[Section]:
        result = []
        for bank in self.banks.values():
            result.extend(bank.sections)
        return result

    def find_section(self, name: str) -> list[Section]:
        exact = [s for s in self.all_sections() if s.name == name]
        if exact:
            return exact
        lower = name.lower()
        return [s for s in self.all_sections() if lower in s.name.lower()]
