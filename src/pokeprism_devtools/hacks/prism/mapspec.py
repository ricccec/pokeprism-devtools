"""The description of a new map to wire in, plus the derived section names.

A map carries two names: a CamelCase *label* used for asm labels, INCLUDE/INCBIN
filenames and section names (``MtEmberSmallRoom``), and a SCREAMING_SNAKE
*const* used for the ``MAP_``/``GROUP_`` enum and the dimension macro
(``MT_EMBER_SMALL_ROOM``). They are not mechanically interconvertible
(``MtEmber`` → ``MT_EMBER``? ``MTEMBER``?), so both are carried explicitly.

The spec covers only the *wiring* fields — the ``map_header`` /
``map_header_2`` arguments, dimensions, group, and the paths to the
already-authored script ``.asm`` and ``.blk``. It does not author map content.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

#: The two spellings of a map's name. `MtEmberSmallRoom` names asm labels, files
#: and sections; `MT_EMBER_SMALL_ROOM` names the enum and the dimension macro.
#: Neither is derivable from the other (`MtEmber` → `MT_EMBER`? `MTEMBER`?), so
#: both are given, and both are checked — a lowercase label produces a label the
#: assembler reads as a local one.
LABEL_RE = re.compile(r"^[A-Z][A-Za-z0-9]*$")
CONST_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")

#: How a blob gets placed in the ROM.
#:
#: ``auto``   — mapfit's packer picks a bank and gives the blob its own SECTION,
#:              pinned in ``contents/romx.link``. The default, and what the tool
#:              did exclusively before.
#: ``into``   — append into a SECTION that already exists (say ``Map Scripts 7``).
#:              The blob inherits that section's bank, so ``romx.link`` is not
#:              touched at all — there is no new section to pin.
#: ``bank``   — the blob gets its own SECTION like ``auto``, but pinned to a bank
#:              you name instead of one the packer chose.
AUTO, INTO, BANK = "auto", "into", "bank"

#: The three blobs a map places. Each maps to the spec fields that describe it.
BLOBS = ("blockdata", "script", "secondary")


@dataclass(frozen=True)
class BlobPlacement:
    """Where one of a map's three blobs will live."""
    blob: str            # "blockdata" | "script" | "secondary"
    mode: str            # AUTO | INTO | BANK
    section: str         # the SECTION it ends up in, either way
    bank: int | None     # the bank, when it's known up front (INTO resolves later)

    @property
    def needs_packing(self) -> bool:
        return self.mode == AUTO

    @property
    def needs_pin(self) -> bool:
        """INTO inherits its section's bank, so it never touches romx.link."""
        return self.mode != INTO


@dataclass
class MapSpec:
    label: str                  # "MtEmberSmallRoom"
    const: str                  # "MT_EMBER_SMALL_ROOM"
    group: int                  # existing group number to append into
    height: int
    width: int

    # primary header — map_header label, tileset, permission, landmark, music,
    #                   phone_service_flag, time_of_day/palette, fishing_group
    tileset: str
    permission: str
    landmark: str
    music: str
    palette: str
    fishgroup: str
    phone: int = 0

    # secondary header — map_header_2 label, const, border_block, conn_flags
    border_block: str = "0"
    conn_flags: str = "0"
    connections: list[str] = field(default_factory=list)

    # already-authored content, paths relative to the repo root
    script_asm: str = ""
    blk: str = ""

    # optional overrides for the auto-derived section names below (blank ==
    # use the default "<Kind> <Label>" convention)
    blockdata_section: str = ""
    script_section: str = ""
    secondary_section: str = ""

    # placement, per blob. Unset on both == auto (let the packer decide).
    #   *_into: append into this already-existing SECTION, inheriting its bank
    #   *_bank: give the blob its own SECTION, pinned to this bank
    # Setting both for one blob is a contradiction and is rejected.
    blockdata_into: str = ""
    script_into: str = ""
    secondary_into: str = ""
    blockdata_bank: int = -1
    script_bank: int = -1
    secondary_bank: int = -1

    @property
    def blk_lz(self) -> str:
        return f"{self.blk}.lz"

    # -- placement ---------------------------------------------------------- #
    def placement(self, blob: str) -> BlobPlacement:
        """How `blob` ("blockdata" | "script" | "secondary") gets placed."""
        if blob not in BLOBS:
            raise ValueError(f"unknown blob {blob!r} (use {', '.join(BLOBS)})")
        into = getattr(self, f"{blob}_into")
        bank = getattr(self, f"{blob}_bank")
        own = {"blockdata": self.section_blockdata,
               "script": self.section_script,
               "secondary": self.section_secondary}[blob]

        if into:
            # The blob joins an existing section, so that section *is* its
            # section — the map's own "<Kind> <Label>" name is never created.
            return BlobPlacement(blob, INTO, into, None)
        if bank >= 0:
            return BlobPlacement(blob, BANK, own, bank)
        return BlobPlacement(blob, AUTO, own, None)

    @property
    def placements(self) -> list[BlobPlacement]:
        return [self.placement(b) for b in BLOBS]

    def section_for(self, blob: str) -> str:
        return self.placement(blob).section

    @property
    def section_blockdata(self) -> str:
        return self.blockdata_section or f"Map block data {self.label}"

    @property
    def section_script(self) -> str:
        return self.script_section or f"Map Scripts {self.label}"

    @property
    def section_secondary(self) -> str:
        return self.secondary_section or f"Second Map Header {self.label}"

    def validate(self, root: Path, *, require_files: bool = True) -> list[str]:
        """Return a list of human-readable problems (empty == OK).

        `require_files=False` checks everything except that the script and the
        `.blk` are already on disk. The studio needs that: it builds every edit —
        including the two that *create* those files — before it writes any of
        them, so at the moment it validates, the files it is about to write do
        not exist yet. Insisting they do would mean writing content to the tree
        before knowing whether the wiring is even legal.
        """
        problems: list[str] = []
        if not LABEL_RE.match(self.label):
            problems.append(f"label '{self.label}' should be CamelCase, "
                            "like MtEmberSmallRoom")
        if not CONST_RE.match(self.const):
            problems.append(f"const '{self.const}' should be SCREAMING_SNAKE_CASE, "
                            "like MT_EMBER_SMALL_ROOM")
        if self.group < 1:
            problems.append(f"group must be >= 1, got {self.group}")
        if not (0 < self.width < 256 and 0 < self.height < 256):
            problems.append(f"dimensions {self.height}x{self.width} out of range")
        if not self.script_asm:
            problems.append("script_asm path is required")
        elif require_files and not (root / self.script_asm).exists():
            problems.append(f"script asm not found: {self.script_asm}")
        if not self.blk:
            problems.append("blk path is required")
        elif require_files and not (root / self.blk).exists():
            problems.append(f"blk file not found: {self.blk}")

        for blob in BLOBS:
            into = getattr(self, f"{blob}_into")
            bank = getattr(self, f"{blob}_bank")
            if into and bank >= 0:
                problems.append(
                    f"{blob}: set either {blob}_into (join an existing section, "
                    f"inheriting its bank) or {blob}_bank (own section, pinned "
                    f"there) — not both"
                )
            if bank >= 0 and not 0 <= bank <= 0xFF:
                problems.append(f"{blob}_bank ${bank:x} is not a ROM bank")
        return problems

    @classmethod
    def from_toml(cls, path: Path) -> "MapSpec":
        with path.open("rb") as f:
            data = tomllib.load(f)
        known = cls.__dataclass_fields__.keys()
        unknown = set(data) - set(known)
        if unknown:
            raise ValueError(f"{path.name}: unknown keys {sorted(unknown)}")
        return cls(**data)

    def to_toml(self) -> str:
        """Serialize to a TOML string that round-trips through `from_toml`.

        Emits only the dataclass fields (not the derived `section_*`/`blk_lz`
        properties), grouped to mirror the documented spec layout.
        """
        return "\n".join([
            f"label       = {_q(self.label)}",
            f"const       = {_q(self.const)}",
            f"group       = {self.group}",
            f"height      = {self.height}",
            f"width       = {self.width}",
            "",
            "# primary header (map_header)",
            f"tileset     = {_q(self.tileset)}",
            f"permission  = {_q(self.permission)}",
            f"landmark    = {_q(self.landmark)}",
            f"music       = {_q(self.music)}",
            f"palette     = {_q(self.palette)}",
            f"fishgroup   = {_q(self.fishgroup)}",
            f"phone       = {self.phone}",
            "",
            "# secondary header (map_header_2)",
            f"border_block = {_q(self.border_block)}",
            f"conn_flags   = {_q(self.conn_flags)}",
            _toml_list("connections", self.connections),
            "",
            "# authored content (repo-relative)",
            f"script_asm  = {_q(self.script_asm)}",
            f"blk         = {_q(self.blk)}",
            "",
            "# section name overrides (blank = \"<Kind> <Label>\" convention)",
            f"blockdata_section = {_q(self.blockdata_section)}",
            f"script_section    = {_q(self.script_section)}",
            f"secondary_section = {_q(self.secondary_section)}",
            "",
            "# placement (blank / -1 = auto: let mapfit's packer choose a bank)",
            "#   *_into: append into this existing SECTION, inheriting its bank",
            "#   *_bank: own SECTION, pinned to this bank",
            f"blockdata_into = {_q(self.blockdata_into)}",
            f"script_into    = {_q(self.script_into)}",
            f"secondary_into = {_q(self.secondary_into)}",
            f"blockdata_bank = {self.blockdata_bank}",
            f"script_bank    = {self.script_bank}",
            f"secondary_bank = {self.secondary_bank}",
        ]) + "\n"


def _q(value: str) -> str:
    """A TOML basic string (escapes backslash and double-quote)."""
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _toml_list(key: str, items: list[str]) -> str:
    if not items:
        return f"{key} = []"
    body = "".join(f"    {_q(it)},\n" for it in items)
    return f"{key} = [\n{body}]"
