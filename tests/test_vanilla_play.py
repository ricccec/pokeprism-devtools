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
    Symbol("wCurMapData",  1, 0xC000),
    Symbol("wMapGroup",    1, 0xC005),   # +5 within the block
    Symbol("wMapNumber",   1, 0xC006),   # +6
    Symbol("wYCoord",      1, 0xC007),   # +7
    Symbol("wXCoord",      1, 0xC008),   # +8
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
    # The private locator is the one the four writes go through; prove it agrees
    # with the offsets this test asserts against, or the rest proves nothing.
    for field, label in (("group", "wMapGroup"), ("number", "wMapNumber"),
                         ("y", "wYCoord"), ("x", "wXCoord")):
        check(f"{label} -> save offset {_OFF[field]}",
              save._curmap_offset(_SYMS, label) == _OFF[field])


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
              "wCurMapData" in str(e) or "sCurMapData" in str(e), str(e))
    except Exception as e:  # noqa: BLE001 — the point is the type
        check("stand_on raises SaveError, not a raw lookup error", False,
              f"{type(e).__name__}: {e}")
    else:
        check("stand_on refuses a .sym missing its symbols", False)


def test_build_clears_the_inherited_toolchain() -> None:
    """A stock pokecrystal wants a newer `rgbds` than a sibling tree may pin in
    the launching shell's `RGBDS`. Vanilla's build must clear that override so it
    falls back to the `rgbds` on `PATH` — the difference that closes the live
    build loop. Prove the runner is handed `RGBDS=""`, without running `make`."""
    from pokeprism_devtools.hacks.vanilla import play  # noqa: PLC0415
    from pokeprism_devtools.shared import make as make_mod  # noqa: PLC0415

    print("\nvanilla's build hands the make-runner an rgbds override, not the inherited pin")
    seen: dict[str, object] = {}

    def fake_run_make(root, target, log, *, jobs, env=None):
        seen["env"] = env
        return True

    original = make_mod.run_make
    make_mod.run_make = fake_run_make
    try:
        ok = play.Player(Path("/nonexistent")).build(lambda _l: None, jobs=1)
    finally:
        make_mod.run_make = original
    check("build succeeds through the runner", ok is True)
    check("it passes an env that clears RGBDS to the PATH toolchain",
          seen.get("env") == {"RGBDS": ""}, str(seen.get("env")))


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


def main() -> int:
    test_offsets_resolve()
    test_a_non_save_is_refused()
    test_the_checksum_round_trips()
    test_it_stands_on_the_exact_tile()
    test_a_missing_symbol_is_a_clear_refusal()
    test_build_clears_the_inherited_toolchain()
    test_real_map_resolution()
    test_a_real_sym_carries_these_symbols()

    print()
    if FAILED:
        print(f"{FAILED} check(s) FAILED")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
