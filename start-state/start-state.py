#!/usr/bin/env python3
"""start-state — launch pokeprism in a custom initial state.

Phase A (this commit): builds an `inventory.json` next to this script
containing every map, pokemon, item, move, and event flag, plus the SRAM
file offsets needed to write a custom .sav. Subsequent runs reuse the
cached inventory unless the .sym is newer.

Phase B (next): patch a .sav from a state.json and launch SameBoy.

Usage:
    start-state.py                       # build inventory if stale, print summary
    start-state.py --rebuild-inventory   # force rebuild
    start-state.py --debug               # use the debug ROM's .sym
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _lib import constants, maps, paths, savefile, symfile  # noqa: E402

INVENTORY_PATH = Path(__file__).parent / "inventory.json"
STATE_PATH = Path(__file__).parent / "state.json"
PRESETS_DIR = Path(__file__).parent / "presets"
SAV_BACKUPS_DIR = Path(__file__).parent / "sav-backups"
SAMEBOY_PATH = "/Applications/SameBoy.app/Contents/MacOS/sameboy"


# WRAM symbols whose values the start-state tool will write. Resolved to .sav
# file offsets in the inventory. Group them by save block so we can validate
# each ends up in the expected region.
WRITABLE_FIELDS: dict[str, dict[str, object]] = {
    # Player block
    "wPlayerName":    {"size": 8,  "block": "PlayerData"},
    "wMoney":         {"size": 3,  "block": "PlayerData"},
    "wNumItems":      {"size": 1,  "block": "PlayerData"},
    "wItems":         {"size": 40, "block": "PlayerData"},
    "wEventFlags":    {"size": 250, "block": "PlayerData"},
    # Map block
    "wMapGroup":      {"size": 1,  "block": "MapData"},
    "wMapNumber":     {"size": 1,  "block": "MapData"},
    "wYCoord":        {"size": 1,  "block": "MapData"},
    "wXCoord":        {"size": 1,  "block": "MapData"},
    # Pokemon block
    "wPartyCount":    {"size": 1,  "block": "PokemonData"},
    "wPartySpecies":  {"size": 7,  "block": "PokemonData"},  # 6 species + 0xFF terminator
    "wPartyMons":     {"size": 288, "block": "PokemonData"}, # 6 * 48
    "wBadges":        {"size": 3,  "block": "PokemonData"},
}

# Save-file framing fields (not in a block — fixed positions in SRAM bank 1).
# `size` is the size of the field itself; for sExtraData it's the size of the
# region the extra checksum covers (computed at inventory-build time from the
# delta between sExtraData and sExtraChecksum).
FRAMING_FIELDS = [
    ("sValidCheck1", 1),
    ("sValidCheck2", 1),
    ("sChecksum", 2),
    ("sExtraData", None),     # size resolved from sExtraChecksum - sExtraData
    ("sExtraChecksum", 2),
]

# Blocks: WRAM source and SRAM mirror. Pulled from sram.asm conventions; the
# WRAM and SRAM block sizes match exactly so we can map symbols 1:1.
SAVE_BLOCKS = [
    ("PlayerData",  "wPlayerData",  "wPlayerDataEnd",  "sPlayerData"),
    ("MapData",     "wMapData",     "wMapDataEnd",     "sMapData"),
    ("PokemonData", "wPokemonData", "wPokemonDataEnd", "sPokemonData"),
]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="start-state")
    p.add_argument(
        "--rebuild-inventory",
        action="store_true",
        help="force rebuild of inventory.json",
    )
    p.add_argument(
        "--debug",
        action="store_true",
        help="use the debug ROM (and its .sym) instead of release",
    )
    p.add_argument(
        "--state",
        type=Path,
        default=STATE_PATH,
        help="state.json describing the desired initial state "
        "(default: tools/start-state/state.json; if missing, uses "
        "presets/default.json)",
    )
    p.add_argument(
        "--template",
        type=Path,
        default=None,
        help="path to a .sav to use as template instead of the ROM's adjacent "
        ".sav (which is also the launch target)",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="write the patched save here instead of overwriting the ROM's "
        ".sav (also implies --no-launch)",
    )
    p.add_argument(
        "--no-launch",
        action="store_true",
        help="patch the save but don't spawn SameBoy",
    )
    p.add_argument(
        "--inventory-only",
        action="store_true",
        help="rebuild the inventory if needed, print a summary, and exit",
    )
    args = p.parse_args(argv)

    root = paths.repo_root()
    sym_path_resolved = paths.sym_path(root, debug=args.debug)

    if args.rebuild_inventory or _needs_rebuild(INVENTORY_PATH, sym_path_resolved):
        print(f"Building inventory from {sym_path_resolved.name}...")
        inv_data = _build_inventory(root, sym_path_resolved)
        INVENTORY_PATH.write_text(json.dumps(inv_data, indent=2))
        print(f"Wrote {INVENTORY_PATH}")
    else:
        print(f"Using cached {INVENTORY_PATH.name} (run --rebuild-inventory to refresh)")

    inv = json.loads(INVENTORY_PATH.read_text())

    if args.inventory_only:
        _print_summary(inv)
        return 0

    # Load state.json (or the default preset).
    state = _load_state(args.state)
    print(f"State loaded from {args.state if args.state.exists() else 'presets/default.json'}")

    # Resolve template and target paths.
    rom_path = paths.rom_path(root, debug=args.debug)
    target_sav = args.out if args.out is not None else rom_path.with_suffix(".sav")
    template_sav = args.template if args.template is not None else target_sav

    if not template_sav.exists():
        print(
            f"\nerror: no template save at {template_sav}.\n"
            "Run the ROM in an emulator once, complete the intro, and save "
            "the game in-game to create a starting .sav. Then re-run "
            "start-state.",
            file=sys.stderr,
        )
        return 2

    sav = savefile.SaveFile.load(template_sav)
    if not _looks_like_real_save(sav, inv):
        print(
            f"\nerror: template at {template_sav} doesn't look like a valid "
            "save (validity bytes missing). Play the game once to create "
            "a proper save.",
            file=sys.stderr,
        )
        return 2

    # Back up the existing target so we never silently destroy progress.
    if target_sav.exists():
        SAV_BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
        ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = SAV_BACKUPS_DIR / f"{target_sav.stem}-{ts}.sav"
        backup.write_bytes(target_sav.read_bytes())
        print(f"Backed up {target_sav.name} → {_pretty_path(backup, root)}")

    # Apply state and recompute checksums.
    changes = _apply_state(sav, state, inv)
    _recompute_checksums(sav, inv)

    sav.write(target_sav)
    print(f"Wrote {_pretty_path(target_sav, root)} ({len(changes)} fields changed)")
    for c in changes:
        print(f"  {c}")

    if args.out is not None or args.no_launch:
        print("\nDone. Launch the ROM manually to verify.")
        return 0

    return _launch(rom_path)


def _needs_rebuild(inventory: Path, sym: Path) -> bool:
    if not inventory.exists():
        return True
    return inventory.stat().st_mtime < sym.stat().st_mtime


def _build_inventory(root: Path, sym_path_resolved: Path) -> dict:
    syms = symfile.SymFile.load(sym_path_resolved)
    map_defs = maps.parse_maps(root / "constants" / "map_dimension_constants.asm")

    # Parse each focused enum file individually. They all inherit a counter
    # of 1 from their parent (constants.asm does `const_def; const NO_X;
    # INCLUDE child`). We stop at the first reset to avoid picking up
    # unrelated constants that share the file (TM IDs, BATTLEANIM_*, etc.).
    def _enum(rel: str) -> list[dict]:
        cs = constants.parse_constants(
            root / rel, start_counter=1, stop_at_reset=True
        )
        return [{"name": c.name, "id": c.value} for c in cs if c.name != "skip"]

    pokemon = _enum("constants/pokemon_constants.asm")
    items = _enum("constants/item_constants.asm")
    # move_constants.asm reuses the same counter for `ANIM_*` (battle
    # animations after the last real move). They aren't moves you can put
    # on a Pokémon — drop them.
    moves = [
        m for m in _enum("constants/move_constants.asm")
        if not m["name"].startswith("ANIM_")
    ]
    flags = _enum("constants/event_flags.asm")

    # Resolve save block layout from symbols.
    blocks = _resolve_blocks(syms)

    # Resolve writable WRAM symbols to .sav file offsets.
    sram_offsets: dict[str, dict] = {}
    for label, meta in WRITABLE_FIELDS.items():
        sym = syms.get(label)
        if sym is None:
            sram_offsets[label] = {
                "error": f"symbol not in .sym; skipping",
                "size": meta["size"],
                "block": meta["block"],
            }
            continue
        block = blocks[meta["block"]]
        offset_in_block = sym.addr - block["wram_start_addr"]
        if not (0 <= offset_in_block < block["size"]):
            sram_offsets[label] = {
                "error": (
                    f"{label}@${sym.addr:04x} not inside "
                    f"{meta['block']} block "
                    f"(${block['wram_start_addr']:04x}–${block['wram_end_addr']:04x})"
                ),
                "size": meta["size"],
                "block": meta["block"],
            }
            continue
        sram_addr = block["sram_start_addr"] + offset_in_block
        file_offset = savefile.sram_to_file_offset(1, sram_addr)
        sram_offsets[label] = {
            "sav_offset": file_offset,
            "size": meta["size"],
            "block": meta["block"],
            "wram_addr": sym.addr,
            "sram_addr": sram_addr,
        }

    # Framing fields live in SRAM directly (not in a WRAM-mirrored block).
    framing: dict[str, dict] = {}
    for label, size in FRAMING_FIELDS:
        sym = syms[label]  # raise if missing — these are essential
        framing[label] = {
            "sav_offset": savefile.sram_to_file_offset(sym.bank, sym.addr),
            "size": size,
            "sram_addr": sym.addr,
        }
    # sExtraData covers up to (but not including) sExtraChecksum.
    framing["sExtraData"]["size"] = (
        syms["sExtraChecksum"].addr - syms["sExtraData"].addr
    )

    return {
        "built_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "sym_path": str(sym_path_resolved.relative_to(root)),
        "sym_mtime": int(sym_path_resolved.stat().st_mtime),
        "counts": {
            "pokemon": len(pokemon),
            "items": len(items),
            "moves": len(moves),
            "event_flags": len(flags),
            "maps": len(map_defs),
        },
        "blocks": blocks,
        "framing": framing,
        "sram_offsets": sram_offsets,
        "pokemon": pokemon,
        "items": items,
        "moves": moves,
        "event_flags": flags,
        "maps": [asdict(m) for m in map_defs],
    }


def _resolve_blocks(syms: symfile.SymFile) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for name, wstart, wend, sstart in SAVE_BLOCKS:
        ws = syms[wstart]
        we = syms[wend]
        ss = syms[sstart]
        size = we.addr - ws.addr
        out[name] = {
            "wram_start": wstart,
            "wram_start_addr": ws.addr,
            "wram_end_addr": we.addr,
            "sram_start": sstart,
            "sram_start_addr": ss.addr,
            "sram_bank": ss.bank,
            "sav_offset": savefile.sram_to_file_offset(ss.bank, ss.addr),
            "size": size,
        }
    return out


def _pretty_path(path: Path, root: Path) -> str:
    """Show path as relative to repo root if possible; otherwise absolute."""
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _load_state(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text())
    default = PRESETS_DIR / "default.json"
    if not default.exists():
        raise FileNotFoundError(
            f"no state at {path} and no default preset at {default}"
        )
    return json.loads(default.read_text())


def _looks_like_real_save(sav: savefile.SaveFile, inv: dict) -> bool:
    v1 = sav.data[inv["framing"]["sValidCheck1"]["sav_offset"]]
    v2 = sav.data[inv["framing"]["sValidCheck2"]["sav_offset"]]
    return v1 == 0x63 and v2 == 0x7F


def _apply_state(sav: savefile.SaveFile, state: dict, inv: dict) -> list[str]:
    """Mutate the save in place and return a list of human-readable changes.

    State schema (all keys optional):
        {
            "player": {"name": "RED", "money": 10000,
                       "badges": [naljo, rijon, other]},
            "map": {"name": "CAPER_HOUSE", "x": 2, "y": 2}
        }

    Out of scope for v1 (will arrive in follow-up commits):
        party, items, event_flags.
    """
    changes: list[str] = []
    offsets = inv["sram_offsets"]

    def off(label: str) -> int:
        e = offsets[label]
        if "error" in e:
            raise RuntimeError(f"{label}: {e['error']}")
        return e["sav_offset"]

    player = state.get("player") or {}
    map_ = state.get("map") or {}

    if "name" in player:
        encoded = savefile.encode_name(player["name"], 8)
        sav.write_bytes(off("wPlayerName"), encoded)
        changes.append(f"wPlayerName = {player['name']!r}")

    if "money" in player:
        amount = int(player["money"])
        if not (0 <= amount <= 999_999):
            raise ValueError(f"money out of range: {amount} (0–999999)")
        sav.write_bytes(off("wMoney"), amount.to_bytes(3, "big"))
        changes.append(f"wMoney = {amount}")

    if "badges" in player:
        b = player["badges"]
        if not (isinstance(b, list) and len(b) == 3):
            raise ValueError("badges must be a list of 3 bytes")
        sav.write_bytes(off("wBadges"), bytes(int(x) & 0xFF for x in b))
        changes.append(f"wBadges = {b}")

    if "name" in map_:
        mdef = next((m for m in inv["maps"] if m["name"] == map_["name"]), None)
        if mdef is None:
            raise ValueError(f"unknown map: {map_['name']}")
        sav.write_byte(off("wMapGroup"), mdef["group"])
        sav.write_byte(off("wMapNumber"), mdef["map_id"])
        changes.append(
            f"map = {map_['name']} (group {mdef['group']}, id {mdef['map_id']})"
        )

    if "x" in map_:
        sav.write_byte(off("wXCoord"), int(map_["x"]) & 0xFF)
        changes.append(f"wXCoord = {map_['x']}")
    if "y" in map_:
        sav.write_byte(off("wYCoord"), int(map_["y"]) & 0xFF)
        changes.append(f"wYCoord = {map_['y']}")

    return changes


def _recompute_checksums(sav: savefile.SaveFile, inv: dict) -> None:
    """Recompute sChecksum (over sGameData) and sExtraChecksum (over
    sExtraData) and write them back to the .sav. After this, the .sav is
    consistent and the game's `TryLoadSaveFile` should accept it on the
    primary path (no fallback to backup needed).
    """
    pb = inv["blocks"]["PlayerData"]
    pkb = inv["blocks"]["PokemonData"]
    game_data_start = pb["sav_offset"]
    game_data_end = pkb["sav_offset"] + pkb["size"]
    game_data = sav.read(game_data_start, game_data_end - game_data_start)
    sav.write_u16_le(
        inv["framing"]["sChecksum"]["sav_offset"],
        savefile.checksum16(game_data),
    )

    ed = inv["framing"]["sExtraData"]
    extra = sav.read(ed["sav_offset"], ed["size"])
    sav.write_u16_le(
        inv["framing"]["sExtraChecksum"]["sav_offset"],
        savefile.checksum16(extra),
    )


def _launch(rom_path: Path) -> int:
    """Spawn SameBoy with the ROM. SameBoy auto-loads the adjacent .sav."""
    import shutil
    import subprocess

    cmd: list[str] | None = None
    if Path(SAMEBOY_PATH).exists():
        cmd = [SAMEBOY_PATH, str(rom_path)]
    elif shutil.which("sameboy") is not None:
        cmd = ["sameboy", str(rom_path)]
    elif sys.platform == "darwin":
        # Last-ditch: ask macOS to open the ROM with the registered handler.
        cmd = ["open", "-a", "SameBoy", str(rom_path)]

    if cmd is None:
        print(
            f"\nWARNING: SameBoy not found. ROM and patched .sav are ready "
            f"at:\n  {rom_path}\nLaunch manually.",
            file=sys.stderr,
        )
        return 0

    print(f"\nLaunching {cmd[0]} ...")
    try:
        subprocess.Popen(cmd)
    except OSError as e:
        print(f"failed to launch: {e}", file=sys.stderr)
        return 1
    return 0


def _print_summary(inv: dict) -> None:
    print()
    print(f"Inventory built at {inv['built_at']}")
    print(f"Source: {inv['sym_path']}")
    print()
    print("Counts:")
    for k, v in inv["counts"].items():
        print(f"  {k:14s} {v}")
    print()
    print("Save blocks:")
    for name, b in inv["blocks"].items():
        print(
            f"  {name:11s} {b['size']:5d} bytes — "
            f"wram ${b['wram_start_addr']:04x}, "
            f"sram ${b['sram_start_addr']:04x}, "
            f".sav offset ${b['sav_offset']:04x}"
        )
    print()
    print(f"Resolved {sum(1 for v in inv['sram_offsets'].values() if 'sav_offset' in v)} "
          f"of {len(inv['sram_offsets'])} writable WRAM symbols.")
    errors = {k: v for k, v in inv["sram_offsets"].items() if "error" in v}
    if errors:
        print("Unresolved:")
        for k, v in errors.items():
            print(f"  {k}: {v['error']}")


if __name__ == "__main__":
    sys.exit(main())
