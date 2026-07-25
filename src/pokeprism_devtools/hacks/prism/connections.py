"""Wiring two maps together, from the only thing a human actually knows.

The intent is always *"B sits north of A, shifted k blocks along the seam"*.
Everything the `connection` macro wants — where the strip lands, where it is
read from, how long it is, and the flag nibble on both maps — follows from that
one number, and this module derives it. Both sides are written, because a
connection the neighbour doesn't mirror is a wall you can walk through one way.

Where k lives in the macro
--------------------------
For a north connection, the macro copies blocks out of B's row (B_HEIGHT - 3)
starting at column `offset`, into A's overworld row starting at column `coord`.
So B's column `offset` and A's column `coord` are the same place in the world,
and therefore B's origin sits at A-column ``coord - offset``. That difference
*is* k — and it is exactly the quantity the macro emits as the player's
crossing shift, ``(coord - offset) * -2``. Crossing back has to undo it, which
is why the reciprocal connection carries -k. That relation holds for 92 of 92
directed connections in the repo, with no exceptions, and it's what
``maplint``'s conn-align checks.

Where the strip comes from
--------------------------
It is *not* derivable, and the plan's expectation that it would be is wrong:
16 of 45 reciprocal pairs in the repo copy different amounts in each direction,
so there is no canonical value to recompute. It's a free parameter, and the
existing maps treat it loosely — 21 of them run past the end of the source map
or the destination row, evidently harmlessly, because the surplus lands
off-screen.

So this generator doesn't imitate that. It emits the **widest strip that is
still in bounds**: everything the two maps genuinely share, including A's
3-block border so the seam's corners are filled. That reproduces 45 existing
connections exactly and is in-bounds by construction everywhere else.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import maps, mapsource
from .blobsizes import SECONDARY_PER_CONNECTION
from ...shared.edits import Edit

_REL = "maps/second_map_headers.asm"

#: The overworld map buffer carries a 3-block border on every side (the macro's
#: `+ 3` on the destination, and the `WIDTH + 6` stride).
BORDER = 3

OPPOSITE = {"north": "south", "south": "north", "east": "west", "west": "east"}

#: Which map dimension runs *along* the seam for each direction.
_ALONG_WIDTH = {"north", "south"}

_MAP_HEADER_2_RE = re.compile(
    r"^(?P<head>\s*map_header_2\s+(?P<label>\w+)\s*,\s*(?P<const>\w+)\s*,\s*"
    r"(?P<border>[^,]+?)\s*,\s*)(?P<flags>.+?)(?P<comment>\s*;.*)?$"
)
_CONNECTION_RE = re.compile(r"^\s*connection\s+(\w+)\s*,\s*(\w+)\s*,")


class WiringError(RuntimeError):
    pass


@dataclass(frozen=True)
class Connection:
    """One side of a connection — everything the macro needs."""
    owner: str           # const of the map this line belongs to
    owner_label: str
    direction: str
    target: str          # const of the neighbour
    target_label: str
    coord: int           # arg 4: where the strip lands in THIS map
    offset: int          # arg 5: where it is read from in the neighbour
    strip: int           # arg 6: how many blocks

    @property
    def delta(self) -> int:
        return self.coord - self.offset

    def render(self) -> str:
        return (f"\tconnection {self.direction}, {self.target}, {self.target_label}, "
                f"{self.coord}, {self.offset}, {self.strip}, {self.owner}")


def plan(root: Path, a: str, direction: str, b: str, k: int) -> tuple[Connection, Connection]:
    """Both halves of "B is `direction` of A, offset k blocks along the seam".

    k is measured in A's coordinates: B's origin sits at A-column (or A-row) k.
    From B's side the same seam has offset -k, which is what makes the pair
    reciprocal.
    """
    if direction not in OPPOSITE:
        raise WiringError(f"{direction!r} is not a direction")

    dims = {m.name: m for m in maps.parse_maps(root / "constants/map_dimension_constants.asm")}
    labels = {const: label for label, const in mapsource.header_pairs(root)}
    for const in (a, b):
        if const not in dims:
            raise WiringError(f"{const} is not a map")
        if const not in labels:
            raise WiringError(f"{const} has no map_header_2 — wire the map first")

    along = _along(dims, a, direction)
    other = _along(dims, b, direction)

    return (
        _side(a, labels[a], direction, b, labels[b], along, other, k),
        _side(b, labels[b], OPPOSITE[direction], a, labels[a], other, along, -k),
    )


def _along(dims, const: str, direction: str) -> int:
    """The map's extent along the seam: width for a north/south join, height for
    an east/west one."""
    d = dims[const]
    return d.width if direction in _ALONG_WIDTH else d.height


def _side(owner, owner_label, direction, target, target_label,
          along: int, other: int, k: int) -> Connection:
    """The widest in-bounds strip of the seam, from `owner`'s point of view.

    In owner coordinates the neighbour spans [k, k + other), and the owner's
    writable row runs from -BORDER to along + BORDER. The shared part of those
    two is the whole seam, border included, and nothing outside it can be
    written or read without running off one map or the other.
    """
    lo = max(-BORDER, k)
    hi = min(along + BORDER, k + other)
    if hi <= lo:
        raise WiringError(
            f"{owner} and {target} don't touch at offset {k}: the neighbour spans "
            f"{k}..{k + other} along the seam, which misses {owner}'s "
            f"{-BORDER}..{along + BORDER}"
        )
    return Connection(owner=owner, owner_label=owner_label, direction=direction,
                      target=target, target_label=target_label,
                      coord=lo, offset=lo - k, strip=hi - lo)


# --------------------------------------------------------------------------- #
# writing                                                                     #
# --------------------------------------------------------------------------- #

def growth(root: Path, a: str, direction: str, b: str) -> dict[str, int]:
    """How many bytes each map's secondary header would gain.

    A new `connection` line emits 12 more bytes into the map's secondary header,
    which is pinned to a bank in `contents/romx.link` — so a connection can push
    a bank over. Nothing here can tell whether it *will*; that's `prism-mapfit`'s
    job with a real free-space number. This just reports the cost so the caller
    can go and ask.
    """
    return {
        const: 0 if _has_connection(root, const, d, other) else SECONDARY_PER_CONNECTION
        for const, d, other in ((a, direction, b), (b, OPPOSITE[direction], a))
    }


def _has_connection(root: Path, owner: str, direction: str, target: str) -> bool:
    lines = (root / _REL).read_text().split("\n")
    try:
        start = _header_line(lines, owner)
    except WiringError:
        return False
    for i in range(start + 1, _block_end(lines, start)):
        m = _CONNECTION_RE.match(lines[i])
        if m and m.group(1).lower() == direction and m.group(2) == target:
            return True
    return False


def connect(root: Path, a: str, direction: str, b: str, k: int) -> tuple[Edit, list[Connection]]:
    """Wire A and B together, both sides, and return the edit to preview/apply.

    Idempotent: re-running with the same geometry is a no-op, and re-running
    with different geometry rewrites the existing lines rather than adding a
    second connection in the same direction.
    """
    left, right = plan(root, a, direction, b, k)

    path = root / _REL
    original = path.read_text()
    lines = original.split("\n")
    for conn in (left, right):
        lines = _splice(lines, conn)

    text = "\n".join(lines)
    if text == original:
        return Edit(_REL, False,
                    f"{a} and {b} are already connected {direction} at offset {k:+d}",
                    base=original), [left, right]

    added = sum(growth(root, a, direction, b).values())
    cost = f"; +{added} bytes of secondary header" if added else ""
    detail = f"{b} is {direction} of {a} at offset {k:+d}{cost}"
    return Edit(_REL, True, detail, text, base=original), [left, right]


def disconnect(root: Path, a: str, direction: str) -> tuple[Edit, list[str]]:
    """Unwire A's `direction` connection, and the neighbour's side of it.

    The exact mirror of :func:`connect`, and safe for the same reason it is safe
    to add one: a connection is named by its *direction*, not by a position, so
    nothing counts its way to it and removing one renumbers nothing. That is what
    makes this the easy half of P4 and the warp the hard half.

    Both sides go. A connection the neighbour still mirrors is a wall you can walk
    through one way — the same asymmetry `connect` exists to prevent, arrived at
    from the other end. If the neighbour never mirrored it, that is said rather
    than fixed: this removes connections, it does not go looking for other ones to
    repair.
    """
    if direction not in OPPOSITE:
        raise WiringError(f"{direction!r} is not a direction")

    path = root / _REL
    original = path.read_text()
    lines = original.split("\n")

    at = _find(lines, _header_line(lines, a), direction)
    if at is None:
        raise WiringError(f"{a} has no {direction} connection to remove")
    b = _CONNECTION_RE.match(lines[at]).group(2)

    notes: list[str] = []
    lines = _unsplice(lines, a, direction)
    try:
        lines = _unsplice(lines, b, OPPOSITE[direction], target=a)
    except WiringError:
        notes.append(f"{b} had no {OPPOSITE[direction]} connection back to {a} — "
                     f"it was already one-way, and only {a}'s side was removed.")

    text = "\n".join(lines)
    detail = f"{a} no longer connects {direction} to {b}"
    return Edit(_REL, text != original, detail, text, base=original), notes


def _unsplice(lines: list[str], owner: str, direction: str,
              target: str | None = None) -> list[str]:
    """Drop `owner`'s connection line in `direction`, and recompute its nibble."""
    start = _header_line(lines, owner)
    at = _find(lines, start, direction, target)
    if at is None:
        raise WiringError(f"{owner} has no {direction} connection"
                          + (f" to {target}" if target else ""))
    del lines[at]
    return _set_flag(lines, start)


def _find(lines: list[str], start: int, direction: str,
          target: str | None = None) -> int | None:
    """Where `start`'s connection in `direction` is written, if it is."""
    for i in range(start + 1, _block_end(lines, start)):
        m = _CONNECTION_RE.match(lines[i])
        if m and m.group(1).lower() == direction and (target is None
                                                      or m.group(2) == target):
            return i
    return None


def _splice(lines: list[str], conn: Connection) -> list[str]:
    """Put `conn` into its map's header block, and make sure the flag nibble
    admits its direction."""
    start = _header_line(lines, conn.owner)
    existing = _find(lines, start, conn.direction)

    if existing is not None:
        lines[existing] = conn.render()
    else:
        lines.insert(_block_end(lines, start), conn.render())

    return _set_flag(lines, start, conn.direction)


def _header_line(lines: list[str], const: str) -> int:
    for i, line in enumerate(lines):
        m = _MAP_HEADER_2_RE.match(line)
        if m and m.group("const") == const:
            return i
    raise WiringError(f"{_REL}: no map_header_2 for {const}")


def _block_end(lines: list[str], start: int) -> int:
    """One past the last connection line under this header."""
    i = start + 1
    while i < len(lines) and _CONNECTION_RE.match(lines[i]):
        i += 1
    return i


def _set_flag(lines: list[str], header: int, direction: str | None = None) -> list[str]:
    """Rewrite the header's connection-flag nibble to name every direction the
    map now actually has a connection line for.

    The engine reads the nibble to decide which connections to load, so it has
    to agree with the lines — a direction set with no line behind it loads
    garbage, and a line the nibble omits is never used. So the nibble is always
    *recomputed from the lines that are there*, never edited: `connect` calls this
    with the direction it just added, and `disconnect` with none at all, having
    already taken the line out.
    """
    m = _MAP_HEADER_2_RE.match(lines[header])
    if not m:                                       # pragma: no cover - located by regex
        raise WiringError(f"{_REL}:{header + 1}: not a map_header_2 line")

    end = _block_end(lines, header)
    present = {c.group(1).lower() for i in range(header + 1, end)
               if (c := _CONNECTION_RE.match(lines[i]))}
    if direction:
        present.add(direction)

    # Written in the source's own order, so the nibble reads the way the rest of
    # the file does.
    order = [d for d in ("north", "south", "west", "east") if d in present]
    flags = " | ".join(d.upper() for d in order) or "0"
    lines[header] = f"{m.group('head')}{flags}{m.group('comment') or ''}"
    return lines
