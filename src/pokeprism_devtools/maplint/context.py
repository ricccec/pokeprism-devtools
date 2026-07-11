"""The repo, parsed once and cached, in the shape the rules want to ask about.

Rules are pure functions of this context, so the same rule bodies serve both the
headless linter and (later) the studio's live diagnostics, where the context is
rebuilt from the in-memory model instead of from disk.

Everything is lazy: linting one map shouldn't pay to parse 464 of them, but a
whole-repo run should parse each file exactly once.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from ..shared import eventflags, eventheader as eh, maps, mapsource, spritesets
from ..shared.maps import MapDef

_SECOND_HEADERS = "maps/second_map_headers.asm"
_MAP_CONSTANTS = "constants/map_constants.asm"          # direction / permission enums
_MAP_DIMENSIONS = "constants/map_dimension_constants.asm"   # the `mapgroup` lines
_LANDMARK_CONSTANTS = "constants/landmark_constants.asm"

#: Connection direction bits — `shift_const EAST, WEST, SOUTH, NORTH` in
#: constants/map_constants.asm, i.e. EAST=1, WEST=2, SOUTH=4, NORTH=8. Read from
#: source in :attr:`LintContext.direction_bits` rather than trusted from here.
_DIRECTIONS = ("east", "west", "south", "north")

OPPOSITE = {"north": "south", "south": "north", "east": "west", "west": "east"}

#: Permissions whose maps draw sprites from the map *group's* OutdoorSprites set
#: rather than from their own objects (engine/overworld.asm AddMapSprites).
OUTDOOR_PERMISSIONS = {"TOWN", "ROUTE"}

_MAP_HEADER_2_RE = re.compile(
    r"^\s*map_header_2\s+(\w+)\s*,\s*(\w+)\s*,\s*([^,]+?)\s*,\s*(.+?)\s*(?:;.*)?$"
)
_CONNECTION_RE = re.compile(
    r"^\s*connection\s+(\w+)\s*,\s*(\w+)\s*,\s*(\w+)\s*,\s*(-?\w+)\s*,\s*(-?\w+)\s*,"
    r"\s*(-?\w+)\s*,\s*(\w+)\s*(?:;.*)?$"
)
_SHIFT_CONST_RE = re.compile(r"^\s*shift_const\s+(\w+)")


@dataclass(frozen=True)
class Connection:
    """One `connection` line, tied to the map whose header block it sits in.

    ``declared_self`` is the macro's 7th argument — the id of *this* map. It is
    only read by the south/west/east branches of the macro, so a wrong value in
    a north connection assembles cleanly and is invisible: hence a rule.
    """
    owner: str           # const of the enclosing map_header_2 — the real owner
    direction: str
    target: str          # const of the neighbouring map
    target_label: str
    coord: int           # macro arg 4: where the strip lands in THIS map
    offset: int          # macro arg 5: where the strip is read from in the TARGET
    strip: int           # macro arg 6: how many blocks are copied
    declared_self: str   # macro arg 7
    line: int            # 1-based, in maps/second_map_headers.asm

    @property
    def delta(self) -> int:
        """The alignment delta between the two maps' coordinate systems. The
        macro emits it as ``(coord - offset) * -2``; the reciprocal connection
        must carry exactly its negation."""
        return self.coord - self.offset


@dataclass(frozen=True)
class MapInfo:
    label: str
    const: str
    path: Path


class LintContext:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._headers: dict[str, eh.EventHeader | None] = {}

    # -- files -------------------------------------------------------------- #
    def rel(self, path: Path) -> str:
        return str(path.relative_to(self.root))

    @cached_property
    def source_lines(self) -> dict[str, list[str]]:
        """Every file a diagnostic can point at, for suppression lookups."""
        out: dict[str, list[str]] = {}
        for path in [self.root / _SECOND_HEADERS, *sorted((self.root / "maps").glob("*.asm"))]:
            out[self.rel(path)] = path.read_text().split("\n")
        return out

    # -- maps --------------------------------------------------------------- #
    @cached_property
    def map_defs(self) -> dict[str, MapDef]:
        """const -> MapDef (group, id, height, width)."""
        return {m.name: m for m in maps.parse_maps(self.root / _MAP_DIMENSIONS)}

    @cached_property
    def label_to_const(self) -> dict[str, str]:
        return dict(mapsource.header_pairs(self.root))

    @cached_property
    def const_to_label(self) -> dict[str, str]:
        return {c: l for l, c in self.label_to_const.items()}

    @cached_property
    def map_infos(self) -> dict[str, MapInfo]:
        """const -> MapInfo, for every map whose asm file exists on disk."""
        out: dict[str, MapInfo] = {}
        for label, const in self.label_to_const.items():
            path = self.root / "maps" / f"{label}.asm"
            if path.exists():
                out[const] = MapInfo(label=label, const=const, path=path)
        return out

    def header(self, const: str) -> eh.EventHeader | None:
        """The map's parsed event header, or None if it can't be managed.

        Cached per map, including the None — an unparseable map is asked about
        by several rules and reparsing it each time would be pure waste.
        """
        if const not in self._headers:
            info = self.map_infos.get(const)
            if info is None:
                self._headers[const] = None
            else:
                try:
                    self._headers[const] = eh.parse_map(info.path)
                except eh.UnparseableHeader:
                    self._headers[const] = None
        return self._headers[const]

    @cached_property
    def primary_headers(self) -> dict[str, mapsource.PrimaryHeader]:
        """const -> primary header (tileset, permission, landmark, …)."""
        out = {}
        for const, info in self.map_infos.items():
            ph = mapsource.primary_header(self.root, info.label)
            if ph:
                out[const] = ph
        return out

    def permission(self, const: str) -> str | None:
        ph = self.primary_headers.get(const)
        return ph.permission if ph else None

    def is_outdoor(self, const: str) -> bool:
        return self.permission(const) in OUTDOOR_PERMISSIONS

    def object_walks(self, obj: eh.Entry) -> bool:
        """Whether this object ever *takes a step* — the only thing that makes it
        fetch walk frames.

        This is a property of the object, not of its sprite. A sprite typed
        ``WALKING_SPRITE`` merely *has* walk-frame graphics in ROM; an object
        that only stands, spins or bobs never reads them, so it is perfectly
        happy in the half of VRAM that has no walk frames behind it.

        Two ways an object steps: a movement function that walks, or a trainer
        who spots the player from more than one tile away and closes the
        distance.
        """
        if self.sprites.steps(obj.movement):
            return True
        if "TRAINER" not in obj.persontype:
            return False
        radius = max(obj.int_arg(4) or 0, obj.int_arg(5) or 0)
        return radius > 1

    # -- connections -------------------------------------------------------- #
    @cached_property
    def direction_bits(self) -> dict[str, int]:
        """The `shift_const EAST/WEST/SOUTH/NORTH` bits, read from source."""
        path = self.root / _MAP_CONSTANTS
        bits: dict[str, int] = {}
        shift = 0
        for line in path.read_text().split("\n"):
            m = _SHIFT_CONST_RE.match(line)
            if not m:
                continue
            name = m.group(1).lower()
            if name in _DIRECTIONS:
                bits[name] = 1 << shift
            shift += 1
        return bits

    @cached_property
    def _second_headers(self) -> tuple[dict[str, tuple[str, int, int]], list[Connection]]:
        """Walk second_map_headers.asm once: every map's connection-flag nibble
        and every connection line, each attributed to the header block it is
        written under (*not* to the macro's self-id argument, which can lie)."""
        path = self.root / _SECOND_HEADERS
        flags: dict[str, tuple[str, int, int]] = {}     # const -> (flag expr, line, line)
        conns: list[Connection] = []
        owner: str | None = None

        for i, line in enumerate(path.read_text().split("\n"), start=1):
            m = _MAP_HEADER_2_RE.match(line)
            if m:
                owner = m.group(2)
                flags[owner] = (m.group(4).strip(), i, i)
                continue
            m = _CONNECTION_RE.match(line)
            if m and owner:
                conns.append(Connection(
                    owner=owner,
                    direction=m.group(1).lower(),
                    target=m.group(2),
                    target_label=m.group(3),
                    coord=_to_int(m.group(4)),
                    offset=_to_int(m.group(5)),
                    strip=_to_int(m.group(6)),
                    declared_self=m.group(7),
                    line=i,
                ))
        return flags, conns

    @cached_property
    def connections(self) -> list[Connection]:
        return self._second_headers[1]

    @cached_property
    def connections_by_map(self) -> dict[str, list[Connection]]:
        out: dict[str, list[Connection]] = {}
        for c in self.connections:
            out.setdefault(c.owner, []).append(c)
        return out

    @cached_property
    def conn_flag_exprs(self) -> dict[str, tuple[str, int, int]]:
        return self._second_headers[0]

    def find_connection(self, owner: str, direction: str, target: str) -> Connection | None:
        return next((c for c in self.connections_by_map.get(owner, [])
                     if c.direction == direction and c.target == target), None)

    # -- landmarks / regions ------------------------------------------------ #
    @cached_property
    def landmark_regions(self) -> dict[str, str]:
        """landmark const -> region name (lowercase), as `RegionCheck` resolves it.

        constants/landmark_constants.asm is one flat enum with `region_def NALJO`
        markers dropped into it, each recording where a region's landmarks start.
        `RegionCheck` (engine/landmarks.asm) walks those same starts as
        thresholds and returns the last region whose start is <= the landmark —
        so regions are contiguous ranges, and this reproduces that exactly.
        """
        path = self.root / _LANDMARK_CONSTANTS
        if not path.exists():
            return {}

        out: dict[str, str] = {}
        region = None
        for line in path.read_text().split("\n"):
            s = line.split(";")[0].strip()
            if m := re.match(r"^region_def\s+(\w+)$", s):
                region = m.group(1).lower()
            elif m := re.match(r"^const\s+(\w+)$", s):
                if region:
                    out[m.group(1)] = region
        return out

    def region_of(self, const: str) -> str | None:
        """The region a *map* belongs to, via its landmark."""
        header = self.primary_headers.get(const)
        if header is None:
            return None
        return self.landmark_regions.get(header.landmark)

    # -- shared data -------------------------------------------------------- #
    @cached_property
    def sprites(self) -> spritesets.SpriteData:
        return spritesets.load(self.root)

    @cached_property
    def flags(self) -> eventflags.EventFlags:
        return eventflags.load(self.root)


def _to_int(s: str) -> int:
    s = s.strip()
    if s.startswith("-"):
        return -_to_int(s[1:])
    if s.startswith("$"):
        return int(s[1:], 16)
    return int(s, 10)
