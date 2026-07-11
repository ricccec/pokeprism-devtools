"""Read-only parsers for the map asm sources, keyed by a map's CamelCase label.

This is the inverse of what ``mapwire`` writes: given an existing, already-wired
map, pull its ``map_header`` / ``map_header_2`` fields, its block-data and script
file paths, and the section each blob lives in — straight from the asm, with no
ROM needed. Shared by ``prism-map`` (inspect) and ``prism-mapfit`` (the
shared-section guard).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .mapspec import MapSpec


# --------------------------------------------------------------------------- #
# section membership                                                          #
# --------------------------------------------------------------------------- #

_SECTION_RE = re.compile(r'^\s*SECTION\s+"([^"]+)"')


def enclosing_section(path: Path, matches) -> str | None:
    """Name of the SECTION that contains the first line for which ``matches``
    returns true, or None if no such line exists. ``matches`` is a predicate on
    the raw line text."""
    cur = None
    for ln in path.read_text().splitlines():
        m = _SECTION_RE.match(ln)
        if m:
            cur = m.group(1)
            continue
        if matches(ln):
            return cur
    return None


def shared_section_conflicts(root: Path, spec: MapSpec) -> list[tuple[str, str, str]]:
    """Find blobs of `spec` that are wired into a section the spec didn't ask for.

    The expected section is whatever the spec's *placement* says: its own
    per-map section normally, or a named existing one when the blob is
    deliberately placed there. So a blob sitting in a shared section is only a
    conflict when nobody asked for it — a hand-added INCLUDE in
    'Map Scripts 7' that the spec still thinks lives on its own.

    Returns ``(blob, actual_section, expected_section)`` for each mismatch.
    Empty means every present blob is where the spec says it is (or the map
    isn't wired yet) — i.e. the tool can manage it.
    """
    label = spec.label
    checks = [
        ("script", root / "maps/map_scripts.asm",
         lambda ln, inc=f'INCLUDE "{spec.script_asm}"': ln.strip() == inc,
         spec.section_for("script")),
        ("block data", root / "maps/blockdata.asm",
         lambda ln, lbl=f"{label}_BlockData:": ln.strip() == lbl,
         spec.section_for("blockdata")),
        ("secondary header", root / "maps/second_map_headers.asm",
         lambda ln: re.match(rf"^\s*map_header_2\s+{re.escape(label)}\s*,", ln) is not None,
         spec.section_for("secondary")),
    ]
    conflicts = []
    for blob, path, pred, expected in checks:
        if not path.exists():
            continue
        actual = enclosing_section(path, pred)
        if actual is not None and actual != expected:
            conflicts.append((blob, actual, expected))
    return conflicts


# --------------------------------------------------------------------------- #
# header / path extraction                                                    #
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class PrimaryHeader:
    label: str
    tileset: str
    permission: str
    landmark: str
    music: str
    phone: int
    palette: str
    fishgroup: str


@dataclass(frozen=True)
class SecondaryHeader:
    label: str
    const: str
    border_block: str
    conn_flags: str
    connections: list[str]


def _split_fields(rest: str) -> list[str]:
    return [f.strip() for f in rest.split(",")]


def primary_header(root: Path, label: str) -> PrimaryHeader | None:
    """Parse `map_header <label>, TILESET, PERMISSION, LANDMARK, MUSIC, phone,
    PALETTE, FISHGROUP` from maps/map_headers.asm."""
    path = root / "maps/map_headers.asm"
    if not path.exists():
        return None
    rx = re.compile(rf"^\s*map_header\s+{re.escape(label)}\s*,(.*)$")
    for ln in path.read_text().splitlines():
        m = rx.match(ln)
        if not m:
            continue
        f = _split_fields(m.group(1))
        if len(f) < 7:
            return None
        try:
            phone = int(f[4], 0)
        except ValueError:
            phone = 0
        return PrimaryHeader(
            label=label, tileset=f[0], permission=f[1], landmark=f[2],
            music=f[3], phone=phone, palette=f[5], fishgroup=f[6],
        )
    return None


def secondary_header(root: Path, label: str) -> SecondaryHeader | None:
    """Parse `map_header_2 <label>, CONST, border_block, conn_flags` plus the
    contiguous `connection …` lines that follow it, from
    maps/second_map_headers.asm."""
    path = root / "maps/second_map_headers.asm"
    if not path.exists():
        return None
    lines = path.read_text().splitlines()
    head = re.compile(rf"^\s*map_header_2\s+{re.escape(label)}\s*,(.*)$")
    conn = re.compile(r"^\s*connection\s+(.*)$")
    for i, ln in enumerate(lines):
        m = head.match(ln)
        if not m:
            continue
        f = _split_fields(m.group(1))
        if len(f) < 3:
            return None
        connections: list[str] = []
        for nxt in lines[i + 1:]:
            cm = conn.match(nxt)
            if cm:
                connections.append(cm.group(1).strip())
                continue
            if nxt.strip() == "":
                break          # blank line ends this map's connection block
            break              # any other line (next map_header_2 / SECTION)
        return SecondaryHeader(
            label=label, const=f[0], border_block=f[1], conn_flags=f[2],
            connections=connections,
        )
    return None


def blk_path(root: Path, label: str) -> str | None:
    """The uncompressed block-data path for `label` (the `INCBIN` under
    `<label>_BlockData:` in maps/blockdata.asm, with `.lz` stripped)."""
    path = root / "maps/blockdata.asm"
    if not path.exists():
        return None
    label_line = f"{label}_BlockData:"
    incbin = re.compile(r'^\s*INCBIN\s+"([^"]+)"')
    lines = path.read_text().splitlines()
    for i, ln in enumerate(lines):
        if ln.strip() != label_line:
            continue
        for nxt in lines[i + 1:]:
            m = incbin.match(nxt)
            if m:
                target = m.group(1)
                return target[:-3] if target.endswith(".lz") else target
            if nxt.strip():
                break          # something other than the INCBIN — give up
        return None
    return None


def script_path(root: Path, label: str) -> str | None:
    """The script include path for `label` — the `INCLUDE "maps/<stem>.asm"` in
    maps/map_scripts.asm whose filename stem equals the label."""
    path = root / "maps/map_scripts.asm"
    if not path.exists():
        return None
    incl = re.compile(r'^\s*INCLUDE\s+"([^"]+\.asm)"')
    for ln in path.read_text().splitlines():
        m = incl.match(ln)
        if m and Path(m.group(1)).stem == label:
            return m.group(1)
    return None


# --------------------------------------------------------------------------- #
# bulk (whole-repo) parsers — for callers checking many maps at once          #
# --------------------------------------------------------------------------- #

_HEADER_2_RE = re.compile(r"^\s*map_header_2\s+(\w+)\s*,\s*(\w+)\s*,")
_BLOCKDATA_LABEL_RE = re.compile(r"^(\w+)_BlockData:\s*$")
_INCBIN_RE = re.compile(r'^\s*INCBIN\s+"([^"]+)"')
_INCLUDE_RE = re.compile(r'^\s*INCLUDE\s+"([^"]+\.asm)"')
_MAPSCRIPTHEADER_RE = re.compile(r"^(\w+)_MapScriptHeader:")


def header_pairs(root: Path) -> list[tuple[str, str]]:
    """Every `(label, const)` pair from uncommented `map_header_2` lines in
    maps/second_map_headers.asm — the only place a map's Pascal-case label and
    SCREAMING_SNAKE const are tied together."""
    path = root / "maps/second_map_headers.asm"
    if not path.exists():
        return []
    pairs = []
    for ln in path.read_text().splitlines():
        if ln.lstrip().startswith(";"):
            continue
        m = _HEADER_2_RE.match(ln)
        if m:
            pairs.append((m.group(1), m.group(2)))
    return pairs


def blockdata_labels(root: Path) -> dict[str, str]:
    """`label -> INCBIN target` for every uncommented `<label>_BlockData:` in
    maps/blockdata.asm. Consecutive labels share the single INCBIN that
    follows them (aliased maps — pokecenters, marts, …)."""
    path = root / "maps/blockdata.asm"
    index: dict[str, str] = {}
    if not path.exists():
        return index
    pending: list[str] = []
    for ln in path.read_text().splitlines():
        m = _BLOCKDATA_LABEL_RE.match(ln.strip())
        if m:
            pending.append(m.group(1))
            continue
        m = _INCBIN_RE.match(ln)
        if m:
            for label in pending:
                index[label] = m.group(1)
            pending = []
            continue
        if ln.strip():             # SECTION / anything else ends the run
            pending = []
    return index


def script_header_labels(root: Path) -> set[str]:
    """Every `label` with a `<label>_MapScriptHeader:` definition in a file
    that maps/map_scripts.asm actually INCLUDEs."""
    map_scripts = root / "maps/map_scripts.asm"
    labels: set[str] = set()
    if not map_scripts.exists():
        return labels
    for ln in map_scripts.read_text().splitlines():
        m = _INCLUDE_RE.match(ln)
        if not m:
            continue
        included = root / m.group(1)
        if not included.exists():
            continue
        for ln2 in included.read_text().splitlines():
            hm = _MAPSCRIPTHEADER_RE.match(ln2.strip())
            if hm:
                labels.add(hm.group(1))
    return labels
