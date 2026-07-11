"""Idempotent, anchor-based editors that wire a new map into the asm sources.

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
from ..shared.mapspec import INTO, MapSpec

__all__ = ["Edit", "apply_edits", "WiringError", "SCRIPTS_GUARD"]

SCRIPTS_GUARD = "DO NOT ADD ANYTHING BELOW THIS LINE"

_SECTION_RE = re.compile(r'^\s*SECTION\s+"([^"]+)"')


# --------------------------------------------------------------------------- #
# constants/map_dimension_constants.asm — the `mapgroup` line                 #
# --------------------------------------------------------------------------- #

def wire_dimensions(root: Path, spec: MapSpec) -> Edit:
    rel = "constants/map_dimension_constants.asm"
    path = root / rel
    lines = path.read_text().splitlines()

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
    return Edit(rel, True, f"added '{new_line.strip()}' to group {spec.group}", text)


# --------------------------------------------------------------------------- #
# maps/map_headers.asm — the positional `map_header` line                     #
# --------------------------------------------------------------------------- #

def wire_primary_header(root: Path, spec: MapSpec) -> Edit:
    rel = "maps/map_headers.asm"
    path = root / rel
    lines = path.read_text().splitlines()

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
    return Edit(rel, True, f"appended map_header {spec.label} to MapGroup{spec.group}", text)


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
    text = path.read_text()
    lines = text.splitlines()

    include = f'INCLUDE "{spec.script_asm}"'
    if any(include == ln.strip() for ln in lines):
        return Edit(rel, False, f"{include} already present")

    placement = spec.placement("script")
    if placement.mode == INTO:
        return _place(rel, text, placement, [include], barrier=SCRIPTS_GUARD)

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
    return Edit(rel, True, f"added section '{spec.section_script}'", text)


# --------------------------------------------------------------------------- #
# contents/romx.link — pin each section to its chosen bank                     #
# --------------------------------------------------------------------------- #

def pin_sections(root: Path, assignments: dict[str, int]) -> Edit:
    """Pin ``{section name: bank}`` in the linker script.

    Re-pins cleanly: any existing entry for a section is removed first, then the
    section is added under its target bank, declaring ``ROMX $XX`` blocks for
    empty high banks that aren't listed yet. Idempotent for an unchanged plan.
    """
    rel = "contents/romx.link"
    path = root / rel
    lines = path.read_text().splitlines()

    wanted = {name: f'\t"{name}"' for name in assignments}
    # Strip any stale placement of these sections.
    before = list(lines)
    lines = [ln for ln in lines if ln not in wanted.values()]

    changed_detail = []
    for name, bank in assignments.items():
        header = _romx_header(bank)
        idx = next((i for i, ln in enumerate(lines) if ln.strip() == header.strip()), None)
        if idx is None:
            # Declare a new (empty high) bank block at EOF.
            if lines and lines[-1].strip() != "":
                lines.append("")
            lines.append(header)
            lines.append(wanted[name])
            changed_detail.append(f"{name} -> new {header.strip()}")
            continue
        # Append under the existing bank block, after its last section line.
        end = idx + 1
        while end < len(lines) and lines[end].strip() and not lines[end].startswith("ROMX"):
            end += 1
        lines.insert(end, wanted[name])
        changed_detail.append(f"{name} -> {header.strip()}")

    text = "\n".join(lines) + "\n"
    changed = lines != before
    detail = "; ".join(changed_detail) if changed else "linker pins already current"
    return Edit(rel, changed, detail, text)


def unpin_sections(root: Path, names: list[str]) -> Edit:
    """Remove any linker pins for ``names`` so the sections float.

    Used before a measurement build of an *already-pinned* map: if the map grew
    past its current bank, building with the stale pin would overflow, so we let
    the sections float (rgblink auto-places them, typically into the empty high
    banks) just long enough to measure their true sizes, then re-pin properly.
    A no-op for a map that was never pinned (e.g. first allocation).
    """
    rel = "contents/romx.link"
    path = root / rel
    lines = path.read_text().splitlines()
    targets = {f'\t"{n}"' for n in names}
    kept = [ln for ln in lines if ln not in targets]
    changed = len(kept) != len(lines)
    text = "\n".join(kept) + "\n"
    detail = f"unpinned {len(lines) - len(kept)} section(s) for measurement" if changed \
        else "nothing pinned to unpin"
    return Edit(rel, changed, detail, text)


def _romx_header(bank: int) -> str:
    return f"ROMX ${bank:02X}"


# --------------------------------------------------------------------------- #
# helpers                                                                      #
# --------------------------------------------------------------------------- #

class WiringError(RuntimeError):
    pass


# --------------------------------------------------------------------------- #
# placing a blob: its own new SECTION, or inside one that already exists       #
# --------------------------------------------------------------------------- #

def _place(rel: str, text: str, placement, entry: list[str],
           barrier: str | None = None) -> Edit:
    """Write `entry` where `placement` says it goes.

    Both modes are anchor-based and idempotent in the same way the rest of this
    module is — the caller has already checked the map isn't wired, and neither
    mode depends on a line number.
    """
    if placement.mode == INTO:
        lines = _append_into_section(text.split("\n"), placement.section, entry, barrier)
        return Edit(rel, True,
                    f"appended into existing section '{placement.section}' "
                    f"(inherits its bank)",
                    "\n".join(lines))

    block = ["", f'SECTION "{placement.section}", ROMX', *entry]
    return Edit(rel, True, f"added section '{placement.section}'",
                text.rstrip("\n") + "\n" + "\n".join(block) + "\n")


def _append_into_section(lines: list[str], section: str, entry: list[str],
                         barrier: str | None = None) -> list[str]:
    """Insert `entry` at the end of an existing ``SECTION "<section>"`` block.

    A section runs until the next ``SECTION`` line, a `barrier` line, or the end
    of the file — and the barrier matters: the last section in map_scripts.asm
    runs to EOF *through* the "DO NOT ADD ANYTHING BELOW THIS LINE" banner, so
    without it an append would land underneath the one comment in the repo that
    exists to say don't.

    The entry goes after the section's last non-blank line, so it lands inside
    the section rather than in the gap before whatever follows.
    """
    start = next((i for i, ln in enumerate(lines)
                  if (m := _SECTION_RE.match(ln)) and m.group(1) == section), None)
    if start is None:
        raise WiringError(
            f"no SECTION \"{section}\" to append into — check the name, or let "
            f"mapfit place this blob automatically"
        )

    def ends_here(line: str) -> bool:
        return bool(_SECTION_RE.match(line)) or (barrier is not None and barrier in line)

    end = next((i for i in range(start + 1, len(lines)) if ends_here(lines[i])),
               len(lines))
    while end > start + 1 and not lines[end - 1].strip():
        end -= 1                       # step back over the blank gap to what follows

    return lines[:end] + entry + lines[end:]


def _group_block(lines, n, delimiter_re):
    """Return [start, end) line indices of the n-th block delimited by a regex
    (1-based). `start` is the delimiter line; `end` is the next delimiter / EOF."""
    delim = re.compile(delimiter_re)
    starts = [i for i, ln in enumerate(lines) if delim.match(ln)]
    if n < 1 or n > len(starts):
        return None, None
    start = starts[n - 1]
    end = starts[n] if n < len(starts) else len(lines)
    return start, end


def _label_block(lines, label, label_re):
    """Like _group_block but keyed on a specific label line (e.g. 'MapGroup7:')."""
    delim = re.compile(label_re)
    starts = [i for i, ln in enumerate(lines) if delim.match(ln)]
    target = next((i for i in starts if lines[i].rstrip(":") == label or lines[i].strip() == f"{label}:"), None)
    if target is None:
        return None, None
    after = [i for i in starts if i > target]
    end = after[0] if after else len(lines)
    return target, end


def _last_match_in(lines, start, end, pattern):
    rx = re.compile(pattern)
    found = None
    for i in range(start, end):
        if rx.match(lines[i]):
            found = i
    return found


ALL_ASM_EDITORS = (
    wire_dimensions,
    wire_primary_header,
    wire_secondary_header,
    wire_blockdata,
    wire_script,
)
