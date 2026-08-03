"""Finding and adding to a block of asm, without ever using a line number.

The primitives every wiring editor is built from. A block is located by an
anchor that survives edits — a `SECTION "name"` line, a `MapGroupN:` label, a
`newgroup` delimiter — which is what makes the editors above idempotent and
safe to re-run against a file someone has since edited by hand.
"""

from __future__ import annotations

import re

from ..hacks.prism.mapspec import INTO
from ..shared.edits import Edit

_SECTION_RE = re.compile(r'^\s*SECTION\s+"([^"]+)"')


class WiringError(RuntimeError):
    pass


def _place(rel: str, text: str, placement, entry: list[str],
           barrier: str | None = None) -> Edit:
    """Write `entry` where `placement` says it goes.

    Both modes are anchor-based and idempotent in the same way the rest of this
    module is — the caller has already checked the map isn't wired, and neither
    mode depends on a line number.
    """
    # INTO says "join this section" outright; but even an own-section placement
    # must join a section of that name if one already exists — writing a second
    # `SECTION "<name>"` is not a rename, it is a duplicate the linker splits back
    # apart. So a section name you reuse in the form appends, it does not fork.
    if placement.mode == INTO or _section_exists(text, placement.section):
        lines = _append_into_section(text.split("\n"), placement.section, entry, barrier)
        return Edit(rel, True,
                    f"appended into existing section '{placement.section}' "
                    f"(inherits its bank)",
                    "\n".join(lines), base=text)

    block = ["", f'SECTION "{placement.section}", ROMX', *entry]
    return Edit(rel, True, f"added section '{placement.section}'",
                text.rstrip("\n") + "\n" + "\n".join(block) + "\n", base=text)


def _section_exists(text: str, section: str) -> bool:
    """Whether a ``SECTION "<section>"`` is already declared in this file."""
    return any((m := _SECTION_RE.match(ln)) and m.group(1) == section
               for ln in text.splitlines())


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
