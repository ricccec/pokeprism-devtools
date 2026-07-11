"""A map's block grid, read from source. No ROM.

:mod:`.blockdata` reads the same grid out of a built ROM, and for a map that is
already in the game that is fine. But the map you are *authoring* is precisely
the one not yet in the ROM: you draw it in polished-map, and until `make` has run
it exists only as a `.blk` on disk and four lines of asm. A grid that needs a ROM
can never show you the map you just made.

It doesn't need one. `maps/blk/*.ablk` is **uncompressed** — exactly `height ×
width` bytes, one per block, row-major, tracked in git. The `.ablk.lz` that
`maps/blockdata.asm` INCBINs is produced from it by the Makefile's generic
`%.lz: %` rule. So everything the ROM knows about a map's shape is already in the
tree, spread across four files:

    maps/second_map_headers.asm         its const, and its border block
    maps/map_headers.asm                its tileset and permission, by name
    constants/map_dimension_constants.asm   its height and width, in blocks
    maps/blockdata.asm                  which .ablk file is *actually* its own

That last one matters: consecutive `_BlockData:` labels share the single INCBIN
beneath them, so a dozen pokecenters are one file. Following the label rather
than guessing `maps/blk/<Label>.ablk` is the difference between reading the map
and reading a map that merely has a similar name.
"""

from __future__ import annotations

from pathlib import Path

from . import constants, lz, maps as maps_mod, mapsource
from .blockdata import BlockData

_DIMENSIONS = "constants/map_dimension_constants.asm"
_TILESETS = "constants/tilemap_constants.asm"
_PERMISSIONS = "constants/map_constants.asm"


class BlockSourceError(RuntimeError):
    pass


def load(root: Path, label: str) -> BlockData:
    """The block grid for one map, by its CamelCase label."""
    sec = mapsource.secondary_header(root, label)
    if sec is None:
        raise BlockSourceError(
            f"no `map_header_2 {label}, ...` in maps/second_map_headers.asm — "
            "is the label spelled exactly, and the map wired in?")

    dims = {m.name: m for m in maps_mod.parse_maps(root / _DIMENSIONS)}
    md = dims.get(sec.const)
    if md is None:
        raise BlockSourceError(f"{sec.const} has no `mapgroup` line in {_DIMENSIONS}")

    prim = mapsource.primary_header(root, label)
    if prim is None:
        # pokeprism has one of these: MoundB2FDark has a secondary header and its
        # own .ablk, but no `map_header` — and its const collides with MoundB2F's,
        # so it isn't a map in the ROM at all. Drawing it anyway would mean
        # picking a tileset, and a map drawn with the wrong tileset looks
        # perfectly fine and is perfectly wrong. Refuse instead.
        raise BlockSourceError(
            f"no `map_header {label}, ...` in maps/map_headers.asm — {label} has "
            "blocks and a secondary header but was never wired into the game, so "
            "there is no tileset to draw it with")

    blocks = _blocks(root, label, md.height, md.width)

    return BlockData(
        name=label,
        group=md.group,
        map_id=md.map_id,
        width=md.width,
        height=md.height,
        border_block=_number(sec.border_block),
        blocks=blocks,
        tileset_id=_lookup(root, _TILESETS, prim.tileset),
        permission=_lookup(root, _PERMISSIONS, prim.permission),
    )


def sketch(root: Path, blk: Path, height: int, width: int,
           tileset: str, permission: str) -> BlockData:
    """A map that is not in the game yet: the one you are about to add.

    :func:`load` follows four asm files to find out what a map is made of. A map
    being *authored* is in none of them — it is a `.blk` you drew somewhere else
    and a form you have half filled in. So everything comes from the caller, and
    the two things that would otherwise silently produce a wrong picture are
    checked rather than guessed: `read_blk` refuses a file with fewer blocks than
    `height × width`, and `_lookup` refuses a tileset that isn't a real constant.

    That is what turns the size check into a picture. A `.blk` of the wrong shape
    doesn't say "expected 675 bytes"; it draws the map skewed, which is what a
    wrong `height` actually looks like, and you fix the number you got wrong.
    """
    return BlockData(
        name=blk.stem,
        group=0, map_id=0,               # not in the game yet; it has neither
        width=width,
        height=height,
        border_block=0,
        blocks=read_blk(blk, height, width),
        tileset_id=_lookup(root, _TILESETS, tileset),
        permission=_lookup(root, _PERMISSIONS, permission),
    )


def blk_file(root: Path, label: str) -> Path | None:
    """The `.ablk` this map's `_BlockData:` label actually points at."""
    target = mapsource.blockdata_labels(root).get(label)
    if target is None:
        return None
    return root / (target[:-3] if target.endswith(".lz") else target)


def read_blk(path: Path, height: int, width: int) -> bytes:
    """`height × width` blocks from an `.ablk`, or from its `.lz` if that's all
    there is.

    A file with **more** bytes than the map has blocks is fine and there are six
    of them in pokeprism: `ReadMapBlocks` copies exactly `height × width` and
    ignores the rest, so the trailing bytes are dead weight, not a bug.

    A file with **fewer** is a bug — the engine reads past the end of the data
    into whatever the linker put next, which is why it renders as a band of
    garbage along the bottom rather than as an error. Say so.
    """
    need = height * width
    if path.exists():
        data = path.read_bytes()
    elif (packed := path.parent / (path.name + ".lz")).exists():
        data, _ = lz.decompress(packed.read_bytes())
    else:
        raise BlockSourceError(f"{path} does not exist, and neither does its .lz")

    if len(data) < need:
        raise BlockSourceError(
            f"{path.name} holds {len(data)} blocks but the map is {height}×{width} "
            f"= {need}. The game will read {need - len(data)} bytes of whatever "
            f"follows it in the ROM.")
    return data[:need]


def _blocks(root: Path, label: str, height: int, width: int) -> bytes:
    path = blk_file(root, label)
    if path is None:
        raise BlockSourceError(
            f"no `{label}_BlockData:` in maps/blockdata.asm — the map has a header "
            "but no blocks are wired to it")
    return read_blk(path, height, width)


def _lookup(root: Path, rel: str, name: str) -> int:
    """A named constant's value. Never a guess: falling back to 0 here means
    `TILESET_FOREST` typo'd as `TILESET_FORREST` silently draws the map in
    tileset 0's colours, which is a picture of a map that does not exist."""
    for c in constants.parse_constants(root / rel):
        if c.name == name:
            return c.value
    raise BlockSourceError(f"{name} is not a constant in {rel}")


def _number(written: str) -> int:
    """`$3e`, `62`, `0` — how a border block is written in the header."""
    try:
        return int(written.replace("$", "0x"), 0)
    except ValueError:
        return 0
