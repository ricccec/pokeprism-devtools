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
FRAMING_FIELDS = [
    ("sValidCheck1", 1),
    ("sValidCheck2", 1),
    ("sChecksum", 2),
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
        help="use the debug ROM's .sym (pokeprism.sym) instead of release",
    )
    args = p.parse_args(argv)

    root = paths.repo_root()
    sym_path_resolved = paths.sym_path(root, debug=args.debug)

    if args.rebuild_inventory or _needs_rebuild(INVENTORY_PATH, sym_path_resolved):
        print(f"Building inventory from {sym_path_resolved.name}...")
        inv = _build_inventory(root, sym_path_resolved)
        INVENTORY_PATH.write_text(json.dumps(inv, indent=2))
        print(f"Wrote {INVENTORY_PATH}")
    else:
        print(f"Using cached {INVENTORY_PATH.name} (run with --rebuild-inventory to refresh)")

    inv = json.loads(INVENTORY_PATH.read_text())
    _print_summary(inv)
    print(
        "\nPhase A complete. Phase B (patch .sav + launch SameBoy) is not "
        "implemented yet.\nSee docs/devtools-plan.md."
    )
    return 0


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
