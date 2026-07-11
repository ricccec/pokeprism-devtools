"""Sprite facts the engine enforces but the assembler doesn't check.

Two independent tables, both needed to tell whether a map's objects will
actually render:

``data/sprite_headers.asm`` — a **positional** array indexed by the SPRITE_*
constant (``SpriteHeaders[id - 1]``), giving each sprite its type. The type is
what costs VRAM: ``GetSpriteLength`` (engine/overworld.asm:573) returns 4 tiles
for a ``STILL_SPRITE`` and 12 for everything that can face and walk. Sprite ids
at or above ``SPRITE_POKEMON`` are overworld Pokémon and have no header — their
graphics come from the species pic.

``engine/overworld.asm`` — ``OutdoorSprites``, one sprite set per map group. For
a map with an *outdoor* permission (TOWN/ROUTE), ``AddMapSprites`` loads GFX
**only** from its group's set, ignoring what the map's own objects ask for; an
object whose sprite isn't in the set renders as garbage at runtime with no build
error. (Indoor maps load from their own objects instead, so they're unaffected.)
Sets are shared between groups and ``db 0``-terminated.

This module only *reads* those tables. The VRAM packing simulation that decides
whether a walking sprite lands in a usable tile slot is Phase 1's job — the tile
costs and capacities it needs are exposed here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from .constants import parse_constants, to_dict

_SPRITE_CONSTANTS = "constants/sprite_constants.asm"
_MISC_CONSTANTS = "constants/misc_constants.asm"
_SPRITE_HEADERS = "data/sprite_headers.asm"
_MAP_OBJECTS = "data/map_objects.asm"
_OVERWORLD = "engine/overworld.asm"

#: GetSpriteLength (engine/overworld.asm:573) — in tiles.
TILES_STILL = 4
TILES_WALKING = 12

#: Movement functions that make an object **take steps** (data/map_objects.asm
#: SpriteMovementData, field 1). Only these need walk-frame graphics: an object
#: that steps animates its walk cycle, which the engine fetches at a fixed +$80
#: tile offset from the sprite's base tile (data/facings.asm).
#:
#: Spins and bounces are deliberately *not* here. They change facing or bob in
#: place without stepping, so a standing sprite serves them fine — even though
#: every one in the repo today happens to sit on a walking sprite.
STEPPING_MOVE_FUNCTIONS = frozenset({
    "SPRITEMOVEFN_RANDOM_WALK_XY",
    "SPRITEMOVEFN_RANDOM_WALK_X",
    "SPRITEMOVEFN_RANDOM_WALK_Y",
    "SPRITEMOVEFN_FOLLOW",
    "SPRITEMOVEFN_FOLLOW_NOT_EXACT",
    "SPRITEMOVEFN_OBEY_DPAD",
})

_SPRITE_HEADER_RE = re.compile(
    r"^\s*sprite_header\s+(\w+)\s*,\s*([^,]+?)\s*,\s*(\w+)\s*,\s*(\w+)\s*(?:;.*)?$"
)
_DW_RE = re.compile(r"^\s*dw\s+(\w+)\s*(?:;.*)?$")
_DB_SPRITE_RE = re.compile(r"^\s*db\s+(\w+)\s*(?:;.*)?$")
_LABEL_RE = re.compile(r"^(\w+):")
_EQU_RE = re.compile(r"^\s*(\w+)\s+EQU\s+\$?([0-9a-fA-F]+)")


class SpriteDataError(RuntimeError):
    pass


@dataclass(frozen=True)
class SpriteHeader:
    sprite: str          # the SPRITE_* constant name
    sprite_id: int
    label: str           # e.g. "SageSprite"
    gfx: str             # e.g. "SageSpriteGFX"
    type: str            # WALKING_SPRITE | STANDING_SPRITE | STILL_SPRITE
    palette: str

    @property
    def walking(self) -> bool:
        """Can animate a walk cycle. Walk frames are fetched at a fixed +$80
        tile offset from the sprite's base tile (data/facings.asm), which is the
        constraint that makes walkers scarce — see the Phase 1 packer."""
        return self.type == "WALKING_SPRITE"

    @property
    def tiles(self) -> int:
        return TILES_STILL if self.type == "STILL_SPRITE" else TILES_WALKING


@dataclass
class SpriteData:
    root: Path
    sprite_ids: dict[str, int]                  # SPRITE_* -> id
    headers: dict[str, SpriteHeader]            # SPRITE_* -> header
    outdoor_sets: dict[int, list[str]]          # map group -> [SPRITE_*]
    set_names: dict[int, str]                   # map group -> set label
    list_capacity: int                          # SPRITE_GFX_LIST_CAPACITY
    pokemon_sprite_id: int                      # SPRITE_POKEMON
    vars_sprite_id: int                         # SPRITE_VARS
    movedata_ids: dict[str, int]                # SPRITEMOVEDATA_* -> index
    move_functions: list[str]                   # index -> SPRITEMOVEFN_*
    type_ids: dict[str, int]                    # WALKING_SPRITE -> 1, …

    def header(self, sprite: str) -> SpriteHeader | None:
        return self.headers.get(sprite)

    def type_rank(self, type_name: str) -> int:
        """SortUsedSprites bubble-sorts the list ascending by *type value*, and
        WALKING(1) < STANDING(2) < STILL(3) — which is what pushes walkers to
        the front of VRAM, where their walk frames are reachable."""
        return self.type_ids.get(type_name, 99)

    def move_function(self, movedata: str) -> str | None:
        """The movement function behind a `person_event`'s movement argument.

        Accepts the constant or a raw literal — a few maps write ``$2`` where
        they mean ``SPRITEMOVEDATA_WANDER``.
        """
        index = self.movedata_ids.get(movedata)
        if index is None:
            try:
                index = _to_int(movedata)
            except ValueError:
                return None
        if 0 <= index < len(self.move_functions):
            return self.move_functions[index]
        return None

    def steps(self, movedata: str) -> bool:
        """Whether this movement makes the object walk — see
        :data:`STEPPING_MOVE_FUNCTIONS`."""
        return self.move_function(movedata) in STEPPING_MOVE_FUNCTIONS

    # The id space has three regions, and only the first one plays by the
    # sprite_header / OutdoorSprites rules:
    #
    #   id < SPRITE_POKEMON    a normal sprite — has a header, costs VRAM tiles
    #   .. < SPRITE_VARS       an overworld Pokémon — GFX comes from the species
    #   id >= SPRITE_VARS      a variable sprite — the engine substitutes a real
    #                          id at runtime, so nothing is knowable statically
    def is_pokemon_sprite(self, sprite: str) -> bool:
        sid = self.sprite_ids.get(sprite)
        return sid is not None and self.pokemon_sprite_id <= sid < self.vars_sprite_id

    def is_variable_sprite(self, sprite: str) -> bool:
        sid = self.sprite_ids.get(sprite)
        return sid is not None and sid >= self.vars_sprite_id

    def needs_header(self, sprite: str) -> bool:
        sid = self.sprite_ids.get(sprite)
        # id 0 is SPRITE_NONE — the absence of a sprite, so no header.
        return sid is not None and 0 < sid < self.pokemon_sprite_id

    def outdoor_set(self, group: int) -> list[str]:
        """The sprites a map in `group` may legally use, if it's outdoors."""
        return self.outdoor_sets.get(group, [])

    @cached_property
    def missing_headers(self) -> set[str]:
        """Sprites that ought to have a header and don't — a build-clean way to
        get garbage GFX. Empty on a healthy repo."""
        return {s for s in self.sprite_ids if self.needs_header(s) and s not in self.headers}


def load(root: Path) -> SpriteData:
    ids = sprite_ids(root)
    misc = to_dict(parse_constants(root / _MISC_CONSTANTS))
    sets, names = _outdoor_sprites(root, ids)
    return SpriteData(
        root=root,
        sprite_ids=ids,
        headers=_sprite_headers(root, ids),
        outdoor_sets=sets,
        set_names=names,
        list_capacity=misc.get("SPRITE_GFX_LIST_CAPACITY", 0x20),
        pokemon_sprite_id=ids.get("SPRITE_POKEMON", 1 << 30),
        vars_sprite_id=ids.get("SPRITE_VARS", 1 << 30),
        movedata_ids=movedata_ids(root),
        move_functions=_move_functions(root),
        type_ids=_type_ids(root),
    )


def _type_ids(root: Path) -> dict[str, int]:
    """The sprite-type enum: `const_value = 1` then WALKING / STANDING / STILL."""
    path = root / _SPRITE_CONSTANTS
    out: dict[str, int] = {}
    counter = 0
    for line in path.read_text().split("\n"):
        s = line.split(";")[0].strip()
        if m := re.match(r"^const_value\s*=\s*(\$?[0-9a-fA-F]+)$", s):
            counter = _to_int(m.group(1))
        elif s == "const_def":
            counter = 0
        elif m := re.match(r"^const\s+(\w*_SPRITE)$", s):
            out[m.group(1)] = counter
            counter += 1
        elif re.match(r"^const\s+\w+$", s):
            counter += 1
    return out


def movedata_ids(root: Path) -> dict[str, int]:
    """The SPRITEMOVEDATA_* enum — a plain run of consts from a const_def."""
    path = root / _SPRITE_CONSTANTS
    out: dict[str, int] = {}
    counter = 0
    for line in path.read_text().split("\n"):
        s = line.split(";")[0].strip()
        if m := re.match(r"^const\s+(SPRITEMOVEDATA_\w+)$", s):
            out[m.group(1)] = counter
            counter += 1
        elif s.startswith("const_def"):
            counter = 0
    return out


def _move_functions(root: Path) -> list[str]:
    """SpriteMovementData, positional: entry N is SPRITEMOVEDATA_* value N. The
    first field is the movement function that decides whether it walks."""
    path = root / _MAP_OBJECTS
    if not path.exists():
        raise SpriteDataError(f"{path} not found")
    return [m.group(1) for line in path.read_text().split("\n")
            if (m := re.match(r"\s*sprite_movement_data\s+(\w+)\s*,", line))]


def sprite_ids(root: Path) -> dict[str, int]:
    """The SPRITE_* id enum, including its ``EQU const_value`` boundary markers.

    Scoping this correctly is fiddly, so it is done structurally. The enum opens
    the file with ``const_def`` and *legitimately jumps its counter* twice
    (``const_value = $ec``, ``= $f0``) to place the variable sprites — so a jump
    can't be taken as the end. It ends at the file's **second ``const_def``**,
    the reset that starts the sprite-header-field enum.

    Stopping there matters: further down, the file defines ``SPRITE_ANIM_*``
    constants off their own counters. Those match a naive ``SPRITE_*`` pattern
    and would collide with real sprite ids in the id→name inversion that
    :func:`_sprite_headers` depends on.
    """
    path = root / _SPRITE_CONSTANTS
    if not path.exists():
        raise SpriteDataError(f"{path} not found")

    ids: dict[str, int] = {}
    counter = 0
    started = False
    for line in path.read_text().split("\n"):
        s = line.split(";")[0].strip()
        if s == "const_def":
            if started:
                break                           # a different enum begins here
            counter, started = 0, True
        elif m := re.match(r"^const_value\s*=\s*(\$?[0-9a-fA-F]+)$", s):
            counter = _to_int(m.group(1))       # a jump *within* the id enum
        elif m := re.match(r"^const\s+(SPRITE_\w+)$", s):
            ids[m.group(1)] = counter
            counter += 1
        elif re.match(r"^const\s+\w+$", s):
            counter += 1
        elif m := re.match(r"^(SPRITE_\w+)\s+EQU\s+const_value$", s):
            ids[m.group(1)] = counter           # a boundary marker, not an id
    return ids


def _to_int(s: str) -> int:
    return int(s[1:], 16) if s.startswith("$") else int(s, 10)


def _sprite_headers(root: Path, ids: dict[str, int]) -> dict[str, SpriteHeader]:
    """SpriteHeaders is positional: the nth ``sprite_header`` is sprite id n."""
    path = root / _SPRITE_HEADERS
    if not path.exists():
        raise SpriteDataError(f"{path} not found")

    by_id = {v: k for k, v in ids.items()}
    out: dict[str, SpriteHeader] = {}
    label = ""
    index = 0
    for line in path.read_text().split("\n"):
        if m := _LABEL_RE.match(line):
            label = m.group(1)
        m = _SPRITE_HEADER_RE.match(line)
        if not m:
            continue
        index += 1                              # ids are 1-based; 0 is SPRITE_NONE
        sprite = by_id.get(index)
        if sprite is None:
            continue
        out[sprite] = SpriteHeader(
            sprite=sprite, sprite_id=index, label=label,
            gfx=m.group(1), type=m.group(3), palette=m.group(4),
        )
    return out


def _outdoor_sprites(root: Path, ids: dict[str, int]) -> tuple[dict[int, list[str]], dict[int, str]]:
    """``OutdoorSprites`` is a ``dw``-per-map-group pointer table into the
    ``XSprites:`` lists further down the same file."""
    path = root / _OVERWORLD
    if not path.exists():
        raise SpriteDataError(f"{path} not found")
    lines = path.read_text().split("\n")

    start = next((i for i, ln in enumerate(lines) if ln.startswith("OutdoorSprites:")), None)
    if start is None:
        raise SpriteDataError(f"{_OVERWORLD}: OutdoorSprites table not found")

    group_to_set: dict[int, str] = {}
    group = 0
    for line in lines[start + 1:]:
        m = _DW_RE.match(line)
        if not m:
            if line.strip() and not line.lstrip().startswith(";"):
                break                            # table ended
            continue
        group += 1
        group_to_set[group] = m.group(1)

    contents = _sprite_lists(lines, ids)
    sets = {g: contents.get(name, []) for g, name in group_to_set.items()}
    return sets, group_to_set


def _sprite_lists(lines: list[str], ids: dict[str, int]) -> dict[str, list[str]]:
    """Every ``XSprites:`` list in the file: ``db SPRITE_*`` until ``db 0``."""
    out: dict[str, list[str]] = {}
    current: str | None = None
    for line in lines:
        if m := _LABEL_RE.match(line):
            current = m.group(1) if m.group(1).endswith("Sprites") else None
            if current:
                out[current] = []
            continue
        if current is None:
            continue
        m = _DB_SPRITE_RE.match(line)
        if not m:
            continue
        name = m.group(1)
        if name == "0":
            current = None                       # db 0 terminates the list
        elif name in ids:
            out[current].append(name)
    return out
