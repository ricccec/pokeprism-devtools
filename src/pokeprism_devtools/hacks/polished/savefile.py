"""A polishedcrystal save, patched to stand you somewhere — polished's format.

Polished's save *framing* is stock Gen-2's, not prism's: three WRAM game-data
blocks (player, current-map, pokemon) each mirrored byte-for-byte into an SRAM
copy, two check bytes and a 16-bit sum checksum the game verifies on load, and a
full backup copy in another bank read only when the primary fails. So this is a
near-copy of `hacks/vanilla/savefile.py`, and deliberately so — the arithmetic
(SRAM banking, the sum checksum) is Game Boy fact, spelled here against polished's
own symbols. The one framing difference is the name of the current-map block's
SRAM mirror: polished calls it `sMapData` where stock calls it `sCurMapData`.

The *map rebuild* is where polished genuinely diverges, and that stays off the
shared stock-family core: its blocks are a custom codec and its object structs a
different size. Standing you on a map is still two jobs — the four position bytes
(`wMapGroup`/`wMapNumber`/`wYCoord`/`wXCoord`), and rebuilding the map around them
because `MAPSETUP_CONTINUE` loads the coordinates over the previous map's state.
Stage 1 rebuilds the tiles (`wScreenSave`, via `mapread` + polished's `lzp`) and
resets the object engine (player placed, old NPCs cleared) with polished's own
struct sizes; loading the destination map's NPCs and their sprite VRAM is Stage 2.
Given the ROM, `stand_on` does the Stage-1 job; without it, only the position.
"""

from __future__ import annotations

from pathlib import Path

from ...shared.overworld import people
from ...shared.symfile import Symbol, SymFile
from . import mapread, objects

SRAM_BANK_SIZE = 0x2000
SRAM_BASE = 0xA000

#: `constants/misc_constants.asm`: the two bytes the game writes either side of the
#: save data and checks on load. A file without them was never a real save.
#: Polished bumped value-1 to 97 at save version 7 and kept 99 as the "_OLD" value;
#: the loader (`engine/menus/save.asm`) still accepts *either*, so a real save reads
#: 97 (current) or 99 (pre-v7). Value-2 is unchanged. (The comment in `ram/sram.asm`
#: still says "loaded with 99" but the actual `EQU` is 97 — the constant is truth.)
CHECK_VALUE_1 = 97
CHECK_VALUE_1_OLD = 99
CHECK_VALUE_2 = 127

#: Polished's object-engine ABI (`constants/map_object_constants.asm`): its object
#: struct is 34 bytes (stock's is 40), its map object 14 (stock's 16), and it has
#: 21 map-object slots (stock's 16). These are the whole difference the object
#: clear needs — the leading field offsets it writes are identical to stock's, so
#: they stay in the shared `people` helper and only the sizes cross here.
OBJECT_STRUCT_LEN = 34
MAP_OBJECT_LEN = 14
NUM_OBJECTS = 21
NUM_OBJECT_STRUCTS = 13

#: The three WRAM blocks the game data spans, each mirrored into an SRAM copy
#: (`ram/sram.asm`). Identical to vanilla's but for the current-map block's mirror
#: name — `sMapData`, not `sCurMapData`. `_saved_offset` locates every field it
#: writes by which block contains it.
_SAVED_BLOCKS = (
    ("wPlayerData",  "wPlayerDataEnd",  "sPlayerData"),
    ("wCurMapData",  "wCurMapDataEnd",  "sMapData"),
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
    """The game's save checksum (`engine/menus/save.asm`): a plain 16-bit running
    sum of the bytes, which is exactly `sum(data) & 0xFFFF`."""
    return sum(data) & 0xFFFF


class Save:
    """One polished `.sav`, in memory. Load it, ask whether it is real, stand
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
        itself away. Value-1 may be the current 97 or the pre-v7 99 — the loader
        accepts either, so we must too."""
        return (self._byte(syms, "sCheckValue1") in (CHECK_VALUE_1, CHECK_VALUE_1_OLD)
                and self._byte(syms, "sCheckValue2") == CHECK_VALUE_2)

    # -- stand somewhere ---------------------------------------------------- #
    def stand_on(self, syms: SymFile, *, group: int, number: int, label: str,
                 width: int, height: int, y: int, x: int,
                 rom_path: Path | None = None,
                 keep_people: bool = False,
                 resolve_neighbour: "mapread.NeighbourResolver | None" = None) -> list[str]:
        """Stand the player at tile `(y, x)` on `(group, number)`, cleanly.

        Writes the four position bytes and — **given `rom_path`** — rebuilds the
        tiles in `wScreenSave` from the ROM (via `mapread`) and resets the object
        engine so the previous map's player and NPCs do not bleed through, then
        fixes the primary checksum the game verifies on load and mirrors the
        backup copy. Without `rom_path` it can only move the position — there is
        no ROM to read the destination map from.

        `label`/`width`/`height` describe the destination map (the caller resolves
        them from `map_constants.asm`); the block grid is named `<label>_BlockData`
        in the `.sym`. `y`/`x` are the raw `wYCoord`/`wXCoord` tiles (no `+4`).
        `keep_people` preserves the objects already in the save. `resolve_neighbour`
        turns a connection's (group, map_id) into the neighbour's `(label, width,
        height)` so an edge position renders the connected map's tiles; without it
        edges fall back to border void. Returns the rebuild's change lines (empty
        when no ROM was given).
        """
        for lbl, value in (("wMapGroup", group), ("wMapNumber", number),
                           ("wYCoord", y), ("wXCoord", x)):
            self.data[self._saved_offset(syms, lbl)] = value & 0xFF
        changes: list[str] = []
        if rom_path is not None:
            changes = self._rebuild_map(syms, rom_path, label=label,
                                        width=width, height=height, x=x, y=y,
                                        keep_people=keep_people,
                                        resolve_neighbour=resolve_neighbour)
        self._recompute_checksum(syms)
        if rom_path is not None:
            self._recompute_backup(syms)
        return changes

    def _rebuild_map(self, syms: SymFile, rom_path: Path, *, label: str,
                     width: int, height: int, x: int, y: int,
                     keep_people: bool,
                     resolve_neighbour: "mapread.NeighbourResolver | None") -> list[str]:
        """Rebuild the tiles (Stage 1) and reset the object engine.

        The tiles come from polished's own `mapread` (its blocks are a custom
        codec the shared reader cannot decompress), with the connected neighbours
        overlaid at the map edges when `resolve_neighbour` can find them; the object
        reset is the shared `people` helper, which is genuinely neutral — polished's
        leading object fields sit where stock's do, so only its struct sizes cross
        as data. Unless `keep_people`, the destination map's own NPCs are then loaded
        into `wMapObjects` and the on-screen ones instantiated into `wObjectStructs`
        with polished's positional VRAM tiles and palettes (`objects`), so the map
        comes up populated.
        """
        rom = rom_path.read_bytes()
        nbrs = (mapread.neighbours(rom, syms, label, width, resolve_neighbour)
                if resolve_neighbour is not None else [])
        ss = mapread.screen_save_bytes(rom, syms, label, width, height, x, y,
                                       neighbors=nbrs)
        at = self._saved_offset(syms, "wScreenSave")
        self.data[at:at + len(ss)] = ss
        edges = ", ".join(c.direction for c, _ in nbrs) or "none"
        changes = [f"recomputed wScreenSave from {width}x{height} block grid "
                   f"(connections filled: {edges}) for {label}"]

        map_objects_size = NUM_OBJECTS * MAP_OBJECT_LEN
        object_structs_offset = self._saved_offset(syms, "wObjectStructs")
        map_objects_offset = self._saved_offset(syms, "wMapObjects")
        people_changes = people.reset_player_and_clear_npcs(
            self,
            object_structs_offset=object_structs_offset,
            map_objects_offset=map_objects_offset,
            map_objects_size=map_objects_size,
            x=x, y=y, keep_npcs=keep_people,
            object_struct_len=OBJECT_STRUCT_LEN,
            map_object_len=MAP_OBJECT_LEN,
        )

        if not keep_people:
            events = objects.object_events(rom, syms, label)
            people_changes |= people.load_map_npcs(
                self,
                map_objects_offset=map_objects_offset,
                map_objects_size=map_objects_size,
                events=events,
                map_object_len=MAP_OBJECT_LEN,
                person_event_len=objects.OBJECT_EVENT_LEN,
            )
            palettes = objects.sprite_palettes(rom, syms, [ev[0] for ev in events])
            people_changes |= people.instantiate_visible_sprites(
                self,
                object_structs_offset=object_structs_offset,
                map_objects_offset=map_objects_offset,
                map_objects_size=map_objects_size,
                x=x, y=y,
                sprite_tiles={}, sprite_palettes=palettes,
                movement_data=objects.movement_data(rom, syms),
                object_struct_len=OBJECT_STRUCT_LEN,
                map_object_len=MAP_OBJECT_LEN,
                num_objects=NUM_OBJECTS,
                num_object_structs=NUM_OBJECT_STRUCTS,
                tile_of=objects.tile_strategy(),
                set_palette=objects.palette_strategy(palettes),
            )

        changes.append("people: " + ", ".join(
            f"{k}={v}" for k, v in people_changes.items()))
        return changes

    def _recompute_checksum(self, syms: SymFile) -> None:
        start = sram_offset(self._sym(syms, "sGameData"))
        end = sram_offset(self._sym(syms, "sGameDataEnd"))
        total = checksum16(self.data[start:end])
        at = sram_offset(self._sym(syms, "sChecksum"))
        self.data[at] = total & 0xFF
        self.data[at + 1] = (total >> 8) & 0xFF

    def _recompute_backup(self, syms: SymFile) -> None:
        """Mirror the patched game data into the backup copy and revalidate it.

        The game keeps a full second copy in another SRAM bank
        (`sBackupGameData`) and reads it only when the primary fails its checksum.
        The boot never needs it — a valid primary loads and the backup is ignored
        — but an in-game save always rewrites it to match, and a *stale* backup
        would mean a later corruption of the primary silently reverts you to a
        pre-teleport map. So mirror it the way the game does: copy the primary
        game data over, stamp the two validity bytes, and sum the backup's own
        checksum.
        """
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
        # Mirror the primary's own validity bytes (97 or the pre-v7 99), so the
        # backup carries the same save version and never disagrees with it.
        self.data[sram_offset(self._sym(syms, "sBackupCheckValue1"))] = \
            self._byte(syms, "sCheckValue1")
        self.data[sram_offset(self._sym(syms, "sBackupCheckValue2"))] = \
            self._byte(syms, "sCheckValue2")
        total = checksum16(self.data[dst0:dst1])
        at = sram_offset(self._sym(syms, "sBackupChecksum"))
        self.data[at] = total & 0xFF
        self.data[at + 1] = (total >> 8) & 0xFF

    # -- locating a field --------------------------------------------------- #
    def _saved_offset(self, syms: SymFile, wlabel: str) -> int:
        """The `.sav` offset of a saved WRAM field, whichever block it is in.

        Each game-data block mirrors a WRAM range into an SRAM copy byte-for-byte,
        so a field's offset within its block is its offset within that block's
        save copy. A block whose symbols are absent is skipped, so a partial
        `.sym` still resolves the fields it does define.
        """
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
                f"the build's .sym has no {label} — is this a polishedcrystal "
                "checkout, built with symbols?") from None
