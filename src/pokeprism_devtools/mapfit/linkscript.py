"""`contents/romx.link` — which bank each section is pinned to.

The other half of wiring a map: the asm editors say a section exists, and this
says where the linker must put it. A blob that joined an existing section is
absent from here on purpose, because it inherits that section's bank and has
nothing of its own to pin.
"""

from __future__ import annotations

from pathlib import Path

from ..shared.edits import Edit


def pin_sections(root: Path, assignments: dict[str, int]) -> Edit:
    """Pin ``{section name: bank}`` in the linker script.

    Re-pins cleanly: any existing entry for a section is removed first, then the
    section is added under its target bank, declaring ``ROMX $XX`` blocks for
    empty high banks that aren't listed yet. Idempotent for an unchanged plan.
    """
    rel = "contents/romx.link"
    path = root / rel
    original = path.read_text()
    lines = original.splitlines()

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
    return Edit(rel, changed, detail, text, base=original)


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
    original = path.read_text()
    lines = original.splitlines()
    targets = {f'\t"{n}"' for n in names}
    kept = [ln for ln in lines if ln not in targets]
    changed = len(kept) != len(lines)
    text = "\n".join(kept) + "\n"
    detail = f"unpinned {len(lines) - len(kept)} section(s) for measurement" if changed \
        else "nothing pinned to unpin"
    return Edit(rel, changed, detail, text, base=original)


def _romx_header(bank: int) -> str:
    return f"ROMX ${bank:02X}"
