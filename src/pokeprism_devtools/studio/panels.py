"""What goes in the tables under the grid — and what a selected row *is*.

Pure functions: each returns `(columns, rows)`, so the contents of every tab can
be tested without starting a terminal and the widgets stay dumb. Nothing here
opens a file — and nothing here parses one either. Each tab's input is a
**declared record** (:class:`Npc`, :class:`Warp`, :class:`WildMon`, …), the
`Attributes` pattern throughout: this side declares the vocabulary, the reading
side — an adapter, `hacks/prism/read` today — fills it in from whatever its
grammar happens to be. Which entry is an NPC and which is an item ball is a
reading of one hack's macros, so the *classification* lives with the adapter
too; this side renders six lists it is handed and never learns what a
`person_event` is.

The six lists are still a *person's* carve-up of a map, not any engine's, and
the carve-up itself is this side's to declare: things that talk (NPCs), things
that battle (Trainers), things lying about on the floor (Objects — item balls,
rocks, and the hidden items the engine files under signs), things you read
(Signposts), places you leave from (Warps), and tiles that fire (Triggers).
An adapter's job is to pour its own lists into those six, however its engine
happens to shelve them.

Every coordinate shown is the number **written in the source**, because that is
the number you would type to change it. Offsets a macro adds while assembling
belong to the assembled bytes and appear nowhere in this file — and a hack that
writes (x, y) has already been turned around by its adapter, the way
`shared.coords.Tile` says.
"""

from __future__ import annotations

from collections.abc import Hashable
from dataclasses import dataclass, field

from ..shared.coords import Tile

_NONE = "—"


class Unreadable(RuntimeError):
    """An adapter's answer when a map's source cannot be read into records —
    the event block doesn't fit its shape, the blocks file is missing. The
    message is the interesting part: it is what the view shows in place of the
    tables, so it should name the file and the way it disappointed."""


# --------------------------------------------------------------------------- #
# what a row is                                                               #
# --------------------------------------------------------------------------- #

#: The `what` of the Ref an "Add new…" row carries. Minted by :func:`add_ref`,
#: recognised by the session's adders — the view only ever sees it as a truthy
#: :attr:`Ref.adds`.
ADD = "add"


@dataclass(frozen=True)
class Ref:
    """What `e` and `d` act on: enough to name one thing on one map.

    **Opaque to the view.** `tabs.py` reads a Ref off the highlighted row and
    hands it straight back to the session, which is the only side of the seam
    allowed to know a `person_event` from a `signpost`. The view's whole share
    of the knowledge is the three declared affordances — "this row names
    something" (the Ref exists at all), :attr:`adds`, :attr:`deletable` — plus
    equality, for finding the row that carries a Ref again. The *fields* are the
    port's own, and no view code may read them.

    Identity itself is not even the port's: it is the adapter's **handle**,
    carried whole and resolved by handing it back. Prism's is a list kind and a
    position, because that is all its source can say about an object; vanilla's
    carries the `object_const_def` name its scripts address the object by. The
    port stores whatever it was given and does no arithmetic on it — all it
    needs of a handle is equality, for finding the row that carries it again.
    A prop's handle can name either engine list — a hidden item is filed with
    the signs — which is exactly why the list is in the handle and not implied
    by `what`.
    """
    #: npc | trainer | prop | signpost | warp | trigger | connection | map
    what: str
    #: The adapter's name for the entry, when this row is one. None for the rows
    #: that are not event entries: the map itself, a connection, "Add new…".
    handle: Hashable | None = None
    #: A connection's direction, or the kind an "Add new…" row offers.
    key: str = ""

    # -- the view-facing surface -------------------------------------------- #
    @property
    def adds(self) -> str:
        """The kind of thing this row would add — the word the tab declared in
        `Tab.adds` — or "" for a row that names something that already exists."""
        return self.key if self.what == ADD else ""

    @property
    def deletable(self) -> bool:
        """Whether `d` exists on this row. The map's own rows say no — deleting
        a whole map is not something the studio does — and so does an "Add
        new…" row, which names nothing yet."""
        return self.what not in (ADD, "map")


def add_ref(kind: str) -> Ref:
    """The Ref an "Add new…" row carries. Minted here, on the port side, so the
    view never assembles a Ref of its own — it draws the dim row because
    `Tab.adds` told it to, and hands back what it was given."""
    return Ref(ADD, key=kind)


@dataclass(frozen=True)
class Row:
    cells: list[str]
    #: None for a row that names nothing you can act on — a wild encounter, a
    #: roof colour. The footer reads this to decide whether `e` and `d` exist.
    ref: Ref | None = None
    #: Where this row's object stands, in coordinate tiles — which is what makes
    #: the grid a way to *navigate* rather than a picture beside the table: point
    #: at a tile, and the row that owns it is the row that says so here.
    #:
    #: The number written in the source, like every other coordinate on this side
    #: of the seam, and that is not a coincidence — a coordinate tile *is* the
    #: source number. The `+4` the `person_event` macro adds exists only in the
    #: assembled struct, which is why `play.boot` can hand the grid's cursor
    #: straight to `wYCoord` and be right.
    #:
    #: None for a row that is not on the map at all: a connection is a property of
    #: the whole edge, a wild encounter is not a place.
    tile: Tile | None = None


Table = tuple[list[str], list[Row]]


@dataclass(frozen=True)
class Tab:
    """One tab: its table, and what "Add new…" would mean on it."""
    name: str
    table: Table
    #: What the dim last row offers, e.g. "NPC". Empty = no adding here (Wild,
    #: Roof, Attributes), and the row is not drawn at all.
    adds: str = ""
    #: Why this tab is read-only, when it is. Shown above the table.
    note: str = ""


#: The studio shows wild encounters and will not edit them, and that had better
#: be on screen rather than in a design document: a wild record is a fixed-size
#: slot in a table the engine indexes by *position*, so writing a short one
#: silently shifts every map below it onto somebody else's Pokémon.
WILD_IS_READ_ONLY = (
    "read-only — wild records are fixed-size and read by position; "
    "a short one shifts every map below it. Edit data/wild/*.asm by hand."
)

ROOF_IS_READ_ONLY = (
    "read-only — a roof belongs to the whole map group, not to this map. "
    "Editing it here would repaint every town in the group."
)


#: Marks a row whose entry is in the file but past its list's count byte. The
#: engine reads `db N` and stops, so it is written down and not in the game.
#: Only an adapter whose lists *have* a count byte can ever set the flag this
#: renders — prism's `db N` is the outlier; the `def_*` macros self-count, so a
#: vanilla or polished row simply never carries it.
UNDECLARED = "⚠"


# --------------------------------------------------------------------------- #
# what crosses the seam: one record per kind of thing on a map                #
# --------------------------------------------------------------------------- #
#
# Filled by the adapter, rendered here. Shared conventions:
#
#   handle       the adapter's name for the entry, carried into the row's Ref
#   index        the entry's position in the engine list it came from — the
#                number scripts address it by where scripts do that — not its
#                position on the tab, which cuts three tabs out of one list
#   y, x         the numbers written in the source, or None where the source
#                writes an expression; the row still exists, the grid just
#                can't point at it
#   undeclared   in the file but past a count byte the engine trusts — see
#                :data:`UNDECLARED`
#
# Display strings (sprite, movement, kind, …) arrive display-ready: the adapter
# knows its own prefixes (`SPRITEMOVEDATA_`, `SIGNPOST_`, `BGEVENT_`) and strips
# them before crossing; "" means "nothing to say" and renders as a dash.

@dataclass(frozen=True)
class Npc:
    handle: Hashable
    index: int
    y: int | None
    x: int | None
    sprite: str
    movement: str
    says: str            # what they say, or the label that says it — resolved
    flag: str
    undeclared: bool = False


@dataclass(frozen=True)
class Trainer:
    handle: Hashable
    index: int
    y: int | None
    x: int | None
    sprite: str
    cls: str             # trainer class
    party: str           # prism's 1-based ordinal; a name where hacks name them
    sight: str
    flag: str            # the flag that remembers you beat them
    undeclared: bool = False


@dataclass(frozen=True)
class Prop:
    """Something lying about: an item ball, a fruit tree, a rock, a hidden item."""
    handle: Hashable
    index: int
    y: int | None
    x: int | None
    kind: str            # "itemball", "hidden", "rock", …: the adapter's word
    what: str            # the item, the tree id, the std script
    qty: str             # "" for the kinds where a count would be meaningless
    flag: str
    undeclared: bool = False


@dataclass(frozen=True)
class Signpost:
    handle: Hashable
    index: int
    y: int | None
    x: int | None
    kind: str
    points_at: str
    undeclared: bool = False


@dataclass(frozen=True)
class Warp:
    handle: Hashable
    index: int
    y: int | None
    x: int | None
    to_map: str
    their_warp: str      # index into the *destination's* warp list, 1-based
    undeclared: bool = False


@dataclass(frozen=True)
class Trigger:
    handle: Hashable
    index: int
    y: int | None
    x: int | None
    scene: str
    runs: str
    undeclared: bool = False


@dataclass(frozen=True)
class MapTables:
    """Everything standing on one map, already carved into the six lists the
    tabs draw. The adapter's whole answer about a map's events — plus `marks`,
    the same objects again as glyphs for the grid, so the two pictures come
    from one enumeration and cannot disagree."""
    npcs: list[Npc]
    trainers: list[Trainer]
    props: list[Prop]
    signposts: list[Signpost]
    warps: list[Warp]
    triggers: list[Trigger]
    marks: dict[Tile, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Link:
    """One edge connection, in the seam's words. Prism writes all four numbers
    in its `connection` macro; the modern `def_*` dialect declares only the
    offset and computes the rest at assembly — so the computed columns are
    None there, and appear only when some row fills them."""
    direction: str
    target: str
    offset: int
    coord: int | None = None
    strip: int | None = None

    @property
    def delta(self) -> int | None:
        """The alignment between the two maps' coordinate systems. The map on
        the other side must carry exactly its negation, or the seam tears."""
        return None if self.coord is None else self.coord - self.offset


Rgb = tuple[int, int, int]

#: A block's four quadrant colors, in reading order. Not an arbitrary carve-up:
#: a block is 2×2 coordinate tiles, so one swatch quadrant is exactly one place
#: you can stand, and the grid's cursor lands on a quadrant. How an adapter
#: arrives at the four colors is its own affair — prism averages real pixels,
#: an adapter without decoded graphics may answer from palettes alone.
Swatch = tuple[Rgb, Rgb, Rgb, Rgb]


@dataclass(frozen=True)
class Blocks:
    """A map's shape as the adapter read it: the block bytes, the size in
    blocks, and one swatch per block id the bytes index into."""
    blocks: bytes
    height: int
    width: int
    swatches: tuple[Swatch, ...]
    #: A name for shapes that aren't a wired map yet — a sketch of a map being
    #: made carries the name typed into the form. "" for an existing map, whose
    #: caller already knows what it asked for.
    label: str = ""


@dataclass(frozen=True)
class Sketch:
    """A grid a form drew, before the tree has put colour on it.

    The counterpart to :class:`Blocks`, and it exists for one reason: the
    family's new-map form is *neutral studio code* while the colours are not.
    A grid file is bytes anywhere, but a tileset name means something only to
    the tree that defines the constant — so the form answers with the grid and
    the name it was given, and each family reader turns that into `Blocks` with
    its own swatches. Prism needs no such record: its action and its reader are
    the same adapter, so it hands itself its own (see `Action.sketch`).
    """
    blocks: bytes
    height: int
    width: int
    #: The tileset constant as typed — `TILESET_JOHTO`. Empty when the tree's
    #: header takes no tileset at all, which is drawn uncoloured rather than
    #: refused: the shape is the half of the picture that catches a wrong
    #: height, and it is still worth seeing without the hue.
    tileset: str = ""
    label: str = ""


def _yx(r) -> tuple[str, str]:
    return (_NONE if r.y is None else str(r.y), _NONE if r.x is None else str(r.x))


def _num(r, shown: int | None = None) -> str:
    """The `#` cell — and a mark on it when the engine will never get this far.

    PhloxLab1F says `db 6 ; FIXME` over seven `person_event`s, so its seventh
    object — a Max Revive on the floor — is in the source and not in the game.
    The row is here because *the line is in the file*: the way to fix an object
    that doesn't spawn is to look at it, and a table that hid it left you staring
    at a map with a ball drawn on it that the studio said did not exist. What it
    cannot do is pretend the count byte is right, so the row says so, and the
    linter's `obj-count` says why.
    """
    n = r.index if shown is None else shown
    return f"{n} {UNDECLARED}" if r.undeclared else str(n)


#: The columns that hold numbers. A DataTable column is as wide as its widest
#: cell, and the dim "Add new NPC…" row at the foot of every tab was putting
#: twenty characters of prose in the first one — so `#`, a column of single
#: digits, was drawn twenty cells wide on every tab, and every number in it sat
#: under a stripe of empty air. The prompt has to go somewhere; it goes in the
#: first column that is *words*, where its width costs nothing.
NUMERIC = {"#", "y", "x", "qty", "scene", "sight", "coord", "offset", "strip", "delta"}


def prompt_column(cols: list[str]) -> int:
    """Which cell of the "Add new…" row its words are written in.

    Never column 0, which is where the ▸ goes: one cell wide, and a caret at the
    left edge is what makes the row scan as a row you can stand on.
    """
    return next((i for i, name in enumerate(cols) if i and name not in NUMERIC), 0)


def _tile(r) -> Tile | None:
    """The tile it stands on, or None when the coordinates aren't literal numbers.

    An object whose `y` is a constant expression rather than a number still gets a
    row — you can see it and delete it — but nothing can point at it on the grid,
    and pretending otherwise would put it at (0, 0).
    """
    return None if r.y is None or r.x is None else Tile(y=r.y, x=r.x)


# --------------------------------------------------------------------------- #
# the object tabs                                                             #
# --------------------------------------------------------------------------- #

def npcs(recs: list[Npc]) -> Table:
    cols = ["#", "y", "x", "sprite", "movement", "says", "event flag"]
    rows = [Row([_num(r), *_yx(r), r.sprite, r.movement, r.says or _NONE, r.flag],
                Ref("npc", r.handle), _tile(r))
            for r in recs]
    return cols, rows


def trainers(recs: list[Trainer]) -> Table:
    cols = ["#", "y", "x", "sprite", "class", "party", "sight", "event flag"]
    rows = [Row([_num(r), *_yx(r), r.sprite, r.cls or _NONE, r.party or _NONE,
                 r.sight or _NONE, r.flag or _NONE],
                Ref("trainer", r.handle), _tile(r))
            for r in recs]
    return cols, rows


def objects(recs: list[Prop]) -> Table:
    """Item balls, TM balls, fruit trees, rocks, boulders — and the hidden items,
    which an engine may keep in the other list entirely. See the module
    docstring: none of them is a person, and that is what the tab is for."""
    cols = ["#", "y", "x", "kind", "what", "qty", "event flag"]
    rows = [Row([_num(r), *_yx(r), r.kind, r.what or _NONE, r.qty or _NONE,
                 r.flag or _NONE],
                Ref("prop", r.handle), _tile(r))
            for r in recs]
    return cols, rows


def signposts(recs: list[Signpost]) -> Table:
    """Every sign — the things you read. The hidden items an engine files with
    them are on the Objects tab, where a person would look."""
    cols = ["#", "y", "x", "kind", "points at"]
    rows = [Row([_num(r), *_yx(r), r.kind or _NONE, r.points_at or _NONE],
                Ref("signpost", r.handle), _tile(r))
            for r in recs]
    return cols, rows


def warps(recs: list[Warp]) -> Table:
    """`their warp #` is an index into the *destination* map's warp list, not a
    map id. Off by one and you land in the wrong doorway."""
    cols = ["#", "y", "x", "to map", "their warp #"]
    rows = [Row([_num(r, r.index + 1), *_yx(r), r.to_map or _NONE,
                 r.their_warp or _NONE],
                Ref("warp", r.handle), _tile(r))
            for r in recs]
    return cols, rows


def triggers(recs: list[Trigger]) -> Table:
    cols = ["#", "scene", "y", "x", "runs"]
    rows = [Row([_num(r), r.scene, *_yx(r), r.runs or _NONE],
                Ref("trigger", r.handle), _tile(r))
            for r in recs]
    return cols, rows


def connections(links: list[Link]) -> Table:
    """`delta` is the alignment between the two maps' coordinate systems. The
    map on the other side must carry exactly its negation, or the seam tears —
    which is why it's a column and not a detail.

    The computed columns exist only when some row fills them: the modern
    `def_*` dialect writes just the offset and lets the assembler derive the
    rest, so there is nothing written in the source for those cells to show.
    """
    links = sorted(links, key=lambda c: c.direction)
    computed = any(c.coord is not None for c in links)
    cols = (["direction", "to map", "coord", "offset", "strip", "delta"]
            if computed else ["direction", "to map", "offset"])
    rows = []
    for c in links:
        cells = [c.direction, c.target]
        if computed:
            cells += [_NONE if c.coord is None else str(c.coord), str(c.offset),
                      _NONE if c.strip is None else str(c.strip),
                      _NONE if c.delta is None else f"{c.delta:+d}"]
        else:
            cells += [str(c.offset)]
        rows.append(Row(cells, Ref("connection", key=c.direction)))
    return cols, rows


# --------------------------------------------------------------------------- #
# the read-only tabs                                                          #
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Attributes:
    """A map's header, as it is written down. Assembled by the session, which is
    the side that knows which five files these eight facts are spread across."""
    label: str
    const: str
    group: int
    map_id: int
    height: int
    width: int
    tileset: str = _NONE
    permission: str = _NONE
    landmark: str = _NONE
    music: str = _NONE
    palette: str = _NONE
    fishgroup: str = _NONE
    phone: str = "0"
    border_block: str = _NONE
    blk: str = _NONE
    #: section name -> the bank it is pinned to in contents/romx.link, or "" for
    #: a section that floats. Three of them: blockdata, script, secondary.
    banks: dict[str, str] = field(default_factory=dict)


def attributes(attrs: Attributes) -> Table:
    """The map itself, as a field/value table. Every row carries the same Ref, so
    `e` opens the map form wherever the cursor happens to be sitting."""
    ref = Ref("map")
    pairs = [
        ("Label", attrs.label),
        ("Map id", attrs.const),
        ("Group", f"{attrs.group}  (map {attrs.map_id} within it)"),
        ("Size", f"{attrs.height} × {attrs.width} blocks"),
        ("Blocks", attrs.blk),
        ("Tileset", attrs.tileset),
        ("Permission", attrs.permission),
        ("Landmark", attrs.landmark),
        ("Music", attrs.music),
        ("Palette", attrs.palette),
        ("Fish group", attrs.fishgroup),
        ("Phone service", attrs.phone),
        ("Border block", attrs.border_block),
    ]
    pairs += [(f"Section: {name}", bank or "floating — not pinned to a bank")
              for name, bank in attrs.banks.items()]
    return ["field", "value"], [Row([k, v], ref) for k, v in pairs]


@dataclass(frozen=True)
class Roof:
    """The roof a map group loads, in the seam's words — including the two ways
    a source can disagree with itself about it, which are facts about the tree
    and so cross as data, not as prose only one adapter could write."""
    group: int
    #: Index into the roof-tiles table, or None when the group has no roof.
    tiles: int | None = None
    #: The tiles file that index names, if it exists. None for an index with no
    #: file behind it — itself worth knowing: the engine will copy whatever
    #: bytes follow the last roof.
    tile_file: str | None = None
    #: morn/day ×2, then nite ×2, as `#rrggbb`.
    colors: tuple[str, str, str, str] | None = None
    #: What the source's comment *says* this byte belongs to, when that is not
    #: this group. Prism's roofs.asm disagrees with its own engine on every row.
    mislabelled: int | None = None
    #: The group is past the end of the roof table — which is not "no roof":
    #: the engine indexes the table unconditionally and reads whatever
    #: assembles next as a roof index.
    past_end: bool = False
    #: How many entries the table actually has, for saying how far past.
    entries: int = 0


def roof(r: Roof) -> Table:
    """The roof the engine loads for this map's group — and the two ways the
    source disagrees with itself about it.

    Both are worth a row rather than a footnote. `MapGroupRoofs` is indexed by
    the group number with no adjustment, but every byte in it is commented with
    the group *after* the one that reads it; and the table has 28 entries while
    the game has 96 map groups, so most groups index past its end and pick up
    whatever assembles next as a roof. Neither is this tool's to fix. Both are
    things you would want to know before wondering why your town has no roof.
    """
    cols = ["field", "value"]
    rows = [Row(["Group", str(r.group)])]

    if r.past_end:
        rows.append(Row([
            "Roof", f"group {r.group} is past the end of MapGroupRoofs, which "
                    f"has {r.entries} entries. The engine still indexes it, so "
                    f"it reads whatever assembles after the table."]))
    elif r.tiles is None:
        rows.append(Row(["Roof", "none — MapGroupRoofs says -1 for this group"]))
    else:
        rows.append(Row(["Roof tiles", r.tile_file or
                         f"roof {r.tiles}, which has no file behind it"]))

    if r.colors:
        morn, day, nite1, nite2 = r.colors
        rows.append(Row(["Morn / day", f"{morn}   {day}"]))
        rows.append(Row(["Nite", f"{nite1}   {nite2}"]))

    if r.mislabelled is not None:
        rows.append(Row([
            "⚠ source", f"roofs.asm comments this byte '; group {r.mislabelled}', "
                        f"but the engine reads it for group {r.group} "
                        f"(LoadMapGroupRoof indexes by wMapGroup, no offset)."]))
    return cols, rows


@dataclass(frozen=True)
class WildMon:
    """One encounter slot, in the seam's words.

    `form` is the axis polished adds: a mon there is `(species, form)`, with the
    ninth species bit living in the form byte. The hacks whose mon is a scalar —
    prism is one — fill it with the constant ``""``, and the column below only
    exists when some row doesn't. That is the whole negotiation: an adapter that
    has no forms never says so, it just has nothing to show.
    """
    level: int
    species: str
    form: str = ""


@dataclass(frozen=True)
class TextRef:
    """A block of dialogue already in the game, as prose. The adapter parses
    its own text macros into this; the macros go back positionally on the way
    home (`wiring/text.reword`), which is what lets the record hold none."""
    label: str          # what a script jumps to, or `.local` under an owner
    owner: str          # the top-level label that owns it
    lineno: int
    prose: str
    #: Which box it is drawn in — the key :meth:`Session.measure` takes. Nearly
    #: everything is "speech"; the full-screen "sign" box is the rarity.
    box: str

    @property
    def opening(self) -> str:
        """Its first words, for a list you are choosing from."""
        first = next((line for line in self.prose.split("\n") if line.strip()), "")
        return first[:40]


@dataclass(frozen=True)
class Measured:
    """One line of dialogue, as the engine will draw it."""
    text: str
    #: Tiles it certainly prints. `#` is four of them.
    tiles: int
    #: Extra tiles if every bounded buffer (`<PLAYER>`, `<RIVAL>`) is at its
    #: longest. A line that fits *today* and not when the player is called
    #: BARTHOLOMEW is a line that overflows in somebody's game and not in yours.
    bounded: int
    #: Tokens whose length can't be bounded from the text at all (`<STRBF1>`).
    unbounded: list[str]
    #: Tokens with no charmap entry — a typo'd `<PLAYR>` prints as garbage.
    unknown: list[str]
    #: How many tiles past the right edge. 0 fits.
    over: int
    #: How many it would be over at the buffers' worst.
    over_at_worst: int


@dataclass(frozen=True)
class TextPreview:
    """A whole speech, measured against the box it will be drawn in."""
    box: str                # what to call it: "speech textbox", "signpost"
    cols: int               # tiles per line
    lines: list[Measured]

    @property
    def fits(self) -> bool:
        return all(m.over == 0 for m in self.lines)

    @property
    def risky(self) -> bool:
        """Fits as written, and won't once a name buffer is at its longest."""
        return self.fits and any(m.over_at_worst for m in self.lines)


def wild(blocks: dict[str, dict[str, list[WildMon]]]) -> Table:
    """The map's encounters, keyed by which table they came from (GRASS, WATER),
    then by time of day."""
    formed = any(m.form for times in blocks.values()
                 for mons in times.values() for m in mons)
    cols = ["table", "time", "#", "level", "species"] + (["form"] if formed else [])
    rows: list[Row] = []
    for kind, times in blocks.items():
        for t, (time, mons) in enumerate(times.items()):
            for i, m in enumerate(mons):
                cells = [kind if t == 0 and i == 0 else "",
                         time if i == 0 else "",
                         str(i + 1), str(m.level), m.species]
                rows.append(Row(cells + ([m.form] if formed else [])))
    return cols, rows
