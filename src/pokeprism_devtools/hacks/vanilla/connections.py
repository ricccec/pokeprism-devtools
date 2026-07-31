"""Wiring two family maps together, from the one number a human actually knows.

The modern `connection` macro — which pokecrystal and polishedcrystal share
byte-for-byte — takes only four things: the direction, the neighbour's label and
id, and how far the neighbour slides along the shared edge. Everything the engine
reads is computed *by the macro* from those: where the strip is copied from, how
long it is, the player's crossing shift, and the map's connection-flag nibble
(`MAP_CONNECTIONS_<id>`). So this module is a fraction of prism's
`hacks/prism/connections.py`, which has to derive all of that by hand into a
seven-argument macro and rewrite a flag nibble on each side. Here there is one
number to write and rgbds does the rest.

Both sides are always written, because a connection the neighbour does not mirror
is a wall you can walk through one way. The neighbour's offset is the *negative*
of this side's — B sits ``k`` blocks along A's edge, so from B's point of view A
sits ``-k`` along B's — which is why the reciprocal carries ``-k``. (Cherrygrove's
``connection north, Route30, ROUTE_30, 5`` is mirrored by Route30's
``connection south, CherrygroveCity, CHERRYGROVE_CITY, -5``.)

The macro **fails to assemble** unless a map's connections are written in north,
south, west, east order, so a new line is spliced into its slot, never appended.

Everything lives in one file, `data/maps/attributes.asm`: a map's block is its
``map_attributes <Label>, <CONST>, <border>`` line followed by zero or more
``connection`` lines, ending at the blank line before the next map.
"""

from __future__ import annotations

import re
from pathlib import Path

from ...shared.edits import Edit

REL = "data/maps/attributes.asm"

OPPOSITE = {"north": "south", "south": "north", "east": "west", "west": "east"}

#: The order the macro insists on. A new line goes into its slot in this sequence.
ORDER = ("north", "south", "west", "east")

_ATTRS_RE = re.compile(r"^\s*map_attributes\s+(?P<label>\w+)\s*,\s*(?P<const>\w+)\s*,")
_CONN_RE = re.compile(
    r"^\s*connection\s+(?P<dir>\w+)\s*,\s*(?P<label>\w+)\s*,\s*(?P<const>\w+)\s*,"
    r"\s*(?P<offset>-?\w+)")


class WiringError(RuntimeError):
    pass


def connect(root: Path, a: str, direction: str, b: str, k: int) -> Edit:
    """Wire A and B together, both sides, and return the edit to preview/apply.

    ``k`` is measured in A's coordinates: B's origin sits ``k`` blocks along A's
    edge. Idempotent — re-running with the same geometry writes nothing, and
    re-running with a different offset rewrites the existing line rather than
    adding a second connection in the same direction.
    """
    if direction not in OPPOSITE:
        raise WiringError(f"{direction!r} is not a direction")

    path = root / REL
    original = path.read_text()
    lines = original.split("\n")

    a_label = _label_of(lines, a)
    b_label = _label_of(lines, b)

    lines = _splice(lines, a, direction, b_label, b, k)
    lines = _splice(lines, b, OPPOSITE[direction], a_label, a, -k)

    text = "\n".join(lines)
    if text == original:
        return Edit(REL, False,
                    f"{a} and {b} are already connected {direction} at offset {k:+d}",
                    base=original)
    detail = f"{b} is {direction} of {a} at offset {k:+d}"
    return Edit(REL, True, detail, text, base=original)


def disconnect(root: Path, a: str, direction: str) -> tuple[Edit, list[str]]:
    """Unwire A's `direction` connection, and the neighbour's side of it.

    The mirror of :func:`connect`, and safe for the same reason: a connection is
    named by its *direction*, not by a position, so removing one renumbers
    nothing. Both sides go — a connection the neighbour still mirrors is the
    one-way wall `connect` exists to prevent, arrived at from the other end. If
    the neighbour never mirrored it, that is said rather than fixed.
    """
    if direction not in OPPOSITE:
        raise WiringError(f"{direction!r} is not a direction")

    path = root / REL
    original = path.read_text()
    lines = original.split("\n")

    at = _find(lines, _header_line(lines, a), direction)
    if at is None:
        raise WiringError(f"{a} has no {direction} connection to remove")
    b = _CONN_RE.match(lines[at]).group("const")

    notes: list[str] = []
    lines = _unsplice(lines, a, direction)
    try:
        lines = _unsplice(lines, b, OPPOSITE[direction], target=a)
    except WiringError:
        notes.append(f"{b} had no {OPPOSITE[direction]} connection back to {a} — "
                     f"it was already one-way, and only {a}'s side was removed.")

    text = "\n".join(lines)
    detail = f"{a} no longer connects {direction} to {b}"
    return Edit(REL, text != original, detail, text, base=original), notes


# --------------------------------------------------------------------------- #
# splicing one map's block                                                    #
# --------------------------------------------------------------------------- #

def _splice(lines: list[str], owner: str, direction: str,
            target_label: str, target: str, k: int) -> list[str]:
    """Put a `connection` from `owner` into its block, in north/south/west/east
    order. Re-uses the existing line for this direction if there is one, so the
    same geometry twice is a no-op and different geometry a rewrite."""
    start = _header_line(lines, owner)
    line = _render(direction, target_label, target, k)
    lines = list(lines)

    at = _find(lines, start, direction)
    if at is not None:
        lines[at] = line
        return lines

    lines.insert(_insert_at(lines, start, direction), line)
    return lines


def _unsplice(lines: list[str], owner: str, direction: str,
              target: str | None = None) -> list[str]:
    """Drop `owner`'s connection line in `direction` (optionally only if it
    points at `target`). Nothing else moves — the macro recomputes the flag."""
    start = _header_line(lines, owner)
    at = _find(lines, start, direction, target)
    if at is None:
        raise WiringError(f"{owner} has no {direction} connection"
                          + (f" to {target}" if target else ""))
    lines = list(lines)
    del lines[at]
    return lines


def _render(direction: str, target_label: str, target: str, k: int) -> str:
    return f"\tconnection {direction}, {target_label}, {target}, {k}"


def _label_of(lines: list[str], const: str) -> str:
    m = _ATTRS_RE.match(lines[_header_line(lines, const)])
    return m.group("label")


def _header_line(lines: list[str], const: str) -> int:
    for i, line in enumerate(lines):
        m = _ATTRS_RE.match(line)
        if m and m.group("const") == const:
            return i
    raise WiringError(f"{REL}: no map_attributes for {const}")


def _block_end(lines: list[str], start: int) -> int:
    """One past the last connection line under this header."""
    i = start + 1
    while i < len(lines) and _CONN_RE.match(lines[i]):
        i += 1
    return i


def _find(lines: list[str], start: int, direction: str,
          target: str | None = None) -> int | None:
    """Where `start`'s connection in `direction` is written, if it is."""
    for i in range(start + 1, _block_end(lines, start)):
        m = _CONN_RE.match(lines[i])
        if m and m.group("dir").lower() == direction and (
                target is None or m.group("const") == target):
            return i
    return None


def _insert_at(lines: list[str], start: int, direction: str) -> int:
    """The line index a new `direction` connection goes at, so the block stays in
    north/south/west/east order — before the first existing connection that
    sorts after it, or at the block's end."""
    rank = ORDER.index(direction)
    for i in range(start + 1, _block_end(lines, start)):
        m = _CONN_RE.match(lines[i])
        if m and ORDER.index(m.group("dir").lower()) > rank:
            return i
    return _block_end(lines, start)
