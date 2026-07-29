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

from pokeprism_devtools.hacks.polished import mapread, objects, savefile  # noqa: E402
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

    # Stage 2: the map's own NPCs are loaded into wMapObjects[1..], each a $ff
    # struct-id followed by the 13-byte ROM record — sprite ids in ROM order.
    ms = at("wMapObjects")
    MOL = savefile.MAP_OBJECT_LEN
    loaded = [save.data[ms + i * MOL + 1] for i in range(1, 6)]
    check("the map's five NPCs are loaded into wMapObjects in ROM order",
          loaded == [10, 9, 125, 105, 135], f"got {loaded}")
    # A loaded slot is either unbound ($ff, off screen) or bound to an object
    # struct that holds the very same sprite (on screen, instantiated).
    OSL = savefile.OBJECT_STRUCT_LEN
    def bound_ok(i: int) -> bool:
        sid = save.data[ms + i * MOL]
        if sid == 0xFF:
            return True
        return save.data[p + sid * OSL] == save.data[ms + i * MOL + 1]
    check("each loaded NPC is unbound ($ff) or bound to a struct with its sprite",
          all(bound_ok(i) for i in range(1, 6)))

    # Both checksums internally valid, as an in-game save leaves them.
    check("primary checksum verifies", _primary_ok(save, syms))
    check("backup game data mirrors the primary and its checksum verifies",
          _backup_ok(save, syms))

    # Falsification: tamper one saved byte and the primary checksum must break.
    save.data[at("wYCoord")] ^= 0xFF
    check("a tampered saved byte breaks the primary checksum",
          not _primary_ok(save, syms),
          "the checksum still verified after tampering — it is not covering the data")


GENUINE = POLISHED / "polishedcrystal-3.2.3_vanilla_outside.sav"


def test_object_events_walk() -> None:
    """The event walk from `<Label>_MapScriptHeader` reaches the object events."""
    print("events — the map-script-header walk lands on the object records")
    if not _present():
        return
    rom = ROM.read_bytes()
    syms = SymFile.load(SYM)
    events = objects.object_events(rom, syms, "NewBarkTown")
    check("New Bark Town yields 5 object events, each 13 bytes",
          len(events) == 5 and all(len(e) == objects.OBJECT_EVENT_LEN for e in events))
    check("their sprite-id sequence is the ROM's [RIVAL, LYRA, POKEFAN_F, FAT_GUY, SCHOOLBOY]",
          [e[0] for e in events] == [10, 9, 125, 105, 135],
          f"got {[e[0] for e in events]}")
    # Falsify: a different map's walk must not give the same records.
    other = objects.object_events(rom, syms, "Route29")
    check("a different map walks to different object events",
          [e[0] for e in other] != [10, 9, 125, 105, 135])


def test_positional_vtile() -> None:
    """The VRAM tile is `12*(slot%8)`, banked, matched against a genuine save."""
    print("vram — the positional tile formula matches the game's assignment")
    if not GENUINE.exists():
        check("a genuine polished save is present for the VRAM ground truth", False,
              f"{GENUINE.name} — a game-written save standing on a populated map")
        return
    syms = SymFile.load(SYM)
    gen = savefile.Save.load(GENUINE)
    os0 = gen._saved_offset(syms, "wObjectStructs")
    OSL = savefile.OBJECT_STRUCT_LEN
    # Struct 0 is the player (sprite 1), struct 1 the game's first on-screen NPC.
    player_tile = gen.data[os0 + 2]
    npc_sprite = gen.data[os0 + OSL + 0]
    npc_tile = gen.data[os0 + OSL + 2]
    check("player struct 0 tile is $80 (12*0 | $80), as the game wrote it",
          objects.sprite_vtile(0, 1) == player_tile == 0x80,
          f"formula {objects.sprite_vtile(0, 1):#x} vs game {player_tile:#x}")
    check("NPC struct 1 tile is $8c (12*1 | $80), as the game wrote it",
          objects.sprite_vtile(1, npc_sprite) == npc_tile == 0x8c,
          f"formula {objects.sprite_vtile(1, npc_sprite):#x} vs game {npc_tile:#x}")
    check("the formula is positional, not a constant (slot 1 != slot 0)",
          objects.sprite_vtile(1, npc_sprite) != objects.sprite_vtile(0, npc_sprite))


def test_stage2_instantiate_vs_genuine() -> None:
    """Standing onto New Bark Town at the genuine save's own spot instantiates the
    same struct the game did — sprite, positional tile and map-object binding."""
    print("stage2 — instantiating the on-screen NPC matches the genuine save")
    if not (_present() and GENUINE.exists()):
        if not GENUINE.exists():
            check("a genuine polished save is present", False, GENUINE.name)
        return
    syms = SymFile.load(SYM)
    gen = savefile.Save.load(GENUINE)
    def gat(s: str) -> int:
        return gen._saved_offset(syms, s)
    OSL = savefile.OBJECT_STRUCT_LEN
    g = gat("wObjectStructs")
    want = (gen.data[g + OSL + 0], gen.data[g + OSL + 2], gen.data[g + OSL + 1])  # spr, vtile, moidx

    save = savefile.Save.load(GENUINE)  # a copy
    group, number, label, w, h = _map("NEW_BARK_TOWN")
    save.stand_on(syms, group=group, number=number, label=label,
                  width=w, height=h, y=6, x=15, rom_path=ROM)
    s = gat("wObjectStructs")
    got = (save.data[s + OSL + 0], save.data[s + OSL + 2], save.data[s + OSL + 1])
    check("struct 1 = (sprite 105, tile $8c, map-object 4), as the game instantiated it",
          got == want == (105, 0x8c, 4), f"got {got}, genuine {want}")
    # Palette index follows the map object's override (FAT_GUY's slot has palette 3).
    check("the palette index is the map object's override (3 - 1 = 2)",
          save.data[s + OSL + 0x21] == 2, f"got {save.data[s + OSL + 0x21]}")
    check("both checksums still verify after the Stage-2 rebuild",
          _primary_ok(save, syms) and _backup_ok(save, syms))


def test_edge_connection_tiles() -> None:
    """The connected neighbours fill the map edges, byte-for-byte against a genuine
    save standing at New Bark Town's east edge (Route 27 fills the border column)."""
    print("edges — the neighbours' tiles fill the border, matched to a genuine save")
    if not (_present() and GENUINE.exists()):
        if not GENUINE.exists():
            check("a genuine polished save is present", False, GENUINE.name)
        return
    rom = ROM.read_bytes()
    syms = SymFile.load(SYM)
    group, number, label, w, h = _map("NEW_BARK_TOWN")

    # New Bark Town connects west→Route29 (24,3) and east→Route27 (24,2).
    conns = [(c.direction, c.group, c.map_id)
             for c in mapread.map_connections(rom, syms, label, w)]
    check("New Bark Town reads its west+east connections in order",
          conns == [("west", 24, 3), ("east", 24, 2)], f"got {conns}")

    nbrs = mapread.neighbours(rom, syms, label, w, _resolver())
    check("both neighbours load (Route29 west, Route27 east)",
          [c.direction for c, _ in nbrs] == ["west", "east"])

    # The genuine save stands at (y=6, x=15) — an east-edge position where Route27
    # fills the window's last column. Its wScreenSave is the ground truth.
    gen = savefile.Save.load(GENUINE)
    ss_off = gen._saved_offset(syms, "wScreenSave")
    genuine = bytes(gen.data[ss_off:ss_off + blockdata.SCREEN_SAVE_SIZE])
    x, y = 15, 6
    with_nb = mapread.screen_save_bytes(rom, syms, label, w, h, x, y, neighbors=nbrs)
    without = mapread.screen_save_bytes(rom, syms, label, w, h, x, y)
    check("the edge window with neighbours matches the genuine save byte-for-byte",
          with_nb == genuine, f"got {with_nb.hex(' ')} vs {genuine.hex(' ')}")
    # Falsify: without the overlay the border column is void, so it must NOT match.
    check("without the overlay the border is void, so it does not match",
          without != genuine and without != with_nb,
          f"the interior-only window matched the genuine edge save: {without.hex(' ')}")

    # End to end: stand_on with the resolver threads the overlay all the way through.
    save = savefile.Save.load(GENUINE)
    save.stand_on(syms, group=group, number=number, label=label,
                  width=w, height=h, y=y, x=x, rom_path=ROM,
                  resolve_neighbour=_resolver())
    got = bytes(save.data[ss_off:ss_off + blockdata.SCREEN_SAVE_SIZE])
    check("stand_on with the resolver reproduces the genuine edge window",
          got == genuine, f"got {got.hex(' ')}")


def _resolver():
    """A `(group, map_id) -> (label, width, height) | None` over the map catalog,
    as `play._neighbour_resolver` builds for the boot."""
    d = dims(POLISHED)
    labels = label_of(POLISHED)
    rev = {(dim.group, dim.map_id): (labels[c], dim.width, dim.height)
           for c, dim in d.items() if c in labels}
    return lambda g, m: rev.get((g, m))


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
    test_object_events_walk()
    test_positional_vtile()
    test_stand_on_synthetic()
    test_stage2_instantiate_vs_genuine()
    test_edge_connection_tiles()
    print(f"\n{'FAILURES: ' + str(_failures) if _failures else 'all ok'}")
    sys.exit(1 if _failures else 0)
