#!/usr/bin/env python3
"""Smoke test for tools/_lib/. Run from anywhere inside the repo:

    python3 tools/test_lib.py

Exits non-zero on the first failed check. Doesn't require pytest — just a
sanity check that the parsers handle the real files.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make `_lib` importable when invoked as a script.
sys.path.insert(0, str(Path(__file__).parent))

from _lib import constants, paths, savefile, symfile  # noqa: E402


def check(label: str, cond: bool, detail: str = "") -> None:
    mark = "OK  " if cond else "FAIL"
    print(f"  [{mark}] {label}{(': ' + detail) if detail else ''}")
    if not cond:
        sys.exit(1)


def main() -> None:
    root = paths.repo_root()
    print(f"Repo root: {root}")

    print("\npaths.py")
    rom = paths.rom_path(root)
    check("rom_path() resolves", rom.exists(), str(rom.name))
    sym = paths.sym_path(root)
    check("sym_path() resolves", sym.exists(), str(sym.name))

    print("\nsymfile.py")
    syms = symfile.SymFile.load(sym)
    check("non-empty", len(syms) > 1000, f"{len(syms)} symbols")
    for label in ("sValidCheck1", "sChecksum", "sPlayerData", "wPlayerName"):
        check(f"contains {label}", label in syms)

    s = syms["sValidCheck1"]
    check(
        "sValidCheck1 is in SRAM bank 1",
        s.bank == 1 and s.region == "SRAM",
        f"{s}",
    )

    # The canonical entry: parse constants.asm with INCLUDEs followed, then
    # we get the full enum table with correct counter context for every file.
    all_consts = constants.parse_constants(
        root / "constants.asm", base_dir=root
    )
    all_d = constants.to_dict(all_consts)

    print("\nconstants.py — pokemon (via constants.asm)")
    check("NO_POKEMON == 0", all_d.get("NO_POKEMON") == 0)
    check("BULBASAUR == 1", all_d.get("BULBASAUR") == 1)
    check("CHARMANDER == 4", all_d.get("CHARMANDER") == 4)
    check("EGG is defined", "EGG" in all_d, f"= {all_d.get('EGG')}")

    print("\nconstants.py — items")
    check("NO_ITEM == 0", all_d.get("NO_ITEM") == 0)
    check("MASTER_BALL == 1", all_d.get("MASTER_BALL") == 1)
    check("POKE_BALL == 5", all_d.get("POKE_BALL") == 5)

    print("\nconstants.py — event flags")
    check("EVENT_0 == 0", all_d.get("EVENT_0") == 0)
    check("EVENT_1 == 1", all_d.get("EVENT_1") == 1)
    # The file uses `const skip` as a placeholder for unused slots — those
    # land in the parsed output as Const(name='skip', value=N) but the
    # counter still advances correctly. The "real" flags are EVENT_*.
    flag_names = [c.name for c in all_consts if c.name.startswith("EVENT_")]
    check("EVENT_* count is sensible", len(flag_names) >= 1000, f"{len(flag_names)} EVENT_* parsed")

    print("\nsavefile.py — checksum")
    check("empty checksum is 0", savefile.checksum16(b"") == 0)
    # For byte=0x42: e = 0x42, d = (0+0-0x42)&0xFF = 0xBE → 0xBE42.
    # The asm's `adc d; sub e` always biases d by -e on the first byte.
    sb = savefile.checksum16(b"\x42")
    check("single-byte 0x42 → 0xBE42", sb == 0xBE42, f"got ${sb:04x}")
    # Overflow case: e wraps to 0 with carry; d advances by +1-e_new.
    val = savefile.checksum16(b"\xff\x01")
    check("overflow 0xFF,0x01 → 0x0200", val == 0x0200, f"got ${val:04x}")

    print("\nsavefile.py — offset math")
    off = savefile.sram_to_file_offset(1, 0xA009)  # sPlayerData
    check("sPlayerData at file offset 0x2009", off == 0x2009, f"got ${off:04x}")
    off = savefile.sram_to_file_offset(1, 0xAD0D)  # sChecksum
    check("sChecksum at file offset 0x2D0D", off == 0x2D0D, f"got ${off:04x}")

    print("\nsavefile.py — verify against existing .sav (if present and used)")
    sav = root / "pokeprism_nodebug.sav"
    if not sav.exists():
        print("  (no .sav present — skipping live verification)")
    else:
        sf = savefile.SaveFile.load(sav)
        valid1, valid2 = sf.data[0x2008], sf.data[0x2D0F]
        if valid1 != 0x63 or valid2 != 0x7F:
            print(
                f"  (.sav has no real save — valid1=${valid1:02x} valid2=${valid2:02x}, "
                "expected $63 / $7f. Skipping checksum cross-check.)"
            )
        else:
            game_data_start = savefile.sram_to_file_offset(
                1, syms["sPlayerData"].addr
            )
            game_data_end = savefile.sram_to_file_offset(
                1, syms["sPokemonDataEnd"].addr
            )
            computed = savefile.checksum16(
                sf.read(game_data_start, game_data_end - game_data_start)
            )
            stored = sf.data[0x2D0D] | (sf.data[0x2D0E] << 8)
            check(
                "checksum matches stored value",
                computed == stored,
                f"computed=${computed:04x} stored=${stored:04x}",
            )

    print("\nall checks passed")


if __name__ == "__main__":
    main()
