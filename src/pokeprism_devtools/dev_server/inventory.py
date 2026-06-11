"""Inventory builder for prism-dev.

Scans the .sym and `constants/*.asm` to produce a JSON catalog of every
map, pokemon, item, move, and event flag — plus the .sav file offsets for
the WRAM fields the patcher writes. Cached as `inventory.json` next to
the prism-dev script; regenerated automatically when the .sym is newer.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict
from pathlib import Path

from pokeprism_devtools.shared import constants, maps, savefile, species, symfile


# WRAM symbols whose values the prism-dev tool will write. Resolved to
# .sav file offsets in the inventory. Group them by save block so we can
# validate each ends up in the expected region.
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
    "wScreenSave":    {"size": 30, "block": "MapData"},  # not user-writable;
                                                          # cleared on map change
    # Engine state used by the people-reset (not user-writable).
    "wObjectStructs": {"size": 40 * 13, "block": "PlayerData"},
    "wMapObjects":    {"size": 16 * 16, "block": "PlayerData"},
    # Pokemon block
    "wPartyCount":         {"size": 1,  "block": "PokemonData"},
    "wPartySpecies":       {"size": 7,  "block": "PokemonData"},  # 6 species + 0xFF terminator
    "wPartyMons":          {"size": 288, "block": "PokemonData"}, # 6 * 48
    "wPartyMonOT":         {"size": 11 * 6, "block": "PokemonData"},
    "wPartyMonNicknames":  {"size": 11 * 6, "block": "PokemonData"},
    "wBadges":             {"size": 3,  "block": "PokemonData"},
    # Player trainer id — used as OT id when synthesizing party mons.
    "wPlayerID":           {"size": 2,  "block": "PlayerData"},
}

# Save-file framing fields (not in a block — fixed positions in SRAM bank 1).
# `size` is the size of the field itself; for `sExtraData` it's resolved at
# build time from the delta between `sExtraData` and `sExtraChecksum`.
FRAMING_FIELDS: list[tuple[str, int | None]] = [
    ("sValidCheck1", 1),
    ("sValidCheck2", 1),
    ("sChecksum", 2),
    ("sExtraData", None),
    ("sExtraChecksum", 2),
]

# Save blocks: WRAM source and SRAM mirror. Pulled from `sram.asm`; the WRAM
# and SRAM block sizes match exactly so we map symbols 1:1.
SAVE_BLOCKS: list[tuple[str, str, str, str]] = [
    ("PlayerData",  "wPlayerData",  "wPlayerDataEnd",  "sPlayerData"),
    ("MapData",     "wMapData",     "wMapDataEnd",     "sMapData"),
    ("PokemonData", "wPokemonData", "wPokemonDataEnd", "sPokemonData"),
]


def needs_rebuild(inventory_path: Path, sym_path: Path) -> bool:
    """True if `inventory_path` is missing or older than `sym_path`."""
    if not inventory_path.exists():
        return True
    return inventory_path.stat().st_mtime < sym_path.stat().st_mtime


def build(root: Path, sym_path: Path) -> dict:
    """Parse the .sym + constants files and return the inventory dict."""
    syms = symfile.SymFile.load(sym_path)
    map_defs = maps.parse_maps(root / "constants" / "map_dimension_constants.asm")

    # Parse each focused enum file individually. They all inherit a counter
    # of 1 from their parent (`constants.asm` does `const_def; const NO_X;
    # INCLUDE child`). Stop at the first reset to avoid picking up unrelated
    # constants that share the file (TM IDs, BATTLEANIM_*, etc.).
    def _enum(rel: str) -> list[dict]:
        cs = constants.parse_constants(
            root / rel, start_counter=1, stop_at_reset=True
        )
        return [{"name": c.name, "id": c.value} for c in cs if c.name != "skip"]

    pokemon = _enum("constants/pokemon_constants.asm")
    items = _enum("constants/item_constants.asm")
    # `move_constants.asm` reuses the same counter for ANIM_* (battle
    # animations after the last real move). They aren't selectable moves;
    # drop them.
    moves = [
        m for m in _enum("constants/move_constants.asm")
        if not m["name"].startswith("ANIM_")
    ]
    flags = _enum("constants/event_flags.asm")

    blocks = _resolve_blocks(syms)

    sram_offsets: dict[str, dict] = {}
    for label, meta in WRITABLE_FIELDS.items():
        sym = syms.get(label)
        if sym is None:
            sram_offsets[label] = {
                "error": "symbol not in .sym; skipping",
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

    species_in_order = [p["name"] for p in pokemon]
    base_stats = species.parse_base_stats(root)
    learnsets = species.parse_movesets(root, species_in_order)
    move_pp = species.parse_move_pp(root)

    species_data: dict[str, dict] = {}
    for name in species_in_order:
        bs = base_stats.get(name)
        ls = learnsets.get(name)
        if bs is None:
            continue
        species_data[name] = {
            "hp": bs.hp, "atk": bs.atk, "def_": bs.def_,
            "spd": bs.spd, "sat": bs.sat, "sdf": bs.sdf,
            "growth_rate": bs.growth_rate,
            "learnset": list(ls.level_moves) if ls is not None else [],
        }

    return {
        "built_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "sym_path": str(sym_path.relative_to(root)),
        "sym_mtime": int(sym_path.stat().st_mtime),
        "counts": {
            "pokemon": len(pokemon),
            "items": len(items),
            "moves": len(moves),
            "event_flags": len(flags),
            "maps": len(map_defs),
            "species_data": len(species_data),
            "move_pp": len(move_pp),
        },
        "blocks": blocks,
        "framing": framing,
        "sram_offsets": sram_offsets,
        "pokemon": pokemon,
        "items": items,
        "moves": moves,
        "event_flags": flags,
        "maps": [asdict(m) for m in map_defs],
        "species_data": species_data,
        "move_pp": move_pp,
    }


def load_or_build(
    root: Path,
    sym_path: Path,
    inventory_path: Path,
    *,
    force: bool = False,
    log=print,
) -> dict:
    """Return inventory dict, rebuilding the JSON file if stale or forced."""
    if force or needs_rebuild(inventory_path, sym_path):
        log(f"Building inventory from {sym_path.name}...")
        inv = build(root, sym_path)
        inventory_path.write_text(json.dumps(inv, indent=2))
        log(f"Wrote {inventory_path}")
        return inv
    log(f"Using cached {inventory_path.name} (force-rebuild with --rebuild-inventory)")
    return json.loads(inventory_path.read_text())


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


def print_summary(inv: dict) -> None:
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
    print(
        f"Resolved {sum(1 for v in inv['sram_offsets'].values() if 'sav_offset' in v)} "
        f"of {len(inv['sram_offsets'])} writable WRAM symbols."
    )
    errors = {k: v for k, v in inv["sram_offsets"].items() if "error" in v}
    if errors:
        print("Unresolved:")
        for k, v in errors.items():
            print(f"  {k}: {v['error']}")
