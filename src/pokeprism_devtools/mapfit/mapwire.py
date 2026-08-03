"""The five editors that wire a new map into the asm sources.

The primitives they are built from are in `asmblocks.py`, and the linker
script they are paired with is in `linkscript.py`; both are re-exported here,
because "wire this map in" is one job to a caller even though it is three
files' worth of code.

Every editor reads its target file, makes the smallest edit that adds the map,
and is a no-op if the map is already wired (matched on a stable token, never a
line number). Each returns an :class:`Edit` describing what happened so the
caller can show a dry-run preview and a summary.

Each blob is placed one of two ways, chosen per blob by the spec:

* **its own SECTION** — uniquely named, appended at the end of the file, and
  pinned to a bank in ``contents/romx.link`` (by the packer, or by hand). No
  existing section is disturbed.
* **into an existing SECTION** — appended inside a section that's already there
  (a shared ``Map Scripts 7``, say), inheriting its bank. Nothing is pinned,
  because no new section exists to pin.

Only the positional primary header (``map_header``) has no choice: it always
grows a shared section in place, since ``MapGroupN`` is an ordered array indexed
by map id.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..shared.edits import Edit, apply_edits
from ..hacks.prism.mapspec import INTO, MapSpec
from .asmblocks import (
    WiringError, _append_into_section, _group_block, _label_block,
    _last_match_in, _place, _section_exists,
)
from .linkscript import pin_sections, unpin_sections

__all__ = [
    "Edit", "apply_edits", "WiringError", "SCRIPTS_GUARD",
    "pin_sections", "unpin_sections", "ALL_ASM_EDITORS",
]

SCRIPTS_GUARD = "DO NOT ADD ANYTHING BELOW THIS LINE"


# --------------------------------------------------------------------------- #
# constants/map_dimension_constants.asm — the `mapgroup` line                 #
# --------------------------------------------------------------------------- #

def wire_dimensions(root: Path, spec: MapSpec) -> Edit:
    rel = "constants/map_dimension_constants.asm"
    path = root / rel
    original = path.read_text()
    lines = original.splitlines()

    if any(re.match(rf"^\s*mapgroup\s+{re.escape(spec.const)}\s*,", ln) for ln in lines):
        return Edit(rel, False, f"mapgroup {spec.const} already present")

    start, end = _group_block(lines, spec.group, r"^\s*newgroup\b")
    if start is None:
        raise WiringError(f"{rel}: group {spec.group} (newgroup) not found")

    insert_at = _last_match_in(lines, start, end, r"^\s*mapgroup\b")
    if insert_at is None:
        insert_at = start  # empty group: right after the `newgroup` line
    new_line = f"\tmapgroup {spec.const}, {spec.height}, {spec.width}"
    lines.insert(insert_at + 1, new_line)
    text = "\n".join(lines) + "\n"
    return Edit(rel, True, f"added '{new_line.strip()}' to group {spec.group}", text,
                base=original)


# --------------------------------------------------------------------------- #
# maps/map_headers.asm — the positional `map_header` line                     #
# --------------------------------------------------------------------------- #

def wire_primary_header(root: Path, spec: MapSpec) -> Edit:
    rel = "maps/map_headers.asm"
    path = root / rel
    original = path.read_text()
    lines = original.splitlines()

    if any(re.match(rf"^\s*map_header\s+{re.escape(spec.label)}\s*,", ln) for ln in lines):
        return Edit(rel, False, f"map_header {spec.label} already present")

    start, end = _label_block(lines, f"MapGroup{spec.group}", r"^MapGroup\d+:")
    if start is None:
        raise WiringError(f"{rel}: MapGroup{spec.group}: not found")

    insert_at = _last_match_in(lines, start, end, r"^\s*map_header\b")
    if insert_at is None:
        insert_at = start
    fields = ", ".join([
        spec.label, spec.tileset, spec.permission, spec.landmark,
        spec.music, str(spec.phone), spec.palette, spec.fishgroup,
    ])
    new_line = f"\tmap_header {fields}"
    lines.insert(insert_at + 1, new_line)
    text = "\n".join(lines) + "\n"
    return Edit(rel, True, f"appended map_header {spec.label} to MapGroup{spec.group}",
                text, base=original)


# --------------------------------------------------------------------------- #
# maps/second_map_headers.asm — own section                                   #
# --------------------------------------------------------------------------- #

def wire_secondary_header(root: Path, spec: MapSpec) -> Edit:
    rel = "maps/second_map_headers.asm"
    path = root / rel
    text = path.read_text()

    if re.search(rf"^\s*map_header_2\s+{re.escape(spec.label)}\s*,", text, re.MULTILINE):
        return Edit(rel, False, f"map_header_2 {spec.label} already present")

    entry = [
        f"\tmap_header_2 {spec.label}, {spec.const}, {spec.border_block}, {spec.conn_flags}",
        *(f"\tconnection {c}" for c in spec.connections),
    ]
    return _place(rel, text, spec.placement("secondary"), entry)


# --------------------------------------------------------------------------- #
# maps/blockdata.asm — own section + INCBIN                                    #
# --------------------------------------------------------------------------- #

def wire_blockdata(root: Path, spec: MapSpec) -> Edit:
    rel = "maps/blockdata.asm"
    path = root / rel
    text = path.read_text()

    if re.search(rf"^{re.escape(spec.label)}_BlockData:", text, re.MULTILINE):
        return Edit(rel, False, f"{spec.label}_BlockData already present")

    entry = [
        f"{spec.label}_BlockData:",
        f'\tINCBIN "{spec.blk_lz}"',
    ]
    return _place(rel, text, spec.placement("blockdata"), entry)


# --------------------------------------------------------------------------- #
# maps/map_scripts.asm — own section + INCLUDE, before the guard comment       #
# --------------------------------------------------------------------------- #

def wire_script(root: Path, spec: MapSpec) -> Edit:
    rel = "maps/map_scripts.asm"
    path = root / rel
    original = path.read_text()
    lines = original.splitlines()

    include = f'INCLUDE "{spec.script_asm}"'
    if any(include == ln.strip() for ln in lines):
        return Edit(rel, False, f"{include} already present")

    placement = spec.placement("script")
    if placement.mode == INTO or _section_exists(original, placement.section):
        return _place(rel, original, placement, [include], barrier=SCRIPTS_GUARD)

    guard = next((i for i, ln in enumerate(lines) if SCRIPTS_GUARD in ln), None)
    block = [
        f'SECTION "{spec.section_script}", ROMX',
        include,
        "",
    ]
    if guard is None:
        # No guard marker: append at EOF.
        new_lines = lines + [""] + block
    else:
        # Insert before the run of guard comment lines (and any blank line just
        # above them), so the "do not add below" banner stays at the bottom.
        at = guard
        while at > 0 and lines[at - 1].strip() == "":
            at -= 1
        new_lines = lines[:at] + ["", *block] + lines[at:]
    text = "\n".join(new_lines) + "\n"
    return Edit(rel, True, f"added section '{spec.section_script}'", text,
                base=original)


ALL_ASM_EDITORS = (
    wire_dimensions,
    wire_primary_header,
    wire_secondary_header,
    wire_blockdata,
    wire_script,
)
