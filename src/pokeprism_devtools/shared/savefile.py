"""Save file I/O and checksum.

The pokeprism .sav is a linear dump of four 8KB SRAM banks (32,768 bytes,
plus a 48-byte RTC trailer that some emulators append → 32,816 total).

Bank layout (each bank 0x2000 bytes):
    Bank 0 → file offset 0x0000–0x1FFF: scratch, RTC, RNG seed, backup save
    Bank 1 → file offset 0x2000–0x3FFF: primary save (sOptions through sBox)
    Bank 2 → file offset 0x4000–0x5FFF: boxes 1–7
    Bank 3 → file offset 0x6000–0x7FFF: boxes 8–14

Symbols in SRAM have addresses in the GB address space (0xA000–0xBFFF). To
convert a symbol's (bank, addr) to a .sav file offset:

    file_offset = bank * 0x2000 + (addr - 0xA000)

The checksum routine in engine/save.asm:1050 is a 16-bit running sum where
the high byte is incremented whenever the low byte overflows. Reimplemented
below as `checksum16`.
"""

from __future__ import annotations

from pathlib import Path

SRAM_BANK_SIZE = 0x2000
SRAM_BASE = 0xA000


def sram_to_file_offset(bank: int, addr: int) -> int:
    """Convert an SRAM (bank, GB-address) pair to a byte offset in the .sav."""
    if not (SRAM_BASE <= addr < SRAM_BASE + SRAM_BANK_SIZE):
        raise ValueError(
            f"Address ${addr:04x} is outside the SRAM window "
            f"(${SRAM_BASE:04x}–${SRAM_BASE + SRAM_BANK_SIZE - 1:04x})."
        )
    return bank * SRAM_BANK_SIZE + (addr - SRAM_BASE)


def checksum16(data: bytes) -> int:
    """Game's save checksum (engine/save.asm:1050-1067).

    Equivalent ASM:
        ld de, 0
    .loop:
        ld a, [hli]
        add e        ; a = (e + byte) & 0xFF, CF = (e + byte > 0xFF)
        ld e, a      ; e = new low byte
        adc d        ; a = a + d + CF
        sub e        ; a = (a + d + CF) - a = d + CF (mod 256)
        ld d, a      ; d = (d + CF) & 0xFF

    The clever `adc d; sub e` pair leaves `d + carry_from_add_e` in `a`.
    Net effect: a plain 16-bit running sum (every byte that wraps the low
    byte bumps the high byte by 1). I.e. just `sum(data) & 0xFFFF`.
    """
    return sum(data) & 0xFFFF


class SaveFile:
    """In-memory mutable .sav. Read with `load()`, mutate via byte ranges, save
    with `write()`. No interpretation of fields — that lives in start-state."""

    def __init__(self, data: bytearray):
        self.data = data

    @classmethod
    def load(cls, path: Path) -> "SaveFile":
        return cls(bytearray(path.read_bytes()))

    @classmethod
    def blank(cls, size: int = 0x8000) -> "SaveFile":
        return cls(bytearray(size))

    def write(self, path: Path) -> None:
        path.write_bytes(bytes(self.data))

    def __len__(self) -> int:
        return len(self.data)

    def read(self, offset: int, length: int) -> bytes:
        return bytes(self.data[offset : offset + length])

    def write_bytes(self, offset: int, payload: bytes) -> None:
        end = offset + len(payload)
        if end > len(self.data):
            raise ValueError(
                f"Write at ${offset:04x}+{len(payload)} overflows .sav of size ${len(self.data):04x}."
            )
        self.data[offset:end] = payload

    def write_byte(self, offset: int, value: int) -> None:
        if not (0 <= value <= 0xFF):
            raise ValueError(f"Byte value {value} out of range.")
        self.data[offset] = value

    def write_u16_le(self, offset: int, value: int) -> None:
        if not (0 <= value <= 0xFFFF):
            raise ValueError(f"u16 value {value} out of range.")
        self.data[offset] = value & 0xFF
        self.data[offset + 1] = (value >> 8) & 0xFF


# Character encoding from macros/charmap.asm. Only the printable subset
# needed for names — punctuation/special tokens (<PLAYER>, <RIVAL>, ...)
# can be added later if a use case appears.
TERMINATOR = 0x50  # "@"

_CHARMAP: dict[str, int] = {}
_CHARMAP[" "] = 0x7F
_CHARMAP["@"] = TERMINATOR
for i, ch in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
    _CHARMAP[ch] = 0x80 + i
for i, ch in enumerate("abcdefghijklmnopqrstuvwxyz"):
    _CHARMAP[ch] = 0xA0 + i
for i, ch in enumerate("0123456789"):
    _CHARMAP[ch] = 0xF6 + i


def encode_name(text: str, length: int) -> bytes:
    """Encode a player/mon name to fixed-length GB charset bytes.

    Pads with the terminator (0x50 = "@"). Raises if `text` is too long or
    contains an unmappable character.
    """
    if len(text) >= length:
        raise ValueError(
            f"name '{text}' is too long: max {length - 1} chars + terminator"
        )
    out = bytearray()
    for ch in text:
        if ch not in _CHARMAP:
            raise ValueError(f"character {ch!r} not in name charset")
        out.append(_CHARMAP[ch])
    while len(out) < length:
        out.append(TERMINATOR)
    return bytes(out)
