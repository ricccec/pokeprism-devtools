"""A stock-Gen-2 save, patched to stand you somewhere — vanilla's save format.

This is deliberately *not* `hacks/prism/savefile.py`. Prism's save is four SRAM
banks with a 48-byte RTC trailer and prism's own field layout; a stock pokecrystal
save is the vanilla Gen-2 one, and its `sGameData`/`sChecksum`/check-value layout
(`ram/sram.asm`) is different enough that sharing the offsets would be sharing a
lie. What the two do share is the shape of the arithmetic — SRAM banking and a
16-bit sum checksum are Game Boy facts, not any hack's — so those read the same
here, spelled against vanilla's own symbols.

Every offset comes from the built `.sym`, never a hardcoded address: the map
position lives in `wCurMapData` (`ram/wram.asm`), the save mirrors it byte-for-byte
into `sCurMapData`, and the game validates the primary save by two check bytes
(`SAVE_CHECK_VALUE_1`/`_2`) and a checksum over `sGameData` before it will load it
(`engine/menus/save.asm`). Patch the four position bytes, fix that checksum, and the
game continues standing where you asked rather than falling back to its backup.
"""

from __future__ import annotations

from pathlib import Path

from ...shared.symfile import Symbol, SymFile

SRAM_BANK_SIZE = 0x2000
SRAM_BASE = 0xA000

#: `constants/misc_constants.asm`: the two bytes the game writes either side of the
#: save data and checks on load. A file without them was never a real save — it
#: boots to a black screen rather than an error — so we refuse before touching it.
CHECK_VALUE_1 = 99
CHECK_VALUE_2 = 127


class SaveError(RuntimeError):
    """This file is not a save we can stand you in — no such save, or its
    validity bytes are missing. The message says which, because both are things
    the player can fix (build and save in-game once)."""


def sram_offset(sym: Symbol) -> int:
    """The `.sav` byte offset of an SRAM symbol. `file = bank*0x2000 +
    (addr - 0xA000)`, the standard mapping of banked SRAM onto a linear dump."""
    if sym.region != "SRAM":
        raise SaveError(f"{sym.label} is not in SRAM (it is {sym.region})")
    return sym.bank * SRAM_BANK_SIZE + (sym.addr - SRAM_BASE)


def checksum16(data: bytes) -> int:
    """The game's save checksum (`engine/menus/save.asm`, `Checksum`): a plain
    16-bit running sum of the bytes. Every byte that wraps the low byte carries
    into the high one, which is exactly `sum(data) & 0xFFFF`."""
    return sum(data) & 0xFFFF


class Save:
    """One stock-Gen-2 `.sav`, in memory. Load it, ask whether it is real, stand
    somewhere in it, write it back. It interprets nothing beyond the save's own
    structure — which map a `(group, number)` names is the caller's knowledge."""

    def __init__(self, data: bytearray) -> None:
        self.data = data

    @classmethod
    def load(cls, path: Path) -> "Save":
        return cls(bytearray(path.read_bytes()))

    def write(self, path: Path) -> None:
        path.write_bytes(bytes(self.data))

    # -- is this a save at all? --------------------------------------------- #
    def looks_real(self, syms: SymFile) -> bool:
        """Both validity bytes present and correct. The game writes these the
        first time it saves; their absence is how a fresh/empty SRAM dump gives
        itself away."""
        return (self._byte(syms, "sCheckValue1") == CHECK_VALUE_1
                and self._byte(syms, "sCheckValue2") == CHECK_VALUE_2)

    # -- stand somewhere ---------------------------------------------------- #
    def stand_on(self, syms: SymFile, *, group: int, number: int,
                 y: int, x: int) -> None:
        """Set the current map to `(group, number)` at tile `(y, x)`, then fix
        the primary checksum so the game loads this save instead of its backup.

        `y`/`x` are the tile coordinates `wYCoord`/`wXCoord` hold — the grid
        cursor's own numbers, no object-struct `+4`. Every field is located by
        its `wCurMapData`-relative offset in the built symbols, so a layout
        change in the engine moves the write with it rather than past it.
        """
        for label, value in (("wMapGroup", group), ("wMapNumber", number),
                             ("wYCoord", y), ("wXCoord", x)):
            self.data[self._curmap_offset(syms, label)] = value & 0xFF
        self._recompute_checksum(syms)

    def _recompute_checksum(self, syms: SymFile) -> None:
        start = sram_offset(self._sym(syms, "sGameData"))
        end = sram_offset(self._sym(syms, "sGameDataEnd"))
        total = checksum16(self.data[start:end])
        at = sram_offset(self._sym(syms, "sChecksum"))
        self.data[at] = total & 0xFF
        self.data[at + 1] = (total >> 8) & 0xFF

    # -- locating a field --------------------------------------------------- #
    def _curmap_offset(self, syms: SymFile, wlabel: str) -> int:
        """The `.sav` offset of a `wCurMapData` field. `sCurMapData` mirrors
        `wCurMapData`, so the field's offset *within the block* — read from the
        WRAM symbols — is its offset within the save's copy."""
        base = self._sym(syms, "wCurMapData").addr
        within = self._sym(syms, wlabel).addr - base
        return sram_offset(self._sym(syms, "sCurMapData")) + within

    def _byte(self, syms: SymFile, label: str) -> int:
        return self.data[sram_offset(self._sym(syms, label))]

    @staticmethod
    def _sym(syms: SymFile, label: str) -> Symbol:
        try:
            return syms[label]
        except KeyError:
            raise SaveError(
                f"the build's .sym has no {label} — is this a stock pokecrystal "
                "checkout, built with symbols?") from None
