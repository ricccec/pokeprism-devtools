#!/usr/bin/env python3
"""The vanilla save patcher, round-tripped — and the check falsified first.

`hacks/vanilla/savefile.py` stands you on a map by writing four bytes into a stock
Gen-2 save and fixing the checksum the game verifies on load. The way to trust a
writer is the one in `docs` — round-trip real bytes and read them back — and the
way to trust the round-trip is to make it fail on purpose first. So each check
here is shown catching the wrong answer (a transposed coordinate, a stale
checksum, a save that was never real) before it is shown passing the right one.

Everything runs against a *synthetic* save and a synthetic `.sym` we lay out
ourselves, because the offsets under test are read from the symbols, not the
game — so a build is not needed to prove the arithmetic. The one thing only a
real build can prove (that a real pokecrystal `.sym` actually carries these
symbols, laid out consistently) runs too, but only if a checkout is next door.

    ./.venv/bin/python tests/test_vanilla_play.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pokeprism_devtools.hacks.vanilla import savefile  # noqa: E402
from pokeprism_devtools.shared.symfile import Symbol, SymFile  # noqa: E402

FAILED = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global FAILED
    print(f"  [{'OK  ' if cond else 'FAIL'}] {label}{f' — {detail}' if detail else ''}")
    if not cond:
        FAILED += 1


# -- a save we control, end to end ----------------------------------------- #
# One SRAM bank (bank 0 keeps the file offsets small and the arithmetic legible).
# The Save section mirrors the real one's shape: a check byte, the game-data block
# (which contains the current-map data), then the checksum and the second check
# byte sitting *outside* the summed range.
_SYMS = SymFile([
    Symbol("sCheckValue1", 0, 0xA000),   # offset 0
    Symbol("sGameData",    0, 0xA001),   # offset 1  — checksum starts here
    Symbol("sCurMapData",  0, 0xA00A),   # offset 10
    Symbol("sGameDataEnd", 0, 0xA028),   # offset 40 — checksum ends here (exclusive)
    Symbol("sChecksum",    0, 0xA028),   # offset 40 — two bytes, outside the sum
    Symbol("sCheckValue2", 0, 0xA02A),   # offset 42
    # WRAM: only the within-block offsets matter (sCurMapData mirrors wCurMapData).
    # `_saved_offset` needs the block's *end* too, to know a field is inside it.
    Symbol("wCurMapData",    1, 0xC000),
    Symbol("wCurMapDataEnd", 1, 0xC009),   # the four fields sit at +5..+8
    Symbol("wMapGroup",      1, 0xC005),   # +5 within the block
    Symbol("wMapNumber",     1, 0xC006),   # +6
    Symbol("wYCoord",        1, 0xC007),   # +7
    Symbol("wXCoord",        1, 0xC008),   # +8
])
# The save offsets those symbols resolve to, spelled out so the test asserts
# against numbers it did not compute the same way the code did.
_OFF = {"group": 15, "number": 16, "y": 17, "x": 18, "chk": 40, "cv1": 0, "cv2": 42}


def fresh_save() -> savefile.Save:
    """A 64-byte save with valid check bytes and a non-trivial game-data block, so
    a wrong checksum can't pass by summing to the same zero."""
    data = bytearray(64)
    for i in range(1, 40):
        data[i] = (i * 7 + 3) & 0xFF      # some texture in the summed region
    data[_OFF["cv1"]] = savefile.CHECK_VALUE_1
    data[_OFF["cv2"]] = savefile.CHECK_VALUE_2
    return savefile.Save(data)


def stored_checksum(save: savefile.Save) -> int:
    lo, hi = save.data[_OFF["chk"]], save.data[_OFF["chk"] + 1]
    return lo | (hi << 8)


def verify_like_the_game(save: savefile.Save) -> bool:
    """VerifyChecksum, as `engine/menus/save.asm` does it: the sum over the game
    data must equal the stored checksum, or the game rejects the save and loads
    its backup instead."""
    got = savefile.checksum16(save.data[1:40])
    return got == stored_checksum(save)


def read_position(save: savefile.Save) -> tuple[int, int, int, int]:
    d = save.data
    return (d[_OFF["group"]], d[_OFF["number"]], d[_OFF["y"]], d[_OFF["x"]])


def test_offsets_resolve() -> None:
    print("\nthe symbols resolve to the offsets the writer will use")
    check("sCurMapData lands at 10", savefile.sram_offset(_SYMS["sCurMapData"]) == 10)
    save = fresh_save()
    # The private locator is the one every write goes through; prove it agrees
    # with the offsets this test asserts against, or the rest proves nothing.
    for field, label in (("group", "wMapGroup"), ("number", "wMapNumber"),
                         ("y", "wYCoord"), ("x", "wXCoord")):
        check(f"{label} -> save offset {_OFF[field]}",
              save._saved_offset(_SYMS, label) == _OFF[field])


def test_a_non_save_is_refused() -> None:
    print("\na file without the validity bytes is not a save — and looks_real says so")
    save = fresh_save()
    # Falsify: break a check byte and prove the guard fails on it.
    save.data[_OFF["cv2"]] = 0
    check("looks_real is False when a validity byte is wrong (the guard bites)",
          not save.looks_real(_SYMS))
    save.data[_OFF["cv2"]] = savefile.CHECK_VALUE_2
    check("and True once both are the values the game writes", save.looks_real(_SYMS))


def test_the_checksum_round_trips() -> None:
    print("\nthe checksum: falsified, then fixed")
    save = fresh_save()
    # Falsify: a save with a stale checksum must fail verification, or fixing it
    # would prove nothing.
    save.data[_OFF["chk"]] = 0
    save.data[_OFF["chk"] + 1] = 0
    check("a stale checksum fails verification (the check bites)",
          not verify_like_the_game(save))
    # stand_on recomputes it as part of the patch.
    save.stand_on(_SYMS, group=3, number=7, y=9, x=4)
    check("after stand_on the checksum verifies, the way the game will",
          verify_like_the_game(save))
    # And it is the sum *including* the position bytes we just wrote, not a stale
    # one taken before them.
    check("the stored checksum is the sum over the patched game data",
          stored_checksum(save) == savefile.checksum16(save.data[1:40]))


def test_it_stands_on_the_exact_tile() -> None:
    print("\nstanding on a map: a transposed coordinate is caught, the right one lands")
    # Falsify: a writer that swapped y and x would put (4, 9) where we asked for
    # (9, 4). Prove the round-trip distinguishes them — the whole point of reading
    # back four separate bytes rather than trusting the call.
    swapped = fresh_save()
    swapped.stand_on(_SYMS, group=3, number=7, y=4, x=9)   # a wrong patch
    check("a y/x swap reads back different from what we asked (the check bites)",
          read_position(swapped) != (3, 7, 9, 4))

    save = fresh_save()
    save.stand_on(_SYMS, group=3, number=7, y=9, x=4)
    check("stands on exactly (group 3, map 7) at tile (y=9, x=4)",
          read_position(save) == (3, 7, 9, 4), str(read_position(save)))
    # Nothing outside the four bytes and the checksum moved.
    before = fresh_save().data
    after = save.data
    moved = {i for i in range(len(after)) if after[i] != before[i]}
    expected = {_OFF["group"], _OFF["number"], _OFF["y"], _OFF["x"],
                _OFF["chk"], _OFF["chk"] + 1}
    check("only the four position bytes and the checksum changed",
          moved <= expected, f"also moved {sorted(moved - expected)}")


def test_a_missing_symbol_is_a_clear_refusal() -> None:
    print("\na .sym without the symbols gives a message, not a KeyError")
    thin = SymFile([Symbol("sCheckValue1", 0, 0xA000)])
    save = fresh_save()
    try:
        save.stand_on(thin, group=1, number=1, y=1, x=1)
    except savefile.SaveError as e:
        check("stand_on raises SaveError naming the missing symbol",
              "wMapGroup" in str(e), str(e))
    except Exception as e:  # noqa: BLE001 — the point is the type
        check("stand_on raises SaveError, not a raw lookup error", False,
              f"{type(e).__name__}: {e}")
    else:
        check("stand_on refuses a .sym missing its symbols", False)


def test_build_toolchain_default_and_override() -> None:
    """The toolchain env is the adapter's *default*, and a caller may override it.
    A stock pokecrystal wants a newer `rgbds` than a sibling tree may pin in the
    launching shell's `RGBDS`, so vanilla's default clears it to the `PATH`
    toolchain (`RGBDS=""`) — the difference that closes the live build loop. But
    a caller who knows the machine's `rgbds` better must win. Prove both, without
    running `make`."""
    from pokeprism_devtools.hacks.vanilla import play  # noqa: PLC0415
    from pokeprism_devtools.shared import make as make_mod  # noqa: PLC0415

    print("\nvanilla's build: the rgbds default clears the pin, and a caller can override it")
    seen: dict[str, object] = {}

    def fake_run_make(root, target, log, *, jobs, env=None):
        seen["env"] = env
        return True

    original = make_mod.run_make
    make_mod.run_make = fake_run_make
    try:
        # An explicit target keeps this off the filesystem: the root is fake, so
        # its Makefile can't be read, and a named target is trusted rather than
        # validated against a list that isn't there. This test is about env.
        t = "pokecrystal.gbc"
        # No env: the adapter's declared default (clear RGBDS to PATH).
        ok = play.Player(Path("/nonexistent")).build(lambda _l: None, jobs=1, target=t)
        check("build succeeds through the runner", ok is True)
        check("env=None takes the default that clears RGBDS to PATH",
              seen.get("env") == {"RGBDS": ""}, str(seen.get("env")))
        # An override: the caller's toolchain wins, the default is dropped.
        chosen = {"RGBDS": "/opt/rgbds-1.0.1/"}
        play.Player(Path("/nonexistent")).build(lambda _l: None, jobs=1, target=t, env=chosen)
        check("a passed env overrides the default entirely",
              seen.get("env") == chosen, str(seen.get("env")))
    finally:
        make_mod.run_make = original


def test_targets_are_read_from_the_makefile() -> None:
    """The targets the studio offers are the `roms :=` list, read from the
    Makefile — not a hardcoded pair that once omitted three real ROMs. A
    synthetic Makefile (the real block's shape: `roms :=` then backslash-
    continued names, ending on a non-continued line) proves the parse without a
    checkout, then the validation the parse feeds."""
    import tempfile  # noqa: PLC0415

    from pokeprism_devtools.hacks.vanilla import play  # noqa: PLC0415
    from pokeprism_devtools.hacks.seam import PlayError  # noqa: PLC0415

    print("\nvanilla's targets are the Makefile's `roms :=` list, read not guessed")
    makefile = (
        "roms := \\\n"
        "\tpokecrystal.gbc \\\n"
        "\tpokecrystal11.gbc \\\n"
        "\tpokecrystal_au.gbc \\\n"
        "\tpokecrystal_debug.gbc \\\n"
        "\tpokecrystal11_debug.gbc\n"
        "patches := pokecrystal11.patch\n"
        "pokecrystal11_vc.gbc: foo\n")   # a .gbc past the block must not be swept in
    want = ("pokecrystal.gbc", "pokecrystal11.gbc", "pokecrystal_au.gbc",
            "pokecrystal_debug.gbc", "pokecrystal11_debug.gbc")

    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "Makefile").write_text(makefile)
        p = play.Player(root)
        check("targets() are the five roms in order, and only those",
              p.targets() == want, str(p.targets()))
        check("the default target is the first rom the Makefile lists",
              p._target(None) == "pokecrystal.gbc")
        check("a rom the Makefile lists validates",
              p._target("pokecrystal11_debug.gbc") == "pokecrystal11_debug.gbc")
        try:
            p._target("pokecrystal_vc.gbc")
        except PlayError:
            check("a target the Makefile does not list is refused", True)
        else:
            check("a target the Makefile does not list is refused", False)

    print("  a tree whose Makefile can't be read offers nothing, and says so")
    empty = play.Player(Path("/nonexistent"))
    check("targets() degrades to () when the Makefile can't be read",
          empty.targets() == ())
    try:
        empty._target(None)
    except PlayError:
        check("no default target when there is no roms list to draw one from", True)
    else:
        check("no default target when there is no roms list to draw one from", False)


# -- the one thing only a real build can show ------------------------------ #
def test_a_real_sym_carries_these_symbols() -> None:
    root = Path.home() / "code/ricccec/pokecrystal"
    sym = root / "pokecrystal.sym"
    print("\nthe real pokecrystal.sym (if built next door) carries the layout")
    if not sym.exists():
        print(f"  --   no built {sym} — skipping (run `make pokecrystal.gbc` to cover this)")
        return
    syms = SymFile.load(sym)
    needed = ("sCheckValue1", "sCheckValue2", "sGameData", "sGameDataEnd",
              "sChecksum", "sCurMapData", "wCurMapData",
              "wMapGroup", "wMapNumber", "wYCoord", "wXCoord")
    missing = [n for n in needed if n not in syms]
    check("every symbol the patcher reads is present", not missing, f"missing {missing}")
    if missing:
        return
    g0 = savefile.sram_offset(syms["sGameData"])
    g1 = savefile.sram_offset(syms["sGameDataEnd"])
    chk = savefile.sram_offset(syms["sChecksum"])
    check("the game-data block is non-empty and the checksum sits outside it",
          g0 < g1 and not (g0 <= chk < g1),
          f"gameData [{g0}, {g1}), checksum at {chk}")
    within = syms["wYCoord"].addr - syms["wCurMapData"].addr
    check("wYCoord sits inside wCurMapData (a positive within-block offset)",
          within > 0, f"offset {within}")


def test_real_map_resolution() -> None:
    """The other half of boot the writer relies on: turning a map constant into
    the `(group, number)` the save stores. That parse runs against the real tree
    with no build at all, so check it there — against values `map_constants.asm`
    spells in its own trailing comments."""
    from pokeprism_devtools.hacks.vanilla import play  # noqa: PLC0415

    root = Path.home() / "code/ricccec/pokecrystal"
    print("\na real pokecrystal checkout resolves maps to the group/number it comments")
    if not root.exists():
        print(f"  --   no checkout at {root} — skipping")
        return
    where = play.Player(root)._where
    # (map const) -> (group, number), read straight off the source comments.
    known = {"OLIVINE_POKECENTER_1F": (1, 1), "OLIVINE_GYM": (1, 2),
             "NEW_BARK_TOWN": (24, 4)}
    for const, want in known.items():
        got = where(const)
        check(f"{const} resolves to group/number {want}", got == want, str(got))


def test_the_boot_rebuilds_the_whole_map() -> None:
    """The heart of it: standing on a map must rebuild the *map*, not just the
    position — the tiles and objects around you — or the game renders the previous
    map's state at the new coordinates (the corruption a live playtest found).

    Runs the whole boot as a dry-run on a *copy* of the real `pokecrystal11_debug`
    save next door (never the file itself). Falsified first, the project idiom:
    each check is shown failing on the *stale* pre-rebuild bytes a position-only
    boot would leave, before it is shown passing on the rebuilt ones. The expected
    tiles/objects are computed independently from the ROM, so a writer that agrees
    with itself but not the game can't pass. Two maps: an outdoor town with
    connections and NPCs, and an indoor lab.
    """
    from pokeprism_devtools.hacks.vanilla import play  # noqa: PLC0415
    from pokeprism_devtools.shared.overworld import blockdata, people  # noqa: PLC0415

    root = Path.home() / "code/ricccec/pokecrystal"
    rom = root / "pokecrystal11_debug.gbc"
    sym = root / "pokecrystal11_debug.sym"
    template = root / "pokecrystal11_debug.sav"
    print("\nthe full boot rebuilds the map (dry-run on a copy of the real debug save)")
    if not (rom.exists() and sym.exists() and template.exists()):
        print("  --   no built debug ROM+save next door — skipping "
              "(build pokecrystal11_debug.gbc and save in-game once to cover this)")
        return

    syms = SymFile.load(sym)
    where = play.Player(root)._where

    for target, y, x in (("CHERRYGROVE_CITY", 8, 8), ("ELMS_LAB", 3, 3)):
        print(f"  {target} at ({y}, {x})")
        group, number = where(target)
        save = savefile.Save(bytearray(template.read_bytes()))
        check("the debug save looks real before we touch it", save.looks_real(syms))

        ss = save._saved_offset(syms, "wScreenSave")
        mo = save._saved_offset(syms, "wMapObjects")
        os_ = save._saved_offset(syms, "wObjectStructs")
        stale_screen = bytes(save.data[ss:ss + 30])

        # What the rebuild *should* produce, computed independently from the ROM.
        bd = blockdata.load(rom, syms, group, number, name=target)
        neighbors = []
        for conn in blockdata.map_connections(rom, syms, group, number,
                                               map_width=bd.width):
            try:
                neighbors.append((conn, blockdata.load(rom, syms, conn.group,
                                                       conn.map_id)))
            except ValueError:
                continue
        want_screen = blockdata.compute_screen_save(bd, x, y, neighbors=neighbors)
        events = blockdata.object_events(rom, syms, group, number, name=target)

        # Falsify: the stale screen bytes are NOT already the destination's, so a
        # boot that left them (the position-only bug) would fail the check below.
        check("  the pre-rebuild wScreenSave is the old map's, not the "
              "destination's (a position-only boot would render corrupt)",
              stale_screen != want_screen)

        changes = save.stand_on(syms, group=group, number=number, y=y, x=x,
                                rom_path=rom, keep_people=False)

        check("  after the rebuild, wScreenSave is the destination map's tiles",
              bytes(save.data[ss:ss + 30]) == want_screen)

        # Objects: slots 1.. hold the destination map's own NPCs (its events).
        room = min(len(events), people.NUM_OBJECTS - 1)
        loaded = all(
            bytes(save.data[mo + (i + 1) * people.MAP_OBJECT_LEN + people.MAPOBJ_SPRITE:
                            mo + (i + 1) * people.MAP_OBJECT_LEN + people.MAPOBJ_SPRITE
                            + people.PERSON_EVENT_LEN]) == events[i]
            for i in range(room))
        check(f"  wMapObjects holds the destination map's {room} NPC(s)",
              room > 0 and loaded)

        # The player object struct sits at the new tile (the +4 map convention).
        check("  the player object struct is at the new tile (x+4, y+4)",
              save.data[os_ + people.OBJ_STANDING_MAP_X] == (x + 4) & 0xFF and
              save.data[os_ + people.OBJ_STANDING_MAP_Y] == (y + 4) & 0xFF)

        # Primary and backup checksums both verify, and the backup mirrors the
        # primary — the whole save is internally consistent, as after an in-game
        # save. Falsify each by corrupting one byte and re-summing.
        def verifies(g0: str, g1: str, ck: str) -> bool:
            a = savefile.sram_offset(syms[g0])
            b = savefile.sram_offset(syms[g1])
            c = savefile.sram_offset(syms[ck])
            return savefile.checksum16(save.data[a:b]) == (save.data[c] | save.data[c + 1] << 8)

        check("  the primary checksum verifies over the rebuilt game data",
              verifies("sGameData", "sGameDataEnd", "sChecksum"))
        check("  the backup checksum verifies over the mirrored game data",
              verifies("sBackupGameData", "sBackupGameDataEnd", "sBackupChecksum"))
        pg0 = savefile.sram_offset(syms["sGameData"])
        pg1 = savefile.sram_offset(syms["sGameDataEnd"])
        bg0 = savefile.sram_offset(syms["sBackupGameData"])
        bg1 = savefile.sram_offset(syms["sBackupGameDataEnd"])
        check("  the backup game data byte-for-byte mirrors the primary",
              bytes(save.data[bg0:bg1]) == bytes(save.data[pg0:pg1]))

        # Falsify the checksum check itself: corrupt a game-data byte and prove
        # verification now fails, so a passing check above means something.
        save.data[pg0] ^= 0xFF
        check("  a corrupted game-data byte fails the primary checksum "
              "(the check bites)",
              not verifies("sGameData", "sGameDataEnd", "sChecksum"))

        check("  the boot reports the rebuild it performed",
              any("wScreenSave" in c for c in changes)
              and any("people" in c for c in changes), str(changes))


#: Saves the *game* wrote, kept under names the backup rotation cannot age out
#: (it only ever writes `pokecrystal11_debug-<timestamp>.sav`). Ground truth for
#: the VRAM check below has to be a save no boot has ever patched, and the working
#: `pokecrystal11_debug.sav` is patched in place, so it can never be one of these.
#: Each was made by warping in, walking through a door and back — `MAPSETUP_WARP`
#: runs both `LoadMapGraphics` (rebuilding the VRAM allocation) and
#: `LoadMapObjects` (writing the structs), so nothing the patcher wrote survives —
#: then saving in-game.
_GENUINE_SAVES = Path.home() / "code/ricccec/pokecrystal/.devtools/sav-backups"
_FIXTURES = (
    # file, the map it stands on, and what only this one reaches
    ("GENUINE-route-32.sav", "ROUTE_32",
     "its group's pool carries a variable sprite, so it is the only one that "
     "reaches the still-vs-walking resolution"),
    ("GENUINE-new-bark-town.sav", "NEW_BARK_TOWN",
     "a different group and a different pool order"),
)


def _engine_wrote_the_structs(raw: bytes, syms: SymFile, rom: Path,
                              group: int, number: int, x: int, y: int) -> tuple[bool, str]:
    """Did the *game* write this save's `wObjectStructs`, or did we?

    The question the old version of this test forgot to ask. `instantiate_visible_sprites`
    writes the same `SPRITE_TILE` field the check below reads, so on a save any boot
    has touched the comparison is self-confirming — it passes by construction and
    can never fail. Provenance is therefore part of the check, not a property of the
    filename.

    Answered by re-running our own patcher on a copy at the save's own map and
    position and looking for bytes the fixture has set where ours are zero. Our
    writer zeroes each slot and fills only what `CopyMapObjectToObjectStruct` and
    `CopySpriteMovementData` set, leaving the animated remainder (step type, step
    frame, the standing/last tile) for the engine's first frame — so those bytes
    are set *only* by a game that actually ran. Deriving the fingerprint from the
    writer rather than listing offsets here means it cannot go stale when the
    writer grows a field.
    """
    from pokeprism_devtools.shared.overworld import people  # noqa: PLC0415

    ours = savefile.Save(bytearray(raw))
    ours.stand_on(syms, group=group, number=number, y=y, x=x,
                  rom_path=rom, keep_people=False)
    at = ours._saved_offset(syms, "wObjectStructs")
    span = people.NUM_OBJECT_STRUCTS * people.OBJECT_STRUCT_LEN
    engine_only = [k for k in range(span) if raw[at + k] and not ours.data[at + k]]
    if not engine_only:
        return False, "our own patcher reproduces every byte — this save is our output"
    slots = sorted({k // people.OBJECT_STRUCT_LEN for k in engine_only})
    return True, (f"{len(engine_only)} bytes across struct(s) {slots} that our "
                  "patcher leaves for the engine's first frame")


def test_visible_sprites_get_the_right_vram_tile() -> None:
    """Every on-screen object must get the VRAM tile the game gives it — or it
    renders as whatever sprite happens to sit at the tile it falls back to (the
    player, at tile 0). This is the check the boot test lacked: it confirmed a
    sprite was *instantiated*, never that it pointed at the *right* graphics.

    Each fixture is a save the game wrote while standing on a real outdoor map, so
    every visible object's `SPRITE_TILE` is the engine's own answer, which we
    recompute from the ROM and compare against. The bug this first guarded:
    `outdoor_sprite_ids` read a group's sprite list until a 0 byte, but stock's
    lists are a fixed 23 entries with no terminator, so it ran into the next
    groups' lists — a pool of a hundred-plus ids that shouldered the map's real
    sprites out of VRAM, so they fell back to the player's tile and rendered as
    the player.

    Two things keep it from quietly rotting the way it did before. Provenance is
    checked, not assumed (see :func:`_engine_wrote_the_structs`), because a save
    the patcher has touched makes this comparison self-confirming. And the check is
    *falsified*: each way the allocation can be got wrong is fed in and must be
    caught by at least one fixture, so a suite that has stopped biting fails loudly
    instead of printing OK. What no fixture reaches today is sizing a still sprite
    as a walking one — neither map has a still sprite on screen ahead of its NPCs —
    and a busier outdoor save would close that.
    """
    from pokeprism_devtools.shared.overworld import blockdata, people, spritevram  # noqa: PLC0415

    root = Path.home() / "code/ricccec/pokecrystal"
    rom = root / "pokecrystal11_debug.gbc"
    sym = root / "pokecrystal11_debug.sym"
    print("\nvisible objects get the game's VRAM tile (saves the game wrote)")
    if not (rom.exists() and sym.exists()):
        print("  --   no built debug ROM next door — skipping")
        return
    present = [f for f in _FIXTURES if (_GENUINE_SAVES / f[0]).exists()]
    if not present:
        print(f"  --   no genuine saves in {_GENUINE_SAVES} — skipping. Make one by "
              "booting to an outdoor map, walking through a door and back, saving "
              "in-game, and copying the .sav out before the next boot patches it.")
        return

    syms = SymFile.load(sym)
    pk, _vars = spritevram._sprite_cutoffs(root / "constants" / "sprite_constants.asm")
    # Every way the allocation can come out wrong, as inputs to the real
    # `sprite_tiles` — no second implementation to drift from the first. Each must
    # be caught somewhere in the fixture set; which fixture catches which is left
    # open, because that depends on what happened to be on screen.
    caught: dict[str, list[str]] = {
        "a pool read to the first 0 byte (the historical overrun)": [],
        "variable sprites left unresolved": [],
        "the pool in sorted order, not the ROM's": [],
        "a pool missing one id": [],
        "the wrong player sprite in slot 0": [],
    }

    for filename, where, reaches in present:
        raw = (_GENUINE_SAVES / filename).read_bytes()
        save = savefile.Save(bytearray(raw))
        off = save._saved_offset
        group = save.data[off(syms, "wMapGroup")]
        number = save.data[off(syms, "wMapNumber")]
        x, y = save.data[off(syms, "wXCoord")], save.data[off(syms, "wYCoord")]
        os_off = off(syms, "wObjectStructs")
        player = save.data[os_off + people.OBJ_SPRITE]
        print(f"  {filename} — {where} at ({x}, {y}), {reaches}")

        check("    the save looks real", save.looks_real(syms))
        genuine, detail = _engine_wrote_the_structs(raw, syms, rom, group, number, x, y)
        check("    the *game* wrote these object structs, not our patcher "
              "(without this the comparison below confirms itself)", genuine, detail)
        if not genuine:
            continue

        bd = blockdata.load(rom, syms, group, number)
        check("    it stands on an outdoor map, so the group pool is in play",
              blockdata.is_outdoor(bd.permission))
        if not blockdata.is_outdoor(bd.permission):
            continue

        pool = spritevram.outdoor_sprite_ids(rom, syms, group)
        check("    the outdoor sprite pool is the group's own fixed list, not an "
              "overrun into the next groups", len(pool) <= 23, f"{len(pool)} ids")

        vs = off(syms, "wVariableSprites")
        variable_sprites = bytes(save.data[vs:vs + 16])

        def agrees(tiles: dict[int, int], report: bool = False) -> bool:
            ok = True
            for i in range(people.NUM_OBJECT_STRUCTS):
                p = os_off + i * people.OBJECT_STRUCT_LEN
                spr = save.data[p + people.OBJ_SPRITE]
                if spr == 0 and i != 0:
                    continue
                is_mon = spr >= pk              # mon/variable ids: the game uses tile 0
                game_tile = save.data[p + people.OBJ_SPRITE_TILE]
                # A real sprite must never be absent from the allocation; and where
                # the game placed a tile (non-zero), ours must equal it. Zero can be
                # a stale slot in the save, so it isn't asserted against.
                if not ((is_mon or spr in tiles)
                        and (game_tile == 0 or tiles.get(spr) == game_tile)):
                    ok = False
                    if report:
                        print(f"      sprite {spr}: game={game_tile} "
                              f"ours={tiles.get(spr)}")
            return ok

        def tiles_from(ids: list[int], *, variables: bytes = variable_sprites,
                       slot0: int = player) -> dict[int, int]:
            return spritevram.sprite_tiles(rom, syms, slot0, ids,
                                           variable_sprites=variables)

        check("    every visible object gets a real VRAM tile, matching the game "
              "where it placed one (so a boulder is a boulder, not the player)",
              agrees(tiles_from(pool), report=True))

        # Falsify. Each mutation is the real allocator fed a wrong pool, a wrong
        # variable-sprite table or a wrong player — if one of these still agrees
        # with the game everywhere, this fixture is not watching that mistake.
        mutants = {
            "a pool read to the first 0 byte (the historical overrun)":
                tiles_from(spritevram.outdoor_sprite_ids(rom, syms, group, count=None)),
            "variable sprites left unresolved": tiles_from(pool, variables=b""),
            "the pool in sorted order, not the ROM's": tiles_from(sorted(pool)),
            "the wrong player sprite in slot 0": tiles_from(pool, slot0=0),
        }
        for name, tiles in mutants.items():
            if not agrees(tiles):
                caught[name].append(where)
        # "Missing one id" is a family of mutations — the pool must be complete, and
        # dropping an id only moves a tile when it sorts ahead of something on
        # screen, so any one of them biting is what makes the claim true.
        if any(not agrees(tiles_from(pool[:i] + pool[i + 1:])) for i in range(len(pool))):
            caught["a pool missing one id"].append(where)

    print("  the check bites — each way of getting the allocation wrong is caught:")
    for name, by in caught.items():
        check(f"    {name}", bool(by), "caught by " + (", ".join(by) or "NO fixture"))

    # Falsify the provenance guard itself: patch one of these saves and it must
    # stop being ground truth. Without this, a guard that returned True
    # unconditionally would sit here looking green while the comparison above went
    # back to reading its own writing — which is exactly how this test decayed.
    filename, where, _ = present[0]
    patched = savefile.Save(bytearray((_GENUINE_SAVES / filename).read_bytes()))
    off = patched._saved_offset
    group = patched.data[off(syms, "wMapGroup")]
    number = patched.data[off(syms, "wMapNumber")]
    x, y = patched.data[off(syms, "wXCoord")], patched.data[off(syms, "wYCoord")]
    patched.stand_on(syms, group=group, number=number, y=y, x=x,
                     rom_path=rom, keep_people=False)
    genuine, detail = _engine_wrote_the_structs(bytes(patched.data), syms, rom,
                                                group, number, x, y)
    check(f"    a patched {where} save is refused as ground truth "
          "(the provenance guard bites)", not genuine, detail)


def main() -> int:
    test_offsets_resolve()
    test_a_non_save_is_refused()
    test_the_checksum_round_trips()
    test_it_stands_on_the_exact_tile()
    test_a_missing_symbol_is_a_clear_refusal()
    test_build_toolchain_default_and_override()
    test_targets_are_read_from_the_makefile()
    test_real_map_resolution()
    test_the_boot_rebuilds_the_whole_map()
    test_visible_sprites_get_the_right_vram_tile()
    test_a_real_sym_carries_these_symbols()

    print()
    if FAILED:
        print(f"{FAILED} check(s) FAILED")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
