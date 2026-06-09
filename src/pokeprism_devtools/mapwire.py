"""Idempotent, anchor-based editors that wire a new map into the asm sources.

Every editor reads its target file, makes the smallest edit that adds the map,
and is a no-op if the map is already wired (matched on a stable token, never a
line number). Each returns an :class:`Edit` describing what happened so the
caller can show a dry-run preview and a summary.

The new blobs each get their *own* uniquely-named ``SECTION`` (the chosen
strategy), so existing shared sections are never disturbed and the linker
pins (see :func:`pin_sections`) place them independently. Only the positional
primary header (``map_header``) grows a shared section in place — there is no
alternative, since ``MapGroupN`` is an ordered array indexed by map id.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .mapspec import MapSpec


SCRIPTS_GUARD = "DO NOT ADD ANYTHING BELOW THIS LINE"


@dataclass
class Edit:
    path: str            # repo-relative
    changed: bool
    detail: str
    new_text: str = ""   # full file text after the edit (for dry-run diffing)


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

    if f'"{spec.section_secondary}"' in text:
        return Edit(rel, False, f"section '{spec.section_secondary}' already present")

    block = [
        "",
        f'SECTION "{spec.section_secondary}", ROMX',
        f"\tmap_header_2 {spec.label}, {spec.const}, {spec.border_block}, {spec.conn_flags}",
    ]
    block += [f"\tconnection {c}" for c in spec.connections]
    new_text = text.rstrip("\n") + "\n" + "\n".join(block) + "\n"
    return Edit(rel, True, f"added section '{spec.section_secondary}'", new_text)


# --------------------------------------------------------------------------- #
# maps/blockdata.asm — own section + INCBIN                                    #
# --------------------------------------------------------------------------- #

def wire_blockdata(root: Path, spec: MapSpec) -> Edit:
    rel = "maps/blockdata.asm"
    path = root / rel
    text = path.read_text()

    if re.search(rf"^{re.escape(spec.label)}_BlockData:", text, re.MULTILINE):
        return Edit(rel, False, f"{spec.label}_BlockData already present")

    block = [
        "",
        f'SECTION "{spec.section_blockdata}", ROMX',
        f"{spec.label}_BlockData:",
        f'\tINCBIN "{spec.blk_lz}"',
    ]
    new_text = text.rstrip("\n") + "\n" + "\n".join(block) + "\n"
    return Edit(rel, True, f"added section '{spec.section_blockdata}'", new_text)


# --------------------------------------------------------------------------- #
# maps/map_scripts.asm — own section + INCLUDE, before the guard comment       #
# --------------------------------------------------------------------------- #

def wire_script(root: Path, spec: MapSpec) -> Edit:
    rel = "maps/map_scripts.asm"
    path = root / rel
    lines = path.read_text().splitlines()

    include = f'INCLUDE "{spec.script_asm}"'
    if any(include == ln.strip() for ln in lines):
        return Edit(rel, False, f"{include} already present")

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
    """Find blobs of `spec` that are already wired but live in a section that
    isn't dedicated to this map (e.g. hand-added into a shared 'Map Scripts 7').

    Returns ``(blob, actual_section, expected_section)`` for each mismatch.
    Empty list means every present blob is in its own per-map section (or the
    map isn't wired yet) — i.e. the tool can manage it.
    """
    label = spec.label
    checks = [
        ("script", root / "maps/map_scripts.asm",
         lambda ln, inc=f'INCLUDE "{spec.script_asm}"': ln.strip() == inc,
         spec.section_script),
        ("block data", root / "maps/blockdata.asm",
         lambda ln, lbl=f"{label}_BlockData:": ln.strip() == lbl,
         spec.section_blockdata),
        ("secondary header", root / "maps/second_map_headers.asm",
         lambda ln: re.match(rf"^\s*map_header_2\s+{re.escape(label)}\s*,", ln) is not None,
         spec.section_secondary),
    ]
    conflicts = []
    for blob, path, pred, expected in checks:
        if not path.exists():
            continue
        actual = enclosing_section(path, pred)
        if actual is not None and actual != expected:
            conflicts.append((blob, actual, expected))
    return conflicts


ALL_ASM_EDITORS = (
    wire_dimensions,
    wire_primary_header,
    wire_secondary_header,
    wire_blockdata,
    wire_script,
)


def apply_edits(root: Path, edits: list[Edit], *, dry_run: bool) -> None:
    """Write each edit's new_text to disk (unless dry_run)."""
    if dry_run:
        return
    for e in edits:
        if e.changed and e.new_text:
            (root / e.path).write_text(e.new_text)
