"""prism-newmap — interactive TUI to author and wire a brand-new map.

`prism-mapfit` "assumes the map content already exists... it does not author
maps" (see docs/devtools.md). This tool fills that gap for a map that doesn't
exist yet: it interactively gathers a `MapSpec` (see `shared.mapspec`), writes
an empty `maps/<Label>.asm` script/event-header stub, places the supplied
`.blk`/`.ablk` at `maps/blk/<Label>.<ext>`, wires the five asm source files
via `mapfit.mapwire.ALL_ASM_EDITORS`, and saves the resulting spec to
`.devtools/specs/<Label>.toml` so `prism-mapfit add` can pick it up for bank
placement and a verify build.

Out of scope (see docs/devtools.md): creating a brand-new map group,
`connection` lines to neighboring maps, and bank placement/build — all left
to `prism-mapfit`.
"""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

from ..mapfit import mapwire
from ..shared import maps as maps_mod
from ..shared import mapsource
from ..shared.mapspec import MapSpec
from ..shared.paths import RepoNotFound, repo_root

_PERMISSIONS = ("TOWN", "ROUTE", "INDOOR", "CAVE", "PERM_5", "GATE", "DUNGEON")

#: An empty map: no triggers, no callbacks, and an event header with four empty
#: lists. Public because the studio's `NewMap` action writes the same one, and a
#: second copy of it would be a second definition of what an empty map *is*.
#:
#: The event header comes *first*, so the top of a map is the list of what stands
#: in it — every object and its attributes, at a glance — and the scripts and
#: dialogue those objects point at fill the second half below. That is the shape
#: MtEmberWest.asm keeps, and the shape the scaffolds add content into: a person
#: joins the object list up top, and its words go under `; ***** Scripts *****`.
TEMPLATE = """{label}_MapScriptHeader:
 ;trigger count
\tdb 0
 ;callback count
\tdb 0

; ***** Event header *****
{label}_MapEventHeader:: db 0, 0

.Warps
\tdb 0

.CoordEvents
\tdb 0

.BGEvents
\tdb 0

.ObjectEvents
\tdb 0

; ***** Map callbacks *****

; ***** Scripts *****
"""

_LABEL_RE = re.compile(r"^[A-Z][A-Za-z0-9]*$")
_CONST_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


class _Aborted(Exception):
    pass


# --------------------------------------------------------------------------- #
# repo introspection                                                          #
# --------------------------------------------------------------------------- #

def _consts(path: Path, prefix: str) -> list[str]:
    """Every `const <prefix>...` name in *path*, in file order."""
    if not path.exists():
        return []
    rx = re.compile(rf"^\s*const\s+({re.escape(prefix)}\w*)")
    out = []
    for ln in path.read_text().splitlines():
        m = rx.match(ln)
        if m:
            out.append(m.group(1))
    return out


def _existing_groups(root: Path) -> dict[int, list[str]]:
    defs = maps_mod.parse_maps(root / "constants" / "map_dimension_constants.asm")
    groups: dict[int, list[str]] = {}
    for d in defs:
        groups.setdefault(d.group, []).append(d.name)
    return groups


def _existing_labels_consts(root: Path) -> tuple[set[str], set[str]]:
    labels = {label for label, _const in mapsource.header_pairs(root)}
    consts = {
        d.name
        for d in maps_mod.parse_maps(root / "constants" / "map_dimension_constants.asm")
    }
    return labels, consts


# --------------------------------------------------------------------------- #
# content authoring                                                           #
# --------------------------------------------------------------------------- #

def write_template(root: Path, label: str) -> str:
    """Write the empty maps/<label>.asm stub. Returns the repo-relative path."""
    rel = f"maps/{label}.asm"
    path = root / rel
    if path.exists():
        raise FileExistsError(f"{rel} already exists")
    path.write_text(TEMPLATE.format(label=label))
    return rel


def place_blk(root: Path, src: Path, label: str) -> str:
    """Copy *src* to maps/blk/<label><ext>. Returns the repo-relative path."""
    ext = src.suffix.lower()
    if ext not in (".blk", ".ablk"):
        raise ValueError(f"blk source must be .blk or .ablk, got {src.suffix!r}")
    rel = f"maps/blk/{label}{ext}"
    dest = root / rel
    if dest.exists():
        raise FileExistsError(f"{rel} already exists")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, dest)
    return rel


# --------------------------------------------------------------------------- #
# interactive wizard                                                          #
# --------------------------------------------------------------------------- #

def _ask(question):
    val = question.ask()
    if val is None:
        raise _Aborted()
    return val


def _gather_spec(root: Path, q) -> tuple[MapSpec, Path]:
    """Prompt for every MapSpec field. Raises _Aborted on Ctrl+C/cancel."""
    from questionary import Choice

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

    def _dim(prompt: str) -> int:
        return int(_ask(q.text(
            prompt,
            validate=lambda s: (
                True if s.isdigit() and 0 < int(s) < 256
                else "must be an integer between 1 and 255"
            ),
        )))

    height = _dim("Map height (blocks):")
    width = _dim("Map width (blocks):")

    blk_src = Path(_ask(q.path(
        "Path to the source .blk/.ablk file:",
        validate=lambda s: (
            f"file not found: {s}" if not Path(s).expanduser().exists()
            else "must be a .blk or .ablk file"
            if Path(s).expanduser().suffix.lower() not in (".blk", ".ablk")
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

    groups = _existing_groups(root)
    group = _ask(q.select(
        "Map group (existing groups only — creating a new group isn't "
        "supported by this tool):",
        choices=[
            Choice(
                f"{n}  ({', '.join(names[:3])}{', ...' if len(names) > 3 else ''})",
                value=n,
            )
            for n, names in sorted(groups.items())
        ],
    ))

    default_blockdata = f"Map block data {label}"
    default_script = f"Map Scripts {label}"
    default_secondary = f"Second Map Header {label}"
    blockdata_section = _ask(q.text(
        "SECTION name for the block data (blank = mapfit default):",
        default=default_blockdata,
    )).strip()
    script_section = _ask(q.text(
        "SECTION name for the script (blank = mapfit default):",
        default=default_script,
    )).strip()
    secondary_section = _ask(q.text(
        "SECTION name for the secondary header (blank = mapfit default):",
        default=default_secondary,
    )).strip()

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

    border_block = _ask(q.text("Border block (usually \"0\"):", default="0")).strip()
    conn_flags = _ask(q.text(
        "Connection flags (e.g. \"0\", \"NORTH\", \"NORTH | EAST\"):", default="0",
    )).strip()

    return MapSpec(
        label=label, const=const, group=group, height=height, width=width,
        tileset=tileset, permission=permission, landmark=landmark,
        music=music, palette=palette, fishgroup=fishgroup, phone=phone,
        border_block=border_block, conn_flags=conn_flags, connections=[],
        script_asm=f"maps/{label}.asm", blk=f"maps/blk/{label}{blk_src.suffix.lower()}",
        blockdata_section=blockdata_section, script_section=script_section,
        secondary_section=secondary_section,
    ), blk_src


def main() -> None:
    try:
        import questionary
    except ImportError:
        print(
            "prism-newmap requires `questionary`. Reinstall pokeprism-devtools:\n"
            "    pipx install --force <path-to-pokeprism-devtools>",
            file=sys.stderr,
        )
        sys.exit(2)

    try:
        root = repo_root()
    except RepoNotFound as e:
        print(f"prism-newmap: {e}", file=sys.stderr)
        sys.exit(2)

    print()
    print("=" * 56)
    print("  prism-newmap — add a new map")
    print("=" * 56)
    print()

    try:
        spec, blk_src = _gather_spec(root, questionary)
    except _Aborted:
        print("\nAborted — no files written.")
        sys.exit(1)

    print(f"\nWill create maps/{spec.label}.asm (empty template)")
    print(f"Will copy {blk_src} -> {spec.blk}")
    try:
        write_template(root, spec.label)
        place_blk(root, blk_src, spec.label)
    except (FileExistsError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(2)

    problems = spec.validate(root)
    if problems:
        for p in problems:
            print(f"error: {p}", file=sys.stderr)
        sys.exit(2)

    edits = [editor(root, spec) for editor in mapwire.ALL_ASM_EDITORS]
    print("\nWiring edits:")
    for e in edits:
        print(f"  [{'edit' if e.changed else 'skip'}] {e.path}: {e.detail}")

    if not questionary.confirm("\nWrite these changes?", default=True).ask():
        print(f"Aborted — {spec.script_asm} and {spec.blk} were already "
              "written; the five source files were not touched.")
        sys.exit(1)

    mapwire.apply_edits(root, edits, dry_run=False)

    spec_dir = root / ".devtools" / "specs"
    spec_dir.mkdir(parents=True, exist_ok=True)
    spec_path = spec_dir / f"{spec.label}.toml"
    spec_path.write_text(spec.to_toml())

    print(f"\nWired {spec.label} ({spec.const}). Spec saved to "
          f"{spec_path.relative_to(root)}")
    if not spec.connections:
        print("Note: no connections were added — if this map borders another, "
              "add `connection ...` lines to both maps by hand in "
              "maps/second_map_headers.asm.")
    print(f"\nNext: prism-mapfit add --spec {spec_path.relative_to(root)}  "
          "(add --park for a still-growing map)")


if __name__ == "__main__":
    main()
