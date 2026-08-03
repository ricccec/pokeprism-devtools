"""Which of a map's blobs a command acts on.

`--blobs` names kinds, not sections. Aliases collapse to the same section so the
selection survives spelling: `blk` and `blockdata` are one blob, `secondary` and
`header` another.
"""

from __future__ import annotations

from ..hacks.prism.mapspec import MapSpec


# Blob kind -> the spec attribute giving its section name. Aliases collapse to
# the same section, so the selection is robust to spelling.
_BLOB_KINDS = {
    "script": lambda s: s.section_script,
    "blk": lambda s: s.section_blockdata,
    "blockdata": lambda s: s.section_blockdata,
    "secondary": lambda s: s.section_secondary,
    "header": lambda s: s.section_secondary,
}
_DEFAULT_BLOBS = "script,blk,secondary"


def parse_blobs(raw: str | None) -> list[str]:
    """Comma list of blob kinds to act on (default: all three)."""
    kinds = []
    for tok in (raw or _DEFAULT_BLOBS).split(","):
        t = tok.strip().lower()
        if not t:
            continue
        if t not in _BLOB_KINDS:
            raise ValueError(f"unknown blob kind {tok!r} (use script, blk, secondary)")
        kinds.append(t)
    if not kinds:
        raise ValueError("--blobs selected nothing")
    return kinds


def selected_section_names(spec: MapSpec, kinds: list[str]) -> set[str]:
    return {_BLOB_KINDS[k](spec) for k in kinds}

