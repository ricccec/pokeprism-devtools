"""Apply a state.json to a SaveFile in memory and recompute checksums.

The state schema is documented in `docs/devtools.md` (the `prism-dev`
section). All fields are optional — anything not set falls through to the
template's existing value, including the map cluster (group/number/x/y).

Map-change side effects (block-data lookup, wScreenSave recompute, player
struct reset, NPC clear) live here too — they're invoked automatically
when any of `map.{name,x,y}` is touched. See
`docs/blockdata-plan.md` for the why.
"""

from __future__ import annotations

import json
from pathlib import Path

from pokeprism_devtools.shared import blockdata, party as party_mod, people, savefile, species, symfile


def load_state(path: Path, presets_dir: Path) -> dict:
    """Load `state.json`, falling back to `presets/default.json`, then to {}.

    An empty dict means "leave the template unchanged" — that's the
    out-of-the-box behaviour on a fresh pokeprism checkout that hasn't
    yet seeded `.devtools/presets/default.json`.
    """
    if path.exists():
        return json.loads(path.read_text())
    default = presets_dir / "default.json"
    if default.exists():
        return json.loads(default.read_text())
    return {}


def looks_like_real_save(sav: savefile.SaveFile, inv: dict) -> bool:
    """Cheap sanity check that the template has the game's validity bytes."""
    v1 = sav.data[inv["framing"]["sValidCheck1"]["sav_offset"]]
    v2 = sav.data[inv["framing"]["sValidCheck2"]["sav_offset"]]
    return v1 == 0x63 and v2 == 0x7F


def apply_state(
    sav: savefile.SaveFile,
    state: dict,
    inv: dict,
    *,
    rom_path: Path,
    syms: symfile.SymFile,
    keep_people: bool = False,
) -> list[str]:
    """Mutate the save in place and return a list of human-readable changes."""
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

    # Resolve final (group, map_id, x, y), defaulting to the template's
    # values for fields the user didn't touch.
    final_group = sav.data[off("wMapGroup")]
    final_map = sav.data[off("wMapNumber")]
    final_x = sav.data[off("wXCoord")]
    final_y = sav.data[off("wYCoord")]
    map_state_changed = False
    map_label = None

    if "name" in map_:
        mdef = next((m for m in inv["maps"] if m["name"] == map_["name"]), None)
        if mdef is None:
            raise ValueError(f"unknown map: {map_['name']}")
        final_group = mdef["group"]
        final_map = mdef["map_id"]
        map_label = map_["name"]
        map_state_changed = True
    if "x" in map_:
        final_x = int(map_["x"]) & 0xFF
        map_state_changed = True
    if "y" in map_:
        final_y = int(map_["y"]) & 0xFF
        map_state_changed = True

    if map_state_changed:
        sav.write_byte(off("wMapGroup"), final_group)
        sav.write_byte(off("wMapNumber"), final_map)
        sav.write_byte(off("wXCoord"), final_x)
        sav.write_byte(off("wYCoord"), final_y)
        # Recompute wScreenSave from ROM so MAPSETUP_CONTINUE's
        # LoadNeighboringBlockData overlays consistent data (otherwise the
        # area around the player renders as stale tiles or zeros).
        bd = blockdata.load(
            rom_path, syms, final_group, final_map, name=map_label or ""
        )
        ss_bytes = blockdata.compute_screen_save(bd, final_x, final_y)
        sav.write_bytes(off("wScreenSave"), ss_bytes)

        label = map_label or f"(group {final_group}, id {final_map})"
        changes.append(
            f"map = {label} at ({final_x}, {final_y}); "
            f"recomputed wScreenSave from {bd.width}x{bd.height} block grid"
        )

        # Reset the player struct + (unless --keep-people) clear NPC slots.
        # Without this, MAPSETUP_CONTINUE leaves wObjectStructs holding the
        # previous map's player position and NPC state, so the player
        # renders off-screen and ghost NPCs from the old map show up.
        people_changes = people.reset_player_and_clear_npcs(
            sav,
            object_structs_offset=offsets["wObjectStructs"]["sav_offset"],
            map_objects_offset=offsets["wMapObjects"]["sav_offset"],
            map_objects_size=offsets["wMapObjects"]["size"],
            x=final_x,
            y=final_y,
            keep_npcs=keep_people,
        )
        changes.append(
            "people: " + ", ".join(f"{k}={v}" for k, v in people_changes.items())
        )

    party_state = state.get("party")
    if party_state:
        changes.extend(_apply_party(sav, party_state, inv, state.get("player") or {}, off))

    flags_state = state.get("flags") or {}
    if flags_state.get("event") or flags_state.get("engine"):
        changes.extend(_apply_flags(sav, flags_state, inv, off))

    return changes


def _apply_flags(
    sav: savefile.SaveFile,
    flags_state: dict,
    inv: dict,
    off,
) -> list[str]:
    """Write event flags and engine flags into the .sav."""
    import sys

    changes: list[str] = []

    event_names: list[str] = flags_state.get("event") or []
    if event_names:
        flag_ids = {f["name"]: f["id"] for f in inv["event_flags"]}
        buf = bytearray(250)
        for name in event_names:
            fid = flag_ids.get(name)
            if fid is None:
                raise ValueError(f"unknown event flag: {name!r}")
            buf[fid >> 3] |= 1 << (fid & 7)
        sav.write_bytes(off("wEventFlags"), bytes(buf))
        changes.append(f"event_flags = {sorted(event_names)}")

    engine_names: list[str] = flags_state.get("engine") or []
    if engine_names:
        ef_meta = {f["name"]: f for f in inv["engine_flags"]}
        mutations: dict[int, int] = {}
        for name in engine_names:
            meta = ef_meta.get(name)
            if meta is None:
                raise ValueError(f"unknown engine flag: {name!r}")
            sav_offset = meta.get("sav_offset")
            if sav_offset is None:
                print(
                    f"warning: engine flag {name!r} has no SRAM offset; skipping",
                    file=sys.stderr,
                )
                continue
            mutations[sav_offset] = mutations.get(sav_offset, 0) | (1 << meta["bit"])
        for sav_offset, bits in mutations.items():
            sav.data[sav_offset] |= bits
        changes.append(f"engine_flags = {sorted(engine_names)}")

    return changes


def _apply_party(
    sav: savefile.SaveFile,
    party_state: list[dict],
    inv: dict,
    player_state: dict,
    off,
) -> list[str]:
    """Write count + species + mons + OT names + nicknames into the .sav.

    `party_state` is a list of dicts: `{species, level, nickname?, moves?, item?}`.
    """
    species_ids = {p["name"]: p["id"] for p in inv["pokemon"]}
    move_ids = {m["name"]: m["id"] for m in inv["moves"]}
    item_ids = {i["name"]: i["id"] for i in inv["items"]}

    base_stats_db = {
        name: species.BaseStats(
            species=name,
            hp=d["hp"], atk=d["atk"], def_=d["def_"],
            spd=d["spd"], sat=d["sat"], sdf=d["sdf"],
            growth_rate=d["growth_rate"],
        )
        for name, d in inv["species_data"].items()
    }
    learnset_db = {
        name: species.Learnset(
            species=name,
            level_moves=[(int(lvl), mv) for lvl, mv in d["learnset"]],
        )
        for name, d in inv["species_data"].items()
    }
    move_pp_db: dict[str, int] = dict(inv["move_pp"])

    mons_in: list[party_mod.PartyMonInput] = []
    for raw in party_state:
        if not isinstance(raw, dict) or "species" not in raw:
            raise ValueError(f"invalid party entry: {raw!r}")
        level = int(raw.get("level", 5))
        if not (1 <= level <= 100):
            raise ValueError(f"level out of range: {level} (1-100)")
        mons_in.append(party_mod.PartyMonInput(
            species=raw["species"],
            level=level,
            nickname=raw.get("nickname"),
            moves=raw.get("moves"),
            item=raw.get("item", "NO_ITEM"),
            happiness=int(raw.get("happiness", 70)),
        ))

    # Read OT name and trainer id from the template (the player's current
    # values), preferring an explicit override in state.player.
    ot_name_bytes = sav.read(off("wPlayerName"), 8)
    ot_name = player_state.get("name") or _decode_name(ot_name_bytes)
    if not ot_name:
        ot_name = "DEV"
    ot_id = int.from_bytes(sav.read(off("wPlayerID"), 2), "big")

    built = party_mod.build_party(
        mons_in,
        species_ids=species_ids,
        move_ids=move_ids,
        item_ids=item_ids,
        base_stats_db=base_stats_db,
        learnset_db=learnset_db,
        move_pp_db=move_pp_db,
        ot_name=ot_name,
        ot_id=ot_id,
    )

    sav.write_byte(off("wPartyCount"), built.count)
    sav.write_bytes(off("wPartySpecies"),      built.species_bytes)
    sav.write_bytes(off("wPartyMons"),         built.mons_bytes)
    sav.write_bytes(off("wPartyMonOT"),        built.ot_names_bytes)
    sav.write_bytes(off("wPartyMonNicknames"), built.nicknames_bytes)

    descs = [
        f"{m.species}@L{m.level}" for m in mons_in
    ]
    return [f"party = [{', '.join(descs)}]"]


def _decode_name(b: bytes) -> str:
    """Reverse of savefile.encode_name for the printable subset.

    Stops at the 0x50 terminator. Unknown bytes are dropped silently.
    """
    out = []
    for ch in b:
        if ch == 0x50:
            break
        if 0x80 <= ch <= 0x99:
            out.append(chr(ord("A") + (ch - 0x80)))
        elif 0xA0 <= ch <= 0xB9:
            out.append(chr(ord("a") + (ch - 0xA0)))
        elif 0xF6 <= ch <= 0xFF:
            out.append(chr(ord("0") + (ch - 0xF6)))
        elif ch == 0x7F:
            out.append(" ")
    return "".join(out)


def recompute_checksums(sav: savefile.SaveFile, inv: dict) -> None:
    """Recompute `sChecksum` (over sGameData) and `sExtraChecksum` (over
    sExtraData) and write them back. After this the .sav is consistent and
    `TryLoadSaveFile` will accept it without falling back to the backup.
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
