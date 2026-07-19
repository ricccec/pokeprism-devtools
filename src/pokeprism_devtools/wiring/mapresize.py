"""Growing or shrinking a map from an edge.

Three things describe a map's shape, in three different files, and they must
move together or the map corrupts:

    constants/map_dimension_constants.asm   `mapgroup CONST, H, W`
    maps/blk/<Label>.ablk                   the block grid: H*W bytes, row-major
    maps/<Label>.asm                        every warp/signpost/trigger/person,
                                            each one a coordinate *into* that grid

A block is 2x2 coordinate tiles (`shared/coords.TILES_PER_BLOCK`), and growing or
shrinking at the **top or left** moves the grid's origin — so every coordinate on
the map has to shift with it, by 2 tiles per block. Growing or shrinking at the
**bottom or right** leaves the origin exactly where it was, and nothing on the
map needs to move at all.

One entry point, taking only primitives — no `Action`, no `Session`, nothing
from `studio/` — so a future `prism-resize` CLI is `argparse` ->
:func:`resize` -> `apply_edits(root, change.changes, dry_run=...)`, the same
shape as `prism-newmap`.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..hacks.prism import blocksrc, maps as maps_mod, mapsource
from ..shared import coords
from ..hacks.prism import eventheader as eh
from ..shared.edits import Edit
from .objedit import (Change, EditError, MapEdit, S_X, S_Y, T_X, T_Y, W_X, W_Y,
                      X, Y, spliced)

EDGES = ("top", "bottom", "left", "right")
MODES = ("grow", "shrink")

DIMENSIONS = "constants/map_dimension_constants.asm"

#: Where y/x sit in each list's entry, per `wiring/objedit.py`'s own constants —
#: the same ones `edit_npc`/`edit_signpost`/`edit_trigger` already splice.
_MOVES: dict[eh.ListKind, tuple[int, int]] = {
    eh.ListKind.WARPS: (W_Y, W_X),
    eh.ListKind.COORD_EVENTS: (T_Y, T_X),
    eh.ListKind.BG_EVENTS: (S_Y, S_X),
    eh.ListKind.OBJECT_EVENTS: (Y, X),
}

_MAPGROUP_RE_TMPL = (
    r"^(?P<head>\s*mapgroup\s+{const}\s*,\s*)"
    r"(?P<h>-?\d+)\s*,\s*(?P<w>-?\d+)(?P<tail>.*)$"
)


def resize(root: Path, map_const: str, edge: str, mode: str, blocks: int,
          fill: str | None = None) -> Change:
    """Grow or shrink `map_const` by `blocks` blocks, from `edge`.

    Refuses (writing nothing) if the map's `.ablk` is shared with another map's
    `_BlockData:` label, if the shrink would take the map below one block on
    that axis, or if anything on the map is standing in the strip being removed.
    """
    if edge not in EDGES:
        raise EditError(f"edge must be one of {', '.join(EDGES)}, not {edge!r}")
    if mode not in MODES:
        raise EditError(f"mode must be one of {', '.join(MODES)}, not {mode!r}")
    if blocks < 1:
        raise EditError("grow/shrink by at least one block")

    label = _label_for(root, map_const)
    secondary = mapsource.secondary_header(root, label)
    if secondary is None:
        raise EditError(f"{label} has no map_header_2 in maps/second_map_headers.asm")
    mapdef = _mapdef_for(root, map_const)
    height, width = mapdef.height, mapdef.width

    blk_path = _blk_path(root, label)
    grid = _read_grid(blk_path, height, width)

    axis = height if edge in ("top", "bottom") else width
    if mode == "shrink" and blocks >= axis:
        raise EditError(
            f"{label} is only {axis} blocks on that axis — shrinking by "
            f"{blocks} would leave nothing")
    if mode == "shrink":
        orphans = _orphans(root, label, edge, blocks, height, width)
        if orphans:
            raise EditError(
                f"shrinking {label}'s {edge} by {blocks} block(s) would remove: "
                f"{', '.join(orphans)} — delete them first")

    if edge in ("top", "bottom"):
        new_height = height + blocks if mode == "grow" else height - blocks
        new_width = width
    else:
        new_height = height
        new_width = width + blocks if mode == "grow" else width - blocks

    fill_block = (_fill_value(fill, secondary.border_block) if mode == "grow"
                 else 0)
    new_grid = _reshape(grid, height, width, edge, mode, blocks, fill_block)

    edits = [
        _rewrite_dims(root, map_const, new_height, new_width),
        Edit(_rel(root, blk_path), True,
             f"{new_height}x{new_width} blocks", f"{len(new_grid)} bytes",
             data=new_grid),
    ]
    notes: list[str] = []

    dy = dx = 0
    if edge == "top":
        dy = blocks * coords.TILES_PER_BLOCK * (1 if mode == "grow" else -1)
    elif edge == "left":
        dx = blocks * coords.TILES_PER_BLOCK * (1 if mode == "grow" else -1)
    if dy or dx:
        coord_edit, moved = _shift_coords(root, map_const, dy, dx)
        if coord_edit.changed:
            edits.append(coord_edit)
        if moved:
            amount = abs(dy or dx)
            direction = ("down" if dy > 0 else "up" if dy < 0 else
                        "right" if dx > 0 else "left")
            notes.append(f"shifted {moved} object(s) {amount} tiles {direction}")

    if secondary.connections:
        notes.append(
            f"{len(secondary.connections)} connection(s) may need review — the "
            f"conn-align linter will flag any that broke.")

    summary = (f"{label}: {mode} {edge} by {blocks} block(s) "
              f"({height}x{width} -> {new_height}x{new_width})")
    return Change(summary, edits, notes)


# --------------------------------------------------------------------------- #
# resolving the map                                                           #
# --------------------------------------------------------------------------- #

def _label_for(root: Path, map_const: str) -> str:
    label = {c: l for l, c in mapsource.header_pairs(root)}.get(map_const)
    if label is None:
        raise EditError(f"{map_const} has no map_header_2 — wire the map first")
    return label


def _mapdef_for(root: Path, map_const: str) -> maps_mod.MapDef:
    for d in maps_mod.parse_maps(root / DIMENSIONS):
        if d.name == map_const:
            return d
    raise EditError(f"{map_const} has no `mapgroup` line in {DIMENSIONS}")


def _blk_path(root: Path, label: str) -> Path:
    labels = mapsource.blockdata_labels(root)
    target = labels.get(label)
    if target is None:
        raise EditError(
            f"no `{label}_BlockData:` in maps/blockdata.asm — the map has no "
            f"blocks wired to it")
    aliases = sorted(l for l, t in labels.items() if t == target and l != label)
    if aliases:
        raise EditError(
            f"{label}'s block data is shared with {', '.join(aliases)} — "
            f"resizing it would corrupt every map that aliases it, since their "
            f"dimension constants don't change with it")
    return root / (target[:-3] if target.endswith(".lz") else target)


def _read_grid(blk_path: Path, height: int, width: int) -> bytes:
    try:
        return blocksrc.read_blk(blk_path, height, width)
    except blocksrc.BlockSourceError as exc:
        raise EditError(str(exc)) from exc


def _rel(root: Path, path: Path) -> str:
    return str(path.relative_to(root))


# --------------------------------------------------------------------------- #
# refusals                                                                    #
# --------------------------------------------------------------------------- #

def _orphans(root: Path, label: str, edge: str, blocks: int,
            height: int, width: int) -> list[str]:
    """Everything standing in the tile-strip a shrink would remove."""
    path = root / "maps" / f"{label}.asm"
    try:
        header = eh.parse_map(path)
    except eh.UnparseableHeader as exc:
        raise EditError(str(exc)) from exc

    lo_y, hi_y = 0, 2 * height
    lo_x, hi_x = 0, 2 * width
    if edge == "top":
        hi_y = 2 * blocks
    elif edge == "bottom":
        lo_y = 2 * (height - blocks)
    elif edge == "left":
        hi_x = 2 * blocks
    else:
        lo_x = 2 * (width - blocks)

    on_the_y_axis = edge in ("top", "bottom")
    found = []
    for kind in eh.LIST_ORDER:
        for entry in header.list_of(kind).entries:
            y, x = entry.coords
            if y is None or x is None:
                continue
            in_strip = lo_y <= y < hi_y if on_the_y_axis else lo_x <= x < hi_x
            if in_strip:
                found.append(f"{entry.macro} at ({y}, {x})")
    return found


def _fill_value(fill: str | None, border_block: str) -> int:
    raw = (fill or "").strip()
    if raw:
        return _byte(raw, "fill block")
    return _byte(border_block, "border block")


def _byte(raw: str, what: str) -> int:
    try:
        n = int(raw.replace("$", "0x"), 0)
    except ValueError:
        raise EditError(
            f"{what} must be a plain block number, e.g. 62 or $3e — not {raw!r}"
        ) from None
    if not 0 <= n <= 255:
        raise EditError(f"a block is one byte — {n} does not fit ({what})")
    return n


# --------------------------------------------------------------------------- #
# the .ablk                                                                   #
# --------------------------------------------------------------------------- #

def _reshape(grid: bytes, height: int, width: int, edge: str, mode: str,
            blocks: int, fill: int) -> bytes:
    rows = [grid[r * width:(r + 1) * width] for r in range(height)]

    if edge in ("top", "bottom"):
        if mode == "grow":
            new_row = bytes([fill]) * width
            new_rows = ([new_row] * blocks + rows if edge == "top"
                       else rows + [new_row] * blocks)
        else:
            new_rows = rows[blocks:] if edge == "top" else rows[:height - blocks]
        return b"".join(new_rows)

    if mode == "grow":
        pad = bytes([fill]) * blocks
        new_rows = ([pad + row for row in rows] if edge == "left"
                   else [row + pad for row in rows])
    else:
        new_rows = ([row[blocks:] for row in rows] if edge == "left"
                   else [row[:width - blocks] for row in rows])
    return b"".join(new_rows)


# --------------------------------------------------------------------------- #
# the dimension constant                                                      #
# --------------------------------------------------------------------------- #

def _rewrite_dims(root: Path, map_const: str, new_height: int, new_width: int) -> Edit:
    path = root / DIMENSIONS
    if not path.exists():
        raise EditError(f"{DIMENSIONS} is missing")
    original = path.read_text()
    lines = original.split("\n")

    rx = re.compile(_MAPGROUP_RE_TMPL.format(const=re.escape(map_const)))
    for i, line in enumerate(lines):
        m = rx.match(line)
        if not m:
            continue
        rebuilt = f"{m.group('head')}{new_height}, {new_width}{m.group('tail')}"
        if rebuilt == line:
            return Edit(DIMENSIONS, False, "unchanged", "", base=original)
        lines[i] = rebuilt
        return Edit(DIMENSIONS, True, f"{map_const}: {new_height}x{new_width}",
                   "\n".join(lines), base=original)
    raise EditError(f"{DIMENSIONS} has no `mapgroup` line for {map_const}")


# --------------------------------------------------------------------------- #
# the coordinates (top/left only)                                            #
# --------------------------------------------------------------------------- #

def _shift_coords(root: Path, map_const: str, dy: int, dx: int) -> tuple[Edit, int]:
    """Move every warp/signpost/trigger/person by (dy, dx). Returns the file
    edit and how many entries actually moved."""
    ctx = MapEdit(root, map_const)
    moved = 0
    for kind in eh.LIST_ORDER:
        yi, xi = _MOVES[kind]
        for i in range(len(ctx.header.list_of(kind).entries)):
            entry = ctx.entry(kind, i)
            y, x = entry.int_arg(yi), entry.int_arg(xi)
            if y is None or x is None:
                continue
            args = spliced(entry, {yi: y + dy, xi: x + dx})
            if args != entry.args:
                ctx.replace_entry(kind, i, args)
                moved += 1
    change = ctx.done("", "")
    return change.edits[0], moved
