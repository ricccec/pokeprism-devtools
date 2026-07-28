"""Read a polished map's block grid from the ROM and compute its `wScreenSave`.

Polished's map headers are not stock-family (a 7-byte primary with packed
nibbles and a bankless attributes pointer, a 10-byte secondary with `dba`
pointers), so `shared.overworld.blockdata`'s header walk cannot reach a map here.
It does not need to: the block-data label the build exports — `<Label>_BlockData`
— is in the `.sym`, so the grid is resolved by name the same way the save patcher
resolves every field, decompressed with polished's own `lzp` codec, and handed to
the *neutral* `compute_screen_save`, which is pure grid arithmetic and learns no
tree's ROM layout.

Stage 1 rebuilds only the interior window: no connected-neighbour overlay yet, so
a spawn at a map edge renders the border blocks (zeros) rather than the real
adjacent map — the same fallback the neutral core already takes for a neighbour it
cannot load. Loading neighbours (and the map's NPCs and sprites) is Stage 2.
"""

from __future__ import annotations

from ...shared.overworld import blockdata
from ...shared.symfile import SymFile
from . import lzp


def screen_save_bytes(rom: bytes, syms: SymFile, label: str,
                      width: int, height: int, x: int, y: int) -> bytes:
    """The 30 `wScreenSave` bytes for standing at tile `(x, y)` on `label`.

    `rom` is the built ROM's bytes; `label` is the map's file label (the
    `<Label>_BlockData` symbol names its compressed grid). `width`/`height` are
    the map's block dimensions, from the caller's `map_constants.asm` parse — the
    compressed stream can encode more than the live grid (shared blocks, padding),
    so the grid is truncated to `width * height` exactly as `ReadMapBlocks` copies.
    """
    sym = syms.get(f"{label}_BlockData")
    if sym is None:
        raise ValueError(
            f"the build's .sym has no {label}_BlockData — is this a polished "
            "checkout, built with symbols?")
    off = blockdata.rom_offset(sym.bank, sym.addr)
    grid, _consumed = lzp.decompress(rom, off)
    need = width * height
    if len(grid) < need:
        raise ValueError(
            f"{label} blockdata is {len(grid)} bytes, need {need} "
            f"({width}x{height}) — wrong map dimensions or a bad stream.")
    bd = blockdata.BlockData(
        name=label, group=0, map_id=0, width=width, height=height,
        border_block=0, blocks=grid[:need])
    return blockdata.compute_screen_save(bd, x, y)
