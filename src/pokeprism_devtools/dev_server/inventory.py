"""Inventory builder for prism-dev.

Scans the .sym and `constants/*.asm` to produce a JSON catalog of every
map, pokemon, item, move, and event flag — plus the .sav file offsets for
the WRAM fields the patcher writes. Cached as `inventory.json` next to
the prism-dev script; regenerated automatically when the .sym is newer.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import asdict
from pathlib import Path

from pokeprism_devtools.shared import constants, maps, savefile, species, symfile


# Bump when the inventory layout changes (new fields, new offsets); cached
# inventory.json files with a different schema are rebuilt regardless of mtime.
INVENTORY_SCHEMA = 3

# WRAM symbols whose values the prism-dev tool will write. Resolved to
# .sav file offsets in the inventory. Group them by save block so we can
# validate each ends up in the expected region.
WRITABLE_FIELDS: dict[str, dict[str, object]] = {
    # Player block
    "wPlayerName":    {"size": 8,  "block": "PlayerData"},
    "wMoney":         {"size": 3,  "block": "PlayerData"},
    "wNumItems":      {"size": 1,  "block": "PlayerData"},
    "wItems":         {"size": 81, "block": "PlayerData"},  # MAX_ITEMS*2 + 1
    "wNumKeyItems":   {"size": 1,  "block": "PlayerData"},
    "wKeyItems":      {"size": 51, "block": "PlayerData"},  # MAX_KEY_ITEMS + 1
    "wNumBalls":      {"size": 1,  "block": "PlayerData"},
    "wBalls":         {"size": 51, "block": "PlayerData"},  # MAX_BALLS*2 + 1
    "wEventFlags":    {"size": 250, "block": "PlayerData"},
    # flag_array NUM_TMS + NUM_HMS — sized from the end symbol so a TM-list
    # change in the game repo can't silently desync the region size.
    "wTMsHMs":        {"size_from_end": "wTMsHMsEnd", "block": "PlayerData"},
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
    # Pocket attribute per item id, from the attributes table. Items without
    # a row (only SPECIAL_ITEM) get None and are rejected by the bag writer.
    pockets = _parse_item_pockets(root / "items" / "item_attributes.asm")
    pocket_by_id = {i + 1: p for i, p in enumerate(pockets)}
    for it in items:
        it["pocket"] = pocket_by_id.get(it["id"])
    # `move_constants.asm` reuses the same counter for ANIM_* (battle
    # animations after the last real move). They aren't selectable moves;
    # drop them.
    moves = [
        m for m in _enum("constants/move_constants.asm")
        if not m["name"].startswith("ANIM_")
    ]
    flags = _enum("constants/event_flags.asm")

    blocks = _resolve_blocks(syms)
    engine_flags = _parse_engine_flags(root / "constants" / "engine_flags.asm")
    _resolve_engine_flag_offsets(engine_flags, syms, blocks)
    tmhms = _parse_tmhms(root / "constants" / "item_constants.asm")

    sram_offsets: dict[str, dict] = {}
    for label, meta in WRITABLE_FIELDS.items():
        sym = syms.get(label)
        if sym is None:
            sram_offsets[label] = {
                "error": "symbol not in .sym; skipping",
                "size": meta.get("size"),
                "block": meta["block"],
            }
            continue
        if "size_from_end" in meta:
            end_sym = syms.get(meta["size_from_end"])
            if end_sym is None:
                sram_offsets[label] = {
                    "error": f"end symbol {meta['size_from_end']!r} not in .sym",
                    "size": None,
                    "block": meta["block"],
                }
                continue
            size = end_sym.addr - sym.addr
        else:
            size = meta["size"]
        block = blocks[meta["block"]]
        offset_in_block = sym.addr - block["wram_start_addr"]
        if not (0 <= offset_in_block < block["size"]):
            sram_offsets[label] = {
                "error": (
                    f"{label}@${sym.addr:04x} not inside "
                    f"{meta['block']} block "
                    f"(${block['wram_start_addr']:04x}–${block['wram_end_addr']:04x})"
                ),
                "size": size,
                "block": meta["block"],
            }
            continue
        sram_addr = block["sram_start_addr"] + offset_in_block
        file_offset = savefile.sram_to_file_offset(1, sram_addr)
        sram_offsets[label] = {
            "sav_offset": file_offset,
            "size": size,
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

    misc = constants.to_dict(
        constants.parse_constants(root / "constants" / "misc_constants.asm")
    )

    tmhm_region_size = sram_offsets.get("wTMsHMs", {}).get("size")
    if tmhm_region_size is not None:
        expected = (len(tmhms) + 7) // 8
        if tmhm_region_size != expected:
            raise ValueError(
                f"wTMsHMs region is {tmhm_region_size} bytes but "
                f"{len(tmhms)} TM/HM entries need {expected} bytes — "
                "item_constants.asm and wram.asm have gone out of sync"
            )

    return {
        "schema": INVENTORY_SCHEMA,
        "built_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "sym_path": str(sym_path.relative_to(root)),
        "sym_mtime": int(sym_path.stat().st_mtime),
        "counts": {
            "pokemon": len(pokemon),
            "items": len(items),
            "moves": len(moves),
            "event_flags": len(flags),
            "engine_flags": len(engine_flags),
            "maps": len(map_defs),
            "species_data": len(species_data),
            "move_pp": len(move_pp),
            "tmhms": len(tmhms),
        },
        "bag_caps": {
            "items": misc["MAX_ITEMS"],
            "balls": misc["MAX_BALLS"],
            "key_items": misc["MAX_KEY_ITEMS"],
        },
        "blocks": blocks,
        "framing": framing,
        "sram_offsets": sram_offsets,
        "pokemon": pokemon,
        "items": items,
        "moves": moves,
        "event_flags": flags,
        "engine_flags": engine_flags,
        "maps": [asdict(m) for m in map_defs],
        "species_data": species_data,
        "move_pp": move_pp,
        "tmhms": tmhms,
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
    inv = json.loads(inventory_path.read_text())
    if inv.get("schema") != INVENTORY_SCHEMA:
        log(
            f"Cached {inventory_path.name} has schema "
            f"{inv.get('schema')!r} (want {INVENTORY_SCHEMA}); rebuilding..."
        )
        inv = build(root, sym_path)
        inventory_path.write_text(json.dumps(inv, indent=2))
        log(f"Wrote {inventory_path}")
        return inv
    log(f"Using cached {inventory_path.name} (force-rebuild with --rebuild-inventory)")
    return inv


_ITEM_ATTR_RE = re.compile(r"^\s*item_attribute\s+(.+)$")
_KNOWN_POCKETS = {"ITEM", "KEY_ITEM", "BALL", "TM_HM"}


def _parse_item_pockets(path: Path) -> list[str]:
    """Pocket name per item id (index 0 == item id 1).

    Parses `items/item_attributes.asm`: one `item_attribute` macro row per
    item, in item-id order; the pocket constant is the 6th macro argument.
    """
    pockets: list[str] = []
    with path.open() as f:
        for line in f:
            line = line[:line.find(";")] if ";" in line else line
            m = _ITEM_ATTR_RE.match(line)
            if not m:
                continue
            args = [a.strip() for a in m.group(1).split(",")]
            if len(args) < 6:
                raise ValueError(f"{path.name}: malformed row: {line.strip()!r}")
            pocket = args[5]
            if pocket not in _KNOWN_POCKETS:
                raise ValueError(
                    f"{path.name}: unknown pocket {pocket!r} in {line.strip()!r}"
                )
            pockets.append(pocket)
    return pockets


_TMHM_RE = re.compile(r"^\s*(add_tm|add_hm)\s+(\w+)\s*$")


def _parse_tmhms(path: Path) -> list[dict]:
    """Extract the TM/HM list from `add_tm`/`add_hm` lines in order.

    Each `add_tm FOO` / `add_hm FOO` assigns the next 1-based TM/HM number
    (TMs first, then HMs) and defines a `TM_FOO`/`HM_FOO` item constant and a
    `FOO_TMNUM` move-index constant. The ownership bit in `wTMsHMs` is
    (number - 1), matching the engine's `FlagAction` convention.
    """
    results: list[dict] = []
    seen_hm = False
    tm_count = 0
    hm_count = 0
    with path.open() as f:
        for line in f:
            line = line[:line.find(";")] if ";" in line else line
            m = _TMHM_RE.match(line)
            if not m:
                continue
            macro, move = m.group(1), m.group(2)
            kind = "TM" if macro == "add_tm" else "HM"
            if kind == "TM":
                if seen_hm:
                    raise ValueError(
                        f"{path.name}: add_tm {move} appears after the first "
                        "add_hm — TM/HM numbering would be corrupted"
                    )
                tm_count += 1
                num = tm_count
            else:
                seen_hm = True
                hm_count += 1
                num = hm_count
            bit = len(results)
            results.append({
                "name": f"{kind}_{move}",
                "move": move,
                "kind": kind,
                "num": num,
                "bit": bit,
            })
    if not results:
        raise ValueError(f"{path.name}: no add_tm/add_hm lines found")
    return results


_ENGINE_FLAG_RE = re.compile(
    r"def_engine_flag\s+(\w+)\s*,\s*([\w]+(?:\s*\+\s*\d+)?)\s*,\s*(\d+)"
)
_WRAM_EXPR_RE = re.compile(r"(\w+)(?:\s*\+\s*(\d+))?$")


def _parse_engine_flags(path: Path) -> list[dict]:
    """Extract (name, id, wram_expr, bit) from every def_engine_flag line."""
    counter = 0
    results = []
    with path.open() as f:
        for line in f:
            line = line[:line.find(";")] if ";" in line else line
            m = _ENGINE_FLAG_RE.search(line)
            if not m:
                continue
            results.append({
                "name": m.group(1),
                "id": counter,
                "wram_expr": m.group(2).strip(),
                "bit": int(m.group(3)),
            })
            counter += 1
    return results


def _resolve_engine_flag_offsets(
    flags: list[dict],
    syms: symfile.SymFile,
    blocks: dict[str, dict],
) -> None:
    """Mutate each engine-flag dict in-place, adding sav_offset when resolvable."""
    for ef in flags:
        m = _WRAM_EXPR_RE.match(ef["wram_expr"])
        if not m:
            continue
        base_sym = m.group(1)
        extra = int(m.group(2)) if m.group(2) else 0
        sym = syms.get(base_sym)
        if sym is None:
            continue
        target_addr = sym.addr + extra
        for block in blocks.values():
            if block["wram_start_addr"] <= target_addr < block["wram_end_addr"]:
                offset_in_block = target_addr - block["wram_start_addr"]
                sram_addr = block["sram_start_addr"] + offset_in_block
                ef["sav_offset"] = savefile.sram_to_file_offset(1, sram_addr)
                break


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
