"""Which hack is this tree, and what can be done with it. **The mount point.**

This is the one module allowed to know hack names. Everything above it — the
session, the reader, the view — speaks to whatever :func:`mount` hands back and
branches only on the *capabilities* it declares, never on the name; everything
below it lives in a `hacks/<name>/` package and knows only its own dialect.
`docs/adapter-plan.md` argues the line, `docs/polished-crystal-feasibility.md`
measures it.

A tree is recognised by its **layout**, not by any name it might carry: the
file a hack cannot function without is the file that identifies it. Prism keeps
its secondary map headers in `maps/second_map_headers.asm`; the pokecrystal
family keeps everything under `data/maps/`, and within the family, polished is
the one whose map scripts start with the event block (`_MapScriptHeader:` at
the head) where vanilla ends with it (`_MapEvents:` at the tail).

What the mount returns
----------------------
A :class:`Hack`: a name for sentences, a read adapter, and the declared
capabilities. The read adapter answers the studio's questions in the seam's
records (see `studio/panels`); the protocol is whatever `studio/reader` and
`Session` ask of it —

    maps() -> {label: const}                 the catalog
    parses(const) -> bool
    connections(const) -> [panels.Link]
    tables(label) -> panels.MapTables        raises panels.Unreadable
    attributes(label, const) -> panels.Attributes
    geometry(label) -> panels.Blocks         raises panels.Unreadable
    wild(const) -> {table: {time: [panels.WildMon]}}
    roof(const) -> panels.Roof | None
    texts(label) -> [panels.TextRef]
    measure(text, box) -> panels.TextPreview    (measures=True only)
    sketch(action) -> panels.Blocks | None      (writes=True only)

A capability the adapter does not declare degrades to *absence* above the
seam: no Diagnostics findings, no edit forms, no boot key — never a crash, and
never an `if <hack name>`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class UnknownTree(RuntimeError):
    """No adapter recognises this tree's layout. The message names what was
    found instead, because "unknown" is not actionable and "this looks like a
    pokecrystal checkout" is."""


@dataclass(frozen=True)
class Hack:
    """One mounted tree: its adapter, and what it declared it can do."""
    name: str
    #: The read adapter — see the module docstring for the questions it answers.
    reads: Any
    #: The linter's context, for the hack the linter is written against. The
    #: session lints exactly when this is not None, and hands it back to
    #: everything that asks repo-wide questions.
    ctx: Any = None
    #: The studio's actions, forms and undo apply to this tree.
    writes: bool = False
    #: Build-and-boot (a patched save, an emulator) is wired for this tree.
    plays: bool = False
    #: Text is measured in tiles against a VWF engine (prism physics).
    measures: bool = False


def mount(root: Path) -> Hack:
    """The adapter for this tree, or :class:`UnknownTree`, loudly.

    Loud on purpose, and measured: before this gate existed, five of the eight
    prism parsers failed *silently* on a pokecrystal checkout (`None`, `[]`,
    `{}`), so the studio opened on one and reported an empty repo with a
    straight face. An error that names the tree beats a session that swears
    the repo has no maps in it.

    Imports run inside the branches: mounting a prism tree is what pulls in
    the linter, and a CLI that only probes pays for no adapter at all.
    """
    if all((root / rel).exists() for rel in _PRISM_LAYOUT):
        from ..maplint.context import LintContext
        from .prism.read import Reader
        ctx = LintContext(root)
        return Hack("prism", Reader(root, ctx), ctx=ctx,
                    writes=True, plays=True, measures=True)

    if (root / "data/maps/maps.asm").exists():
        anchor = _family_anchor(root)
        if anchor == "_MapEvents":
            from .vanilla.read import Reader
            return Hack("vanilla", Reader(root))
        if anchor == "_MapScriptHeader":
            raise UnknownTree(
                f"{root} is a polished-family checkout (its map files open "
                "with the event block) — that read adapter is the last slice "
                "of Phase 3 in docs/polished-crystal-feasibility.md and is "
                "not built yet.")
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
