"""Paired warps: a door on both sides, with the back-indices right.

`warp_def y, x, warp_to, TARGET` — `warp_to` is a **1-based index into the
target map's own warp list**, not a coordinate. That's the whole difficulty:
the number A writes depends on how many warps B has, and vice versa, so a pair
of warps can only be added if both sides are worked out *before* either is
appended. Do it one map at a time and the second one's index is off by one.

Appending is also the only safe way to add a warp. Every existing `warp_to`
anywhere in the repo that points at this map is a position in its list, so
inserting in the middle silently repoints all of them.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..shared import eventheader as eh, mapsource
from ..shared.edits import Edit
from ..shared.eventheader import ListKind


class WarpError(RuntimeError):
    pass


@dataclass(frozen=True)
class Warp:
    map: str             # const
    y: int
    x: int
    index: int           # this warp's own 1-based position, once added
    leads_to: str        # const of the map it enters
    back_index: int      # the warp it arrives on, in that map


def add_paired_warp(root: Path, a: str, a_at: tuple[int, int],
                    b: str, b_at: tuple[int, int]) -> tuple[list[Edit], tuple[Warp, Warp]]:
    """Put a warp at `a_at` in A leading to `b_at` in B, and the return trip.

    Both new warps land at the end of their map's list, so each one's index is
    one past what's already there — and each points at the *other's* new index.
    Both are computed up front, since appending to A changes what B must write.
    """
    labels = {const: label for label, const in mapsource.header_pairs(root)}
    headers = {}
    for const in (a, b):
        label = labels.get(const)
        if label is None:
            raise WarpError(f"{const} is not a wired map")
        path = root / "maps" / f"{label}.asm"
        try:
            headers[const] = eh.parse_map(path)
        except eh.UnparseableHeader as e:
            raise WarpError(f"{const} can't be edited safely: {e}") from e

    # Each warp is appended, so it becomes the last entry in its own map.
    a_index = len(headers[a].warps) + 1
    b_index = len(headers[b].warps) + 1

    warp_a = Warp(map=a, y=a_at[0], x=a_at[1], index=a_index,
                  leads_to=b, back_index=b_index)
    warp_b = Warp(map=b, y=b_at[0], x=b_at[1], index=b_index,
                  leads_to=a, back_index=a_index)

    if a == b:
        raise WarpError("a map can't be paired with itself — add the two warps "
                        "separately if that's really what you want")

    edits = []
    for warp in (warp_a, warp_b):
        header = headers[warp.map]
        header.add_entry(ListKind.WARPS, [
            str(warp.y), str(warp.x), str(warp.back_index), warp.leads_to,
        ])
        edits.append(header.to_edit(
            root,
            f"warp {warp.index} at ({warp.y},{warp.x}) -> {warp.leads_to} "
            f"warp {warp.back_index}",
        ))
    return edits, (warp_a, warp_b)
