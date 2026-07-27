"""A stock-Gen-2 save, patched to stand you somewhere — vanilla's save format.

This is deliberately *not* `hacks/prism/savefile.py`. Prism's save is four SRAM
banks with a 48-byte RTC trailer and prism's own field layout; a stock pokecrystal
save is the vanilla Gen-2 one, and its `sGameData`/`sChecksum`/check-value layout
(`ram/sram.asm`) is different enough that sharing the offsets would be sharing a
lie. What the two do share is the shape of the arithmetic — SRAM banking and a
16-bit sum checksum are Game Boy facts, not any hack's — so those read the same
here, spelled against vanilla's own symbols.

Every offset comes from the built `.sym`, never a hardcoded address. The game
data spans three WRAM blocks — player, current-map, pokemon — each mirrored
byte-for-byte into an SRAM copy (`ram/sram.asm`), and the game validates the
primary save by two check bytes (`SAVE_CHECK_VALUE_1`/`_2`) and a checksum over
`sGameData` before it will load it (`engine/menus/save.asm`).

Standing you on a map is two jobs. The *position* is four bytes in the map block
(`wMapGroup`/`wMapNumber`/`wYCoord`/`wXCoord`). But `MAPSETUP_CONTINUE` loads
those coordinates over whatever map you were on before, so the *map itself* has to
be rebuilt too — the tiles around you (`wScreenSave`) and the objects
(`wObjectStructs`/`wMapObjects`). That rebuild is engine-general Gen-2 and lives
in `shared.overworld`; this module resolves the save offsets it writes into, wires
it up, and then fixes the checksums the game checks — the *primary* it verifies on
load, and the *backup* copy it keeps consistent. Given the ROM to read the map
from, `stand_on` does the whole job; without it, it can only move the position.
"""

from __future__ import annotations

from pathlib import Path

from ...shared.overworld import people, rebuild
from ...shared.symfile import Symbol, SymFile

SRAM_BANK_SIZE = 0x2000
SRAM_BASE = 0xA000

#: `constants/misc_constants.asm`: the two bytes the game writes either side of the
#: save data and checks on load. A file without them was never a real save — it
#: boots to a black screen rather than an error — so we refuse before touching it.
CHECK_VALUE_1 = 99
CHECK_VALUE_2 = 127

#: The three WRAM blocks the game data spans, each mirrored into an SRAM copy
#: (`ram/sram.asm`). `_saved_offset` locates every field it writes by which of
#: these contains it, so the position bytes, the tiles (`wScreenSave`) and the
#: objects (`wObjectStructs`/`wMapObjects`) all resolve through one rule. A block
#: whose symbols aren't in the `.sym` is skipped, so a partial map (a unit test's
#: synthetic layout, say) still resolves the fields it does define.
_SAVED_BLOCKS = (
    ("wPlayerData",  "wPlayerDataEnd",  "sPlayerData"),
    ("wCurMapData",  "wCurMapDataEnd",  "sCurMapData"),
    ("wPokemonData", "wPokemonDataEnd", "sPokemonData"),
)


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
                 y: int, x: int, rom_path: Path | None = None,
                 keep_people: bool = False) -> list[str]:
        """Stand the player at tile `(y, x)` on `(group, number)`, cleanly.

        Writes the four position bytes and — **given `rom_path`** — rebuilds the
        map around them (`shared.overworld.rebuild`: the tiles in `wScreenSave`
        and the objects in `wObjectStructs`/`wMapObjects`), because
        `MAPSETUP_CONTINUE` loads the new coordinates over the *previous* map's
        state and would otherwise render it corrupt. Then it fixes the primary
        checksum the game verifies on load, and mirrors the backup copy the game
        keeps beside it. Without `rom_path` it can only move the position — there
        is no ROM to read the destination map from — so a real boot always passes
        one; the ROM-less path is for exercising the position arithmetic alone.

        `y`/`x` are the tile coordinates `wYCoord`/`wXCoord` hold — the grid
        cursor's own numbers, no object-struct `+4` (the objects' `+4` lives in
        the rebuild). `keep_people` preserves the objects already in the save
        instead of reloading the destination map's own. Returns the rebuild's
        change lines (empty when no ROM was given). Every field is located from
        the built symbols, so an engine layout change moves the write with it.
        """
        for label, value in (("wMapGroup", group), ("wMapNumber", number),
                             ("wYCoord", y), ("wXCoord", x)):
            self.data[self._saved_offset(syms, label)] = value & 0xFF
        changes: list[str] = []
        if rom_path is not None:
            changes = self._rebuild_map(syms, rom_path, group=group,
                                        number=number, y=y, x=x,
                                        keep_people=keep_people)
        self._recompute_checksum(syms)
        if rom_path is not None:
            self._recompute_backup(syms)
        return changes

    def _rebuild_map(self, syms: SymFile, rom_path: Path, *, group: int,
                     number: int, y: int, x: int,
                     keep_people: bool) -> list[str]:
        """Drive the shared Gen-2 map rebuild with vanilla's resolved offsets.

        The rebuild is engine-general; what is vanilla's is *where* its fields sit
        in this save, so that is all this resolves before handing over. The
        `wMapObjects` byte length has no end symbol, so it comes from the Gen-2
        constant the core itself owns (`NUM_OBJECTS * MAP_OBJECT_LEN`). The
        variable-sprite table travels along because the VRAM allocation needs it:
        a variable sprite's real type is only in the save (`wVariableSprites`, a
        `$100 - SPRITE_VARS` = 16-byte array in the player block)."""
        offsets = rebuild.SaveOffsets(
            screen_save=self._saved_offset(syms, "wScreenSave"),
            object_structs=self._saved_offset(syms, "wObjectStructs"),
            map_objects=self._saved_offset(syms, "wMapObjects"),
            map_objects_size=people.NUM_OBJECTS * people.MAP_OBJECT_LEN,
        )
        vs = self._saved_offset(syms, "wVariableSprites")
        return rebuild.rebuild_map(
            self, rom_path=rom_path, syms=syms,
            group=group, number=number, x=x, y=y,
            offsets=offsets, keep_people=keep_people,
            variable_sprites=bytes(self.data[vs:vs + 16]))

    def _recompute_checksum(self, syms: SymFile) -> None:
        start = sram_offset(self._sym(syms, "sGameData"))
        end = sram_offset(self._sym(syms, "sGameDataEnd"))
        total = checksum16(self.data[start:end])
        at = sram_offset(self._sym(syms, "sChecksum"))
        self.data[at] = total & 0xFF
        self.data[at + 1] = (total >> 8) & 0xFF

    def _recompute_backup(self, syms: SymFile) -> None:
        """Mirror the patched game data into the backup copy and revalidate it.

        The game keeps a full second copy of the save in a different SRAM bank
        (`sBackupGameData`) and reads it only when the primary fails its checksum
        (`TryLoadSaveData`). So the boot never needs it — a valid primary loads
        and the backup is ignored. But an in-game save always rewrites the backup
        to match, and a *stale* backup here would mean a later corruption of the
        primary silently reverts you to a pre-teleport map. So mirror it the way
        the game does: copy the primary game data over, stamp the two validity
        bytes, and sum the backup's own checksum. Both copies then agree, exactly
        as they do after saving in-game."""
        src0 = sram_offset(self._sym(syms, "sGameData"))
        src1 = sram_offset(self._sym(syms, "sGameDataEnd"))
        dst0 = sram_offset(self._sym(syms, "sBackupGameData"))
        dst1 = sram_offset(self._sym(syms, "sBackupGameDataEnd"))
        if (src1 - src0) != (dst1 - dst0):
            raise SaveError(
                f"the backup game-data block is {dst1 - dst0} bytes but the "
                f"primary is {src1 - src0} — this is not the save layout the "
                "patcher understands.")
        self.data[dst0:dst1] = self.data[src0:src1]
        self.data[sram_offset(self._sym(syms, "sBackupCheckValue1"))] = CHECK_VALUE_1
        self.data[sram_offset(self._sym(syms, "sBackupCheckValue2"))] = CHECK_VALUE_2
        total = checksum16(self.data[dst0:dst1])
        at = sram_offset(self._sym(syms, "sBackupChecksum"))
        self.data[at] = total & 0xFF
        self.data[at + 1] = (total >> 8) & 0xFF

    # -- locating a field --------------------------------------------------- #
    def _saved_offset(self, syms: SymFile, wlabel: str) -> int:
        """The `.sav` offset of a saved WRAM field, whichever block it is in.

        Each game-data block mirrors a WRAM range into an SRAM copy byte-for-byte,
        so a field's offset within its block is its offset within that block's
        save copy. This generalises the old wCurMapData-only locator to reach the
        object and screen fields the map rebuild writes, which live in the player
        and map blocks. A block whose symbols are absent is skipped, so a partial
        `.sym` still resolves the fields it does define."""
        addr = self._sym(syms, wlabel).addr
        for wstart, wend, smirror in _SAVED_BLOCKS:
            s0, s1, sm = syms.get(wstart), syms.get(wend), syms.get(smirror)
            if s0 is None or s1 is None or sm is None:
                continue
            if s0.addr <= addr < s1.addr:
                return sram_offset(sm) + (addr - s0.addr)
        raise SaveError(
            f"{wlabel} (${addr:04x}) is not inside a saved game-data block "
            "(player/map/pokemon) — it is not part of the save the game checks.")

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
