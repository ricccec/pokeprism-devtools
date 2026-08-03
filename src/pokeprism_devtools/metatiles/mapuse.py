"""Which maps use which metatiles, read out of the pokeprism sources.

A map references a metatile two ways and both count: statically, through the
bytes of its block data, and dynamically, through a `changeblock` or
`eventflagchangeblock` in its script. Counting only the first reports a metatile
as unused when a script is the only thing that places it — which is exactly the
metatile someone would then delete.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ..shared import constants, lz

_MAP_HEADER_RE = re.compile(r"^\s*map_header\s+(\w+)\s*,\s*([A-Za-z_]\w*)")


@dataclass(frozen=True)
class MapUse:
    label: str
    blocks: bytes
    # Metatiles placed dynamically by the map's scripts (changeblock /
    # eventflagchangeblock), which never appear in the static block data.
    script_ids: frozenset[int] = field(default_factory=frozenset)



def _norm(name: str) -> str:
    return name.replace("_", "").lower()


def tileset_id_map(root: Path) -> dict[str, int]:
    """`TILESET_* -> numeric id` from constants/tilemap_constants.asm."""
    consts = constants.parse_constants(root / "constants" / "tilemap_constants.asm")
    return {c.name: c.value for c in consts if c.name.startswith("TILESET_")}


_BLOCKDATA_LABEL_RE = re.compile(r"^(\w+)_BlockData:\s*$")
_INCBIN_RE = re.compile(r'^\s*INCBIN\s+"([^"]+)"')


def blockdata_index(root: Path) -> dict[str, str]:
    """`_norm(map label) -> INCBIN target` from maps/blockdata.asm.

    Consecutive `<Label>_BlockData:` labels share the single INCBIN that
    follows them (many maps — pokecenters, marts, … — alias one block-data
    blob), so a per-label entry is emitted for every label in the run.
    """
    index: dict[str, str] = {}
    asm = root / "maps" / "blockdata.asm"
    if not asm.exists():
        return index
    pending: list[str] = []
    for line in asm.read_text(encoding="utf-8").splitlines():
        m = _BLOCKDATA_LABEL_RE.match(line.strip())
        if m:
            pending.append(m.group(1))
            continue
        m = _INCBIN_RE.match(line)
        if m:
            for label in pending:
                index[_norm(label)] = m.group(1)
            pending = []
            continue
        if line.strip():           # SECTION / anything else ends the run
            pending = []
    return index


# Script commands that write a metatile id into the live map. In both the
# block id is the LAST argument (changeblock x,y,BLOCK ;
# eventflagchangeblock FLAG,x,y,BLOCK).
_BLOCK_CMD_RE = re.compile(r"^\s*(?:changeblock|eventflagchangeblock)\b(.*)$")


def _parse_block_literal(tok: str) -> int | None:
    tok = tok.strip()
    try:
        if tok.startswith("$"):
            return int(tok[1:], 16)
        if tok.lower().startswith("0x"):
            return int(tok, 16)
        if tok.isdigit():
            return int(tok)
    except ValueError:
        return None
    return None  # symbolic constant — can't resolve to an id, skip


def script_block_ids(text: str) -> set[int]:
    """Metatile ids placed by changeblock/eventflagchangeblock in a map script."""
    ids: set[int] = set()
    for line in text.splitlines():
        m = _BLOCK_CMD_RE.match(line)
        if not m:
            continue
        args = m.group(1).split(";", 1)[0]          # drop trailing comment
        last = args.rsplit(",", 1)[-1]              # block id = last arg
        val = _parse_block_literal(last)
        if val is not None:
            ids.add(val)
    return ids


def _read_blocks(root: Path, target: str) -> bytes:
    """Read block bytes for an INCBIN target, decompressing `.lz` as needed.

    Falls back to the .lz/.raw counterpart if the literal target is absent.
    """
    path = root / target
    if not path.exists():
        alt = path.parent / (path.name[:-3] if path.name.endswith(".lz") else path.name + ".lz")
        path = alt if alt.exists() else path
    if path.name.endswith(".lz"):
        data, _ = lz.decompress(path.read_bytes())
        return data
    return path.read_bytes()


def group_maps_by_tileset(root: Path) -> tuple[dict[int, list[MapUse]], list[str]]:
    """Group maps by the tileset id they use.

    Returns `({tileset_id: [MapUse, ...]}, warnings)`.
    """
    ts_map = tileset_id_map(root)
    blk_index = blockdata_index(root)
    script_index = _script_index(root)
    warnings: list[str] = []

    by_tileset: dict[int, list[MapUse]] = {}
    headers = (root / "maps" / "map_headers.asm").read_text(encoding="utf-8")
    for line in headers.splitlines():
        m = _MAP_HEADER_RE.match(line)
        if not m:
            continue
        label, tileset_const = m.group(1), m.group(2)
        tid = ts_map.get(tileset_const)
        if tid is None:
            warnings.append(f"{label}: unknown tileset {tileset_const}")
            continue
        target = blk_index.get(_norm(label))
        if target is None:
            warnings.append(f"{label}: no block-data file")
            continue
        try:
            blocks = _read_blocks(root, target)
        except Exception as e:  # pragma: no cover - corrupt blob
            warnings.append(f"{label}: {e}")
            continue
        script = script_index.get(_norm(label))
        script_ids = frozenset(
            script_block_ids(script.read_text(encoding="utf-8")) if script else ()
        )
        by_tileset.setdefault(tid, []).append(MapUse(label, blocks, script_ids))

    return by_tileset, warnings


def _script_index(root: Path) -> dict[str, Path]:
    """`_norm(map label) -> maps/<Label>.asm` (the per-map script file)."""
    index: dict[str, Path] = {}
    maps_dir = root / "maps"
    if maps_dir.is_dir():
        for p in maps_dir.glob("*.asm"):
            index[_norm(p.stem)] = p
    return index

