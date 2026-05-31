"""Build the SRAM party blob (count, species list, partymon structs,
OT names, nicknames) from a user-friendly `[{species, level, ...}]` list.

Struct layout from `macros/wram.asm:5-43` (box_struct + party_struct), with
NUM_MOVES=4. All multi-byte stats and exp are big-endian (matches Game
Boy's `de` register convention; see the "; big endian" comment in the
asm macro).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pokeprism_devtools import savefile, species as sp


PARTY_LENGTH = 6
NUM_MOVES = 4
PARTYMON_STRUCT_LENGTH = 48
NAME_LENGTH = 11        # OT name
PKMN_NAME_LENGTH = 11   # nickname

# Offsets inside a 48-byte PartyMon struct.
_OFF_SPECIES        = 0
_OFF_ITEM           = 1
_OFF_MOVES          = 2   # 4 bytes
_OFF_ID             = 6   # 2 bytes, big-endian
_OFF_EXP            = 8   # 3 bytes, big-endian
_OFF_HP_EXP         = 11  # 2 bytes big-endian
_OFF_ATK_EXP        = 13
_OFF_DEF_EXP        = 15
_OFF_SPD_EXP        = 17
_OFF_SPC_EXP        = 19
_OFF_DVS            = 21  # 2 bytes packed
_OFF_PP             = 23  # 4 bytes
_OFF_HAPPINESS      = 27
_OFF_PKRUS          = 28
_OFF_CAUGHT_DATA    = 29
_OFF_CAUGHT_LOC     = 30
_OFF_LEVEL          = 31
_OFF_STATUS         = 32
_OFF_SEMISTATUS     = 33
_OFF_HP             = 34
_OFF_MAXHP          = 36
_OFF_ATK            = 38
_OFF_DEF            = 40
_OFF_SPD            = 42
_OFF_SAT            = 44
_OFF_SDF            = 46


@dataclass
class PartyMonInput:
    species: str
    level: int = 5
    nickname: str | None = None     # None → species name uppercased
    moves: list[str] | None = None  # None → derived from learnset
    item: str = "NO_ITEM"
    happiness: int = 70
    # Default DVs = all 15s (max). Order: atk, def, spd, spc.
    dvs: tuple[int, int, int, int] = (15, 15, 15, 15)


@dataclass
class BuiltParty:
    count: int
    species_bytes: bytes      # 7 bytes: 6 species ids + 0xFF terminator
    mons_bytes: bytes         # 6 × 48 = 288 bytes
    ot_names_bytes: bytes     # 6 × 11 = 66 bytes
    nicknames_bytes: bytes    # 6 × 11 = 66 bytes


def build_party(
    mons: list[PartyMonInput],
    *,
    species_ids: dict[str, int],
    move_ids: dict[str, int],
    item_ids: dict[str, int],
    base_stats_db: dict[str, sp.BaseStats],
    learnset_db: dict[str, sp.Learnset],
    move_pp_db: dict[str, int],
    ot_name: str,
    ot_id: int,
) -> BuiltParty:
    if len(mons) > PARTY_LENGTH:
        raise ValueError(f"party can hold at most {PARTY_LENGTH} mons")

    species_arr = bytearray([0xFF] * (PARTY_LENGTH + 1))
    mons_arr = bytearray(PARTYMON_STRUCT_LENGTH * PARTY_LENGTH)
    ot_arr = bytearray(NAME_LENGTH * PARTY_LENGTH)
    nick_arr = bytearray(PKMN_NAME_LENGTH * PARTY_LENGTH)

    encoded_ot = savefile.encode_name(ot_name, NAME_LENGTH)

    for i, mon in enumerate(mons):
        if mon.species not in species_ids:
            raise ValueError(f"unknown species: {mon.species}")
        if mon.species not in base_stats_db:
            raise ValueError(f"no base stats for {mon.species}")
        bs = base_stats_db[mon.species]
        ls = learnset_db.get(mon.species, sp.Learnset(species=mon.species))

        # Resolve moves: explicit override, else learnset default.
        if mon.moves is not None:
            chosen_moves = list(mon.moves)
        else:
            chosen_moves = sp.default_moves_for_level(ls, mon.level)
        if not chosen_moves:
            # Fall back to whatever level-1 move the species has; if none,
            # leave move slot 0 empty (id=0) — the game treats 0 as no move.
            chosen_moves = []
        chosen_moves = chosen_moves[:NUM_MOVES]
        while len(chosen_moves) < NUM_MOVES:
            chosen_moves.append("")  # pad with no-move

        species_arr[i] = species_ids[mon.species] & 0xFF

        struct = bytearray(PARTYMON_STRUCT_LENGTH)
        struct[_OFF_SPECIES] = species_ids[mon.species] & 0xFF
        struct[_OFF_ITEM] = item_ids.get(mon.item, 0) & 0xFF
        for j, mv in enumerate(chosen_moves):
            struct[_OFF_MOVES + j] = move_ids.get(mv, 0) & 0xFF
        # Trainer ID — big-endian.
        struct[_OFF_ID:_OFF_ID + 2] = (ot_id & 0xFFFF).to_bytes(2, "big")
        # Experience for current level — 3 bytes big-endian.
        exp = sp.exp_at_level(bs.growth_rate, mon.level)
        struct[_OFF_EXP:_OFF_EXP + 3] = (exp & 0xFFFFFF).to_bytes(3, "big")
        # StatExp all zero (already initialized).
        # DVs.
        atk_dv, def_dv, spd_dv, spc_dv = mon.dvs
        struct[_OFF_DVS] = ((atk_dv & 0xF) << 4) | (def_dv & 0xF)
        struct[_OFF_DVS + 1] = ((spd_dv & 0xF) << 4) | (spc_dv & 0xF)
        # PP for each move (default = full).
        for j, mv in enumerate(chosen_moves):
            struct[_OFF_PP + j] = move_pp_db.get(mv, 0) & 0xFF
        struct[_OFF_HAPPINESS] = mon.happiness & 0xFF
        struct[_OFF_PKRUS] = 0
        struct[_OFF_CAUGHT_DATA] = 0
        struct[_OFF_CAUGHT_LOC] = 0
        struct[_OFF_LEVEL] = mon.level & 0xFF
        struct[_OFF_STATUS] = 0
        struct[_OFF_SEMISTATUS] = 0

        # Computed stats (HP, Atk, Def, Spd, SpA, SpD). Big-endian.
        hpdv = sp.hp_dv(atk_dv, def_dv, spd_dv, spc_dv)
        max_hp = sp.calc_stat(bs.hp,  hpdv,  0, mon.level, is_hp=True)
        atk    = sp.calc_stat(bs.atk, atk_dv, 0, mon.level, is_hp=False)
        def_s  = sp.calc_stat(bs.def_, def_dv, 0, mon.level, is_hp=False)
        spd    = sp.calc_stat(bs.spd, spd_dv, 0, mon.level, is_hp=False)
        sat    = sp.calc_stat(bs.sat, spc_dv, 0, mon.level, is_hp=False)
        sdf    = sp.calc_stat(bs.sdf, spc_dv, 0, mon.level, is_hp=False)
        struct[_OFF_HP:_OFF_HP + 2]       = max_hp.to_bytes(2, "big")
        struct[_OFF_MAXHP:_OFF_MAXHP + 2] = max_hp.to_bytes(2, "big")
        struct[_OFF_ATK:_OFF_ATK + 2]     = atk.to_bytes(2, "big")
        struct[_OFF_DEF:_OFF_DEF + 2]     = def_s.to_bytes(2, "big")
        struct[_OFF_SPD:_OFF_SPD + 2]     = spd.to_bytes(2, "big")
        struct[_OFF_SAT:_OFF_SAT + 2]     = sat.to_bytes(2, "big")
        struct[_OFF_SDF:_OFF_SDF + 2]     = sdf.to_bytes(2, "big")

        base = i * PARTYMON_STRUCT_LENGTH
        mons_arr[base:base + PARTYMON_STRUCT_LENGTH] = struct

        nick = mon.nickname if mon.nickname else mon.species
        ot_arr[i * NAME_LENGTH:(i + 1) * NAME_LENGTH] = encoded_ot
        nick_arr[i * PKMN_NAME_LENGTH:(i + 1) * PKMN_NAME_LENGTH] = (
            savefile.encode_name(nick, PKMN_NAME_LENGTH)
        )

    return BuiltParty(
        count=len(mons),
        species_bytes=bytes(species_arr),
        mons_bytes=bytes(mons_arr),
        ot_names_bytes=bytes(ot_arr),
        nicknames_bytes=bytes(nick_arr),
    )
