#!/usr/bin/env python3
"""Polished's `plays` writer, proven offline against the real build.

Two halves, both falsified-first ([[round-trip-to-verify-writer]]):

  * the **tiles** — `mapread` resolves a map's `<Label>_BlockData` in the `.sym`,
    decompresses it from the ROM, and computes `wScreenSave`; that must match the
    same window computed from the plain `.ablk` the build was made from, or the
    symbol resolution / truncation is wrong. No save needed.
  * the **save patcher** — on a *synthetic* save sized to the real SRAM layout
    (there is no genuine polished save yet; the user makes one by hand for the
    live boot), `stand_on` writes the position, resets the player struct with
    polished's own 34/14/21 sizes, clears the NPC slots, and leaves both the
    primary and backup checksums internally valid. This exercises every offset
    against the real `.sym` without a game save; the genuine round-trip and the
    clean SameBoy boot are the human step that follows.

    python tests/test_polished_play.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pokeprism_devtools.hacks.polished import mapread, savefile  # noqa: E402
from pokeprism_devtools.hacks.vanilla.read import dims, label_of  # noqa: E402
from pokeprism_devtools.shared.overworld import blockdata  # noqa: E402
from pokeprism_devtools.shared.symfile import SymFile  # noqa: E402

POLISHED = Path.home() / "code/ricccec/polishedcrystal"
ROM = POLISHED / "polishedcrystal-3.2.3.gbc"
SYM = POLISHED / "polishedcrystal-3.2.3.sym"

_failures = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global _failures
    ok = bool(cond)
    if not ok:
        _failures += 1
    print(f"  {'ok  ' if ok else 'FAIL'} {label}"
          f"{(': ' + detail) if detail and not ok else ''}")


def _present() -> bool:
    if not (ROM.exists() and SYM.exists()):
        check("built polishedcrystal ROM + .sym are present", False,
              f"{ROM.name} / {SYM.name} — run `make` in polished")
        return False
    return True


def test_screen_save_from_rom() -> None:
    """`mapread` off the ROM equals the plain `.ablk` window, on real maps."""
    print("tiles — wScreenSave from the ROM matches the tracked .ablk source")
    if not _present():
        return
    rom = ROM.read_bytes()
    syms = SymFile.load(SYM)
    d = dims(POLISHED)
    labels = label_of(POLISHED)

    checked = 0
    trouble: list[str] = []
    x, y = 6, 6
    for const, label in sorted(labels.items()):
        dim = d.get(const)
        plain = POLISHED / "maps" / f"{label}.ablk"
        if dim is None or not plain.exists():
            continue
        grid = plain.read_bytes()
        if len(grid) != dim.width * dim.height:
            continue  # a shared/aliased block file — its own map owns the shape
        bd = blockdata.BlockData(name=label, group=0, map_id=0,
                                 width=dim.width, height=dim.height,
                                 border_block=0, blocks=grid)
        want = blockdata.compute_screen_save(bd, x, y)
        try:
            got = mapread.screen_save_bytes(rom, syms, label,
                                            dim.width, dim.height, x, y)
        except Exception as exc:  # noqa: BLE001
            trouble.append(f"{label}: raised {exc!r}")
            continue
        if got != want:
            trouble.append(f"{label}: window differs")
        checked += 1
        if checked >= 200:
            break
    check(f"{checked} maps' ROM tiles match their .ablk window",
          checked > 0 and not trouble, "; ".join(trouble[:4]))


def test_screen_save_falsified() -> None:
    """The window is map-specific, so reading a map's tiles with a *different*
    map's dimensions must not accidentally match — else the check proves little."""
    print("falsification — the wrong map's dimensions give the wrong window")
    if not _present():
        return
    rom = ROM.read_bytes()
    syms = SymFile.load(SYM)
    a = mapread.screen_save_bytes(rom, syms, "NewBarkTown",
                                  *_wh("NEW_BARK_TOWN"), 6, 6)
    b = mapread.screen_save_bytes(rom, syms, "Route29",
                                  *_wh("ROUTE_29"), 6, 6)
    check("NewBarkTown and Route29 windows differ", a != b,
          "two different maps produced the same wScreenSave")


def _wh(const: str) -> tuple[int, int]:
    dim = dims(POLISHED)[const]
    return dim.width, dim.height


def test_stand_on_synthetic() -> None:
    """`stand_on` on a synthetic save: real offsets, real checksums, no game save."""
    print("save — stand_on writes position + reset + valid checksums")
    if not _present():
        return
    syms = SymFile.load(SYM)
    save = savefile.Save(bytearray(0x8000))
    # Stamp the two validity bytes so `looks_real` holds and the game would load it.
    save.data[savefile.sram_offset(syms["sCheckValue1"])] = savefile.CHECK_VALUE_1
    save.data[savefile.sram_offset(syms["sCheckValue2"])] = savefile.CHECK_VALUE_2
    check("the synthetic save looks real before patching", save.looks_real(syms))

    group, number, label, w, h = _map("NEW_BARK_TOWN")
    x, y = 5, 7
    save.stand_on(syms, group=group, number=number, label=label,
                  width=w, height=h, y=y, x=x, rom_path=ROM)

    # Position bytes.
    def at(sym: str) -> int:
        return save._saved_offset(syms, sym)
    check("wMapGroup/wMapNumber/wYCoord/wXCoord written",
          save.data[at("wMapGroup")] == group
          and save.data[at("wMapNumber")] == number
          and save.data[at("wYCoord")] == y and save.data[at("wXCoord")] == x)

    # Player object struct: standing/last/init map coords = (x+4, y+4).
    p = at("wObjectStructs")
    cx, cy = (x + 4) & 0xFF, (y + 4) & 0xFF
    check("player struct standing/init coords carry the +4",
          save.data[p + 16] == cx and save.data[p + 17] == cy
          and save.data[p + 20] == cx and save.data[p + 21] == cy,
          f"got x={save.data[p + 16]}, y={save.data[p + 17]}")

    # NPC slots cleared (slot 1 of both arrays, polished's 34 / 14 strides).
    ms = at("wMapObjects")
    check("first NPC map-object slot is zeroed (14-byte stride)",
          save.data[ms + savefile.MAP_OBJECT_LEN
                    : ms + 2 * savefile.MAP_OBJECT_LEN] == bytes(savefile.MAP_OBJECT_LEN))
    check("first NPC object struct is zeroed (34-byte stride)",
          save.data[p + savefile.OBJECT_STRUCT_LEN
                    : p + 2 * savefile.OBJECT_STRUCT_LEN] == bytes(savefile.OBJECT_STRUCT_LEN))

    # Both checksums internally valid, as an in-game save leaves them.
    check("primary checksum verifies", _primary_ok(save, syms))
    check("backup game data mirrors the primary and its checksum verifies",
          _backup_ok(save, syms))

    # Falsification: tamper one saved byte and the primary checksum must break.
    save.data[at("wYCoord")] ^= 0xFF
    check("a tampered saved byte breaks the primary checksum",
          not _primary_ok(save, syms),
          "the checksum still verified after tampering — it is not covering the data")


def _map(const: str) -> tuple[int, int, str, int, int]:
    d = dims(POLISHED)[const]
    return d.group, d.map_id, label_of(POLISHED)[const], d.width, d.height


def _primary_ok(save: savefile.Save, syms: SymFile) -> bool:
    lo = savefile.sram_offset(syms["sGameData"])
    hi = savefile.sram_offset(syms["sGameDataEnd"])
    at = savefile.sram_offset(syms["sChecksum"])
    total = savefile.checksum16(save.data[lo:hi])
    return save.data[at] == (total & 0xFF) and save.data[at + 1] == (total >> 8) & 0xFF


def _backup_ok(save: savefile.Save, syms: SymFile) -> bool:
    s0 = savefile.sram_offset(syms["sGameData"])
    s1 = savefile.sram_offset(syms["sGameDataEnd"])
    d0 = savefile.sram_offset(syms["sBackupGameData"])
    d1 = savefile.sram_offset(syms["sBackupGameDataEnd"])
    if save.data[d0:d1] != save.data[s0:s1]:
        return False
    at = savefile.sram_offset(syms["sBackupChecksum"])
    total = savefile.checksum16(save.data[d0:d1])
    return save.data[at] == (total & 0xFF) and save.data[at + 1] == (total >> 8) & 0xFF


if __name__ == "__main__":
    test_screen_save_from_rom()
    test_screen_save_falsified()
    test_stand_on_synthetic()
    print(f"\n{'FAILURES: ' + str(_failures) if _failures else 'all ok'}")
    sys.exit(1 if _failures else 0)
