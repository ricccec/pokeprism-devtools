"""Adding a map to a pokecrystal-family tree: six files, one order to keep.

`wiring/placement.py` answers *where the blobs go*; this answers *what gets
written*. The two are separate because placement is the entire fork between the
trees and this is very nearly shared — the same six files in the same order,
differing only in how a handful of lines are spelled, which is what the
:class:`Dialect` carries.

    constants/map_constants.asm   map_const CONST, W, H      the id and the size
    data/maps/maps.asm            map Label, tileset, ...    the header
    data/maps/attributes.asm      map_attributes Label, ...  border and pointers
    data/maps/blocks.asm          Label_Blocks: INCBIN       the grid
    data/maps/scripts.asm         INCLUDE "maps/Label.asm"   the script
    maps/<Label>.asm              an empty script and event block
    maps/<Label>.blk              the grid itself, copied in

The invariant that makes this dangerous
---------------------------------------
Two of those files are **parallel arrays**, and nothing in either says so.
`map_const` assigns ids by counting: the macro does `DEF MAP_\\1 EQU
__map_value__` and then increments, so a map's id is simply its position in its
`newgroup` block. `MapGroupPointers` in `data/maps/maps.asm` is then indexed by
that id. Insert a `map_const` in the middle of a group and every map below it
in that group silently becomes a different map — the game builds, and doors
open onto the wrong rooms.

So both insertions go at the **end** of their group, and they go together. That
is not a stylistic choice about where new things belong; it is the only
position where the two arrays cannot fall out of step. :func:`add_map` builds
both edits or neither, and `tests/test_mapnew.py` checks the two arrays agree
map-for-map after the write rather than checking that the lines look right.

The transposition, for the third time
-------------------------------------
The dimension line is written by :meth:`MapShape.line` and not by anything
here, for the reason `wiring/mapresize.py` gives at length: `mapgroup NAME, H,
W` against `map_const NAME, W, H`. A new map is the *worst* case for it — a
resize can at least be checked against the grid that already exists, but here
the grid and the constant are written in the same breath from the same two
numbers, so a swap is perfectly self-consistent and produces a map that is
sideways.

One entry point taking primitives and a dialect, so a `prism-mapadd` CLI would
be `argparse` -> :func:`add_map` -> `apply_edits`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from ..shared.edits import Edit
from .mapresize import MapShape
from .editvocab import Change, EditError
from .placement import Placement, Section

#: The two spellings of a map's name, and why both are given rather than one
#: derived: `MtEmber` -> `MT_EMBER` or `MTEMBER`? The same argument prism's
#: `mapspec` makes, and the same two patterns, because a lowercase label
#: assembles as a *local* label and fails somewhere else entirely.
LABEL_RE = re.compile(r"^[A-Z][A-Za-z0-9]*$")
CONST_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")

MAPS = "data/maps/maps.asm"
ATTRIBUTES = "data/maps/attributes.asm"
CONSTANTS = "constants/map_constants.asm"

_NEWGROUP_RE = re.compile(r"^\s*newgroup\b")
_MAP_CONST_RE = re.compile(r"^\s*map_const\b")
_MAP_RE = re.compile(r"^\s*map\s+\w")
_PTR_RE = re.compile(r"^\s*dw\s+(\w+)")
_SECTION_RE = re.compile(r'^\s*SECTION\s+"([^"]+)"')

#: What ends a section, and the reason this is a separate pattern: each of the
#: four map data files closes its *last* section with an explicit `ENDSECTION`
#: rather than letting the end of the file do it. A search that only stopped at
#: the next `SECTION` would run past it — and since the last section is exactly
#: the one a numbered tree defaults to, that miss would put the default answer
#: outside every section it named. Caught by reading the generated file, not by
#: the tests, which agreed with the bug.
_ENDS_RE = re.compile(r'^\s*(SECTION\s+"|ENDSECTION\b)')
_ATTR_RE = re.compile(r"^\s*map_attributes\s+(\w+)\s*,")


@dataclass(frozen=True)
class NewMap:
    """A map that does not exist yet, in the fields every tree in the family
    needs. What the header line is *made of* differs between the trees and
    lives in `header`, keyed by the argument names the tree's own form uses."""
    label: str                   # MtEmberSmallRoom
    const: str                   # MT_EMBER_SMALL_ROOM
    group: int                   # an existing group; making one is not this job
    height: int                  # in blocks
    width: int
    #: The grid the author drew, somewhere outside the tree.
    blk: Path
    #: The block the world is made of past the edge.
    border_block: str = "0"
    #: Tileset, environment, landmark, music... whatever this tree's `map`
    #: macro takes. The dialect turns it into a line; nothing here reads it.
    header: dict[str, str] = field(default_factory=dict)

    def problems(self) -> list[str]:
        out = []
        if not LABEL_RE.match(self.label):
            out.append(f"label {self.label!r} should be CamelCase, "
                       "like MtEmberSmallRoom")
        if not CONST_RE.match(self.const):
            out.append(f"const {self.const!r} should be SCREAMING_SNAKE_CASE, "
                       "like MT_EMBER_SMALL_ROOM")
        if self.group < 1:
            out.append(f"group must be at least 1, got {self.group}")
        if not (0 < self.height < 256 and 0 < self.width < 256):
            out.append(f"{self.height}x{self.width} is not a map size")
        return out


class Dialect(Protocol):
    """The handful of things the two trees spell differently."""

    #: The dimension macro and, critically, its argument order.
    shape: MapShape

    def placements(self, root: Path) -> tuple[Placement, ...]:
        """Where this tree's scripts and blocks may go — one per blob."""

    def template(self, label: str) -> str:
        """An empty map: the script header and the five empty event lists."""

    def blk_name(self, label: str, src: Path) -> str:
        """Repo-relative path for the copied grid — `maps/<Label>.blk`."""

    def blocks_entry(self, label: str, blk_rel: str) -> list[str]:
        """The label and `INCBIN` that index the grid. Two lines in vanilla;
        polished INCBINs the *compressed* file the build makes from it."""

    def script_entry(self, label: str) -> list[str]:
        """The `INCLUDE` that pulls the map's asm into the ROM."""

    def header_line(self, spec: NewMap) -> str:
        """The `map` macro. Vanilla ends in a fishing group; polished carries a
        location sign in the middle and no fishing group at all."""

    def attributes_line(self, spec: NewMap) -> str:
        """The `map_attributes` line. The same three arguments in both."""


# --------------------------------------------------------------------------- #
# the entry point                                                             #
# --------------------------------------------------------------------------- #

def add_map(root: Path, spec: NewMap, answers: dict[str, str], *,
            dialect: Dialect) -> Change:
    """Wire `spec` into the tree, placing its blobs per `answers`.

    `answers` is keyed by blob name (`"script"`, `"blocks"`) and holds whatever
    the form came back with for that blob's :class:`Placement` — a section name
    for a `JOIN`, a bank or blank for a `PIN`, ignored for a `MINT`. Nothing is
    written: every edit comes back in the :class:`Change` and the caller applies
    them together or not at all.
    """
    if problems := spec.problems():
        raise EditError("; ".join(problems))
    if problems := _collisions(root, spec):
        raise EditError("; ".join(problems))

    grid = read_grid(spec.blk, spec.height, spec.width)
    placed = {p.blob: (p, p.resolve(answers.get(p.blob, ""), spec.label))
              for p in dialect.placements(root)}
    for blob in ("script", "blocks"):
        if blob not in placed:
            raise EditError(f"this tree declares no placement for {blob}")
    sections = {blob: section for blob, (_, section) in placed.items()}

    blk_rel = dialect.blk_name(spec.label, spec.blk)
    # The id and the header, in that order and never one without the other —
    # see the module docstring. Both append at the end of group `spec.group`.
    edits = [
        _add_const(root, spec, dialect.shape),
        _add_header(root, spec, dialect.header_line(spec)),
        _add_attributes(root, spec, dialect.attributes_line(spec)),
        _place(root, *placed["blocks"],
               entry=dialect.blocks_entry(spec.label, blk_rel)),
        _place(root, *placed["script"],
               entry=dialect.script_entry(spec.label)),
        Edit(f"maps/{spec.label}.asm", True, "an empty script and event block",
             dialect.template(spec.label)),
        Edit(blk_rel, True,
             f"{spec.height}x{spec.width} blocks from {spec.blk.name}",
             f"{len(grid)} bytes", data=grid),
    ]
    return Change(
        f"{spec.const} ({spec.label}), {spec.height}x{spec.width} blocks "
        f"in group {spec.group}",
        edits, _notes(sections))


def _notes(sections: dict[str, Section]) -> list[str]:
    out = [f"{blob}: {section.describe()}"
           for blob, section in sorted(sections.items())]
    pinned = [s for s in sections.values() if s.pinned]
    if pinned:
        # Honest about what is not checked: see `wiring/placement.py`.
        out.append("joining a pinned section means the map shares that bank — "
                   "if the build overflows it, they no longer fit together")
    out.append("the map has no connections or events yet")
    return out


def grids(folders, suffixes: tuple[str, ...]) -> list[str]:
    """Every grid file within reach, **newest first**.

    Deliberately uncached and deliberately not sorted by name: the file you are
    looking for is the one you drew in polished-map ninety seconds ago, so it is
    the newest thing here by definition, and a list cached at startup would be a
    list with exactly that file missing from it.

    Both `folders` and `suffixes` are the caller's because both fork. Prism
    keeps its grids in `maps/blk/`; the family keeps them in `maps/`, and
    polished's are `.ablk` beside a `.ablk.lzp` the build makes. A folder that
    is not there is not an error — most of these are somebody's habit rather
    than part of the tree.
    """
    seen: dict[Path, float] = {}
    for folder in folders:
        try:
            entries = list(Path(folder).iterdir())
        except OSError:
            continue
        for f in entries:
            # The same suffixes the action will *check* the answer against — a
            # list that offered a file the action then refused would be worse
            # than no list at all.
            if f.suffix.lower() in suffixes and f.is_file():
                seen.setdefault(f.resolve(), f.stat().st_mtime)
    return [str(p) for p in sorted(seen, key=lambda p: -seen[p])]


def read_grid(blk: Path, height: int, width: int) -> bytes:
    """The grid, at exactly the size the constant is about to declare.

    Checked here rather than trusted, because this is the one mistake that
    produces a map which builds: a `.blk` that is not `height * width` bytes
    leaves the engine reading whatever is next in the bank as terrain.

    Public because the new-map *form* draws through it as well as writing
    through it (`studio/mapadd.AddMap.sketch`). One rule, read once: a grid the
    picture refused cannot then be written, and a grid that drew is the grid
    that lands. Two copies of this arithmetic would eventually disagree, and
    the disagreement would be invisible — both sides assemble.
    """
    if not blk.is_file():
        raise EditError(f"no such file: {blk}")
    data = blk.read_bytes()
    need = height * width
    if len(data) != need:
        raise EditError(
            f"{blk.name} is {len(data)} bytes but {height}x"
            f"{width} is {need} — one of the two is wrong, and the "
            f"map would build either way")
    return data


def _collisions(root: Path, spec: NewMap) -> list[str]:
    """A label or const the tree already uses.

    The half-collision is the one worth catching: a new label reusing an
    existing const wires a header with no dimensions behind it, and rgbds says
    so at *link* time, minutes later, without naming the map.
    """
    out = []
    if re.search(rf"^\s*map_const\s+{re.escape(spec.const)}\s*,",
                 (root / CONSTANTS).read_text(), re.M):
        out.append(f"{spec.const} is already a map id")
    if re.search(rf"^\s*map\s+{re.escape(spec.label)}\s*,",
                 (root / MAPS).read_text(), re.M):
        out.append(f"{spec.label} is already a map")
    if (root / f"maps/{spec.label}.asm").exists():
        out.append(f"maps/{spec.label}.asm already exists — it belongs to "
                   f"something")
    return out


# --------------------------------------------------------------------------- #
# the two parallel arrays                                                     #
# --------------------------------------------------------------------------- #

def _add_const(root: Path, spec: NewMap, shape: MapShape) -> Edit:
    """`map_const` at the end of its `newgroup` block — which is what assigns
    the map its id, so the end is the only safe place. See the docstring."""
    lines, original = _lines(root, CONSTANTS)
    start, end = _group(lines, spec.group, _NEWGROUP_RE, CONSTANTS)
    at = _last(lines, start, end, _MAP_CONST_RE)
    if at is None:
        raise EditError(f"{CONSTANTS}: group {spec.group} has no maps in it")
    index = sum(1 for i in range(start, end) if _MAP_CONST_RE.match(lines[i]))
    line = _like(lines[at], shape.line(spec.const, spec.height, spec.width),
                 f"; {index + 1:>2}")
    lines.insert(at + 1, line)
    return Edit(CONSTANTS, True,
                f"{spec.const} is map {index + 1} of group {spec.group}",
                "\n".join(lines), base=original)


def _add_header(root: Path, spec: NewMap, line: str) -> Edit:
    """The `map` line at the end of the same group's table. Its position *is*
    the map id assigned above, which is why these two are never separated."""
    lines, original = _lines(root, MAPS)
    label = _group_label(lines, spec.group)
    start = next(i for i, ln in enumerate(lines)
                 if ln.strip().rstrip(":") == label and ln.rstrip().endswith(":"))
    end = _until(lines, start + 1, lambda ln: bool(re.match(r"^\w", ln)))
    at = _last(lines, start, end, _MAP_RE)
    if at is None:
        raise EditError(f"{MAPS}: {label} has no maps in it")
    lines.insert(at + 1, line)
    return Edit(MAPS, True, f"{spec.label} appended to {label}",
                "\n".join(lines), base=original)


def _group_label(lines: list[str], group: int) -> str:
    """Group N's label, read from `MapGroupPointers` rather than guessed.

    The trees name their groups differently — `MapGroup_Olivine` against
    `MapGroup1` — but both index them through the same `dw` table, so reading
    the table works for either and does not encode a naming convention that
    only one of them follows.
    """
    start = next((i for i, ln in enumerate(lines)
                  if ln.startswith("MapGroupPointers")), None)
    if start is None:
        raise EditError(f"{MAPS} has no MapGroupPointers table")
    labels = [m.group(1) for ln in lines[start:_until(
        lines, start + 1, lambda l: bool(re.match(r"^\w", l)))]
        if (m := _PTR_RE.match(ln))]
    if not 1 <= group <= len(labels):
        raise EditError(f"group {group} is not one of this tree's "
                        f"{len(labels)} map groups")
    return labels[group - 1]


def _add_attributes(root: Path, spec: NewMap, line: str) -> Edit:
    """`map_attributes` goes at the end of the file's list — order here is not
    load-bearing (each one defines a label the header points at *by name*), so
    the end is merely where new ones have been going."""
    lines, original = _lines(root, ATTRIBUTES)
    at = _last(lines, 0, len(lines), _ATTR_RE)
    if at is None:
        raise EditError(f"{ATTRIBUTES} has no map_attributes lines")
    # A map's `connection` lines follow its `map_attributes`; skip past them so
    # the new entry does not land inside its predecessor's neighbours.
    end = _until(lines, at + 1, lambda ln: not ln.strip()
                 or bool(_ATTR_RE.match(ln)))
    lines.insert(end, line)
    return Edit(ATTRIBUTES, True, f"{spec.label} attributes",
                "\n".join(lines), base=original)


# --------------------------------------------------------------------------- #
# putting an entry in a section                                               #
# --------------------------------------------------------------------------- #

def _place(root: Path, placement: Placement, section: Section, *,
           entry: list[str]) -> Edit:
    """Append `entry` into `section`, minting the section if it is not there.

    Which of the two happens is not decided here: `Placement.resolve` already
    refused to hand back a section name a `JOIN` tree does not have, so a name
    that is missing at this point is one a `MINT` tree is entitled to create.
    """
    rel = placement.path
    lines, original = _lines(root, rel)
    at = next((i for i, ln in enumerate(lines)
               if (m := _SECTION_RE.match(ln)) and m.group(1) == section.name),
              None)
    if at is None:
        lines += ["", f'SECTION "{section.name}", ROMX', "", *entry]
        detail = f"minted SECTION {section.name!r}"
    else:
        end = _until(lines, at + 1, lambda ln: bool(_ENDS_RE.match(ln)))
        while end > at + 1 and not lines[end - 1].strip():
            end -= 1
        lines[end:end] = ["", *entry]
        detail = f"appended to SECTION {section.name!r}"
    return Edit(rel, True, detail, "\n".join(lines), base=original)


# --------------------------------------------------------------------------- #
# small shared mechanics                                                      #
# --------------------------------------------------------------------------- #

def _lines(root: Path, rel: str) -> tuple[list[str], str]:
    path = root / rel
    if not path.exists():
        raise EditError(f"{rel} is missing")
    original = path.read_text()
    return original.split("\n"), original


def _group(lines: list[str], group: int, marker: re.Pattern,
           rel: str) -> tuple[int, int]:
    """The half-open line range of the `group`-th block opened by `marker`."""
    starts = [i for i, ln in enumerate(lines) if marker.match(ln)]
    if not 1 <= group <= len(starts):
        raise EditError(f"{rel}: group {group} is not one of the "
                        f"{len(starts)} groups in this tree")
    start = starts[group - 1]
    end = starts[group] if group < len(starts) else len(lines)
    return start, end


def _last(lines: list[str], start: int, end: int,
          pattern: re.Pattern) -> int | None:
    return next((i for i in range(end - 1, start - 1, -1)
                 if pattern.match(lines[i])), None)


def _until(lines: list[str], start: int, stop) -> int:
    return next((i for i in range(start, len(lines)) if stop(lines[i])),
                len(lines))


def _like(template: str, body: str, comment: str) -> str:
    """`body` with `comment` in the column the file already puts it in.

    These files align their trailing index comments into a column, and matching
    it is not reformatting — it is declining to be the one line that doesn't.
    A template with no comment gets none back.
    """
    at = template.find(";")
    if at < 0:
        return body
    return body.ljust(max(at, len(body) + 1)) + comment
