#!/usr/bin/env python3
"""Smoke test for the pokeprism_devtools library against a real pokeprism
build. Run from anywhere inside the pokeprism repo (or with the package
installed via pipx):

    python -m pokeprism_devtools.tests.test_lib   # if exposed as a module
    python /path/to/pokeprism-devtools/tests/test_lib.py

Exits non-zero on the first failed check. No pytest dependency — just a
sanity check that the parsers handle the real files.
"""

from __future__ import annotations

import sys

from pokeprism_devtools import blockdata, constants, lz, maps, paths, savefile, symfile


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

    print("\nlz.py")
    # Round-trip every (X.lz, X) pair under tilesets/ that the build left
    # behind. These are real compressed assets fed through the game's own
    # compressor (utils/lzcomp); decompressing must reproduce them byte-for-byte.
    pairs = [
        (p, p.with_suffix(""))
        for p in (root / "tilesets").glob("*.lz")
        if p.with_suffix("").exists()
    ]
    if not pairs:
        print("  (no .lz pairs found — run `make nodebug` to generate them)")
    else:
        fails = []
        for lzp, rawp in pairs:
            try:
                decompressed, consumed = lz.decompress(lzp.read_bytes())
                if decompressed != rawp.read_bytes() or consumed != lzp.stat().st_size:
                    fails.append(lzp.name)
            except Exception as e:
                fails.append(f"{lzp.name} ({e})")
        check(
            f"round-trip {len(pairs)} (.lz, raw) pairs",
            not fails,
            f"{len(fails)} fail" if fails else "all match byte-for-byte",
        )

    print("\nblockdata.py — load")
    rom = paths.rom_path(root)
    caper = blockdata.load(rom, syms, group=2, map_id=5, name="CAPER_HOUSE")
    check(
        "CAPER_HOUSE is 4x4 blocks with 16 bytes of grid",
        caper.width == 4 and caper.height == 4 and len(caper.blocks) == 16,
        f"{caper.width}x{caper.height}, len={len(caper.blocks)}",
    )
    aqua = blockdata.load(rom, syms, group=31, map_id=2, name="ACQUA_TUTORIAL")
    check(
        "ACQUA_TUTORIAL is 25x30 blocks with 750 bytes of grid",
        aqua.width == 25 and aqua.height == 30 and len(aqua.blocks) == 750,
        f"{aqua.width}x{aqua.height}, len={len(aqua.blocks)}",
    )

    print("\nblockdata.py — strong cross-check against real save")
    # If a backup of the user's pre-patch save exists, use it to verify our
    # computed wScreenSave matches what the game wrote.
    backups = sorted((root / ".devtools" / "sav-backups").glob(
        "pokeprism_nodebug-*.sav"
    ))
    candidate = None
    for p in backups:
        # Find a backup with intact warp state (= a real save, not a
        # post-over-zero artifact).
        sf = savefile.SaveFile.load(p)
        if any(b != 0 for b in sf.data[0x2833:0x2843]):
            candidate = p
            break
    if candidate is None:
        print("  (no intact backup .sav found — skipping)")
    else:
        sf = savefile.SaveFile.load(candidate)
        off = {k: v["sav_offset"] for k, v in (
            ("wMapGroup", {"sav_offset": 0x2843}),
            ("wMapNumber", {"sav_offset": 0x2844}),
            ("wYCoord", {"sav_offset": 0x2845}),
            ("wXCoord", {"sav_offset": 0x2846}),
            ("wScreenSave", {"sav_offset": 0x2847}),
        )}  # values pulled from the inventory; pinning them keeps the
            # check honest if the inventory changes.
        g = sf.data[off["wMapGroup"]]
        m = sf.data[off["wMapNumber"]]
        y = sf.data[off["wYCoord"]]
        x = sf.data[off["wXCoord"]]
        bd = blockdata.load(rom, syms, group=g, map_id=m)
        computed = blockdata.compute_screen_save(bd, x, y)
        actual = bytes(sf.data[off["wScreenSave"]:off["wScreenSave"] + 30])
        check(
            f"wScreenSave for (g={g},m={m},x={x},y={y}) matches the save's actual bytes",
            computed == actual,
            f"computed={computed.hex()} vs actual={actual.hex()}",
        )

    print("\nmaps.py")
    map_defs = maps.parse_maps(root / "constants" / "map_dimension_constants.asm")
    check("non-empty", len(map_defs) > 100, f"{len(map_defs)} maps")
    first = map_defs[0]
    check(
        "first map is INTRO_OUTSIDE group=1 id=1",
        first.name == "INTRO_OUTSIDE" and first.group == 1 and first.map_id == 1,
        str(first),
    )
    azalea = next((m for m in map_defs if m.name == "AZALEA_TOWN"), None)
    check("AZALEA_TOWN parses", azalea is not None, str(azalea))

    print("\nconstants.py — stop_at_reset")
    pokemon = constants.parse_constants(
        root / "constants" / "pokemon_constants.asm",
        start_counter=1,
        stop_at_reset=True,
    )
    check(
        "pokemon enum gives BULBASAUR=1 .. LIBABEEL=254",
        pokemon[0].name == "BULBASAUR" and pokemon[0].value == 1
        and pokemon[-1].name == "LIBABEEL" and pokemon[-1].value == 254,
        f"first={pokemon[0]} last={pokemon[-1]}",
    )

    print("\nsavefile.py — checksum")
    check("empty checksum is 0", savefile.checksum16(b"") == 0)
    sb = savefile.checksum16(b"\x42")
    check("single-byte 0x42 → 0x0042", sb == 0x0042, f"got ${sb:04x}")
    # Overflow case: low byte wraps from 0xFF to 0x00, high byte bumps to 1.
    val = savefile.checksum16(b"\xff\x01")
    check("overflow 0xFF,0x01 → 0x0100", val == 0x0100, f"got ${val:04x}")
    # Four 0xFF bytes: low cycles FF→FE→FD→FC, high bumps three times.
    val = savefile.checksum16(b"\xff" * 4)
    check("four 0xFF → 0x03FC", val == 0x03FC, f"got ${val:04x}")

    print("\nsavefile.py — encode_name")
    # "Adam" + 4 terminators: 0x80 ('A'), 0xa3 ('d'), 0xa0 ('a'),
    # 0xac ('m'), then four 0x50 ('@'). Confirmed against the real save.
    enc = savefile.encode_name("Adam", 8)
    check(
        "encode 'Adam' to 8 bytes",
        enc == bytes([0x80, 0xA3, 0xA0, 0xAC, 0x50, 0x50, 0x50, 0x50]),
        f"got {enc.hex()}",
    )
    enc = savefile.encode_name("RED", 8)
    check(
        "encode 'RED' to 8 bytes",
        enc == bytes([0x91, 0x84, 0x83, 0x50, 0x50, 0x50, 0x50, 0x50]),
        f"got {enc.hex()}",
    )

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
            # sGameData = sPlayerData..sExtraData (the next SRAM section).
            # No sGameDataEnd label exists in the .sym, but the gap between
            # sPokemonData and sExtraData is exactly the PokemonData size
            # (sGameData ends where sExtraData starts).
            game_data_start = savefile.sram_to_file_offset(
                1, syms["sPlayerData"].addr
            )
            game_data_end = savefile.sram_to_file_offset(
                1, syms["sExtraData"].addr
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
