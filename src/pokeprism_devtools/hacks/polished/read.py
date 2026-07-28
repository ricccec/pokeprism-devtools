"""Polished's read adapter: what the fork changed, and only that.

The catalog grammar polished kept — `map_attributes`, `connection`,
`map_const` — is read by vanilla's parsers, imported. What is parsed here is
what polished rewrote: the eight-arg `map` macro (a location sign where
vanilla's landmark prefix was, no fish group), `_BlockData` labels over
compressed `.ablk.lzp` INCBINs whose *plain* sibling holds the bytes,
`wildmon` slots that may carry a form, roof constants that moved to
`constants/tileset_constants.asm`, and a `roofs.pal` that packs morn/day,
nite and eve onto one line per group.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from ...studio import panels
from ...studio.actions import ActionError
from ..vanilla import measures
from ..vanilla.read import attrs, dims, label_of, lines
from . import events, metrics, swatches

_MAP = re.compile(r"^\s*map\s+(\w+)\s*,\s*(.+)")
_BLOCKS_LABEL = re.compile(r"^(\w+)_BlockData:")
_INCBIN = re.compile(r'INCBIN\s+"([^"]+)"')
_DB = re.compile(r"^\s*db\s+(\S+)")
_ROOF_CONST = re.compile(r"^\s*const\s+(ROOF_\w+)")
_ROOF_GFX = re.compile(r'RoofGFX::?\s+INCBIN\s+"([^"]+)"')
_RGB = re.compile(r"^\s*RGB\s+([\d, ]+)")
_WILDMON = re.compile(r"^\s*wildmon\s+(\d+)\s*,\s*(\w+)\s*,?\s*(\w+)?")


class Reader:
    """One polishedcrystal tree, answering the studio's questions in the
    seam's words. Like vanilla it sketches — the new-map form draws before it
    writes — and like vanilla it keeps `measure` in a subclass the mount builds
    only when the text engine is there to measure against."""

    def __init__(self, root: Path) -> None:
        self.root = root

    # -- the catalog --------------------------------------------------------- #
    def maps(self) -> dict[str, str]:
        return {label: a.const for label, a in attrs(self.root).items()}

    def parses(self, const: str) -> bool:
        label = label_of(self.root).get(const)
        return label is not None and (self.root / f"maps/{label}.asm").exists()

    def connections(self, const: str) -> list[panels.Link]:
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
            phone=m.phone if m else "0",
            border_block=a.border if a else "—")

    def geometry(self, label: str) -> panels.Blocks:
        """The shape. The build INCBINs `maps/X.ablk.lzp`; the tracked,
        editable bytes are the plain `maps/X.ablk` beside it, one byte per
        block like any `.blk` — that sibling is what is read."""
        a = attrs(self.root).get(label)
        d = dims(self.root).get(a.const) if a else None
        rel = _blk(self.root).get(label)
        if d is None or rel is None:
            raise panels.Unreadable(
                f"{label} is not in constants/map_constants.asm and "
                "data/maps/blocks.asm both — it has no declared shape.")
        path = self.root / rel.removesuffix(".lzp")
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
        """The new-map form's grid, in this tree's colours.

        The same fork as `geometry` and for the same reason: the shape is
        shared family mechanics, the swatches come from polished's own
        metatile attributes. See vanilla's `sketch` for why an unfinished
        tileset draws uncoloured while a wrong one is refused.
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
        """Same shape as the rest of the family — grass 7×3, water 3 — but a
        slot is `wildmon level, SPECIES[, FORM]`: the form crosses when it is
        written, and the column above the seam exists exactly then."""
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
        d = dims(self.root).get(const)
        if d is None:
            return None
        names, values = _roof_table(self.root)
        files = _roof_files(self.root)
        if d.group >= len(values):
            return panels.Roof(group=d.group, past_end=True,
                               entries=len(values),
                               colors=_roof_colors(self.root, d.group))
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
    """The same reader, on a tree whose n-gram widths can be read.

    Vanilla's `MeasuringReader` with polished's `Metrics` handed in — the fork is
    the one argument, exactly as it is for the linter. The measuring itself, the
    box and the tile arithmetic are shared, because polished's map dialogue draws
    through the same fixed-width path vanilla's does. Its menu VWF is somewhere
    else entirely and no line measured here goes through it.
    """

    def measure(self, text: str, box: str) -> panels.TextPreview:
        return measures.measure_lines(self.root, metrics.load(self.root), text)


# --------------------------------------------------------------------------- #
# what polished rewrote, each file parsed once                                #
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class _Style:
    """The eight-arg `map` macro: a SIGN_* slot vanilla doesn't have, a bare
    landmark, and no fish group anywhere — so `Attributes.fishgroup` keeps
    its dash and the row above the seam says so honestly."""
    tileset: str
    environment: str
    sign: str
    landmark: str
    music: str
    phone: str
    palette: str


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
    out: dict[str, list[panels.WildMon]] = {}
    current: list[panels.WildMon] | None = None
    for raw in lines(root / rel):
        s = raw.split(";")[0]
        if "wildmons" in s and s.strip().startswith(("def_", "end_")):
            current = (out.setdefault(s.strip().split()[-1], [])
                       if s.strip().startswith("def_") else None)
        elif current is not None and (m := _WILDMON.match(s)):
            current.append(panels.WildMon(int(m.group(1)), m.group(2),
                                          m.group(3) or ""))
    return out


@lru_cache(maxsize=None)
def _roof_table(root: Path) -> tuple[list[str], list[str]]:
    """(ROOF_* names in ordinal order, MapGroupRoofs values by group). The
    constants live with the tilesets now, the table kept its file."""
    names = [m.group(1)
             for raw in lines(root / "constants/tileset_constants.asm")
             if (m := _ROOF_CONST.match(raw))]
    values: list[str] = []
    in_groups = False
    for raw in lines(root / "data/maps/roofs.asm"):
        if raw.startswith("MapGroupRoofs"):
            in_groups = True
        elif in_groups and not raw.startswith(("\t", " ", ";")) and raw.strip():
            break
        elif in_groups and (m := _DB.match(raw.split(";")[0])):
            values.append(m.group(1))
    return names, values


@lru_cache(maxsize=None)
def _roof_files(root: Path) -> list[str]:
    """Roof tile files in ROOF_* order, from `gfx/misc.asm`'s `*RoofGFX`
    INCBINs — polished compresses them, but the file it names is the file."""
    return [m.group(1) for raw in lines(root / "gfx/misc.asm")
            if (m := _ROOF_GFX.search(raw))]


@lru_cache(maxsize=None)
def _roof_pal(root: Path) -> list[tuple[str, ...]]:
    """One (morn/day ×2, nite ×2) tuple per map group. Polished writes all
    three times on one line — morn/day, nite, eve, two colors each — and the
    seam's record wants the first four."""
    out: list[tuple[str, ...]] = []
    for raw in lines(root / "gfx/tilesets/roofs.pal"):
        if m := _RGB.match(raw):
            vals = [int(v) for v in m.group(1).replace(",", " ").split()]
            if len(vals) >= 12:
                out.append(tuple(
                    "#{:02x}{:02x}{:02x}".format(*(v * 255 // 31
                                                   for v in vals[i:i + 3]))
                    for i in (0, 3, 6, 9)))
    return out


def _roof_colors(root: Path, group: int) -> tuple[str, str, str, str] | None:
    pals = _roof_pal(root)
    return pals[group] if group < len(pals) else None
