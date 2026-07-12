"""Everything about one map, read off disk once, in a form the view can draw.

Split out of :mod:`.session` when that module grew past the size where one file
is still one idea: the session is the *model* — it owns the linter, the history
and the writing — and this is the reading. Nothing in here mutates anything, and
nothing in here takes a lock, which is what lets `Session.load` run it on a
thread while the UI stays alive.

A map's eight header facts are spread across five files, and each of them
answers to a different name for the same map: `maps/<Label>.asm` and
`maps/map_headers.asm` know it as a **label**, `constants/map_dimension_
constants.asm` and every warp know it as a **const**, and `contents/romx.link`
knows only the three **section names** its blobs were given. Reassembling one map
out of that is this module's whole job, and it is why the view is not allowed to
try.

A map whose event header doesn't parse still comes back **with its geometry**,
and the parse error where its objects would have been. Hiding a broken map from
the person looking for the break is the worst thing this could do.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..maplint.context import LintContext
from ..shared import (blocksrc, coords, dialogue, eventheader, maps as maps_mod,
                      mapsource, roofs, swatches, textbox, wilddata)
from . import panels
from .model import MapData, MapGeometry, Measured, TextPreview, TextRef

#: A map's three relocatable blobs, and the line that marks each one. Only these
#: three ever get a bank: the primary `map_header` is a positional line inside
#: `MapGroupN` and has no section of its own, which is why the new-map form's
#: Bank field has never mentioned it.
#:
#: The section a blob lives in is **found, not assumed**. A new map gets a
#: section of its own (`Map block data <Label>`), but the maps already in the
#: game mostly sit in shared ones — OxalisCity's blocks are in "Map block data 4"
#: along with a dozen others. Guessing the per-map name would report every
#: shipped map as unpinned, which is both wrong and exactly backwards.
BLOBS = ("block data", "script", "secondary header")


def read_map(root: Path, ctx: LintContext, label: str,
             boxes: dict[str, textbox.Box]) -> MapData:
    """One map, whole. Four files at worst, and no state."""
    const = ctx.label_to_const.get(label, label)
    tabs: list[panels.Tab] = []
    error = None

    header = None
    try:
        header = eventheader.parse_map(root / f"maps/{label}.asm")
    except (eventheader.UnparseableHeader, FileNotFoundError) as exc:
        error = str(exc)

    tabs.append(panels.Tab("Attributes",
                           panels.attributes(_attributes(root, label, const))))

    if header is not None:
        says = _says(root, label, boxes)
        tabs += [
            panels.Tab("NPCs", panels.npcs(header, says), adds="NPC"),
            panels.Tab("Trainers", panels.trainers(header), adds="trainer"),
            panels.Tab("Pickups", panels.pickups(header), adds="pickup"),
            panels.Tab("Warps", panels.warps(header), adds="warp"),
            panels.Tab("Signposts", panels.signposts(header), adds="signpost"),
            panels.Tab("Triggers", panels.triggers(header), adds="trigger"),
        ]
    else:
        # The map has a shape but its header doesn't parse. Say so where the
        # objects would have been, rather than showing empty tables that read as
        # "this map has nothing on it".
        tabs.append(panels.Tab(
            "Unreadable", (["why"], [panels.Row([error or ""])]),
            note="this map's event header does not parse, so nothing on it can "
                 "be listed or edited. Its shape is still real."))

    tabs.append(panels.Tab(
        "Connections",
        panels.connections(ctx.connections_by_map.get(const, [])),
        adds="connection"))

    group = _group(root, const)
    if group is not None:
        tabs.append(panels.Tab("Roof", panels.roof(roofs.for_group(root, group)),
                               note=panels.ROOF_IS_READ_ONLY))
    tabs.append(panels.Tab("Wild", panels.wild(_wild(root, const)),
                           note=panels.WILD_IS_READ_ONLY))

    try:
        bd = blocksrc.load(root, label)
    except blocksrc.BlockSourceError as exc:
        return MapData(label, const, None, str(exc), tabs)

    geometry = MapGeometry(
        label=label, blocks=bd.blocks, height=bd.height, width=bd.width,
        swatches=swatches.for_map(root, bd.tileset_id, bd.permission),
        marks=coords.markers(header) if header else {},
    )
    return MapData(label, const, geometry, error, tabs)


# --------------------------------------------------------------------------- #
# the pieces                                                                  #
# --------------------------------------------------------------------------- #

def _says(root: Path, label: str, boxes: dict[str, textbox.Box]) -> dict[str, str]:
    """`text label -> its first words`, so the NPC table can show what an NPC
    actually says instead of the name of the block that says it.

    A map with a script this can't parse is a map whose NPCs simply have no
    preview — not a map that fails to open.
    """
    path = root / f"maps/{label}.asm"
    if not path.exists():
        return {}
    try:
        blocks = dialogue.parse(root, path)
    except Exception:                                  # noqa: BLE001 - see above
        return {}
    out = {}
    for b in blocks:
        first = next((ln for ln in dialogue.plain(b).split("\n") if ln.strip()), "")
        out[b.label] = first[:40]
    return out


def _def(root: Path, const: str) -> maps_mod.MapDef | None:
    dims = root / "constants/map_dimension_constants.asm"
    if not dims.exists():
        return None
    return next((d for d in maps_mod.parse_maps(dims) if d.name == const), None)


def _group(root: Path, const: str) -> int | None:
    d = _def(root, const)
    return d.group if d else None


def _attributes(root: Path, label: str, const: str) -> panels.Attributes:
    """A map's header, reassembled out of the five files that hold a piece of it.

    Every lookup here can come back empty, and none of them is fatal: a map
    part-way through being wired is a map you especially want to be able to look
    at. What you get for a missing piece is a dash, not an exception.
    """
    d = _def(root, const)
    p = mapsource.primary_header(root, label)
    s = mapsource.secondary_header(root, label)

    return panels.Attributes(
        label=label, const=const,
        group=d.group if d else 0, map_id=d.map_id if d else 0,
        height=d.height if d else 0, width=d.width if d else 0,
        blk=mapsource.blk_path(root, label) or "—",
        tileset=p.tileset if p else "—",
        permission=p.permission if p else "—",
        landmark=p.landmark if p else "—",
        music=p.music if p else "—",
        palette=p.palette if p else "—",
        fishgroup=p.fishgroup if p else "—",
        phone=str(p.phone) if p else "0",
        border_block=s.border_block if s else "—",
        banks=_banks(root, label),
    )


def _banks(root: Path, label: str) -> dict[str, str]:
    """Which SECTION each of the map's three blobs sits in, and its bank.

    The section is located by *finding the line and looking up* — see
    :data:`BLOBS`. A blob whose section isn't pinned in `contents/romx.link` is
    floating, which is a real and normal state (rgblink places it), not a fault.
    """
    pinned = mapsource.section_banks(root)
    script = mapsource.script_path(root, label)
    finders = {
        "block data": ("maps/blockdata.asm",
                       lambda ln: ln.strip() == f"{label}_BlockData:"),
        "script": ("maps/map_scripts.asm",
                   lambda ln: bool(script) and ln.strip() == f'INCLUDE "{script}"'),
        "secondary header": ("maps/second_map_headers.asm",
                             lambda ln: _HEADER_2(label).match(ln) is not None),
    }

    out: dict[str, str] = {}
    for blob, (rel, matches) in finders.items():
        path = root / rel
        section = mapsource.enclosing_section(path, matches) if path.exists() else None
        if section is None:
            out[blob] = "not wired — no such line in " + rel
        elif (bank := pinned.get(section)) is not None:
            out[blob] = f"${bank:02X}   in “{section}”"
        else:
            out[blob] = f"floating — “{section}” is not pinned to a bank"
    return out


def _HEADER_2(label: str) -> re.Pattern[str]:
    return re.compile(rf"^\s*map_header_2\s+{re.escape(label)}\s*,")


def _wild(root: Path, const: str) -> dict[str, wilddata.WildBlock]:
    """The map's encounters. A map with none is the common case, not an error —
    most maps are indoors."""
    found: dict[str, wilddata.WildBlock] = {}
    for kind in (wilddata.GRASS, wilddata.WATER):
        try:
            table = wilddata.table_for(root, const, kind)
        except wilddata.WildDataError:
            continue
        for block in table.blocks:
            if block.map_const == const:
                found[kind] = block
    return found


# --------------------------------------------------------------------------- #
# the words                                                                   #
# --------------------------------------------------------------------------- #

def texts(root: Path, label: str, boxes: dict[str, textbox.Box]) -> list[TextRef]:
    """Every text block in one map, as prose you could hand to a person.

    The macros are deliberately not here. `plain` shows the words; `wiring/text.
    reword` puts the macros back from the block itself, positionally — so a `cont`
    that scrolls the box is still a `cont` after you fix a typo in it.
    """
    sign = boxes["sign"]
    return [
        TextRef(label=b.label, owner=b.owner, lineno=b.lineno,
                prose=dialogue.plain(b),
                box="sign" if b.box.name == sign.name else "speech")
        for b in dialogue.parse(root, root / f"maps/{label}.asm")
    ]


def measure(root: Path, ctx: LintContext, text: str,
            box: textbox.Box) -> TextPreview:
    """Dialogue-in-progress against the box it lands in.

    The same prose model the form submits: one line per screen line, a blank line
    starts a new box. Only *width* is checked, and that is not a shortcut — the
    third row of a box and every row after it are `cont`, which scrolls, so a
    speech can be any length. What it cannot be is wide.
    """
    return TextPreview(box.name, box.cols, [
        _measured(root, ctx, line, box.cols)
        for line in text.replace("\r\n", "\n").split("\n")
    ])


def _measured(root: Path, ctx: LintContext, line: str, cols: int) -> Measured:
    det, bnd, unb, unknown = ctx.textbox_metrics.tiles(root, line)
    return Measured(text=line, tiles=det, bounded=bnd, unbounded=unb,
                    unknown=unknown, over=max(0, det - cols),
                    over_at_worst=max(0, det + bnd - cols))
