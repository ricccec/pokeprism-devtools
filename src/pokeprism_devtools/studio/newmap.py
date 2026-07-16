"""Adding a map to the game — the action the studio exists for.

Every other action changes a map you are looking at. This one has no map to look
at, and that is the whole difficulty: `prism-newmap` asks you seventeen questions
in a terminal and you find out whether the answers were right several minutes
later, from `rgblink`, or worse, from a map that builds and is subtly wrong.

So this action draws itself. :meth:`NewMap.sketch` reads the `.blk` you pointed
at, at the height and width you typed, in the tileset you named, and puts it on
the grid **while you are still filling the form in**. The one mistake that
silently ruins a new map — a `.blk` that is not exactly `height × width` bytes —
stops being an error message you might not read and becomes a picture of a map
that is the wrong shape. A wrong tileset is a forest drawn in cave colours. You
do not need to be told; you can see it.

What it writes, all of it undoable, none of it behind your back:

    maps/<Label>.asm              an empty script and event header
    maps/blk/<Label>.ablk         the blocks, copied in from where you drew them
    .devtools/specs/<Label>.toml  the spec, for `prism-mapfit add` to pack later

plus the five source files that `mapfit.mapwire` wires, by anchor, idempotently.

**Bank placement is deliberately not here.** mapfit chooses banks by *measuring*
the three blobs, and measuring them means building the ROM — minutes, not
keystrokes. Packing cannot honestly happen inside a modal dialog, so it doesn't:
leave the bank blank and the sections float (rgblink puts them somewhere; the
spec on disk is the handoff to `prism-mapfit add --spec`), or name a bank and
they are pinned there, by you, now. What the form will not do is pick a bank for
you and not say so.
"""

from __future__ import annotations

from pathlib import Path

from ..map_new import TEMPLATE
from ..mapfit import mapwire
from ..shared import blocksrc, consts, maps as maps_mod, mapsource
from ..shared.blockdata import BlockData
from ..shared.edits import Edit
from ..shared.mapspec import MapSpec
from .actions import (BLOCKS, FISHGROUPS, GROUPS, LANDMARKS, MUSIC, PERMISSIONS,
                      TILESETS, TIMES, Action, ActionError, Field, Result)

#: The `permission` a map_header takes — its third argument, and a bare `const`
#: block in constants/map_constants.asm rather than a prefixed one, so there is
#: nothing to match on and the list has to be written down. It decides which
#: collision, encounter and sprite rules the map lives under: name the wrong one
#: and the map assembles, loads, and behaves like somewhere else.
PERMS = ("TOWN", "ROUTE", "INDOOR", "CAVE", "PERM_5", "GATE", "DUNGEON")

#: Where each named header argument's constants are defined, and what they all
#: start with. The form offers these and this module checks them, from the same
#: two lines — a form that suggests a constant its own validator rejects is worse
#: than no form at all.
ENUMS: dict[str, tuple[str, str]] = {
    "tileset": (consts.TILESETS, "TILESET_"),
    "landmark": (consts.LANDMARKS, ""),
    "music": (consts.MUSIC, "MUSIC_"),
    "palette": (consts.MAP, "PALETTE_"),
    "fishgroup": (consts.MISC, "FISHGROUP_"),
}

#: What polished-map hands you. `.ablk` is the uncompressed grid — one byte per
#: block — and is what 369 of pokeprism's 375 maps ship as; the Makefile makes
#: the `.lz` that the ROM actually INCBINs, from either.
BLK_SUFFIXES = (".ablk", ".blk")

_SPECS = ".devtools/specs"


class NewMap(Action):
    name = "newmap"
    title = "Add a new map"
    sketches = True

    FIELDS = (
        Field("label", "Label", help="CamelCase — its asm labels, its .blk, its sections"),
        Field("const", "Map id", help="SCREAMING_SNAKE — the MAP_ enum and the dimensions"),
        Field("group", "Group", kind="int", default="1", choices=GROUPS,
              help="an existing group; making a new one is not this tool's job"),
        Field("height", "Height", kind="int", help="in blocks — a block is 2×2 tiles"),
        Field("width", "Width", kind="int"),
        Field("blk", "Blocks", choices=BLOCKS,
              help="the .ablk you drew in polished-map — newest first"),
        Field("tileset", "Tileset", choices=TILESETS),
        Field("permission", "Permission", choices=PERMISSIONS, default="ROUTE"),
        Field("landmark", "Landmark", choices=LANDMARKS,
              help="its own, usually — or the town it sits inside"),
        Field("music", "Music", choices=MUSIC),
        Field("palette", "Palette", choices=TIMES, default="PALETTE_AUTO",
              help="PALETTE_AUTO follows the clock; PALETTE_DARK is a cave"),
        Field("fishgroup", "Fish group", choices=FISHGROUPS, default="FISHGROUP_NONE"),
        Field("phone", "Phone service", kind="int", default="0"),
        Field("border_block", "Border block", default="0",
              help="the block the world is made of past the edge"),
        # No connection flags: a new map starts with no neighbours, and connections
        # are their own form — `connections._set_flag` recomputes this nibble from
        # the edges that are actually there, so a value typed here would only be a
        # second place to keep in step with them.
        Field("bank", "Bank", default="",
              help="blank: leave the sections floating for prism-mapfit to pack. "
                   "Or pin all three yourself, e.g. $7C"),
        Field("blockdata_section", "Blocks section",
              help="blank = the convention, `Map block data <Label>`"),
        Field("script_section", "Script section", help="blank = `Map Scripts <Label>`"),
        Field("secondary_section", "Header section",
              help="blank = `Second Map Header <Label>`"),
    )

    def __init__(self, map_const: str = "", **values: str) -> None:
        # The map you happened to be looking at when you pressed the key. A new
        # map has nothing to do with it; the palette hands it to every action.
        super().__init__(**values)
        self.map = map_const

    def describe(self) -> str:
        return f"add {self.text('const')} ({self.text('label')})"

    def selects(self) -> str | None:
        return self.text("label") or None

    # -- the picture ---------------------------------------------------------- #
    def sketch(self, root: Path) -> BlockData | None:
        """The map on the grid, before any of it is written down.

        Everything it needs is on the form, so it can be wrong in every way the
        form can be wrong — and each of those is worth seeing rather than being
        told. It refuses only what it cannot draw at all.
        """
        blk = self.blk_source()
        height, width = self.integer("height"), self.integer("width")
        if height < 1 or width < 1:
            raise ActionError("a map is at least one block by one block")
        try:
            return blocksrc.sketch(root, blk, height, width,
                                   self.text("tileset"), self.text("permission"))
        except blocksrc.BlockSourceError as e:
            raise ActionError(str(e)) from e

    def blk_source(self) -> Path:
        raw = self.text("blk")
        if not raw:
            raise ActionError("point at the .ablk you drew")
        blk = Path(raw).expanduser()
        if blk.suffix.lower() not in BLK_SUFFIXES:
            raise ActionError(f"{blk.name} is not a .ablk or a .blk")
        if not blk.is_file():
            raise ActionError(f"no such file: {blk}")
        return blk

    # -- the writing ----------------------------------------------------------- #
    def run(self, root: Path) -> Result:
        blk = self.blk_source()
        spec = self.spec(blk)

        problems = spec.validate(root, require_files=False)
        problems += self._collisions(root, spec)
        problems += self._unknown_names(root)
        if problems:
            raise ActionError("; ".join(problems))

        # Read the blocks through `sketch`, not through `read_bytes` — so the
        # bytes that land in the repo are the same bytes that were on the grid,
        # checked against the same height and width, by the same code. A `.blk`
        # that drew wrong cannot quietly write right.
        blocks = self.sketch(root)
        assert blocks is not None

        rel_blk = f"maps/blk/{spec.label}{blk.suffix.lower()}"
        edits = [
            Edit(f"maps/{spec.label}.asm", True, "empty script and event header",
                 TEMPLATE.format(label=spec.label)),
            Edit(rel_blk, True, f"{spec.height}×{spec.width} blocks from {blk.name}",
                 f"{len(blocks.blocks)} bytes", data=blocks.blocks),
            *(editor(root, spec) for editor in mapwire.ALL_ASM_EDITORS),
            Edit(f"{_SPECS}/{spec.label}.toml", True, "the spec, for prism-mapfit",
                 spec.to_toml()),
        ]
        if spec.blockdata_bank >= 0:
            edits.append(mapwire.pin_sections(root, {
                spec.section_for(blob): spec.blockdata_bank
                for blob in ("blockdata", "script", "secondary")
            }))

        return Result(f"{spec.const} ({spec.label}), {spec.height}×{spec.width} "
                      f"blocks in group {spec.group}",
                      [e for e in edits if e.changed], self._notes(spec))

    def _notes(self, spec: MapSpec) -> list[str]:
        if spec.blockdata_bank >= 0:
            return [f"three sections pinned to bank ${spec.blockdata_bank:02X} — "
                    f"if the build overflows it, they are too big for it"]
        return [f"the three sections are unpinned: run `prism-mapfit add --spec "
                f"{_SPECS}/{spec.label}.toml` to measure and pack them",
                "the map has no connections yet — add them with `a`, once it is built"]

    def spec(self, blk: Path) -> MapSpec:
        return MapSpec(
            label=self.text("label"), const=self.text("const"),
            group=self.integer("group"),
            height=self.integer("height"), width=self.integer("width"),
            tileset=self.text("tileset"), permission=self.text("permission"),
            landmark=self.text("landmark") or self.text("const"),
            music=self.text("music"), palette=self.text("palette"),
            fishgroup=self.text("fishgroup"), phone=self.integer("phone"),
            border_block=self.text("border_block") or "0",
            conn_flags=self.text("conn_flags") or "0",
            connections=[],
            script_asm=f"maps/{self.text('label')}.asm",
            blk=f"maps/blk/{self.text('label')}{blk.suffix.lower()}",
            blockdata_section=self.text("blockdata_section"),
            script_section=self.text("script_section"),
            secondary_section=self.text("secondary_section"),
            # One bank for all three, or none for any of them. Three separate
            # banks is a thing mapfit does with measurements in hand; a form has
            # none, and guessing three is three chances to be wrong.
            blockdata_bank=self._bank(), script_bank=self._bank(),
            secondary_bank=self._bank(),
        )

    def _bank(self) -> int:
        """The bank, written the way the linker writes it. `$7C` is how every
        bank in this repo is spelled, and `int(…, 0)` has never heard of it."""
        raw = self.text("bank")
        if not raw:
            return -1
        try:
            return int(raw.replace("$", "0x"), 0)
        except ValueError:
            raise ActionError(f"{raw!r} is not a bank — write it like $7C") from None

    # -- what the form can get wrong -------------------------------------------- #
    def _collisions(self, root: Path, spec: MapSpec) -> list[str]:
        """A label or const already in the game.

        The wiring editors are idempotent on a map that is *entirely* already
        there, which is what makes re-running mapfit safe. What they cannot see is
        a half-collision — a new label reusing a const that exists — and that one
        wires a `map_header` with no `mapgroup` behind it.
        """
        out = []
        if spec.label in {label for label, _ in mapsource.header_pairs(root)}:
            out.append(f"{spec.label} is already a map")
        dims = root / "constants/map_dimension_constants.asm"
        if spec.const in {d.name for d in maps_mod.parse_maps(dims)}:
            out.append(f"{spec.const} is already a map id")
        if (root / spec.script_asm).exists():
            out.append(f"{spec.script_asm} already exists — it belongs to something")
        # The .blk is a collision only if writing it would *overwrite a different
        # file*. Point the form at `maps/blk/X.blk` and name the map `X` and the
        # source and the destination are the same path — we copy it onto itself,
        # changing nothing. And a .blk drawn once and reused for a second map is
        # ordinary here, so the destination merely existing is not the objection;
        # it belonging to something else is.
        dest = root / spec.blk
        if dest.exists() and dest.resolve() != self.blk_source().resolve():
            out.append(f"{spec.blk} already exists — it belongs to something")
        return out

    def _unknown_names(self, root: Path) -> list[str]:
        """Every constant the header names, checked before it is written.

        rgbds resolves these at *link* time, so a typo comes back minutes later as
        `Unknown symbol` with nothing to say about which map you were adding.
        """
        out = []
        if self.text("permission") not in PERMS:
            out.append(f"permission must be one of {', '.join(PERMS)}")
        for name, (rel, prefix) in ENUMS.items():
            value = self.text(name) or (self.text("const") if name == "landmark" else "")
            if not value:
                out.append(f"{name} is required")
            elif value not in consts.with_prefix(root, rel, prefix):
                close = consts.suggest(value, consts.with_prefix(root, rel, prefix))
                hint = f" — did you mean {', '.join(close)}?" if close else ""
                out.append(f"{value} is not in {rel}{hint}")
        return out
