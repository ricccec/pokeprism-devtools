#!/usr/bin/env python3
"""Characterization tests for prism-map: what it reports about one map.

Hermetic — a temp fixture repo, no ROM/build.

    python tests/test_map_show.py

`map_show` is the one of Phase 1's six packages with no test file of its own.
Its analysis half is covered by `test_grid.py` and `test_mapsource.py`, which
are named for what they test rather than for the package; the command that
prints the report was covered by nothing.

Unlike the other four CLIs pinned in this phase, `map_show` holds none of the
over-long functions being shortened — `main` is 44 lines and `_print_report`
is 44. These goldens are therefore insurance for the phases that move this
code, not an oracle for a shortening happening now.

Goldens are recorded from the behaviour as it stood, not written by hand.

**`--grid` is deliberately not covered.** Drawing a map needs real tileset
graphics, a palette table and decompressed block data — a fixture an order of
magnitude larger than everything else here, for a code path that is one call
into `grid.print_grid`. `test_grid.py` covers the zoom arithmetic under it.
"""

from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pokeprism_devtools import map_show  # noqa: E402

_failures = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global _failures
    mark = "OK  " if cond else "FAIL"
    print(f"  [{mark}] {label}{(': ' + detail) if detail else ''}")
    if not cond:
        _failures += 1


#: `compressed_blk_size` shells out to `utils/lzcomp` and takes the size of
#: what it writes; a stub at that process boundary keeps the number fixed.
_LZCOMP_STUB = """#!/bin/sh
wc -c < "$2" | awk '{ n = int($1 / 2); s = ""; while (length(s) < n) s = s "z"; \
printf "%s", s }' > "$3"
"""

#: CaperRidge has its own section for every blob. MoundB2F deliberately does
#: not: its script is INCLUDEd into the shared "Map Scripts 1", which is the
#: case the report exists to flag — prism-mapfit cannot relocate it.
_MAP = """ROMX bank #1:
  SECTION: $4000-$7eff ($3f00 bytes) ["Map Scripts 1"]
  TOTAL EMPTY: $0100 bytes
ROMX bank #2:
  SECTION: $4000-$5fff ($2000 bytes) ["Map Headers"]
  SECTION: $6000-$63ff ($0400 bytes) ["Map Scripts CaperRidge"]
  SECTION: $6400-$65ff ($0200 bytes) ["Map block data CaperRidge"]
  SECTION: $6600-$661a ($001b bytes) ["Second Map Header CaperRidge"]
  TOTAL EMPTY: $19e5 bytes
"""


def _fixture_repo(tmp: Path) -> Path:
    root = tmp / "repo"
    (root / "constants").mkdir(parents=True)
    (root / "maps" / "blk").mkdir(parents=True)
    (root / "utils").mkdir()

    (root / "Makefile").write_text("all:\n")
    (root / "main.asm").write_text('INCLUDE "constants.asm"\n')

    lzcomp = root / "utils" / "lzcomp"
    lzcomp.write_text(_LZCOMP_STUB)
    lzcomp.chmod(0o755)

    (root / "constants" / "map_dimension_constants.asm").write_text(
        "\tconst_def\n"
        "\tnewgroup ; 1\n"
        "\tmapgroup CAPER_RIDGE, 9, 20\n"
        "\tmapgroup MOUND_B2F, 8, 8\n"
    )
    (root / "maps" / "map_headers.asm").write_text(
        'SECTION "Map Headers", ROMX\n'
        "MapGroup1:\n"
        "\tmap_header CaperRidge, TILESET_NALJO_2, TOWN, CAPER_RIDGE, "
        "MUSIC_NEW_BARK_TOWN, 0, PALETTE_AUTO, FISHGROUP_SHORE\n"
        "\tmap_header MoundB2F, TILESET_CAVE4, INDOOR, MOUND, "
        "MUSIC_NONE, 1, PALETTE_NITE, FISHGROUP_NONE\n"
    )
    (root / "maps" / "second_map_headers.asm").write_text(
        'SECTION "Second Map Header CaperRidge", ROMX\n'
        "\tmap_header_2 CaperRidge, CAPER_RIDGE, $3f, NORTH | EAST\n"
        "\tconnection north, MtEmber, MT_EMBER, 0\n"
        "\tconnection east, KindleRoad, KINDLE_ROAD, -3\n"
        'SECTION "Second Map Header MoundB2F", ROMX\n'
        "\tmap_header_2 MoundB2F, MOUND_B2F, 0, 0\n"
    )
    (root / "maps" / "blockdata.asm").write_text(
        'SECTION "Map block data CaperRidge", ROMX\n'
        "CaperRidge_BlockData:\n"
        '\tINCBIN "maps/blk/CaperRidge.blk.lz"\n'
        'SECTION "Map block data 1", ROMX\n'
        "MoundB2F_BlockData:\n"
        '\tINCBIN "maps/blk/MoundB2F.blk.lz"\n'
    )
    (root / "maps" / "map_scripts.asm").write_text(
        'SECTION "Map Scripts CaperRidge", ROMX\n'
        'INCLUDE "maps/CaperRidge.asm"\n'
        'SECTION "Map Scripts 1", ROMX\n'
        'INCLUDE "maps/MoundB2F.asm"\n'
    )
    (root / "maps" / "CaperRidge.asm").write_text(
        "CaperRidge_MapScriptHeader:\n\tdb 0\n\tdb 0\n"
    )
    (root / "maps" / "MoundB2F.asm").write_text(
        "MoundB2F_MapScriptHeader:\n\tdb 0\n\tdb 0\n"
    )
    (root / "maps" / "blk" / "CaperRidge.blk").write_bytes(bytes(180))
    (root / "maps" / "blk" / "MoundB2F.blk").write_bytes(bytes(64))
    (root / "build.map").write_text(_MAP)
    return root


def _run_cli(argv: list[str], cwd: Path) -> tuple[int, str, str]:
    """Run `prism-map <argv>` with *cwd* as the repo."""
    out, err = io.StringIO(), io.StringIO()
    old_cwd = Path.cwd()
    os.chdir(cwd)
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                rc = map_show.main(argv)
            except SystemExit as e:
                rc = e.code if isinstance(e.code, int) else 0
    finally:
        os.chdir(old_cwd)
    return rc, out.getvalue(), err.getvalue()


#: (label, argv, expected rc, expected stdout, expected stderr). `{map}` is
#: filled in per run. Recorded from the package as it stood.
_CLI_CASES: list[tuple[str, list[str], int, str, str]] = [
    (
        'the report, with a .map for banks',
        ['CaperRidge', '--map', '{map}'], 0,
        """Map: CaperRidge  (CAPER_RIDGE)
  group 1 · 9x20 (180 blocks)

Header (map_header)
  tileset     TILESET_NALJO_2
  permission  TOWN
  landmark    CAPER_RIDGE
  music       MUSIC_NEW_BARK_TOWN
  phone       0
  palette     PALETTE_AUTO
  fishgroup   FISHGROUP_SHORE

Secondary (map_header_2)
  border_block $3f
  conn_flags  NORTH | EAST
  connection  north, MtEmber, MT_EMBER, 0
  connection  east, KindleRoad, KINDLE_ROAD, -3

Files
  script      maps/CaperRidge.asm
  blk         maps/blk/CaperRidge.blk

Sections
  primary    Map Headers                     $02        9 B
  secondary  Second Map Header CaperRidge    $02       36 B
  blk        Map block data CaperRidge       $02       90 B
  script     Map Scripts CaperRidge          $02     1024 B
""",
        "",
    ),
    (
        'the report with no .map at all',
        ['CaperRidge'], 0,
        """Map: CaperRidge  (CAPER_RIDGE)
  group 1 · 9x20 (180 blocks)

Header (map_header)
  tileset     TILESET_NALJO_2
  permission  TOWN
  landmark    CAPER_RIDGE
  music       MUSIC_NEW_BARK_TOWN
  phone       0
  palette     PALETTE_AUTO
  fishgroup   FISHGROUP_SHORE

Secondary (map_header_2)
  border_block $3f
  conn_flags  NORTH | EAST
  connection  north, MtEmber, MT_EMBER, 0
  connection  east, KindleRoad, KINDLE_ROAD, -3

Files
  script      maps/CaperRidge.asm
  blk         maps/blk/CaperRidge.blk

Sections
  (no .map found — bank column omitted; pass --map or build the ROM)
  primary    Map Headers                     n/a        9 B
  secondary  Second Map Header CaperRidge    n/a       36 B
  blk        Map block data CaperRidge       n/a       90 B
  script     Map Scripts CaperRidge          n/a  40 B (src)
  (src) script size is the source .asm byte count (no dedicated .map section to measure); the assembled size differs.
""",
        "",
    ),
    (
        'a map whose script shares a section',
        ['MoundB2F', '--map', '{map}'], 0,
        """Map: MoundB2F  (MOUND_B2F)
  group 1 · 8x8 (64 blocks)

Header (map_header)
  tileset     TILESET_CAVE4
  permission  INDOOR
  landmark    MOUND
  music       MUSIC_NONE
  phone       1
  palette     PALETTE_NITE
  fishgroup   FISHGROUP_NONE

Secondary (map_header_2)
  border_block 0
  conn_flags  0
  connections (none)

Files
  script      maps/MoundB2F.asm
  blk         maps/blk/MoundB2F.blk

Sections
  primary    Map Headers                   $02        9 B
  secondary  Second Map Header MoundB2F      ?       12 B
  blk        Map block data 1                ?       32 B *shared*
  script     Map Scripts 1                 $01  38 B (src) *shared*

  * in a section shared with other maps — prism-mapfit can't relocate it independently until it's in its own section.
  (src) script size is the source .asm byte count (no dedicated .map section to measure); the assembled size differs.
""",
        "",
    ),
    (
        '--toml emits the spec',
        ['CaperRidge', '--toml'], 0,
        """label       = "CaperRidge"
const       = "CAPER_RIDGE"
group       = 1
height      = 9
width       = 20

# primary header (map_header)
tileset     = "TILESET_NALJO_2"
permission  = "TOWN"
landmark    = "CAPER_RIDGE"
music       = "MUSIC_NEW_BARK_TOWN"
palette     = "PALETTE_AUTO"
fishgroup   = "FISHGROUP_SHORE"
phone       = 0

# secondary header (map_header_2)
border_block = "$3f"
conn_flags   = "NORTH | EAST"
connections = [
    "north, MtEmber, MT_EMBER, 0",
    "east, KindleRoad, KINDLE_ROAD, -3",
]

# authored content (repo-relative)
script_asm  = "maps/CaperRidge.asm"
blk         = "maps/blk/CaperRidge.blk"

# section name overrides (blank = "<Kind> <Label>" convention)
blockdata_section = ""
script_section    = ""
secondary_section = ""

# placement (blank / -1 = auto: let mapfit's packer choose a bank)
#   *_into: append into this existing SECTION, inheriting its bank
#   *_bank: own SECTION, pinned to this bank
blockdata_into = ""
script_into    = ""
secondary_into = ""
blockdata_bank = -1
script_bank    = -1
secondary_bank = -1
""",
        "",
    ),
]


def test_cli(root: Path) -> None:
    print("\nprism-map — exact output")
    for label, argv_t, want_rc, want_out, want_err in _CLI_CASES:
        argv = [a.format(map=root / "build.map") for a in argv_t]
        rc, out, err = _run_cli(argv, root)
        check(f"{label}: exit code", rc == want_rc,
              "" if rc == want_rc else f"got {rc}, want {want_rc}")
        check(f"{label}: stdout", out == want_out,
              "" if out == want_out else f"\n--- got ---\n{out}--- want ---\n{want_out}")
        check(f"{label}: stderr", err == want_err,
              "" if err == want_err else f"\n--- got ---\n{err}--- want ---\n{want_err}")


def test_out_writes_the_toml_to_a_file(root: Path, tmp: Path) -> None:
    """`-o` implies `--toml` and sends the spec to a file, not to stdout —
    so stdout stays clean for a caller redirecting it, and the "wrote" notice
    goes to stderr."""
    print("\nprism-map -o")
    dest = tmp / "spec.toml"
    rc, out, err = _run_cli(["CaperRidge", "-o", str(dest)], root)
    check("exit code 0", rc == 0, f"got {rc}")
    check("nothing on stdout", out == "", out)
    check("the notice names the file", err == f"wrote {dest}\n", repr(err))
    check("the file holds the spec",
          dest.exists() and '"CaperRidge"' in dest.read_text()
          and '"CAPER_RIDGE"' in dest.read_text(),
          dest.read_text()[:200] if dest.exists() else "absent")

    stdout_rc, stdout_out, _ = _run_cli(["CaperRidge", "--toml"], root)
    check("-o and --toml produce the same TOML",
          stdout_rc == 0 and stdout_out == dest.read_text())


def test_a_missing_map_is_named_not_guessed(root: Path) -> None:
    print("\nprism-map — a label that is not wired")
    rc, out, err = _run_cli(["NoSuchMap"], root)
    check("exit code 2", rc == 2, f"got {rc}")
    check("stdout is empty", out == "", out)
    check("stderr says which file it looked in",
          err.startswith("error: no `map_header_2 NoSuchMap, ...` in "
                         "maps/second_map_headers.asm"), repr(err))


def test_cli_outside_a_repo(tmp: Path) -> None:
    print("\nprism-map — run from outside a game repo")
    outside = tmp / "elsewhere"
    outside.mkdir()
    rc, out, err = _run_cli(["CaperRidge"], outside)
    check("exit code 2", rc == 2, f"got {rc}")
    check("stdout is empty", out == "", out)
    check("stderr reports the missing root",
          err.startswith("error: Could not find pokeprism repo root from "), repr(err))


def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        root = _fixture_repo(tmp)
        test_cli(root)
        test_out_writes_the_toml_to_a_file(root, tmp)
        test_a_missing_map_is_named_not_guessed(root)
        test_cli_outside_a_repo(tmp)

    print()
    if _failures:
        print(f"{_failures} check(s) FAILED")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
