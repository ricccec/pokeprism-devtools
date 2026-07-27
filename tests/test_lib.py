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

from pokeprism_devtools.hacks.prism import (
    eventheader, maps, mapsource, party, render, savefile, species)
from pokeprism_devtools.hacks.prism.mapformat import PRISM_FORMAT
from pokeprism_devtools.shared import constants, lz, paths, symfile
from pokeprism_devtools.shared.overworld import blockdata, people, spritevram


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
    caper = blockdata.load(rom, syms, group=2, map_id=5, name="CAPER_HOUSE",
                           format=PRISM_FORMAT)
    check(
        "CAPER_HOUSE is 4x4 blocks with 16 bytes of grid",
        caper.width == 4 and caper.height == 4 and len(caper.blocks) == 16,
        f"{caper.width}x{caper.height}, len={len(caper.blocks)}",
    )
    aqua = blockdata.load(rom, syms, group=31, map_id=2, name="ACQUA_TUTORIAL",
                          format=PRISM_FORMAT)
    check(
        "ACQUA_TUTORIAL is 25x30 blocks with 750 bytes of grid",
        aqua.width == 25 and aqua.height == 30 and len(aqua.blocks) == 750,
        f"{aqua.width}x{aqua.height}, len={len(aqua.blocks)}",
    )

    print("\nblockdata.py — connection overlay (hermetic)")
    # A 10x10 map of block $11, and a neighbour of block $22. The Connection
    # places two neighbour blocks into two known window cells; everything else
    # stays the map's own $11. This pins the overlay arithmetic (dest→window
    # offset and source→neighbour index) without needing the ROM.
    home = blockdata.BlockData(
        name="home", group=1, map_id=1, width=10, height=10,
        border_block=0, blocks=bytes([0x11]) * 100,
    )
    away = blockdata.BlockData(
        name="away", group=1, map_id=2, width=10, height=10,
        border_block=0, blocks=bytes([0x22]) * 100,
    )
    # Player at (8, 8): anchor (row 5, col 5), window covers wOverworldMap rows
    # 5..9, cols 5..10 — all inside the map, so the base is pure $11.
    conn = blockdata.Connection(
        direction="south", group=1, map_id=2,
        source_row=0, source_col=0, dest_row=7, dest_col=6, rows=1, cols=2,
    )
    ss = blockdata.compute_screen_save(home, 8, 8, neighbors=[(conn, away)])
    # dest (7,6) and (7,7) → window rows/cols (2,1) and (2,2) → indices 13, 14.
    check("overlay writes the two targeted cells from the neighbour",
          ss[13] == 0x22 and ss[14] == 0x22, ss.hex())
    check("overlay leaves the rest of the window as the map's own blocks",
          ss[12] == 0x11 and ss[15] == 0x11 and ss.count(0x22) == 2, ss.hex())
    # Out-of-window and out-of-neighbour-bounds strips are dropped, not crash.
    off_conn = blockdata.Connection(
        direction="south", group=1, map_id=2,
        source_row=9, source_col=9, dest_row=99, dest_col=99, rows=3, cols=3,
    )
    ss2 = blockdata.compute_screen_save(home, 8, 8, neighbors=[(off_conn, away)])
    check("a strip outside the window changes nothing",
          ss2 == blockdata.compute_screen_save(home, 8, 8))

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
        bd = blockdata.load(rom, syms, group=g, map_id=m, format=PRISM_FORMAT)
        # Fold in the neighbours the same way apply.py does — without them an
        # edge save (one standing near a connection) never matches, because the
        # game filled that padding from the adjacent map.
        neighbors = []
        for conn in blockdata.map_connections(
            rom, syms, g, m, map_width=bd.width, format=PRISM_FORMAT
        ):
            try:
                nb = blockdata.load(rom, syms, conn.group, conn.map_id,
                                    format=PRISM_FORMAT)
            except ValueError:
                continue
            neighbors.append((conn, nb))
        computed = blockdata.compute_screen_save(bd, x, y, neighbors=neighbors)
        actual = bytes(sf.data[off["wScreenSave"]:off["wScreenSave"] + 30])
        edges = ", ".join(c.direction for c, _ in neighbors) or "none"
        check(
            f"wScreenSave for (g={g},m={m},x={x},y={y}) matches the save's actual "
            f"bytes [connections: {edges}]",
            computed == actual,
            f"computed={computed.hex()} vs actual={actual.hex()}",
        )

    print("\nblockdata.py — object_events, against every map's source")
    # The ROM stores no length for the object-event array; you only reach it by
    # counting past the warps, coord events and signposts, in the bank the
    # engine happens to have paged in. Every one of those is a chance to land on
    # the wrong bytes and still read a plausible count — so check all 450 maps,
    # against what the .asm says, not a spot check. (Getting the bank wrong once
    # scored 11/450 here, and read a *valid-looking* count for each of them.)
    rom_mtime = rom.stat().st_mtime
    gm = {m.name: (m.group, m.map_id) for m in maps.parse_maps(
        root / "constants" / "map_dimension_constants.asm"
    )}
    agree = disagree = stale = unparseable = 0
    first_bad = ""
    for label, const in mapsource.header_pairs(root):
        asm = root / "maps" / f"{label}.asm"
        if const not in gm or not asm.exists():
            continue
        try:
            hdr = eventheader.parse_map(asm)
            declared = hdr.list_of(eventheader.ListKind.OBJECT_EVENTS).declared_count
        except Exception:                            # noqa: BLE001
            # A map whose *source* we can't read (HaywardMartElevator declares no
            # object_events count). Nothing to compare against; not a ROM bug.
            unparseable += 1
            continue
        try:
            events = blockdata.object_events(rom, syms, *gm[const], name=label,
                                             format=PRISM_FORMAT)
        except Exception as e:                       # noqa: BLE001 — report, don't crash
            disagree += 1
            first_bad = first_bad or f"{label}: {e}"
            continue
        if asm.stat().st_mtime > rom_mtime:
            # The source has been edited since this ROM was built, so the ROM is
            # allowed to disagree with it. Nothing to check — but say so, rather
            # than counting it as a pass.
            stale += 1
        elif len(events) == declared and all(
            len(e) == blockdata.PERSON_EVENT_SIZE for e in events
        ):
            agree += 1
        else:
            disagree += 1
            first_bad = first_bad or f"{label}: rom={len(events)} source={declared}"
    check(
        f"every built map's ROM object-event count matches its source ({agree} maps)",
        disagree == 0 and agree > 400,
        first_bad or f"{stale} edited since the build, {unparseable} unparseable, skipped",
    )

    print("\npeople.py — load_map_npcs")
    # A map with NPCs in it, synthesized into a blank wMapObjects the way
    # ReadObjectEvents would have.
    events = blockdata.object_events(rom, syms, group=2, map_id=5, name="CAPER_HOUSE",
                                     format=PRISM_FORMAT)
    slots = 16
    size = slots * people.MAP_OBJECT_LEN
    sav = type("S", (), {"data": bytearray(size)})()
    changes = people.load_map_npcs(
        sav, map_objects_offset=0, map_objects_size=size, events=events
    )
    check("CAPER_HOUSE has NPCs to load", len(events) > 0, changes["map_npcs"])

    ok = True
    for i, e in enumerate(events):
        at = (i + 1) * people.MAP_OBJECT_LEN
        # $ff, then the person_event verbatim — a memcpy, like the engine's.
        ok &= sav.data[at] == people.OBJECT_STRUCT_ID_NONE
        ok &= bytes(sav.data[at + 1:at + 1 + people.PERSON_EVENT_LEN]) == e
    check(
        f"each of the {len(events)} slots is $ff + the map's person_event bytes",
        ok,
    )
    # The player's slot is not ours to touch — reset_player_and_clear_npcs owns it.
    check("slot 0 (the player) untouched", bytes(sav.data[:people.MAP_OBJECT_LEN]) == bytes(16))
    empty = (len(events) + 1) * people.MAP_OBJECT_LEN
    check(
        "the first unused slot is sprite 0, y = -1 (not zeroed — 0 is a real coord)",
        sav.data[empty + people.MAPOBJ_SPRITE] == 0
        and sav.data[empty + people.MAPOBJ_Y_COORD] == 0xFF,
        f"sprite={sav.data[empty + 1]} y={sav.data[empty + 2]}",
    )

    # More NPCs than slots: drop the tail rather than write past wMapObjects.
    small = 4 * people.MAP_OBJECT_LEN
    sav2 = type("S", (), {"data": bytearray(small)})()
    many = [bytes([i] * people.PERSON_EVENT_LEN) for i in range(9)]
    ch2 = people.load_map_npcs(
        sav2, map_objects_offset=0, map_objects_size=small, events=many
    )
    check(
        "more object events than slots drops the tail, and says so",
        len(sav2.data) == small and "map_npcs_dropped" in ch2,
        ch2.get("map_npcs_dropped", "(no warning!)"),
    )

    print("\npeople.py — instantiate_visible_sprites (hermetic)")
    # InitRadius bumps each nibble; $00 -> $11, and a low nibble that wraps to 0
    # takes the carry into the high nibble instead of a second +$10.
    check("radius $00 -> $11", people._incremented_radius(0x00) == 0x11)
    check("radius $0f -> $10", people._incremented_radius(0x0F) == 0x10)
    check("radius $23 -> $34", people._incremented_radius(0x23) == 0x34)

    # Two rocks like MtEmberWest's: one on screen at map (21,79), one behind the
    # player at (9,79). Player raw coords (15,79). Only the visible one is bound.
    mo_size = 16 * people.MAP_OBJECT_LEN
    os_size = people.NUM_OBJECT_STRUCTS * people.OBJECT_STRUCT_LEN
    buf = bytearray(mo_size + os_size)
    sav = type("S", (), {"data": buf})()
    os_off = mo_size  # object structs laid out right after the map objects

    def put_mapobj(slot, *, sprite, y, x, movement, radius, color, param):
        at = slot * people.MAP_OBJECT_LEN
        buf[at + people.MAPOBJ_OBJECT_STRUCT_ID] = people.OBJECT_STRUCT_ID_NONE
        buf[at + people.MAPOBJ_SPRITE] = sprite
        buf[at + people.MAPOBJ_Y_COORD] = y
        buf[at + people.MAPOBJ_X_COORD] = x
        buf[at + people.MAPOBJ_MOVEMENT] = movement
        buf[at + people.MAPOBJ_RADIUS] = radius
        buf[at + people.MAPOBJ_COLOR] = color
        buf[at + people.MAPOBJ_PARAMETER] = param

    put_mapobj(13, sprite=89, y=79, x=9, movement=24, radius=0, color=0x37, param=0)
    put_mapobj(14, sprite=89, y=79, x=21, movement=24, radius=0, color=0x37, param=0)
    move_rows = [(0, 0, 0, 0, 0)] * 40
    move_rows[24] = (0, 1, 0x2E, 0x10, 0x00)  # facing DOWN, action STAND, flags, pal 0
    ch = people.instantiate_visible_sprites(
        sav,
        object_structs_offset=os_off,
        map_objects_offset=0,
        map_objects_size=mo_size,
        x=15, y=79,
        sprite_tiles={89: 200},
        sprite_palettes={89: 7},
        movement_data=move_rows,
        default_tile=0,
    )
    p = os_off + people.OBJECT_STRUCT_LEN  # struct slot 1
    check("only the on-screen NPC is instantiated", "instantiated 1" in ch["visible_sprites"],
          ch["visible_sprites"])
    check("off-screen NPC (behind player) left unbound",
          buf[13 * people.MAP_OBJECT_LEN + people.MAPOBJ_OBJECT_STRUCT_ID]
          == people.OBJECT_STRUCT_ID_NONE)
    check("on-screen NPC bound to struct 1",
          buf[14 * people.MAP_OBJECT_LEN + people.MAPOBJ_OBJECT_STRUCT_ID] == 1)
    check("struct: sprite=89, tile=200, map-object index=14",
          buf[p + people.OBJ_SPRITE] == 89 and buf[p + people.OBJ_SPRITE_TILE] == 200
          and buf[p + people.OBJ_MAP_OBJECT_INDEX] == 14)
    check("struct: movement type + flags copied from the movement row",
          buf[p + people.OBJ_MOVEMENTTYPE] == 24 and buf[p + people.OBJ_FLAGS1] == 0x2E
          and buf[p + people.OBJ_FLAGS2] == 0x10)
    check("struct: palette is the colour-nibble override, ORed with the move palette",
          buf[p + people.OBJ_PALETTE] == 3, f"got {buf[p + people.OBJ_PALETTE]}")
    check("struct: radius $00 -> $11", buf[p + people.OBJ_RADIUS] == 0x11)
    check("struct: sprite_x = (Δx & $f) << 4 = (21-15) << 4 = 96",
          buf[p + people.OBJ_SPRITE_X] == 96 and buf[p + people.OBJ_SPRITE_Y] == 0)
    check("struct: init/map/next coords all seeded from the map object",
          buf[p + people.OBJ_INIT_X] == 21 and buf[p + people.OBJ_MAP_X] == 21
          and buf[p + people.OBJ_NEXT_MAP_Y] == 79)

    print("\nspritevram.py — VRAM allocator vs a real game-written save")
    truth = root / "pokeprism_ember_west_79_15.sav"
    try:
        drom = paths.rom_path(root, debug=True, fallback=False)
        dsym = paths.sym_path(root, debug=True, fallback=False)
    except FileNotFoundError:
        drom = None
    if truth.exists() and drom is not None and drom.exists():
        dsyms = symfile.SymFile.load(dsym)
        # MtEmberWest is group 95; the player is SPRITE_P0 (id 1). The engine
        # rebuilds this same list on Continue, so the tile must match the save.
        pool = spritevram.outdoor_sprite_ids(drom, dsyms, 95, name="MT_EMBER_WEST",
                                             count=PRISM_FORMAT.outdoor_sprites)
        tiles = spritevram.sprite_tiles(drom, dsyms, 1, pool,
                                        headers_symbol=PRISM_FORMAT.sprite_headers)
        check("SPRITE_ROCK (89) allocates to VRAM tile 200 (matches the save)",
              tiles.get(89) == 200, f"got {tiles.get(89)}")

        # Full path: patch a template save to MtEmberWest (15,79) and confirm the
        # instantiated struct matches the game's, on every field the game does not
        # re-derive per frame (step type / walking direction / anim counters do).
        from pokeprism_devtools.dev_server import apply as devapply, inventory as devinv
        template = root / "pokeprism.sav"
        if template.exists():
            inv = devinv.build(root, dsym)
            mdef = next(m for m in inv["maps"] if m["group"] == 95 and m["map_id"] == 2)
            patched = savefile.SaveFile.load(template)
            devapply.apply_state(
                patched, {"map": {"name": mdef["name"], "x": 15, "y": 79}},
                inv, rom_path=drom, syms=dsyms,
            )
            truth_sf = savefile.SaveFile.load(truth)
            o = inv["sram_offsets"]["wObjectStructs"]["sav_offset"] + people.OBJECT_STRUCT_LEN
            stable = [0, 1, 2, 3, 4, 5, 6, 8, 16, 17, 18, 19, 20, 21, 22, 23, 24, 32]
            same = all(patched.data[o + f] == truth_sf.data[o + f] for f in stable)
            check("patched struct 1 matches the real save on every settled field",
                  same,
                  "diverged: " + ", ".join(
                      f"@{f}={patched.data[o+f]}!={truth_sf.data[o+f]}"
                      for f in stable if patched.data[o+f] != truth_sf.data[o+f]
                  ) if not same else "all 18 fields equal")
        else:
            print("  (no pokeprism.sav template — skipping the full-path cross-check)")
    else:
        print("  (no debug build + MtEmberWest truth save — skipping)")

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

    print("\nspecies.py — parsers")
    base_stats = species.parse_base_stats(root)
    check("base_stats has BULBASAUR", "BULBASAUR" in base_stats)
    bs = base_stats["BULBASAUR"]
    check(
        "BULBASAUR base stats canonical",
        (bs.hp, bs.atk, bs.def_, bs.spd, bs.sat, bs.sdf) == (45, 49, 49, 45, 65, 65)
        and bs.growth_rate == "MEDIUM_SLOW",
        f"{bs}",
    )
    move_pp = species.parse_move_pp(root)
    check("TACKLE has PP=35", move_pp.get("TACKLE") == 35)
    pokemon_order = [
        c.name for c in constants.parse_constants(
            root / "constants" / "pokemon_constants.asm",
            start_counter=1, stop_at_reset=True,
        ) if c.name != "skip"
    ]
    learnsets = species.parse_movesets(root, pokemon_order)
    check("BULBASAUR has a learnset", "BULBASAUR" in learnsets and learnsets["BULBASAUR"].level_moves)

    print("\nspecies.py — formulas")
    check("MEDIUM_SLOW @ L5 = 135",  species.exp_at_level("MEDIUM_SLOW", 5) == 135)
    check("MEDIUM_FAST @ L5 = 125",  species.exp_at_level("MEDIUM_FAST", 5) == 125)
    check("FAST @ L100 = 800000",    species.exp_at_level("FAST", 100) == 800_000)
    check("calc_stat hp Bulba L5 = 20",  species.calc_stat(45, 15, 0, 5, is_hp=True) == 20)
    check("calc_stat atk Bulba L5 = 10", species.calc_stat(49, 15, 0, 5, is_hp=False) == 10)

    print("\nparty.py — build_party")
    built = party.build_party(
        [
            party.PartyMonInput(species="CHARMANDER", level=5),
            party.PartyMonInput(species="PIKACHU", level=10, nickname="SPARKY"),
        ],
        species_ids={"CHARMANDER": 4, "PIKACHU": 25},
        move_ids={"SCRATCH": 10, "GROWL": 45, "THUNDERSHOCK": 84, "TAIL_WHIP": 39},
        item_ids={"NO_ITEM": 0},
        base_stats_db={
            "CHARMANDER": species.BaseStats("CHARMANDER", 39, 52, 43, 65, 60, 50, "MEDIUM_SLOW"),
            "PIKACHU": species.BaseStats("PIKACHU", 35, 55, 40, 90, 50, 50, "MEDIUM_FAST"),
        },
        learnset_db={
            "CHARMANDER": species.Learnset("CHARMANDER", [(1, "SCRATCH"), (4, "GROWL")]),
            "PIKACHU": species.Learnset("PIKACHU", [(1, "THUNDERSHOCK"), (6, "TAIL_WHIP")]),
        },
        move_pp_db={"SCRATCH": 35, "GROWL": 40, "THUNDERSHOCK": 30, "TAIL_WHIP": 30},
        ot_name="DEV",
        ot_id=12345,
    )
    check("party count = 2", built.count == 2)
    check("species terminator at index 2",
          built.species_bytes[0] == 4 and built.species_bytes[1] == 25
          and built.species_bytes[2] == 0xFF)
    check("CHARMANDER struct is 48B", len(built.mons_bytes) == 288)
    char = built.mons_bytes[:48]
    check("CHARMANDER species byte = 4", char[0] == 4)
    check("CHARMANDER level = 5", char[31] == 5)
    check("CHARMANDER exp BE = 135",
          int.from_bytes(char[8:11], "big") == 135)
    check("CHARMANDER HP big-endian = 19",
          int.from_bytes(char[34:36], "big") == 19)

    print("\ndev_server — inventory bag fields")
    from pokeprism_devtools.dev_server import apply as dev_apply
    from pokeprism_devtools.dev_server import inventory as dev_inventory

    inv = dev_inventory.build(root, sym)
    check(
        "bag_caps parsed from misc_constants.asm",
        inv.get("bag_caps") == {"items": 40, "balls": 25, "key_items": 50},
        str(inv.get("bag_caps")),
    )
    so = inv["sram_offsets"]
    check("wItems region is 81 bytes", so["wItems"]["size"] == 81)
    check("wBalls region is 51 bytes", so["wBalls"]["size"] == 51)
    check("wKeyItems region is 51 bytes", so["wKeyItems"]["size"] == 51)
    for num_sym, list_sym in (
        ("wNumItems", "wItems"),
        ("wNumBalls", "wBalls"),
        ("wNumKeyItems", "wKeyItems"),
    ):
        check(
            f"{list_sym} directly follows {num_sym}",
            so[list_sym]["sav_offset"] == so[num_sym]["sav_offset"] + 1,
        )

    pocket_of = {i["name"]: i.get("pocket") for i in inv["items"]}
    check("POTION → ITEM pocket", pocket_of.get("POTION") == "ITEM")
    check("POKE_BALL → BALL pocket", pocket_of.get("POKE_BALL") == "BALL")
    check("BICYCLE → KEY_ITEM pocket", pocket_of.get("BICYCLE") == "KEY_ITEM")
    check("SPECIAL_ITEM has no pocket", pocket_of.get("SPECIAL_ITEM") is None)
    bad_pockets = {
        p for p in pocket_of.values() if p not in (None, "ITEM", "KEY_ITEM", "BALL", "TM_HM")
    }
    check("all pockets are known values", not bad_pockets, str(bad_pockets))

    print("\ndev_server — apply items to .sav")
    rom_file = paths.rom_path(root)
    template_sav = rom_file.with_suffix(".sav")
    if not template_sav.exists():
        print(f"  (no template .sav at {template_sav.name} — skipping items apply check)")
    else:
        item_id = {i["name"]: i["id"] for i in inv["items"]}

        def apply_items(items_state: dict) -> savefile.SaveFile:
            sf = savefile.SaveFile.load(template_sav)
            dev_apply.apply_state(
                sf, {"items": items_state}, inv, rom_path=rom_file, syms=syms
            )
            return sf

        sf = apply_items({
            "items": [{"name": "POTION", "qty": 5}, "ESCAPE_ROPE"],
            "balls": [{"name": "POKE_BALL", "qty": 10}],
            "key_items": ["BICYCLE"],
        })
        check("wNumItems == 2", sf.data[so["wNumItems"]["sav_offset"]] == 2)
        expect = bytes([item_id["POTION"], 5, item_id["ESCAPE_ROPE"], 1, 0xFF])
        got = sf.read(so["wItems"]["sav_offset"], 81)
        check(
            "wItems = pairs + 0xFF + zero fill",
            got == expect + bytes(81 - len(expect)),
            got[:8].hex(),
        )
        check("wNumBalls == 1", sf.data[so["wNumBalls"]["sav_offset"]] == 1)
        check(
            "wBalls = [POKE_BALL x10] + 0xFF",
            sf.read(so["wBalls"]["sav_offset"], 4)
            == bytes([item_id["POKE_BALL"], 10, 0xFF, 0]),
        )
        check("wNumKeyItems == 1", sf.data[so["wNumKeyItems"]["sav_offset"]] == 1)
        check(
            "wKeyItems = [BICYCLE] + 0xFF",
            sf.read(so["wKeyItems"]["sav_offset"], 3)
            == bytes([item_id["BICYCLE"], 0xFF, 0]),
        )

        sf = apply_items({"items": []})
        check("empty pocket → count 0", sf.data[so["wNumItems"]["sav_offset"]] == 0)
        check(
            "empty pocket → 0xFF + zero fill",
            sf.read(so["wItems"]["sav_offset"], 81) == b"\xff" + bytes(80),
        )
        # An untouched pocket keeps the template's bytes.
        template = savefile.SaveFile.load(template_sav)
        check(
            "absent sub-key leaves the balls pocket untouched",
            sf.read(so["wNumBalls"]["sav_offset"], 52)
            == template.read(so["wNumBalls"]["sav_offset"], 52),
        )

        def rejects(label: str, items_state: dict) -> None:
            try:
                apply_items(items_state)
            except ValueError:
                check(f"rejects {label}", True)
            else:
                check(f"rejects {label}", False)

        rejects("unknown item", {"items": ["NOT_AN_ITEM"]})
        rejects("wrong pocket", {"balls": ["POTION"]})
        rejects("qty 0", {"items": [{"name": "POTION", "qty": 0}]})
        rejects("qty 100", {"items": [{"name": "POTION", "qty": 100}]})
        rejects("duplicate item", {"items": ["POTION", {"name": "POTION", "qty": 2}]})
        rejects("qty on a key item", {"key_items": [{"name": "BICYCLE", "qty": 2}]})
        rejects("unknown sub-key", {"tms": ["TM_ROCK_SMASH"]})
        all_items = [i["name"] for i in inv["items"] if i.get("pocket") == "ITEM"]
        rejects("pocket overflow (41 items)", {"items": all_items[:41]})

    print("\ndev_server — inventory tmhms")
    tmhms = inv["tmhms"]
    check("tmhms is non-empty", len(tmhms) > 0, str(len(tmhms)))
    check(
        "first entry is TM_DYNAMICPUNCH kind=TM num=1 bit=0",
        tmhms[0]["name"] == "TM_DYNAMICPUNCH"
        and tmhms[0]["kind"] == "TM"
        and tmhms[0]["num"] == 1
        and tmhms[0]["bit"] == 0,
        str(tmhms[0]),
    )
    check(
        "last entry is HM_ROCK_SMASH with bit == len - 1",
        tmhms[-1]["name"] == "HM_ROCK_SMASH" and tmhms[-1]["bit"] == len(tmhms) - 1,
        str(tmhms[-1]),
    )
    hm_entries = [e for e in tmhms if e["kind"] == "HM"]
    check("exactly 5 HM entries", len(hm_entries) == 5, str(len(hm_entries)))
    check(
        "HM entries are contiguous at the end",
        [e["bit"] for e in hm_entries] == list(range(len(tmhms) - 5, len(tmhms))),
        str([e["bit"] for e in hm_entries]),
    )
    check(
        "wTMsHMs region size matches (len(tmhms)+7)//8",
        so["wTMsHMs"]["size"] == (len(tmhms) + 7) // 8,
        str(so["wTMsHMs"]),
    )
    check(
        "wNumItems directly follows wTMsHMs",
        so["wNumItems"]["sav_offset"]
        == so["wTMsHMs"]["sav_offset"] + so["wTMsHMs"]["size"],
    )

    print("\ndev_server — apply tmhms to .sav")
    if not template_sav.exists():
        print(f"  (no template .sav at {template_sav.name} — skipping tmhms apply check)")
    else:
        tmhm_size = so["wTMsHMs"]["size"]
        bit_of = {e["name"]: e["bit"] for e in tmhms}

        def apply_tmhms(names: list) -> savefile.SaveFile:
            sf = savefile.SaveFile.load(template_sav)
            dev_apply.apply_state(
                sf, {"tmhms": names}, inv, rom_path=rom_file, syms=syms
            )
            return sf

        sf = apply_tmhms(["TM_DYNAMICPUNCH", "HM_CUT"])
        expect = bytearray(tmhm_size)
        expect[bit_of["TM_DYNAMICPUNCH"] >> 3] |= 1 << (bit_of["TM_DYNAMICPUNCH"] & 7)
        expect[bit_of["HM_CUT"] >> 3] |= 1 << (bit_of["HM_CUT"] & 7)
        got = sf.read(so["wTMsHMs"]["sav_offset"], tmhm_size)
        check(
            "TM_DYNAMICPUNCH + HM_CUT set the expected bits",
            got == bytes(expect),
            got.hex(),
        )

        sf = apply_tmhms(["TM_TOXIC"])
        got = sf.read(so["wTMsHMs"]["sav_offset"], tmhm_size)
        expect_byte0 = 1 << (bit_of["TM_TOXIC"] & 7)
        check(
            "TM_TOXIC sets the expected bit in its byte",
            got[bit_of["TM_TOXIC"] >> 3] == expect_byte0,
            got.hex(),
        )

        sf = apply_tmhms([])
        check(
            "empty tmhms list -> all-zero region",
            sf.read(so["wTMsHMs"]["sav_offset"], tmhm_size) == bytes(tmhm_size),
        )

        # Absent key leaves the template's bytes untouched.
        sf2 = savefile.SaveFile.load(template_sav)
        dev_apply.apply_state(sf2, {}, inv, rom_path=rom_file, syms=syms)
        template = savefile.SaveFile.load(template_sav)
        check(
            "absent tmhms key leaves wTMsHMs untouched",
            sf2.read(so["wTMsHMs"]["sav_offset"], tmhm_size)
            == template.read(so["wTMsHMs"]["sav_offset"], tmhm_size),
        )

        all_names = [e["name"] for e in tmhms]
        sf = apply_tmhms(all_names)
        got = sf.read(so["wTMsHMs"]["sav_offset"], tmhm_size)
        popcount = sum(bin(b).count("1") for b in got)
        check("owning all TM/HMs sets popcount == len(tmhms)", popcount == len(tmhms), str(popcount))
        last_byte_bits = len(tmhms) % 8 or 8
        check(
            "last byte matches the tail bit count when all owned",
            got[-1] == (1 << last_byte_bits) - 1,
            f"{got[-1]:#04x}",
        )

        def rejects_tmhms(label: str, names: list) -> None:
            try:
                apply_tmhms(names)
            except ValueError:
                check(f"rejects {label}", True)
            else:
                check(f"rejects {label}", False)

        rejects_tmhms("unknown TM/HM name", ["TM_NOT_A_MOVE"])
        rejects_tmhms("bare move name", ["CUT"])
        rejects_tmhms("duplicate entry", ["TM_TOXIC", "TM_TOXIC"])
        rejects_tmhms("non-string entry", [{"name": "HM_CUT"}])

    print("\nmapfile.py")
    from pokeprism_devtools.shared import mapfile as mapfile_mod
    mp = mapfile_mod.MapFile.parse(paths.map_path(root))
    rom = mp.rom_banks()
    check("at least 118 ROM banks", len(rom) >= 118, f"{len(rom)}")
    failing = [
        b for b in rom
        if b.capacity != b.used + b.free or b.used != sum(s.size for s in b.sections)
    ]
    check("all ROM bank capacity invariants hold", not failing,
          f"{len(failing)} fail" if failing else "")
    b0 = mp.banks[("ROM0", 0)]
    check("ROM0 bank #0 free == $0339", b0.free == 0x0339, f"got ${b0.free:04x}")
    b1 = mp.banks[("ROMX", 1)]
    check("ROMX bank #1 free == $00fd", b1.free == 0x00fd, f"got ${b1.free:04x}")
    sram_banks = mp.banks_by_region("SRAM")
    check("SRAM has at least 1 bank", len(sram_banks) >= 1, f"{len(sram_banks)}")

    # The .map only lists banks the linker touched; the physical cartridge has
    # trailing $ff padding banks rgbfix adds to reach a valid ROM size.
    total = paths.rom_bank_count(paths.rom_path(root))
    check("rom_bank_count reads a power-of-two bank count",
          total in (2, 4, 8, 16, 32, 64, 128, 256, 512), f"{total} banks")
    used_before = len(mp.rom_banks())
    mp.fill_rom_banks(total)
    rom = mp.rom_banks()
    check("fill_rom_banks pads ROM to the cartridge size", len(rom) == total,
          f"{used_before} → {len(rom)} of {total}")
    check("highest bank is the last cartridge bank",
          rom[-1].number == total - 1, f"${rom[-1].number:02x}")
    padded = [b for b in rom if b.used == 0 and b.free == b.capacity]
    check("padding banks are 100% free", padded and all(not b.sections for b in padded),
          f"{len(padded)} empty banks")
    check("fill_rom_banks is idempotent",
          (mp.fill_rom_banks(total), len(mp.rom_banks()))[1] == total)

    print("\nrender.py")
    for table in render.PALETTE_TABLES:
        for tod in range(4):
            pals = render.palettes_for_table(root, table, tod)
            ok = (
                len(pals) == 8
                and all(len(p) == 4 and all(len(c) == 3 for c in p) for p in pals)
            )
            check(f"palettes_for_table({table}, {tod}) → 8×4 RGB", ok,
                  f"{len(pals)} palettes")

    # `rom` was reassigned to a list of banks in the mapfile section above.
    rom_file = paths.rom_path(root)
    rmap = next((m for m in map_defs if m.name == "AZALEA_TOWN"), map_defs[0])
    bd = blockdata.load(rom_file, syms, rmap.group, rmap.map_id, name=rmap.name,
                        format=PRISM_FORMAT)
    base_img = render.render_map(root, rom_file, syms, rmap.group, rmap.map_id, name=rmap.name)
    check(f"render_map({rmap.name}) → {bd.width}×{bd.height} blocks",
          base_img.size == (bd.width * 32, bd.height * 32), f"{base_img.size}")

    # outdoor and indoor tables differ in all 8 slots, so any non-empty map
    # renders differently — a robust check of the override mechanism.
    img_out = render.render_map(root, rom_file, syms, rmap.group, rmap.map_id,
                                name=rmap.name, palette_table="outdoor")
    img_in = render.render_map(root, rom_file, syms, rmap.group, rmap.map_id,
                               name=rmap.name, palette_table="indoor")
    check("palette override keeps dimensions", img_out.size == base_img.size,
          f"{img_out.size}")
    check("different palette tables change pixels",
          img_out.tobytes() != img_in.tobytes())

    sheet = render.render_tileset_sheet(
        root, bd.tileset_id, render.palettes_for_table(root, "outdoor", 1))
    check(f"render_tileset_sheet(tileset {bd.tileset_id}) → 512×512",
          sheet.size == (512, 512), f"{sheet.size}")

    print("\nall checks passed")


if __name__ == "__main__":
    main()
