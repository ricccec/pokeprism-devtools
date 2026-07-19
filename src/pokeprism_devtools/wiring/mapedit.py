"""Changing a map's own header: what it is made of, what plays, what it is called.

Two lines, in two files, and nothing else:

    map_header   Label, TILESET, PERMISSION, LANDMARK, MUSIC, phone, PALETTE, FISHGROUP
    map_header_2 Label, MAP_CONST, border_block, conn_flags

Both are rewritten in place, argument by argument, under the same rule the object
editor works by: **an argument you did not change comes back exactly as it was
written** (see `objedit.spliced`, whose `same()` this borrows). So a header whose
phone number is `$0` keeps its `$0`, and a form submitted untouched writes nothing.

**What is not here is the interesting part.**

*The label and the map id* are read-only. A rename is not a field — it touches
every reference to the map in the repo, and it is its own operation.

*The group* is read-only, and this is the one that would actually hurt. A map's id
is its **position inside its group**, so moving a map out of one group and into
another renumbers the ids of every map in both. Every reference in the source is
symbolic, so the ROM would be fine — but a `.sav` stores the numeric `(group, id)`
pair, so **every existing save file would drop the player onto the wrong map.**
That is not something a form field should be able to do while you were looking at
the music dropdown.

*The height and the width* are not fields here. The `mapgroup` line in
`constants/map_dimension_constants.asm` is where they live, and changing them
without resizing the `.blk` behind them — and, at the top or left, every
object's coordinates — corrupts the map. That is a real operation, with its own
refusals, and it lives in `wiring/mapresize.py` rather than as a field on this
form.

*conn_flags* is read-only because it is not a fact about the map — it is a summary
of the `connection` lines underneath it, and `connections._set_flag` already
recomputes it from the ones that are actually there. A header form that let you
type it could only ever disagree with the truth.
"""

from __future__ import annotations

import re

from pathlib import Path

from ..hacks.prism import mapsource
from ..shared.edits import Edit
from .objedit import Change, EditError, same

PRIMARY = "maps/map_headers.asm"
SECONDARY = "maps/second_map_headers.asm"

#: The `map_header` arguments after the label, in the order the macro takes them.
#: The form's field names are these, so the two cannot drift apart.
FIELDS = ("tileset", "permission", "landmark", "music", "phone", "palette",
          "fishgroup")

#: Where `border_block` sits in `map_header_2`'s arguments, after the label:
#: the map const, the border block, the connection flags.
BORDER = 1


def values(root: Path, label: str) -> dict[str, str]:
    """The header as it stands — what the form opens with.

    The read side is `mapsource`'s, which every other reader of these two lines
    already goes through. This module only writes.
    """
    primary = mapsource.primary_header(root, label)
    secondary = mapsource.secondary_header(root, label)
    if primary is None:
        raise EditError(f"{label} has no map_header line in {PRIMARY}")
    if secondary is None:
        raise EditError(f"{label} has no map_header_2 line in {SECONDARY}")
    return {
        "label": label,
        "const": secondary.const,
        "tileset": primary.tileset,
        "permission": primary.permission,
        "landmark": primary.landmark,
        "music": primary.music,
        "phone": str(primary.phone),
        "palette": primary.palette,
        "fishgroup": primary.fishgroup,
        "border_block": secondary.border_block,
    }


def edit_map(root: Path, label: str, new: dict[str, str]) -> Change:
    """Rewrite this map's two header lines with the values the form came back with."""
    was = values(root, label)
    edits = [
        _rewrite(root, PRIMARY, "map_header", label,
                 {i: new[f] for i, f in enumerate(FIELDS) if f in new},
                 f"{label}: map header"),
        _rewrite(root, SECONDARY, "map_header_2", label,
                 {BORDER: new["border_block"]} if "border_block" in new else {},
                 f"{label}: border block"),
    ]
    # Named one by one, because a header is a list of unrelated facts and "the map
    # header changed" tells you nothing about which of them you are agreeing to.
    moved = [f"{k} -> {new[k]}" for k in (*FIELDS, "border_block")
             if k in new and not same(was[k], new[k])]
    return Change(
        f"{label}: {', '.join(moved) if moved else 'nothing changed'}",
        edits,
        [] if any(e.changed for e in edits) else ["unchanged — nothing to write"],
    )


def _rewrite(root: Path, rel: str, macro: str, label: str,
             changed: dict[int, str], detail: str) -> Edit:
    """One `macro Label, …` line, with only these arguments replaced.

    Anchored on the label, so a map whose name is a prefix of another's
    (`Route30`, `Route30Gate`) is not matched by its neighbour's line — which is
    what `\\s*,` after the label is doing, and why this is not a bare substring
    search.
    """
    path = root / rel
    if not path.exists():
        raise EditError(f"{rel} is missing")
    original = path.read_text()
    lines = original.split("\n")

    rx = re.compile(
        rf"^(?P<head>\s*{macro}\s+{re.escape(label)}\s*,)"
        rf"(?P<args>.*?)(?P<comment>\s*;.*)?$")
    for i, line in enumerate(lines):
        m = rx.match(line)
        if not m:
            continue
        args = [a.strip() for a in m.group("args").split(",")]
        for at, value in changed.items():
            if at >= len(args):
                raise EditError(
                    f"{rel}:{i + 1}: this {macro} has {len(args)} arguments, so "
                    f"there is nothing at {at} to change.")
            if not same(args[at], value):
                args[at] = str(value).strip()
        rebuilt = f"{m.group('head')} {', '.join(args)}{m.group('comment') or ''}"
        if rebuilt == line:
            break                       # nothing moved: leave the line alone
        lines[i] = rebuilt
        text = "\n".join(lines)
        return Edit(rel, True, detail, text, base=original)
    else:
        raise EditError(f"{rel} has no {macro} line for {label}")

    return Edit(rel, False, detail, "", base=original)
