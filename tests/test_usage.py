#!/usr/bin/env python3
"""Characterization tests for prism-usage: every subcommand's exact output.

Hermetic — a synthetic .map in a temp dir, no ROM/build.

    python tests/test_usage.py

`usage` was the one CLI package with no test at all, and measured by line its
445 LOC ran 0% of themselves (docs/refactor-phase-1-STATE.md). Its eight
commands print rather than return, so nothing about them was pinned. These
goldens are recorded from the behaviour as it stood before the package was
split, which is the only thing that can say afterwards whether the split moved
code or changed it.

Golden output is deliberate. A test asserting "the summary mentions three
banks" would survive a rewrite of every line it prints; these do not.

Two normalisations, both because the value is not the code's to decide: the
build timestamp comes from the file's mtime, and colour is off because stdout
is not a tty under capture — which is `_color()`'s real answer, not a stub.
"""

from __future__ import annotations

import contextlib
import io
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pokeprism_devtools import usage  # noqa: E402

_failures = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global _failures
    mark = "OK  " if cond else "FAIL"
    print(f"  [{mark}] {label}{(': ' + detail) if detail else ''}")
    if not cond:
        _failures += 1


# Three ROMX banks and a WRAMX one: a roomy bank, a nearly-full bank (the only
# one `check` should ever flag), the bank holding "Map Headers", and a RAM
# region so `--region` has something to find. `TOTAL EMPTY` must equal capacity
# minus the sections, or MapFile.parse rejects the file.
_OLD_MAP = """ROMX bank #1:
  SECTION: $4000-$41f3 ($01f4 bytes) ["Map Scripts 1"]
  SECTION: $4200-$4a3f ($0840 bytes) ["Caper Ridge BlockData"]
  TOTAL EMPTY: $35cc bytes
ROMX bank #2:
  SECTION: $4000-$7f7f ($3f80 bytes) ["Big Tileset"]
  TOTAL EMPTY: $0080 bytes
ROMX bank #3:
  SECTION: $4000-$4fff ($1000 bytes) ["Map Headers"]
  TOTAL EMPTY: $3000 bytes
WRAMX bank #1:
  SECTION: $d000-$d0ff ($0100 bytes) ["Overworld Map"]
  TOTAL EMPTY: $0f00 bytes
"""

# The same ROM one edit later: a block-data section grew, and a script section
# appeared. That is what `diff` has to report.
_NEW_MAP = """ROMX bank #1:
  SECTION: $4000-$41f3 ($01f4 bytes) ["Map Scripts 1"]
  SECTION: $4200-$4c3f ($0a40 bytes) ["Caper Ridge BlockData"]
  TOTAL EMPTY: $33cc bytes
ROMX bank #2:
  SECTION: $4000-$7f7f ($3f80 bytes) ["Big Tileset"]
  TOTAL EMPTY: $0080 bytes
ROMX bank #3:
  SECTION: $4000-$4fff ($1000 bytes) ["Map Headers"]
  SECTION: $5000-$50ff ($0100 bytes) ["Mound B2F Script"]
  TOTAL EMPTY: $2f00 bytes
WRAMX bank #1:
  SECTION: $d000-$d0ff ($0100 bytes) ["Overworld Map"]
  TOTAL EMPTY: $0f00 bytes
"""

_BUILT_RE = re.compile(r"\(built: \d{4}-\d\d-\d\d \d\d:\d\d:\d\d\)")


def _scrub(text: str) -> str:
    """The summary header prints the .map's mtime, which a temp file makes new
    every run. Nothing else in any command's output depends on the clock."""
    return _BUILT_RE.sub("(built: TIMESTAMP)", text)


def _run(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = usage.main(argv)
    return rc, _scrub(out.getvalue()), err.getvalue()


def test_bank_selectors() -> None:
    print("\nparse_bank_selectors")
    check("decimal", usage.parse_bank_selectors(["23"]) == [23])
    check("$hex", usage.parse_bank_selectors(["$17"]) == [23])
    check("0x hex", usage.parse_bank_selectors(["0x17"]) == [23])
    check("bare hex digits", usage.parse_bank_selectors(["1a"]) == [26])
    check("inclusive range", usage.parse_bank_selectors(["10-12"]) == [10, 11, 12])
    check("reversed range is normalised",
          usage.parse_bank_selectors(["12-10"]) == [10, 11, 12])
    check("sorted and deduped across tokens",
          usage.parse_bank_selectors(["5", "3", "3", "4-5"]) == [3, 4, 5])

    try:
        usage.parse_bank_selectors(["zz!"])
        check("a junk token raises ValueError", False, "no exception")
    except ValueError as e:
        check("a junk token raises ValueError", "zz!" in str(e), str(e))


#: (label, argv, expected rc, expected stdout, expected stderr). Recorded from
#: the package before it was split, not written by hand.
_CASES: list[tuple[str, list[str], int, str, str]] = [
    (
        "summary", ["--map", "{new}"], 0,
        """new.map   (built: TIMESTAMP)

ROM     23,732 / 49,152 bytes used   (48.3%)
        25,420 free across 3 banks

WRAMX   256 / 4,096 bytes used   (6.2%)

Most-full ROM banks (top 5)
  Bank $02   128 bytes free   99.22%
  Bank $03   12,032 bytes free   26.56%
  Bank $01   13,260 bytes free   19.07%

Most-free ROM banks (top 5)
  Bank $01   13,260 bytes free   19.1% used
  Bank $03   12,032 bytes free   26.6% used
  Bank $02   128 bytes free   99.2% used
""", "",
    ),
    (
        "banks", ["--map", "{new}", "banks"], 0,
        """Bank $01  ███░░░░░░░░░░░░░   19%  13,260 free
Bank $02  ████████████████   99%  128 free
Bank $03  ████░░░░░░░░░░░░   27%  12,032 free
""", "",
    ),
    (
        "banks with a selector", ["--map", "{new}", "banks", "1", "3"], 0,
        """Bank $01  ███░░░░░░░░░░░░░   19%  13,260 free
Bank $03  ████░░░░░░░░░░░░   27%  12,032 free
""", "",
    ),
    (
        "banks --region", ["--map", "{new}", "banks", "--region", "WRAMX"], 0,
        """Bank $01  █░░░░░░░░░░░░░░░    6%  3,840 free
""", "",
    ),
    (
        "banks --region with nothing in it",
        ["--map", "{new}", "banks", "--region", "SRAM"], 1,
        "", "no banks in region SRAM\n",
    ),
    (
        "bank", ["--map", "{new}", "bank", "1"], 0,
        """Bank $01 (ROMX)
  Used: 3,124 / 16,384 bytes   (19.1%)
  Free: 13,260 bytes

Sections
  $4000–$41f3  $01f4 bytes  Map Scripts 1
  $4200–$4c3f  $0a40 bytes  Caper Ridge BlockData
""", "",
    ),
    (
        "bank over a range", ["--map", "{new}", "bank", "1-2"], 0,
        """Bank $01 (ROMX)
  Used: 3,124 / 16,384 bytes   (19.1%)
  Free: 13,260 bytes

Sections
  $4000–$41f3  $01f4 bytes  Map Scripts 1
  $4200–$4c3f  $0a40 bytes  Caper Ridge BlockData

Bank $02 (ROMX)
  Used: 16,256 / 16,384 bytes   (99.2%)
  Free: 128 bytes

Sections
  $4000–$7f7f  $3f80 bytes  Big Tileset
""", "",
    ),
    (
        "bank that does not exist", ["--map", "{new}", "bank", "99"], 1,
        "", "no bank #99 (0x63) found\n",
    ),
    (
        "largest", ["--map", "{new}", "largest", "-n", "3"], 0,
        """Section                    Size   Bank
Big Tileset              16,256   $02
Map Headers               4,096   $03
Caper Ridge BlockData     2,624   $01
""", "",
    ),
    (
        "free", ["--map", "{new}", "free"], 0,
        """Bank $01    13,260 bytes free   ROMX
Bank $03    12,032 bytes free   ROMX
Bank $02       128 bytes free   ROMX
""", "",
    ),
    (
        "section by exact name", ["--map", "{new}", "section", "Map Headers"], 0,
        """Map Headers   $03     4,096 bytes

Total: 1 occurrence, 4,096 bytes across 1 bank
""", "",
    ),
    (
        "section by substring", ["--map", "{new}", "section", "blockdata"], 0,
        """Caper Ridge BlockData   $01     2,624 bytes

Total: 1 occurrence, 2,624 bytes across 1 bank
""", "",
    ),
    (
        "section with no match", ["--map", "{new}", "section", "Nope"], 1,
        "", "no section matching 'Nope'\n",
    ),
    (
        "check under the threshold",
        ["--map", "{new}", "check", "--max-bank-usage", "99.5"], 0, "", "",
    ),
    (
        "check over the threshold", ["--map", "{new}", "check"], 1,
        """ERROR: Bank $02 exceeds threshold
  Usage: 99.22%   (limit: 95.0%)
  Used:  16,256 / 16,384 bytes

""", "",
    ),
    (
        "diff", ["diff", "{old}", "{new}"], 0,
        """ROM utilization:  +1.6%   (22,964 → 23,732)

Banks
  Bank $01   +512 bytes used
  Bank $03   +256 bytes used

Sections
  Caper Ridge BlockData   +512   2,112 → 2,624

New sections   (1)
  Mound B2F Script  $03  +256

Removed sections   (0)
""", "",
    ),
]


def test_commands(old: Path, new: Path) -> None:
    print("\nevery subcommand's exact output")
    for label, argv_template, want_rc, want_out, want_err in _CASES:
        argv = [a.format(old=old, new=new) for a in argv_template]
        rc, out, err = _run(argv)
        check(f"{label}: exit code", rc == want_rc,
              "" if rc == want_rc else f"got {rc}, want {want_rc}")
        check(f"{label}: stdout", out == want_out,
              "" if out == want_out else f"\n--- got ---\n{out}--- want ---\n{want_out}")
        check(f"{label}: stderr", err == want_err,
              "" if err == want_err else f"got {err!r}, want {want_err!r}")


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        old, new = tmp / "old.map", tmp / "new.map"
        old.write_text(_OLD_MAP)
        new.write_text(_NEW_MAP)

        test_bank_selectors()
        test_commands(old, new)

    print()
    if _failures:
        print(f"{_failures} check(s) FAILED")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
