#!/usr/bin/env python3
"""Tests for prism-maps: the used/RAW/LZ detection in map_inspect.collect(),
and the exact output of every flag its command line offers.
Hermetic — temp fixtures, no ROM/build.

    python tests/test_map_inspect.py

The CLI half is characterization, added before `main` and `collect` are
shortened: measured against the whole suite, `main`'s 65 lines ran none and
`collect`'s 61 ran 46, so nothing pinned what the command actually prints.
Goldens are recorded from the behaviour as it stood, not written by hand.

`main` is driven through `sys.argv` and `SystemExit`, not by passing an argv
list, because that is how the console entry point really calls it — and it
keeps the test honest if `main` later grows a parameter.
"""

from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pokeprism_devtools import map_inspect  # noqa: E402

_failures = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global _failures
    mark = "OK  " if cond else "FAIL"
    print(f"  [{mark}] {label}{(': ' + detail) if detail else ''}")
    if not cond:
        _failures += 1


def _fixture_repo(tmp: Path) -> Path:
    root = tmp / "repo"
    (root / "constants").mkdir(parents=True)
    (root / "maps" / "blk").mkdir(parents=True)

    # What repo_root() walks up looking for; the CLI locates the tree by cwd.
    (root / "Makefile").write_text("all:\n")
    (root / "main.asm").write_text('INCLUDE "constants.asm"\n')

    (root / "constants" / "map_dimension_constants.asm").write_text(
        "\tconst_def\n"
        "\tnewgroup ; 1\n"
        "\tmapgroup CAPER_RIDGE, 10, 9\n"          # fully wired, normal
        "\tmapgroup MT_EMBER_SOUTH, 15, 52\n"       # merged blk filename
        "\tmapgroup MOUND_B2F, 8, 8\n"              # aliased labels
        "\tmapgroup GHOST_TOWN, 4, 4\n"              # never wired
        "\tmapgroup OLD_LAB, 4, 4\n"                 # commented-out blockdata
    )

    (root / "maps" / "second_map_headers.asm").write_text(
        'SECTION "Second Map Header CaperRidge", ROMX\n'
        "\tmap_header_2 CaperRidge, CAPER_RIDGE, 0, NORTH\n"
        'SECTION "Second Map Header MtEmberSouth", ROMX\n'
        "\tmap_header_2 MtEmberSouth, MT_EMBER_SOUTH, $43, NORTH | EAST\n"
        'SECTION "Second Map Header MoundB2F", ROMX\n'
        "\tmap_header_2 MoundB2FDark, MOUND_B2F, $9, 0\n"
        "\tmap_header_2 MoundB2F, MOUND_B2F, 9, 0\n"
        'SECTION "Second Map Header OldLab", ROMX\n'
        "\tmap_header_2 OldLab, OLD_LAB, 0, 0\n"
        "\t; map_header_2 CommentedOut, GHOST_TOWN, 0, 0\n"
    )

    (root / "maps" / "blockdata.asm").write_text(
        'SECTION "Map block data 1", ROMX\n'
        "CaperRidge_BlockData:\n"
        '\tINCBIN "maps/blk/CaperRidge.blk.lz"\n'
        'SECTION "Map block data MtEmberSouth", ROMX\n'
        "MtEmberSouth_BlockData:\n"
        '\tINCBIN "maps/blk/MtEmberSouthKindleRoadMerge.blk.lz"\n'
        'SECTION "Map block data Mound", ROMX\n'
        "MoundB2FDark_BlockData:\n"
        '\tINCBIN "maps/blk/MoundB2FDark.blk.lz"\n'
        "MoundB2F_BlockData:\n"
        '\tINCBIN "maps/blk/MoundB2F.blk.lz"\n'
        'SECTION "Map block data Old", ROMX\n'
        ";OldLab_BlockData:\n"
        '\t;INCBIN "maps/blk/OldLab.blk.lz"\n'
    )

    (root / "maps" / "map_scripts.asm").write_text(
        'SECTION "Map Scripts", ROMX\n'
        'INCLUDE "maps/CaperRidge.asm"\n'
        'INCLUDE "maps/MtEmberSouth.asm"\n'
        'INCLUDE "maps/MoundB2F.asm"\n'
        # MoundB2FDark and OldLab are intentionally NOT included.
    )

    (root / "maps" / "CaperRidge.asm").write_text(
        "CaperRidge_MapScriptHeader:\n\tdb 0\n\tdb 0\n"
    )
    (root / "maps" / "MtEmberSouth.asm").write_text(
        "MtEmberSouth_MapScriptHeader:\n\tdb 0\n\tdb 0\n"
    )
    (root / "maps" / "MoundB2F.asm").write_text(
        "MoundB2F_MapScriptHeader:\n\tdb 0\n\tdb 0\n"
    )

    # Real block-data bytes on disk (raw + compressed), including the
    # merged/aliased filenames the labels above actually point at.
    for stem, raw_size, lz_size in [
        ("CaperRidge", 90, 40),
        ("MtEmberSouthKindleRoadMerge", 780, 300),
        ("MoundB2FDark", 64, 30),
        ("MoundB2F", 64, 30),
    ]:
        (root / "maps" / "blk" / f"{stem}.blk").write_bytes(bytes(raw_size))
        (root / "maps" / "blk" / f"{stem}.blk.lz").write_bytes(bytes(lz_size))

    return root


def _run_cli(argv: list[str], cwd: Path) -> tuple[int, str, str]:
    """Run `prism-maps <argv>` with *cwd* as the repo, capturing everything.

    `main` locates the tree from the working directory and reports by exiting,
    so both have to be staged: chdir in, and read the code off SystemExit. An
    exit that never happens is a 0, which is what the console script sees.
    """
    out, err = io.StringIO(), io.StringIO()
    old_cwd, old_argv = Path.cwd(), sys.argv
    os.chdir(cwd)
    sys.argv = ["prism-maps", *argv]
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                map_inspect.main()
                rc = 0
            except SystemExit as e:
                rc = e.code if isinstance(e.code, int) else 0
    finally:
        os.chdir(old_cwd)
        sys.argv = old_argv
    return rc, out.getvalue(), err.getvalue()


#: (label, argv, expected rc, expected stdout). Recorded from the package as it
#: stood, not written by hand. stderr is empty for all of these; the one command
#: that writes to it is checked separately, where the message is the point.
_CLI_CASES: list[tuple[str, list[str], int, str]] = [
    (
        'default table, sorted by name', [], 0,
        """NAME            W   H   BLKS  RAW  LZ   RATIO  SCRIPT  NPCS  USED
--------------  --  --  ----  ---  ---  -----  ------  ----  ----
CAPER_RIDGE     9   10  90    90   40   44%    40      0     ✓   
GHOST_TOWN      4   4   16    —    —    —      —       —     ✗   
MOUND_B2F       8   8   64    64   30   47%    38      0     ✓   
MT_EMBER_SOUTH  52  15  780   780  300  38%    42      0     ✓   
OLD_LAB         4   4   16    —    —    —      —       —     ✗   
""",
    ),
    (
        '--reverse turns the name order around', ['--reverse'], 0,
        """NAME            W   H   BLKS  RAW  LZ   RATIO  SCRIPT  NPCS  USED
--------------  --  --  ----  ---  ---  -----  ------  ----  ----
OLD_LAB         4   4   16    —    —    —      —       —     ✗   
MT_EMBER_SOUTH  52  15  780   780  300  38%    42      0     ✓   
MOUND_B2F       8   8   64    64   30   47%    38      0     ✓   
GHOST_TOWN      4   4   16    —    —    —      —       —     ✗   
CAPER_RIDGE     9   10  90    90   40   44%    40      0     ✓   
""",
    ),
    (
        '--sort blocks', ['--sort', 'blocks'], 0,
        """NAME            W   H   BLKS  RAW  LZ   RATIO  SCRIPT  NPCS  USED
--------------  --  --  ----  ---  ---  -----  ------  ----  ----
GHOST_TOWN      4   4   16    —    —    —      —       —     ✗   
OLD_LAB         4   4   16    —    —    —      —       —     ✗   
MOUND_B2F       8   8   64    64   30   47%    38      0     ✓   
CAPER_RIDGE     9   10  90    90   40   44%    40      0     ✓   
MT_EMBER_SOUTH  52  15  780   780  300  38%    42      0     ✓   
""",
    ),
    (
        '--sort raw keeps the unmeasured maps last', ['--sort', 'raw'], 0,
        """NAME            W   H   BLKS  RAW  LZ   RATIO  SCRIPT  NPCS  USED
--------------  --  --  ----  ---  ---  -----  ------  ----  ----
MOUND_B2F       8   8   64    64   30   47%    38      0     ✓   
CAPER_RIDGE     9   10  90    90   40   44%    40      0     ✓   
MT_EMBER_SOUTH  52  15  780   780  300  38%    42      0     ✓   
GHOST_TOWN      4   4   16    —    —    —      —       —     ✗   
OLD_LAB         4   4   16    —    —    —      —       —     ✗   
""",
    ),
    (
        '--sort raw --reverse keeps them last too', ['--sort', 'raw', '--reverse'], 0,
        """NAME            W   H   BLKS  RAW  LZ   RATIO  SCRIPT  NPCS  USED
--------------  --  --  ----  ---  ---  -----  ------  ----  ----
MT_EMBER_SOUTH  52  15  780   780  300  38%    42      0     ✓   
CAPER_RIDGE     9   10  90    90   40   44%    40      0     ✓   
MOUND_B2F       8   8   64    64   30   47%    38      0     ✓   
GHOST_TOWN      4   4   16    —    —    —      —       —     ✗   
OLD_LAB         4   4   16    —    —    —      —       —     ✗   
""",
    ),
    (
        '--search is a case-insensitive substring', ['--search', 'mound'], 0,
        """NAME       W  H  BLKS  RAW  LZ  RATIO  SCRIPT  NPCS  USED
---------  -  -  ----  ---  --  -----  ------  ----  ----
MOUND_B2F  8  8  64    64   30  47%    38      0     ✓   
""",
    ),
    (
        '--min-blocks', ['--min-blocks', '90'], 0,
        """NAME            W   H   BLKS  RAW  LZ   RATIO  SCRIPT  NPCS  USED
--------------  --  --  ----  ---  ---  -----  ------  ----  ----
CAPER_RIDGE     9   10  90    90   40   44%    40      0     ✓   
MT_EMBER_SOUTH  52  15  780   780  300  38%    42      0     ✓   
""",
    ),
    (
        '--max-blocks', ['--max-blocks', '16'], 0,
        """NAME        W  H  BLKS  RAW  LZ  RATIO  SCRIPT  NPCS  USED
----------  -  -  ----  ---  --  -----  ------  ----  ----
GHOST_TOWN  4  4  16    —    —   —      —       —     ✗   
OLD_LAB     4  4  16    —    —   —      —       —     ✗   
""",
    ),
    (
        '--min-blocks and --max-blocks are ANDed', ['--min-blocks', '17', '--max-blocks', '90'], 0,
        """NAME         W  H   BLKS  RAW  LZ  RATIO  SCRIPT  NPCS  USED
-----------  -  --  ----  ---  --  -----  ------  ----  ----
CAPER_RIDGE  9  10  90    90   40  44%    40      0     ✓   
MOUND_B2F    8  8   64    64   30  47%    38      0     ✓   
""",
    ),
    (
        '--used', ['--used'], 0,
        """NAME            W   H   BLKS  RAW  LZ   RATIO  SCRIPT  NPCS  USED
--------------  --  --  ----  ---  ---  -----  ------  ----  ----
CAPER_RIDGE     9   10  90    90   40   44%    40      0     ✓   
MOUND_B2F       8   8   64    64   30   47%    38      0     ✓   
MT_EMBER_SOUTH  52  15  780   780  300  38%    42      0     ✓   
""",
    ),
    (
        '--unused', ['--unused'], 0,
        """NAME        W  H  BLKS  RAW  LZ  RATIO  SCRIPT  NPCS  USED
----------  -  -  ----  ---  --  -----  ------  ----  ----
GHOST_TOWN  4  4  16    —    —   —      —       —     ✗   
OLD_LAB     4  4  16    —    —   —      —       —     ✗   
""",
    ),
    (
        '--json emits the record, not the table', ['--json', '--search', 'ghost'], 0,
        """[
  {
    "name": "GHOST_TOWN",
    "group": 1,
    "map_id": 4,
    "width": 4,
    "height": 4,
    "blocks": 16,
    "blk_raw": null,
    "blk_lz": null,
    "lz_ratio": null,
    "script_src": null,
    "npc_count": null,
    "used": false
  }
]
""",
    ),
    (
        'a filter that matches nothing exits 1 and prints nothing', ['--search', 'nosuchmap'], 1,
        "",
    ),
]


def test_goldens_kept_their_padding() -> None:
    """`render_table` pads the last column, so every data row ends in spaces.

    That is invisible in an editor and the first thing a stray "strip trailing
    whitespace" would eat — which would fail every golden below at once and
    look like a code defect. This check fails first, and says what happened.
    """
    print("\nthe goldens' trailing padding")
    padded = sum(
        1 for _, _, _, out in _CLI_CASES for line in out.splitlines()
        if line.endswith(" ")
    )
    check("the recorded tables still carry their right-hand padding",
          padded > 0,
          "every golden lost its trailing spaces — an editor stripped them, "
          "the table did not stop emitting them")


def test_cli(root: Path) -> None:
    print("\nprism-maps — every flag's exact output")
    for label, argv, want_rc, want_out in _CLI_CASES:
        rc, out, err = _run_cli(argv, root)
        check(f"{label}: exit code", rc == want_rc,
              "" if rc == want_rc else f"got {rc}, want {want_rc}")
        check(f"{label}: stdout", out == want_out,
              "" if out == want_out else f"\n--- got ---\n{out}--- want ---\n{want_out}")
        check(f"{label}: stderr empty", err == "", err)


def test_cli_outside_a_repo(tmp: Path) -> None:
    """The one path that reports on stderr: no Makefile above the cwd."""
    print("\nprism-maps — run from outside a game repo")
    outside = tmp / "elsewhere"
    outside.mkdir()
    rc, out, err = _run_cli([], outside)
    check("exit code is 2", rc == 2, f"got {rc}")
    check("stdout is empty", out == "", out)
    check("stderr names the tool and the missing root",
          err.startswith("prism-maps: Could not find pokeprism repo root from ")
          and err.endswith("found in any parent directory.\n"), repr(err))


def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        root = _fixture_repo(Path(d))
        rows = {r.name: r for r in map_inspect.collect(root)}

        print("\nmap_inspect.collect() — used detection")
        check("CAPER_RIDGE (normal) used=True", rows["CAPER_RIDGE"].used)
        check(
            "MT_EMBER_SOUTH used=True despite merged blk filename",
            rows["MT_EMBER_SOUTH"].used,
        )
        check(
            "MT_EMBER_SOUTH RAW/LZ resolved via the merged blk file",
            rows["MT_EMBER_SOUTH"].blk_raw == 780 and rows["MT_EMBER_SOUTH"].blk_lz == 300,
            f"raw={rows['MT_EMBER_SOUTH'].blk_raw} lz={rows['MT_EMBER_SOUTH'].blk_lz}",
        )
        check(
            "MOUND_B2F used=True via the fully-wired MoundB2F label "
            "(ignoring the partial MoundB2FDark alias)",
            rows["MOUND_B2F"].used,
        )
        check("GHOST_TOWN (no map_header_2 at all) used=False", not rows["GHOST_TOWN"].used)
        check(
            "GHOST_TOWN RAW/LZ are None",
            rows["GHOST_TOWN"].blk_raw is None and rows["GHOST_TOWN"].blk_lz is None,
        )
        check(
            "OLD_LAB (commented-out _BlockData:) used=False",
            not rows["OLD_LAB"].used,
        )

        test_goldens_kept_their_padding()
        test_cli(root)
        test_cli_outside_a_repo(Path(d))

    print()
    if _failures:
        print(f"{_failures} check(s) FAILED")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
