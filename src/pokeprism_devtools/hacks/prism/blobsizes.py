"""Sizes of a map's data blobs, shared by the tools that place and inspect maps.

A map contributes four blobs to the ROM:

* primary header — a fixed 8 bytes appended to the shared ``Map Headers`` array.
* secondary header — ``12 + 12·connections`` bytes (a 12-byte base plus 12 per
  ``connection`` line).
* block data — the LZ-compressed ``.blk`` (sized exactly by ``utils/lzcomp``).
* script/event — only known after assembly; read from the ``.map`` elsewhere.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path


PRIMARY_HEADER_GROWTH = 8        # bytes a map_header adds to the "Map Headers" section
SECONDARY_BASE = 12              # map_header_2 base bytes (before connections)
SECONDARY_PER_CONNECTION = 12    # bytes each `connection` line emits


def secondary_size(n_connections: int) -> int:
    """Exact secondary-header size for a map with `n_connections` connections."""
    return SECONDARY_BASE + SECONDARY_PER_CONNECTION * n_connections


def compressed_blk_size(root: Path, blk: str) -> int:
    """Exact size of the LZ-compressed block data, via ``utils/lzcomp``.

    `blk` is the repo-relative path to the uncompressed ``.blk``/``.ablk``.
    """
    lzcomp = root / "utils" / "lzcomp"
    src = root / blk
    if not lzcomp.exists():
        raise FileNotFoundError(f"{lzcomp} not built — run `make utils` first")
    if not src.exists():
        raise FileNotFoundError(f"block data not found: {blk}")
    with tempfile.NamedTemporaryFile(suffix=".lz", delete=False) as tmp:
        out = Path(tmp.name)
    try:
        subprocess.run(
            [str(lzcomp), "--", str(src), str(out)],
            check=True, capture_output=True,
        )
        return out.stat().st_size
    finally:
        out.unlink(missing_ok=True)
