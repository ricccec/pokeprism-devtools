"""The questions that add up to a `MapSpec`.

Every prompt validates against the tree rather than against a pattern alone, so
a label that is well-formed but already wired is refused at the prompt instead of
failing four questions later. Cancelling any prompt raises `_Aborted`, which the
CLI turns into "no files written".
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from ..hacks.prism.mapspec import MapSpec
from .repoquery import _consts, _existing_groups, _existing_labels_consts

_PERMISSIONS = ("TOWN", "ROUTE", "INDOOR", "CAVE", "PERM_5", "GATE", "DUNGEON")

_LABEL_RE = re.compile(r"^[A-Z][A-Za-z0-9]*$")
_CONST_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


class _Aborted(Exception):
    pass


def _ask(question):
    val = question.ask()
    if val is None:
        raise _Aborted()
    return val


_BLK_SUFFIXES = (".blk", ".ablk")
_MAX_DIMENSION = 255          # a map dimension is one byte, and 0 is no map
_GROUP_NAMES_SHOWN = 3


def _ask_identity(q, root: Path) -> tuple[str, str]:
    """The label and const, refused here if the tree already has them."""
    existing_labels, existing_consts = _existing_labels_consts(root)

    label = _ask(q.text(
        "PascalCase map label (e.g. OneIsland):",
        validate=lambda s: (
            "must be CamelCase (start uppercase, letters/digits only)"
            if not _LABEL_RE.match(s)
            else f"label '{s}' is already wired" if s in existing_labels
            else True
        ),
    )).strip()

    const = _ask(q.text(
        "SCREAMING_SNAKE_CASE map id (e.g. ONE_ISLAND):",
        validate=lambda s: (
            "must be SCREAMING_SNAKE_CASE (letters, digits, underscores)"
            if not _CONST_RE.match(s)
            else f"const '{s}' is already used" if s in existing_consts
            else True
        ),
    )).strip()
    return label, const


def _ask_dimensions(q) -> tuple[int, int]:
    def _dim(prompt: str) -> int:
        return int(_ask(q.text(
            prompt,
            validate=lambda s: (
                True if s.isdigit() and 0 < int(s) <= _MAX_DIMENSION
                else f"must be an integer between 1 and {_MAX_DIMENSION}"
            ),
        )))

    return _dim("Map height (blocks):"), _dim("Map width (blocks):")


def _ask_blk_source(q, height: int, width: int) -> Path:
    """The .blk to copy in, warning if its size disagrees with the dimensions.

    Only a raw `.blk` can be checked: an `.ablk` is compressed, so its size
    says nothing about the map's shape. A mismatch is a warning rather than a
    refusal because either answer could be the wrong one, and only the person
    at the prompt knows which.
    """
    blk_src = Path(_ask(q.path(
        "Path to the source .blk/.ablk file:",
        validate=lambda s: (
            f"file not found: {s}" if not Path(s).expanduser().exists()
            else "must be a .blk or .ablk file"
            if Path(s).expanduser().suffix.lower() not in _BLK_SUFFIXES
            else True
        ),
    )).strip()).expanduser()

    if blk_src.suffix.lower() == ".blk":
        expected = height * width
        actual = blk_src.stat().st_size
        if actual != expected:
            print(f"warning: {blk_src.name} is {actual} bytes, expected "
                  f"{expected} ({height}x{width}) — continuing anyway.",
                  file=sys.stderr)
    return blk_src


def _ask_group(q, root: Path) -> int:
    """Which existing group the map joins. Creating one is out of scope."""
    from questionary import Choice

    groups = _existing_groups(root)
    return _ask(q.select(
        "Map group (existing groups only — creating a new group isn't "
        "supported by this tool):",
        choices=[
            Choice(
                f"{n}  ({', '.join(names[:_GROUP_NAMES_SHOWN])}"
                f"{', ...' if len(names) > _GROUP_NAMES_SHOWN else ''})",
                value=n,
            )
            for n, names in sorted(groups.items())
        ],
    ))


def _ask_sections(q, label: str) -> tuple[str, str, str]:
    """The three SECTION names, defaulting to what mapfit would pick anyway."""
    blockdata = _ask(q.text(
        "SECTION name for the block data (blank = mapfit default):",
        default=f"Map block data {label}",
    )).strip()
    script = _ask(q.text(
        "SECTION name for the script (blank = mapfit default):",
        default=f"Map Scripts {label}",
    )).strip()
    secondary = _ask(q.text(
        "SECTION name for the secondary header (blank = mapfit default):",
        default=f"Second Map Header {label}",
    )).strip()
    return blockdata, script, secondary


def _ask_header_fields(q, root: Path, const: str) -> dict:
    """Everything that ends up in `map_header`, each checked against the tree."""
    tilesets = _consts(root / "constants" / "tilemap_constants.asm", "TILESET_")
    tileset = _ask(q.autocomplete(
        "Tileset (tab to autocomplete):",
        choices=tilesets,
        validate=lambda s: s in tilesets or f"unknown tileset: {s}",
    ))

    permission = _ask(q.select(
        "Permission (map type):",
        choices=list(_PERMISSIONS),
    ))

    landmark = _ask(q.text(
        "Landmark const (usually the map's own const, or its parent town's "
        "for an indoor sub-map):",
        default=const,
        validate=lambda s: True if _CONST_RE.match(s) else "must be SCREAMING_SNAKE_CASE",
    )).strip()

    musics = _consts(root / "constants" / "music_constants.asm", "MUSIC_")
    music = _ask(q.autocomplete(
        "Music (tab to autocomplete):",
        choices=musics,
        validate=lambda s: s in musics or f"unknown music: {s}",
    ))

    palettes = _consts(root / "constants" / "map_constants.asm", "PALETTE_")
    palette = _ask(q.select("Palette:", choices=palettes))

    fishgroups = _consts(root / "constants" / "misc_constants.asm", "FISHGROUP_")
    fishgroup = _ask(q.select("Fish group:", choices=fishgroups))

    phone = 1 if _ask(q.confirm("Has phone service?", default=False)) else 0

    return {
        "tileset": tileset, "permission": permission, "landmark": landmark,
        "music": music, "palette": palette, "fishgroup": fishgroup,
        "phone": phone,
    }


def _ask_secondary_fields(q) -> tuple[str, str]:
    border_block = _ask(q.text("Border block (usually \"0\"):", default="0")).strip()
    conn_flags = _ask(q.text(
        "Connection flags (e.g. \"0\", \"NORTH\", \"NORTH | EAST\"):", default="0",
    )).strip()
    return border_block, conn_flags


def _gather_spec(root: Path, q) -> tuple[MapSpec, Path]:
    """Prompt for every MapSpec field. Raises _Aborted on Ctrl+C/cancel.

    The order of these calls is the order the questions are asked, and it is
    the order a person can answer them in: what the map is, how big, what to
    draw it from, where it lives, then the two headers' contents.
    """
    label, const = _ask_identity(q, root)
    height, width = _ask_dimensions(q)
    blk_src = _ask_blk_source(q, height, width)
    group = _ask_group(q, root)
    blockdata_section, script_section, secondary_section = _ask_sections(q, label)
    header = _ask_header_fields(q, root, const)
    border_block, conn_flags = _ask_secondary_fields(q)

    return MapSpec(
        label=label, const=const, group=group, height=height, width=width,
        border_block=border_block, conn_flags=conn_flags, connections=[],
        script_asm=f"maps/{label}.asm", blk=f"maps/blk/{label}{blk_src.suffix.lower()}",
        blockdata_section=blockdata_section, script_section=script_section,
        secondary_section=secondary_section,
        **header,
    ), blk_src
