"""Vanilla's read adapter: a stock pokecrystal tree, in the seam's records.

The catalog lives in three files and each fact is read from the one that
owns it: `data/maps/attributes.asm` names the maps (label ↔ const, border,
connections), `constants/map_constants.asm` sizes and groups them, and
`data/maps/maps.asm` styles them (tileset, environment, landmark, music,
palette, fish group). `data/maps/blocks.asm` says where each shape's bytes
are. None of the five is optional in a checkout that builds, but every
lookup here still degrades to a dash — a tree mid-edit is a tree you
especially want to look at.

Everything file-shaped is parsed once per mount through `lru_cache`;
`shared.caches.clear` finds these caches by walking the imported modules, so
a session reload drops them without this module knowing reloads exist.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from ...studio import panels
from ...studio.actions import ActionError
from . import events, measures, metrics, swatches

_ATTR = re.compile(r"^\s*map_attributes\s+(\w+)\s*,\s*(\w+)\s*,\s*(\$\w+|\d+)")
_CONN = re.compile(r"^\s*connection\s+(\w+)\s*,\s*(\w+)\s*,\s*(\w+)\s*,\s*(-?\d+)")
#: Vanilla names its groups, polished's `newgroup` is bare — both count.
_GROUP = re.compile(r"^\s*newgroup\b")
_MAP_CONST = re.compile(r"^\s*map_const\s+(\w+)\s*,\s*(\d+)\s*,\s*(\d+)")
_MAP = re.compile(r"^\s*map\s+(\w+)\s*,\s*(.+)")
_BLOCKS_LABEL = re.compile(r"^(\w+)_Blocks:")
_INCBIN = re.compile(r'INCBIN\s+"([^"]+)"')
_DB = re.compile(r"^\s*db\s+(\S+)")
_ROOF_CONST = re.compile(r"^\s*const\s+(ROOF_\w+)")
_RGB = re.compile(r"^\s*RGB\s+([\d, ]+)")
_WILDMON = re.compile(r"^\s*db\s+(\d+)\s*,\s*(\w+)")


class Reader:
    """One pokecrystal tree, answering the studio's questions in the seam's
    words. `sketch` is present: the new-map form draws before it writes.
    `measure` is not here but in :class:`MeasuringReader`, which is what the
    mount builds when the tree's text engine is on disk to measure against."""

    def __init__(self, root: Path) -> None:
        self.root = root

    # -- the catalog --------------------------------------------------------- #
    def maps(self) -> dict[str, str]:
        """label -> const, in `attributes.asm` order — the file that says a
        map exists at all."""
        return {label: a.const for label, a in attrs(self.root).items()}

    def parses(self, const: str) -> bool:
        label = label_of(self.root).get(const)
        return label is not None and (self.root / f"maps/{label}.asm").exists()

    def connections(self, const: str) -> list[panels.Link]:
        """The modern `connection` macro declares only the offset and lets
        the assembler compute the rest, so the computed columns cross empty
        and the table above the seam narrows to match."""
        label = label_of(self.root).get(const)
        a = attrs(self.root).get(label or "")
        return [panels.Link(direction=d, target=target, offset=offset)
                for d, target, offset in (a.connections if a else [])]

    # -- one map ------------------------------------------------------------- #
    def tables(self, label: str) -> panels.MapTables:
        return events.tables(self.root / f"maps/{label}.asm")

    def attributes(self, label: str, const: str) -> panels.Attributes:
        d = dims(self.root).get(const)
        m = _styles(self.root).get(label)
        a = attrs(self.root).get(label)
        return panels.Attributes(
            label=label, const=const,
            group=d.group if d else 0, map_id=d.map_id if d else 0,
            height=d.height if d else 0, width=d.width if d else 0,
            blk=_blk(self.root).get(label, "—"),
            tileset=m.tileset if m else "—",
            permission=m.environment if m else "—",
            landmark=m.landmark if m else "—",
            music=m.music if m else "—",
            palette=m.palette if m else "—",
            fishgroup=m.fishgroup if m else "—",
            phone=m.phone if m else "0",
            border_block=a.border if a else "—")

    def geometry(self, label: str) -> panels.Blocks:
        const = attrs(self.root).get(label)
        d = dims(self.root).get(const.const) if const else None
        rel = _blk(self.root).get(label)
        if d is None or rel is None:
            raise panels.Unreadable(
                f"{label} is not in constants/map_constants.asm and "
                "data/maps/blocks.asm both — it has no declared shape.")
        path = self.root / rel
        try:
            blocks = path.read_bytes()
        except FileNotFoundError as exc:
            raise panels.Unreadable(f"{path} does not exist.") from exc
        if len(blocks) != d.width * d.height:
            raise panels.Unreadable(
                f"{path} is {len(blocks)} bytes; map_const says "
                f"{d.width}×{d.height} = {d.width * d.height}.")
        m = _styles(self.root).get(label)
        return panels.Blocks(
            blocks=blocks, height=d.height, width=d.width,
            swatches=swatches.for_tileset(self.root, m.tileset) if m else ())

    # -- what a form is sketching -------------------------------------------- #
    def sketch(self, action) -> panels.Blocks | None:
        """A picture of what the new-map form would put on the grid.

        The form draws the *shape* — it is neutral code and a grid file is
        bytes in any tree. This puts the tree's *colour* on it, which is the
        half only an adapter can answer.

        A tileset that is merely unfinished draws uncoloured, because a form is
        unfinished for as long as you are typing into it and the shape is the
        half that catches a wrong height. One that is finished and *wrong* is
        refused, with what is wrong about it: a map drawn in another tileset's
        colours looks perfectly fine and is perfectly wrong, so it is the one
        case where saying nothing would be worse than drawing nothing.
        """
        drawn = action.sketch(self.root)
        if drawn is None:
            return None
        try:
            colors = swatches.for_tileset(self.root, drawn.tileset) if drawn.tileset else ()
        except panels.Unreadable as exc:
            raise ActionError(str(exc)) from exc
        return panels.Blocks(blocks=drawn.blocks, height=drawn.height,
                             width=drawn.width, swatches=colors,
                             label=drawn.label)

    def wild(self, const: str) -> dict[str, dict[str, list[panels.WildMon]]]:
        """Grass splits by time of day, water doesn't — seven slots ×3 and
        three slots ×1, fixed by the engine. A map with no encounters is the
        common case, not an error."""
        found: dict[str, dict[str, list[panels.WildMon]]] = {}
        for kind, rel in (("grass", "data/wild/johto_grass.asm"),
                          ("grass", "data/wild/kanto_grass.asm"),
                          ("water", "data/wild/johto_water.asm"),
                          ("water", "data/wild/kanto_water.asm")):
            mons = _wild_file(self.root, rel).get(const)
            if mons is None:
                continue
            if kind == "grass":
                found[kind] = {time: mons[i * 7:(i + 1) * 7]
                               for i, time in enumerate(("morn", "day", "nite"))}
            else:
                found[kind] = {"any": mons}
        return found

    def roof(self, const: str) -> panels.Roof | None:
        """The roof this map's group loads. Vanilla's `MapGroupRoofs` covers
        every group and its comments agree with its engine, so the pathology
        fields prism fills stay empty — absence, not luck."""
        d = dims(self.root).get(const)
        if d is None:
            return None
        names, values, files = _roof_table(self.root)
        if d.group >= len(values):
            return panels.Roof(group=d.group, past_end=True,
                               entries=len(values), colors=_roof_colors(self.root, d.group))
        tiles = names.index(values[d.group]) if values[d.group] in names else None
        return panels.Roof(
            group=d.group, tiles=tiles,
            tile_file=files[tiles] if tiles is not None and tiles < len(files)
            else None,
            colors=_roof_colors(self.root, d.group))

    # -- the words ----------------------------------------------------------- #
    def texts(self, label: str) -> list[panels.TextRef]:
        return events.texts(self.root / f"maps/{label}.asm")


class MeasuringReader(Reader):
    """The same reader, on a tree whose text engine can be read.

    Two classes rather than one method that sometimes refuses, because the seam
    declares `measures` as a flag and the two must not be able to disagree: a
    reader that answers `measure` on a tree it cannot measure is a crash on a
    keystroke, and a flag that is false on a reader that could is a gutter nobody
    ever sees. The mount picks one, once, from what is actually on disk.
    """

    def measure(self, text: str, box: str) -> panels.TextPreview:
        """Dialogue-in-progress against the box it lands in, in tiles.

        Fixed-width tiles, which is why this exists at all: the family dialogue
        path is `PlaceString`, one tile per glyph, so the count is exact rather
        than the pixel guess a proportional font would need. What has no answer
        here is the *pixel* width of polished's menu VWF, and nothing on the
        dialogue path asks for it.
        """
        return measures.measure_lines(self.root, metrics.load(self.root), text)


# --------------------------------------------------------------------------- #
# the catalog files, each parsed once                                         #
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Attr:
    const: str
    border: str
    connections: tuple[tuple[str, str, int], ...]   # direction, target, offset


@dataclass(frozen=True)
class Dims:
    group: int
    map_id: int
    width: int
    height: int


@dataclass(frozen=True)
class _Style:
    tileset: str
    environment: str
    landmark: str
    music: str
    phone: str
    palette: str
    fishgroup: str


@lru_cache(maxsize=None)
def attrs(root: Path) -> dict[str, _Attr]:
    out: dict[str, _Attr] = {}
    label, const, border = "", "", ""
    conns: list[tuple[str, str, int]] = []

    def flush() -> None:
        if label:
            out[label] = Attr(const, border, tuple(conns))

    for raw in lines(root / "data/maps/attributes.asm"):
        if m := _ATTR.match(raw):
            flush()
            label, const, border = m.group(1), m.group(2), m.group(3)
            conns = []
        elif m := _CONN.match(raw):
            conns.append((m.group(1), m.group(3), int(m.group(4))))
    flush()
    return out


@lru_cache(maxsize=None)
def label_of(root: Path) -> dict[str, str]:
    return {a.const: label for label, a in attrs(root).items()}


@lru_cache(maxsize=None)
def dims(root: Path) -> dict[str, _Dims]:
    out: dict[str, _Dims] = {}
    group = map_id = 0
    for raw in lines(root / "constants/map_constants.asm"):
        if _GROUP.match(raw):
            group += 1
            map_id = 0
        elif m := _MAP_CONST.match(raw):
            map_id += 1
            out[m.group(1)] = Dims(group, map_id,
                                    int(m.group(2)), int(m.group(3)))
    return out


@lru_cache(maxsize=None)
def _styles(root: Path) -> dict[str, _Style]:
    out: dict[str, _Style] = {}
    for raw in lines(root / "data/maps/maps.asm"):
        if m := _MAP.match(raw):
            args = [a.strip() for a in m.group(2).split(";")[0].split(",")]
            if len(args) >= 7:
                out[m.group(1)] = _Style(*args[:7])
    return out


@lru_cache(maxsize=None)
def _blk(root: Path) -> dict[str, str]:
    """label -> the .blk path its `INCBIN` names. Several labels may stack on
    one INCBIN — maps that share a shape — so pending labels drain together."""
    out: dict[str, str] = {}
    pending: list[str] = []
    for raw in lines(root / "data/maps/blocks.asm"):
        if m := _BLOCKS_LABEL.match(raw):
            pending.append(m.group(1))
        elif m := _INCBIN.search(raw):
            for label in pending:
                out[label] = m.group(1)
            pending = []
    return out


@lru_cache(maxsize=None)
def _wild_file(root: Path, rel: str) -> dict[str, list[panels.WildMon]]:
    """Every map's slots in one wild file, in written order. The rates line
    also matches `db N, M` shapes, so it is skipped by its `percent` word."""
    out: dict[str, list[panels.WildMon]] = {}
    current: list[panels.WildMon] | None = None
    for raw in lines(root / rel):
        s = raw.split(";")[0]
        if "wildmons" in s:
            if s.strip().startswith("def_"):
                current = out.setdefault(s.strip().split()[-1], [])
            else:
                current = None
        elif current is not None and "percent" not in s:
            if m := _WILDMON.match(s):
                current.append(panels.WildMon(int(m.group(1)), m.group(2)))
    return out


@lru_cache(maxsize=None)
def _roof_table(root: Path) -> tuple[list[str], list[str], list[str]]:
    """(ROOF_* names in ordinal order, MapGroupRoofs values by group,
    roof tile files in ordinal order)."""
    names: list[str] = []
    values: list[str] = []
    files: list[str] = []
    in_groups = False
    for raw in lines(root / "data/maps/roofs.asm"):
        if m := _ROOF_CONST.match(raw):
            names.append(m.group(1))
        elif raw.startswith("MapGroupRoofs"):
            in_groups = True
        elif raw.startswith("Roofs"):
            in_groups = False
        elif in_groups and (m := _DB.match(raw.split(";")[0])):
            values.append(m.group(1))
        elif not in_groups and (m := _INCBIN.search(raw)):
            files.append(m.group(1))
    return names, values, files


@lru_cache(maxsize=None)
def _roof_pal(root: Path) -> list[tuple[str, ...]]:
    """One (morn/day ×2, nite ×2) tuple per map group, in file order —
    `roofs.pal` is indexed by *group*, unlike the tiles."""
    colors: list[str] = []
    for raw in lines(root / "gfx/tilesets/roofs.pal"):
        if m := _RGB.match(raw):
            vals = [int(v) for v in m.group(1).replace(",", " ").split()]
            colors += ["#{:02x}{:02x}{:02x}".format(*(v * 255 // 31 for v in vals[i:i + 3]))
                       for i in (0, 3) if len(vals) >= i + 3]
    return [tuple(colors[i:i + 4]) for i in range(0, len(colors) - 3, 4)]


def _roof_colors(root: Path, group: int) -> tuple[str, str, str, str] | None:
    pals = _roof_pal(root)
    return pals[group] if group < len(pals) else None


def lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
