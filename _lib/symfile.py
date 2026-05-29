"""Parser for RGBDS .sym files.

Format (one symbol per line, after a header comment):

    BB:AAAA Label

where BB is the bank in hex and AAAA is the address in hex. Multiple labels
can share the same (bank, addr) — common at section boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class Symbol:
    label: str
    bank: int
    addr: int

    @property
    def region(self) -> str:
        """One of: ROM0, ROMX, VRAM, SRAM, WRAM0, WRAMX, OAM, HRAM, IO, ECHO."""
        a = self.addr
        if a < 0x4000:
            return "ROM0"
        if a < 0x8000:
            return "ROMX"
        if a < 0xA000:
            return "VRAM"
        if a < 0xC000:
            return "SRAM"
        if a < 0xD000:
            return "WRAM0"
        if a < 0xE000:
            return "WRAMX"
        if a < 0xFE00:
            return "ECHO"
        if a < 0xFEA0:
            return "OAM"
        if a < 0xFF00:
            return "UNUSED"
        if a < 0xFF80:
            return "IO"
        return "HRAM"

    def __str__(self) -> str:
        return f"{self.bank:02x}:{self.addr:04x} {self.label}"


class SymFile:
    def __init__(self, symbols: list[Symbol]):
        self.symbols = symbols
        # Most callers want by-label lookup. Duplicate labels are rare — keep
        # the last one (matches rgblink resolution).
        self._by_label: dict[str, Symbol] = {s.label: s for s in symbols}
        self._sorted: list[Symbol] | None = None

    @classmethod
    def load(cls, path: Path) -> "SymFile":
        return cls(list(_parse(path)))

    def __getitem__(self, label: str) -> Symbol:
        return self._by_label[label]

    def get(self, label: str) -> Symbol | None:
        return self._by_label.get(label)

    def __contains__(self, label: str) -> bool:
        return label in self._by_label

    def __len__(self) -> int:
        return len(self.symbols)

    def find_prefix(self, prefix: str) -> list[Symbol]:
        return [s for s in self.symbols if s.label.startswith(prefix)]

    def find_substring(self, needle: str) -> list[Symbol]:
        n = needle.lower()
        return [s for s in self.symbols if n in s.label.lower()]

    def at_or_before(self, bank: int, addr: int) -> list[Symbol]:
        """Return symbols at (bank, addr), or the nearest preceding (bank, *)."""
        sorted_syms = self._sorted_symbols()
        candidates = [s for s in sorted_syms if s.bank == bank and s.addr <= addr]
        if not candidates:
            return []
        # All symbols sharing the same max addr.
        max_addr = candidates[-1].addr
        return [s for s in candidates if s.addr == max_addr]

    def _sorted_symbols(self) -> list[Symbol]:
        if self._sorted is None:
            self._sorted = sorted(self.symbols, key=lambda s: (s.bank, s.addr))
        return self._sorted


def _parse(path: Path) -> Iterable[Symbol]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith(";"):
                continue
            head, _, label = line.partition(" ")
            if not label:
                continue
            bank_s, _, addr_s = head.partition(":")
            if not addr_s:
                continue
            try:
                bank = int(bank_s, 16)
                addr = int(addr_s, 16)
            except ValueError:
                continue
            yield Symbol(label=label, bank=bank, addr=addr)
