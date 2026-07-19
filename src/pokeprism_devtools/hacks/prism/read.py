"""Prism's read adapter: its maps, poured into the seam's records.

The port declares the vocabulary — `studio/panels` owns :class:`~...studio.
panels.Npc`, :class:`Warp`, :class:`Roof` and the rest — and this module fills
it in from prism's grammar. The import runs adapter → port on purpose: a record
the port declares is a record every adapter can fill without the port learning
any adapter's macros, which is the same arrangement `Attributes` and `WildMon`
already live under.

:class:`Reader` is what `hacks.mount` hands the studio for a prism tree. It is
constructed *with* the linter's context, so the catalog it answers from and the
linter's view of the repo are one parse — `Session._invalidate` keeps both
fresh with a single call, and the two can never disagree about which maps
exist.

The carve-up implemented in :func:`tables` is the seam's (a *person's*: NPCs
talk, trainers battle, objects lie on the floor), and prism's engine disagrees
with it twice — item balls are `person_event`s while hidden items are
`signpost`s, and both belong on the Objects tab. The one that had to be
*found* is the rock. A `SPRITE_ROCK` is a JUMPSTD like a mart clerk is, so it
sat on the NPC tab with a sprite box, a movement box and an empty field asking
what it says. It is not a person and it has never said anything; what makes it
not a person is written down in `eventmodel.Entry.prop`, and it is not the
sprite.
"""

from __future__ import annotations

import re
from functools import cached_property
from pathlib import Path

from ...studio import panels
from . import blocksrc, dialogue, eventheader as eh
from . import maps as maps_mod
from . import mapsource, roofs, swatches, textbox, wilddata

TRAINER_TYPES = ("PERSONTYPE_TRAINER", "PERSONTYPE_GENERICTRAINER")
PICKUP_TYPES = ("PERSONTYPE_ITEMBALL", "PERSONTYPE_TMHMBALL", "PERSONTYPE_FRUITTREE")
HIDDEN_ITEM = "SIGNPOST_ITEM"


class Reader:
    """One prism tree, answering the studio's questions in the seam's words.

    `ctx` is the linter's :class:`~...maplint.context.LintContext` — prism is
    the hack the linter is written against, so the adapter leans on the same
    cached parse the rules use rather than keeping a second copy of the truth.
    """

    def __init__(self, root: Path, ctx) -> None:
        self.root = root
        self.ctx = ctx

    # -- the catalog --------------------------------------------------------- #
    def maps(self) -> dict[str, str]:
        """label -> const, for every wired map."""
        return self.ctx.label_to_const

    def parses(self, const: str) -> bool:
        return self.ctx.header(const) is not None

    def connections(self, const: str) -> list[panels.Link]:
        """Prism's `connection` macro writes all four numbers down, so every
        computed column crosses filled."""
        return [panels.Link(direction=c.direction, target=c.target,
                            offset=c.offset, coord=c.coord, strip=c.strip)
                for c in self.ctx.connections_by_map.get(const, [])]

    # -- one map ------------------------------------------------------------- #
    def tables(self, label: str) -> panels.MapTables:
        """Everything standing on one map. Raises :class:`panels.Unreadable`
        with the parser's own sentence when the event header doesn't fit."""
        try:
            header = eh.parse_map(self.root / f"maps/{label}.asm")
        except (eh.UnparseableHeader, FileNotFoundError) as exc:
            raise panels.Unreadable(str(exc)) from exc
        return tables(header, self._says(label))

    def attributes(self, label: str, const: str) -> panels.Attributes:
        return _attributes(self.root, label, const)

    def geometry(self, label: str) -> panels.Blocks:
        """The map's shape. Raises :class:`panels.Unreadable` when the blocks
        can't be read — a map with no shape at all, unlike one whose header is
        broken, has nothing left to look at."""
        try:
            bd = blocksrc.load(self.root, label)
        except blocksrc.BlockSourceError as exc:
            raise panels.Unreadable(str(exc)) from exc
        return panels.Blocks(
            blocks=bd.blocks, height=bd.height, width=bd.width,
            swatches=swatches.for_map(self.root, bd.tileset_id, bd.permission))

    def wild(self, const: str) -> dict[str, dict[str, list[panels.WildMon]]]:
        return _wild(self.root, const)

    def roof(self, const: str) -> panels.Roof | None:
        """The roof the engine will actually load for this map's group —
        including the two ways prism's source disagrees with itself about it,
        which is :mod:`.roofs`' finding; this is only that finding crossing
        the seam. None for a map that is in no group at all."""
        d = _def(self.root, const)
        if d is None:
            return None
        r = roofs.for_group(self.root, d.group)
        return panels.Roof(group=r.group, tiles=r.tiles, tile_file=r.tile_file,
                           colors=r.colors, mislabelled=r.mislabelled,
                           past_end=r.past_end, entries=r.entries)

    # -- the words ----------------------------------------------------------- #
    def texts(self, label: str) -> list[panels.TextRef]:
        """Every text block in one map, as prose you could hand to a person.

        The macros are deliberately not here. `dialogue.plain` shows the words;
        `wiring/text.reword` puts the macros back from the block itself,
        positionally — so a `cont` that scrolls the box is still a `cont` after
        you fix a typo in it.
        """
        sign = self.boxes["sign"]
        return [
            panels.TextRef(label=b.label, owner=b.owner, lineno=b.lineno,
                           prose=dialogue.plain(b),
                           box="sign" if b.box.name == sign.name else "speech")
            for b in dialogue.parse(self.root, self.root / f"maps/{label}.asm")
        ]

    def measure(self, text: str, box: str) -> panels.TextPreview:
        """Dialogue-in-progress against the box it lands in.

        The same prose model the form submits: one line per screen line, a
        blank line starts a new box. Only *width* is checked, and that is not a
        shortcut — the third row of a box and every row after it are `cont`,
        which scrolls, so a speech can be any length. What it cannot be is wide.
        """
        b = self.boxes[box]
        return panels.TextPreview(b.name, b.cols, [
            self._measured(line, b.cols)
            for line in text.replace("\r\n", "\n").split("\n")
        ])

    def _measured(self, line: str, cols: int) -> panels.Measured:
        det, bnd, unb, unknown = self.ctx.textbox_metrics.tiles(self.root, line)
        return panels.Measured(text=line, tiles=det, bounded=bnd, unbounded=unb,
                               unknown=unknown, over=max(0, det - cols),
                               over_at_worst=max(0, det + bnd - cols))

    @cached_property
    def boxes(self) -> dict[str, textbox.Box]:
        return textbox.boxes(self.root)

    # -- what a form is sketching -------------------------------------------- #
    def sketch(self, action) -> panels.Blocks | None:
        """A picture of what an action would put on the grid, before it exists.

        Only the new-map action has anything to show — see `Action.sketch`.
        Raises `ActionError` for a form that isn't ready yet, which is the
        normal state of a form you are typing into, not a failure.
        """
        bd = action.sketch(self.root)
        if bd is None:
            return None
        return panels.Blocks(
            blocks=bd.blocks, height=bd.height, width=bd.width,
            swatches=swatches.for_map(self.root, bd.tileset_id, bd.permission),
            label=bd.name)

    def _says(self, label: str) -> dict[str, str]:
        """`text label -> its first words`, so the NPC table can show what an
        NPC actually says instead of the name of the block that says it.

        A map with a script this can't parse is a map whose NPCs simply have no
        preview — not a map that fails to open.
        """
        path = self.root / f"maps/{label}.asm"
        if not path.exists():
            return {}
        try:
            blocks = dialogue.parse(self.root, path)
        except Exception:                              # noqa: BLE001 - see above
            return {}
        out = {}
        for b in blocks:
            first = next((ln for ln in dialogue.plain(b).split("\n") if ln.strip()), "")
            out[b.label] = first[:40]
        return out


# --------------------------------------------------------------------------- #
# the event tables                                                            #
# --------------------------------------------------------------------------- #

def tables(header: eh.EventHeader, says: dict[str, str]) -> panels.MapTables:
    """One map's event header, carved into the six lists the tabs draw.

    `says` maps a text label to its first words, so an NPC's row can show what
    he actually says instead of the name of the block that says it.
    """
    npcs: list[panels.Npc] = []
    trainers: list[panels.Trainer] = []
    props: list[panels.Prop] = []

    for i, e in enumerate(header.object_events):
        if len(e.args) <= 9:
            continue
        h = eh.Handle(eh.ListKind.OBJECT_EVENTS, i)
        late = _late(header, eh.ListKind.OBJECT_EVENTS, i)
        y, x = e.coords

        if e.persontype in TRAINER_TYPES:
            # The flag that remembers you beat a trainer lives on the inline
            # `trainer` macro, not on his person_event — which carries a `-1`
            # where every other object keeps its flag. `trainer_of` walks there.
            t = eh.trainer_of(header, e)
            trainers.append(panels.Trainer(
                handle=h, index=i, y=y, x=x, sprite=e.sprite,
                cls=t.cls if t else "", party=t.party if t else "",
                sight=e.arg(10) if len(e.args) > 10 else "",
                flag=t.flag if t else "", undeclared=late))
        elif e.persontype in PICKUP_TYPES or e.prop is not None:
            # The item ball is the only one that carries a quantity: `\11` is
            # the count and `\12` the item. A TM ball spends `\11` on the item
            # itself and a fruit tree keeps its tree id in the pointer slot, so
            # for both of those the count column is meaningless rather than 1.
            if (prop := e.prop) is not None:
                # A rock's slot 11 is a std script id, and its "flag" is the -1
                # that means "always here" — the only thing a rock could be.
                kind, what = prop, e.arg(11)
            else:
                kind = e.persontype.replace("PERSONTYPE_", "").lower()
                what = e.pointer if e.persontype != "PERSONTYPE_TMHMBALL" else e.arg(10)
            props.append(panels.Prop(
                handle=h, index=i, y=y, x=x, kind=kind, what=what or "",
                qty=e.arg(10) if e.persontype == "PERSONTYPE_ITEMBALL" else "",
                flag=e.event_flag, undeclared=late))
        else:
            pointer = e.pointer or ""
            npcs.append(panels.Npc(
                handle=h, index=i, y=y, x=x, sprite=e.sprite,
                movement=e.movement.replace("SPRITEMOVEDATA_", ""),
                says=says.get(pointer, pointer), flag=e.event_flag,
                undeclared=late))

    signs: list[panels.Signpost] = []
    for i, e in enumerate(header.bg_events):
        h = eh.Handle(eh.ListKind.BG_EVENTS, i)
        late = _late(header, eh.ListKind.BG_EVENTS, i)
        y, x = e.coords
        kind = e.arg(2) if len(e.args) > 2 else ""
        if kind == HIDDEN_ITEM:
            # A hidden item's item and flag are in the record it points at, not
            # in the bg_event: `dw EVENT_… / db ITEM`. It goes on the Objects
            # tab: it is a thing on the floor, however the engine files it.
            record = eh.script_block(header, e.pointer)
            flag = next((ln.split()[-1] for ln in record
                         if ln.strip().startswith("dw ")), "")
            item = next((ln.split()[-1] for ln in record
                         if ln.strip().startswith("db ")), "")
            props.append(panels.Prop(
                handle=h, index=i, y=y, x=x, kind="hidden", what=item, qty="",
                flag=flag, undeclared=late))
        else:
            signs.append(panels.Signpost(
                handle=h, index=i, y=y, x=x,
                kind=kind.replace("SIGNPOST_", ""), points_at=e.pointer or "",
                undeclared=late))

    warps = [panels.Warp(
                handle=eh.Handle(eh.ListKind.WARPS, i), index=i,
                y=e.coords[0], x=e.coords[1],
                # warp_def y, x, id, map — `id` indexes the destination's list.
                to_map=e.arg(3) if len(e.args) > 3 else "",
                their_warp=e.arg(2) if len(e.args) > 2 else "",
                undeclared=_late(header, eh.ListKind.WARPS, i))
             for i, e in enumerate(header.warps)]

    triggers = [panels.Trigger(
                    handle=eh.Handle(eh.ListKind.COORD_EVENTS, i), index=i,
                    y=e.coords[0], x=e.coords[1], scene=e.arg(0),
                    runs=e.pointer or "",
                    undeclared=_late(header, eh.ListKind.COORD_EVENTS, i))
                for i, e in enumerate(header.coord_events)]

    return panels.MapTables(npcs=npcs, trainers=trainers, props=props,
                            signposts=signs, warps=warps, triggers=triggers,
                            marks=eh.markers(header))


def _late(header: eh.EventHeader, kind: eh.ListKind, i: int) -> bool:
    """Past the list's `db N`: written down, and not in the game. The count
    byte is prism's alone in its family — the `def_*` macros self-count — so
    only this adapter ever sets the flag."""
    return i >= header.lists[kind].declared_count


# --------------------------------------------------------------------------- #
# the header facts                                                            #
# --------------------------------------------------------------------------- #

#: A map's three relocatable blobs, and the line that marks each one. Only these
#: three ever get a bank: the primary `map_header` is a positional line inside
#: `MapGroupN` and has no section of its own, which is why the new-map form's
#: Bank field has never mentioned it.
#:
#: The section a blob lives in is **found, not assumed**. A new map gets a
#: section of its own (`Map block data <Label>`), but the maps already in the
#: game mostly sit in shared ones — OxalisCity's blocks are in "Map block data 4"
#: along with a dozen others. Guessing the per-map name would report every
#: shipped map as unpinned, which is both wrong and exactly backwards.
BLOBS = ("block data", "script", "secondary header")


def _def(root: Path, const: str) -> maps_mod.MapDef | None:
    dims = root / "constants/map_dimension_constants.asm"
    if not dims.exists():
        return None
    return next((d for d in maps_mod.parse_maps(dims) if d.name == const), None)


def _attributes(root: Path, label: str, const: str) -> panels.Attributes:
    """A map's header, reassembled out of the five files that hold a piece of it.

    Every lookup here can come back empty, and none of them is fatal: a map
    part-way through being wired is a map you especially want to be able to look
    at. What you get for a missing piece is a dash, not an exception.
    """
    d = _def(root, const)
    p = mapsource.primary_header(root, label)
    s = mapsource.secondary_header(root, label)

    return panels.Attributes(
        label=label, const=const,
        group=d.group if d else 0, map_id=d.map_id if d else 0,
        height=d.height if d else 0, width=d.width if d else 0,
        blk=mapsource.blk_path(root, label) or "—",
        tileset=p.tileset if p else "—",
        permission=p.permission if p else "—",
        landmark=p.landmark if p else "—",
        music=p.music if p else "—",
        palette=p.palette if p else "—",
        fishgroup=p.fishgroup if p else "—",
        phone=str(p.phone) if p else "0",
        border_block=s.border_block if s else "—",
        banks=_banks(root, label),
    )


def _banks(root: Path, label: str) -> dict[str, str]:
    """Which SECTION each of the map's three blobs sits in, and its bank.

    The section is located by *finding the line and looking up* — see
    :data:`BLOBS`. A blob whose section isn't pinned in `contents/romx.link` is
    floating, which is a real and normal state (rgblink places it), not a fault.
    """
    pinned = mapsource.section_banks(root)
    script = mapsource.script_path(root, label)
    finders = {
        "block data": ("maps/blockdata.asm",
                       lambda ln: ln.strip() == f"{label}_BlockData:"),
        "script": ("maps/map_scripts.asm",
                   lambda ln: bool(script) and ln.strip() == f'INCLUDE "{script}"'),
        "secondary header": ("maps/second_map_headers.asm",
                             lambda ln: _HEADER_2(label).match(ln) is not None),
    }

    out: dict[str, str] = {}
    for blob, (rel, matches) in finders.items():
        path = root / rel
        section = mapsource.enclosing_section(path, matches) if path.exists() else None
        if section is None:
            out[blob] = "not wired — no such line in " + rel
        elif (bank := pinned.get(section)) is not None:
            out[blob] = f"${bank:02X}   in “{section}”"
        else:
            out[blob] = f"floating — “{section}” is not pinned to a bank"
    return out


def _HEADER_2(label: str) -> re.Pattern[str]:
    return re.compile(rf"^\s*map_header_2\s+{re.escape(label)}\s*,")


def _wild(root: Path, const: str) -> dict[str, dict[str, list[panels.WildMon]]]:
    """The map's encounters, in the seam's words. A map with none is the common
    case, not an error — most maps are indoors.

    Prism's mon is a scalar species, so `WildMon.form` is filled with its
    constant, `""` — the form column exists for the hacks whose mon is
    `(species, form)`, and an adapter without forms never has to say so.
    """
    found: dict[str, dict[str, list[panels.WildMon]]] = {}
    for kind in (wilddata.GRASS, wilddata.WATER):
        try:
            table = wilddata.table_for(root, const, kind)
        except wilddata.WildDataError:
            continue
        for block in table.blocks:
            if block.map_const == const:
                found[kind] = {time: [panels.WildMon(e.level, e.species)
                                      for e in mons]
                               for time, mons in block.mons.items()}
    return found
