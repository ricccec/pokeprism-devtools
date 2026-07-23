"""Which hack is this tree. **The mount point.**

This is the one module allowed to know hack names — what a hack must *answer*
once mounted is `seam.py`, which knows none. The split is not filing: the seam
is a contract that outlives any hack in this repo, the mount is a list of the
hacks that happen to be here today, and the two change for unrelated reasons.

A tree is recognised by its **layout**, not by any name it might carry: the
file a hack cannot function without is the file that identifies it. Prism keeps
its secondary map headers in `maps/second_map_headers.asm`; the pokecrystal
family keeps everything under `data/maps/`, and within the family, polished is
the one whose map scripts start with the event block (`_MapScriptHeader:` at
the head) where vanilla ends with it (`_MapEvents:` at the tail).

What the mount returns is a :class:`~.seam.Hack`: a name for sentences, a read
adapter, a write adapter, and the declared capabilities. A capability the
adapter does not declare degrades to *absence* above the seam — never a crash,
and never an `if <hack name>`.
"""

from __future__ import annotations

import re
from pathlib import Path

from .seam import Hack


class UnknownTree(RuntimeError):
    """No adapter recognises this tree's layout. The message names what was
    found instead, because "unknown" is not actionable and "this looks like a
    pokecrystal checkout" is."""


def mount(root: Path) -> Hack:
    """The adapter for this tree, or :class:`UnknownTree`, loudly.

    Loud on purpose, and measured: before this gate existed, five of the eight
    prism parsers failed *silently* on a pokecrystal checkout (`None`, `[]`,
    `{}`), so the studio opened on one and reported an empty repo with a
    straight face. An error that names the tree beats a session that swears
    the repo has no maps in it.

    Imports run inside the branches: recognition is the mount's job, but
    building the adapter is the hack's, so each branch defers to its
    `hacks/<name>/claim` module — mounting a prism tree is what pulls in the
    linter, and a CLI that only probes pays for no reader, writer or linter.
    """
    if all((root / rel).exists() for rel in _PRISM_LAYOUT):
        from .prism.claim import build
        return build(root)

    if (root / "data/maps/maps.asm").exists():
        anchor = _family_anchor(root)
        if anchor == "_MapEvents":
            from .vanilla.claim import build
            return build(root)
        if anchor == "_MapScriptHeader":
            from .polished.claim import build
            return build(root)
        raise UnknownTree(
            f"{root} keeps map data under data/maps/ like the pokecrystal "
            "family, but no map file carries either family anchor "
            "(_MapEvents at the tail, _MapScriptHeader at the head), so no "
            "adapter can claim it.")

    missing = ", ".join(rel for rel in _PRISM_LAYOUT if not (root / rel).exists())
    raise UnknownTree(
        f"{root} is not a gen-2 map source layout these tools know "
        f"({missing} missing, and no data/maps/ either).")


#: The two files every prism map parser starts from. Their *presence* is what
#: makes a tree prism-shaped; every other gen-2 hack keeps these facts elsewhere.
_PRISM_LAYOUT = ("maps/second_map_headers.asm",
                 "constants/map_dimension_constants.asm")


def _family_anchor(root: Path) -> str:
    """Which event-block anchor the first listed map file carries. Within the
    pokecrystal family this is the one structural difference the mount needs:
    vanilla ends a map file with `<Label>_MapEvents:`, polished opens it with
    `<Label>_MapScriptHeader:`. "" when no map file can be probed at all."""
    listing = re.compile(r"^\s*map\s+(\w+)\s*,")
    try:
        lines = (root / "data/maps/maps.asm").read_text(encoding="utf-8")
    except OSError:
        return ""
    for m in map(listing.match, lines.splitlines()):
        if m is None:
            continue
        src = root / f"maps/{m.group(1)}.asm"
        if not src.exists():
            continue
        text = src.read_text(encoding="utf-8", errors="replace")
        for anchor in ("_MapEvents", "_MapScriptHeader"):
            if f"{m.group(1)}{anchor}:" in text:
                return anchor
    return ""
