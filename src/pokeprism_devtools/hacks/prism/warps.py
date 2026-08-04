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

from . import eventheader as eh, mapsource
from ...shared.edits import Edit
from .eventheader import ListKind
from ...asmedit.editvocab import Change, same, spliced
from .objedit import W_MAP, W_TO, W_X, W_Y, MapEdit


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

def edit_warp(root: Path, map_const: str, index: int, y: int, x: int, *,
              dest: str = "", dest_warp: int = 1) -> Change:
    """Where one warp is, and where it goes.

    **Renumbers nothing**, which is the whole reason this is safe and deleting a
    warp is not. `warp_to` is a *pointer* into the destination's list, not an
    identity, so rewriting this line moves no other warp and invalidates nobody
    else's `warp_to`. The warp keeps its own position in this map's list, and
    every map that counts its way to it still counts right.

    The destination warp number is checked against the warps that map actually
    has. It is the one mistake here that assembles perfectly and is only found by
    walking into the door.
    """
    ctx = MapEdit(root, map_const)
    entry = ctx.entry(ListKind.WARPS, index)

    if not dest:
        # A door to nowhere — `dummy_warp`, and never `-1`, which in this engine is
        # a *dynamic* warp the engine fills in from wBackupWarpNumber.
        args = ([str(y), str(x)] if entry.macro == "warp_def"
                else spliced(entry, {W_Y: y, W_X: x}))
        ctx.replace_entry(ListKind.WARPS, index, args, macro="dummy_warp")
        return ctx.done(f"{map_const} warp #{index + 1} leads nowhere",
                        f"warp #{index + 1}: a door to nowhere")

    # A destination that was already there is not re-checked. Two warps in this
    # repo point at -1 — dynamic warps — and refusing to let you nudge one of those
    # a tile sideways, on the grounds that its destination is a number we would not
    # write ourselves, is refusing to leave alone what we cannot improve. You may
    # keep what is there. You may not type a new one that is wrong.
    kept = (entry.macro == "warp_def" and same(entry.args[W_MAP], dest)
            and same(entry.args[W_TO], dest_warp))
    if not kept:
        count = _warp_count(root, dest)
        if not 1 <= dest_warp <= count:
            raise WarpError(
                f"{dest} has {count} warp{'s' if count != 1 else ''}, so there is "
                f"no warp #{dest_warp} to come out of."
                if count else f"{dest} has no warps to come out of.")

    args = ([str(y), str(x), str(dest_warp), dest] if entry.macro == "dummy_warp"
            else spliced(entry, {W_Y: y, W_X: x, W_TO: dest_warp, W_MAP: dest}))
    ctx.replace_entry(ListKind.WARPS, index, args, macro="warp_def")
    return ctx.done(f"{map_const} warp #{index + 1} -> {dest} warp #{dest_warp}",
                    f"warp #{index + 1} -> {dest} #{dest_warp}")


def _warp_count(root: Path, dest: str) -> int:
    """How many warps the destination map has — what bounds a `warp_to`. Read from
    the destination's own file: this is the number the player's feet will meet."""
    label = {c: l for l, c in mapsource.header_pairs(root)}.get(dest)
    if label is None:
        raise WarpError(f"{dest} is not a map in this repo")
    try:
        return len(eh.parse_map(root / "maps" / f"{label}.asm").warps)
    except (eh.UnparseableHeader, FileNotFoundError) as exc:
        raise WarpError(f"{dest}'s event header can't be read, so its warps "
                        f"can't be counted: {exc}") from exc
