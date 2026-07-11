"""Rules about how maps are stitched together: connections and warps.

Every threshold here was fitted against the whole repo before being written down
(see the phase-1 calibration): the delta law holds for 92/92 existing directed
connections and the flag nibble agrees on 453/453 maps, so both are safe to
report as errors. The one thing the plan expected to check and *isn't* checkable
is a canonical strip length — 16 of 45 reciprocal pairs legitimately copy
different amounts in each direction, so there is no single expected value.
"""

from __future__ import annotations

from .context import OPPOSITE, LintContext
from .diagnostics import Diagnostic, Severity

_SECOND_HEADERS = "maps/second_map_headers.asm"


# --------------------------------------------------------------------------- #
# connections                                                                 #
# --------------------------------------------------------------------------- #

def conn_self(ctx: LintContext) -> list[Diagnostic]:
    """The macro's 7th argument must name the map the connection belongs to.

    Only the south/west/east branches of the `connection` macro read it, so a
    wrong id in a *north* connection assembles cleanly and silently — which is
    how ROUTE_69_NORTH ended up declaring itself `ROUTE_s_NORTH`.
    """
    out = []
    for c in ctx.connections:
        if c.declared_self != c.owner:
            out.append(Diagnostic(
                "conn-self", Severity.ERROR, _SECOND_HEADERS, c.line,
                f"{c.owner}'s {c.direction} connection declares itself as "
                f"'{c.declared_self}' (7th argument); expected '{c.owner}'",
            ))
    return out


def conn_target(ctx: LintContext) -> list[Diagnostic]:
    """The neighbour must be a real map."""
    out = []
    for c in ctx.connections:
        if c.target not in ctx.map_defs:
            out.append(Diagnostic(
                "conn-target", Severity.ERROR, _SECOND_HEADERS, c.line,
                f"{c.owner} connects {c.direction} to '{c.target}', which is not a map",
            ))
    return out


def conn_missing(ctx: LintContext) -> list[Diagnostic]:
    """Connections must be reciprocal: if A is north of B, B is south of A.

    A one-way connection means the player can walk off the edge one way and not
    come back — the neighbour never scrolls in.
    """
    out = []
    for c in ctx.connections:
        if c.target not in ctx.map_defs:
            continue                      # conn-target already reported it
        back = ctx.find_connection(c.target, OPPOSITE[c.direction], c.owner)
        if back is None:
            out.append(Diagnostic(
                "conn-missing", Severity.ERROR, _SECOND_HEADERS, c.line,
                f"{c.owner} connects {c.direction} to {c.target}, but {c.target} has "
                f"no '{OPPOSITE[c.direction]}' connection back to {c.owner}",
            ))
    return out


def conn_align(ctx: LintContext) -> list[Diagnostic]:
    """Both halves of a connection must agree on the alignment delta.

    The macro emits ``(coord - offset) * -2`` as the shift applied to the player
    when crossing. Crossing back must undo it exactly, so the reciprocal
    connection's delta has to be this one's negation. Disagreement means the two
    maps are stitched at different offsets depending on the direction you walk —
    the seam jumps.
    """
    out = []
    for c in ctx.connections:
        back = ctx.find_connection(c.target, OPPOSITE[c.direction], c.owner)
        if back is None:
            continue                      # conn-missing already reported it
        if c.line > back.line:
            continue                      # one finding per pair, on its first line
        if c.delta != -back.delta:
            out.append(Diagnostic(
                "conn-align", Severity.ERROR, _SECOND_HEADERS, c.line,
                f"{c.owner} {c.direction} -> {c.target} has alignment delta "
                f"{c.delta:+d} (coord {c.coord} - offset {c.offset}), but the "
                f"connection back (line {back.line}) has {back.delta:+d}; the two "
                f"must be opposite, so one of them is wrong",
            ))
    return out


def conn_flags(ctx: LintContext) -> list[Diagnostic]:
    """The connection-flag nibble in `map_header_2` must list exactly the
    directions the map actually has connection lines for.

    The engine reads the nibble to decide which connections to load; a direction
    set in the nibble with no line behind it loads garbage, and a line the nibble
    omits is simply never used.
    """
    bits = ctx.direction_bits
    out = []
    for const, (expr, line, _) in ctx.conn_flag_exprs.items():
        declared = _eval_flags(expr, bits)
        if declared is None:
            continue                      # an expression we can't evaluate
        actual = 0
        for c in ctx.connections_by_map.get(const, []):
            actual |= bits.get(c.direction, 0)
        if declared != actual:
            out.append(Diagnostic(
                "conn-flags", Severity.ERROR, _SECOND_HEADERS, line,
                f"{const} declares connection flags {expr!r} (${declared:x}) but has "
                f"{_names(actual, bits) or 'no'} connection lines (${actual:x})",
            ))
    return out


def _eval_flags(expr: str, bits: dict[str, int]) -> int | None:
    value = 0
    for token in expr.replace("+", "|").split("|"):
        token = token.strip()
        if not token:
            continue
        low = token.lower()
        if low in bits:
            value |= bits[low]
        elif token.startswith("$"):
            value |= int(token[1:], 16)
        elif token.isdigit():
            value |= int(token)
        else:
            return None
    return value


def _names(value: int, bits: dict[str, int]) -> str:
    return " | ".join(sorted(n.upper() for n, b in bits.items() if value & b))


# --------------------------------------------------------------------------- #
# warps                                                                       #
# --------------------------------------------------------------------------- #

def warp_target(ctx: LintContext) -> list[Diagnostic]:
    """`warp_def y, x, warp_to, TARGET` — `warp_to` is a **1-based index** into
    the target map's own warp list. Off-by-one here drops the player somewhere
    else entirely, or reads a warp that doesn't exist."""
    out = []
    for const, info in sorted(ctx.map_infos.items()):
        header = ctx.header(const)
        if header is None:
            continue
        path = ctx.rel(info.path)
        for i, warp in enumerate(header.warps, start=1):
            if warp.macro == "dummy_warp":
                continue
            target = warp.args[3]
            index = warp.int_arg(2)

            if target not in ctx.map_defs:
                out.append(Diagnostic(
                    "warp-target", Severity.ERROR, path, warp.lineno + 1,
                    f"warp {i} targets '{target}', which is not a map",
                ))
                continue
            if index is None:
                continue                  # a symbolic index; not our business

            dest = ctx.header(target)
            if dest is None:
                continue                  # unmanaged destination — can't check
            n = len(dest.warps)
            if not 1 <= index <= n:
                out.append(Diagnostic(
                    "warp-target", Severity.ERROR, path, warp.lineno + 1,
                    f"warp {i} enters {target} at warp #{index}, but {target} has "
                    f"{n} warp{'s' if n != 1 else ''} (valid: 1-{n})"
                    if n else
                    f"warp {i} enters {target} at warp #{index}, but {target} has no warps",
                ))
    return out


def warp_oneway(ctx: LintContext) -> list[Diagnostic]:
    """The warp you arrive on should usually send you back where you came from.

    Often deliberate (one-way drops, ledges, cave exits), so this is `info`.
    """
    out = []
    for const, info in sorted(ctx.map_infos.items()):
        header = ctx.header(const)
        if header is None:
            continue
        path = ctx.rel(info.path)
        for i, warp in enumerate(header.warps, start=1):
            if warp.macro == "dummy_warp":
                continue
            target, index = warp.args[3], warp.int_arg(2)
            if index is None or target not in ctx.map_defs:
                continue
            dest = ctx.header(target)
            if dest is None or not 1 <= index <= len(dest.warps):
                continue                  # warp-target already reported it

            back = dest.warps[index - 1]
            if back.macro == "dummy_warp":
                continue
            if back.args[3] != const:
                out.append(Diagnostic(
                    "warp-oneway", Severity.INFO, path, warp.lineno + 1,
                    f"warp {i} enters {target} at warp #{index}, which leads to "
                    f"{back.args[3]} rather than back to {const}",
                ))
    return out


ALL = (conn_self, conn_target, conn_missing, conn_align, conn_flags,
       warp_target, warp_oneway)
