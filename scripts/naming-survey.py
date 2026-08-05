#!/usr/bin/env python3
"""Count the functions whose name does not say what they do to what.

CLAUDE.md: *name functions with a verb and its object* — reading the name alone,
could someone answer *what does this return or change?* `get_registered_hacks`
passes, `discover` does not, and `rom_path` does not either: a bare noun is a
step below a bare verb, because it reads as an attribute.

    python scripts/naming-survey.py            # the counts, per product
    python scripts/naming-survey.py --list D   # every name still owed, in D
    python scripts/naming-survey.py --file src/.../paths.py

**This is a survey, not a gate.** The debt is ~500 functions across four
products, and a single commit renaming them would be the exact shape that has
bitten this refactor three times: a word-boundary rename is not a rename, and at
500 names nobody can read every hit. So it is paid **on touch** — each phase
renames the functions in files it already had a reason to open — and this script
is how that drains measurably instead of by assertion. Run it before and after a
phase; the number is the phase's naming line.

**It over-reports on purpose.** The verb list below is finite and English is not,
so a name it flags may be fine. Three known families it gets wrong, left in
rather than special-cased, because a survey that quietly forgives things stops
measuring:

* `main` and `cmd_*` — Phase 1's R3 keeps these deliberately: for a tool whose
  whole product is a command, the command line is the domain.
* past participles — `spliced`, `repainted`, `_purged` read as *"the thing,
  spliced"* and answer the question a name has to answer.
* plural collections — `banks`, `sections`, `labels` return exactly what they
  say. `get_banks` is the rule's form; whether it is an improvement is a
  judgement this script does not make.

A name in one of those families is a reading, not a rename. Record the decision
in the phase's STATE; do not add it here, or the survey starts measuring the
allowlist instead of the code.
"""

from __future__ import annotations

import argparse
import ast
import sys
from collections import defaultdict
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent / "src" / "pokeprism_devtools"

#: Product membership, kept in step with `tests/test_products.py::PRODUCTS`.
PRODUCTS = {
    "A": ("shared", "asmedit", "usage", "sym_lookup"),
    "B": ("contract",),
    "C": ("studio", "hacks/vanilla", "hacks/polished"),
    "D": ("hacks/prism", "dev_server", "gfx_view", "map_inspect", "map_new",
          "map_show", "mapfit", "maplint", "mapview", "metatiles"),
}

#: Words that start a name saying what it *does*. Deliberately not exhaustive —
#: see the module docstring on why over-reporting is the point.
VERBS = frozenset("""
add apply are as ask assert boot build can check choose claim clear close collect
colour color compress compute connect copy count create decode declare decompress
dedent delete describe digest divide draw emit encode ensure explain fill filter
find fix flag fmt fork format free from get grow has hash init insert instantiate
is iter join launch lift list load lookup make mark match measure mount move must
name next normalise normalize offer open pack paint parse patch pick pin place
play prefill prev print query read rebuild refresh register reload remove replace
report reserve reset resize resolve rewrite reword run save scan seed select set
should show shrink sketch sort spell splice split stamp start step stop strip
suggest swap to trim unpack update validate walk wrap write yield
""".split())


def product_of(rel: str) -> str | None:
    parts = rel.split("/")
    for name, owned in PRODUCTS.items():
        if parts[0] in owned or "/".join(parts[:2]) in owned:
            return name
    return None


def says_what_it_does(name: str) -> bool:
    """Whether the name opens with a verb. The whole of the check."""
    return name.lstrip("_").split("_")[0].lower() in VERBS


def unnamed_functions(root: Path) -> dict[str, list[tuple[str, str, int]]]:
    """Every module-level function whose name opens with a non-verb, by product.

    Module-level only: a method reads against its class (`Writer.form` says what
    it does to what), and folding methods in would triple the count with names
    the rule does not judge the same way.
    """
    found: dict[str, list[tuple[str, str, int]]] = defaultdict(list)
    for f in sorted(root.rglob("*.py")):
        rel = str(f.relative_to(PKG))
        product = product_of(rel)
        if product is None:
            continue
        try:
            tree = ast.parse(f.read_text())
        except SyntaxError:
            found["!"].append((rel, "<unparseable>", 0))
            continue
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not says_what_it_does(node.name):
                    found[product].append((rel, node.name, node.lineno))
    return found


def print_counts(found: dict[str, list[tuple[str, str, int]]]) -> None:
    total = 0
    for product in "ABCD":
        rows = found.get(product, [])
        total += len(rows)
        files = len({rel for rel, _, _ in rows})
        print(f"  {product}  {len(rows):>4} functions in {files:>3} files")
    print(f"  --\n  {total:>7} tree-wide")
    if found.get("!"):
        print(f"  WARNING: {len(found['!'])} file(s) did not parse")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="naming-survey",
        description="Functions whose name does not say what they do to what.")
    ap.add_argument("--list", metavar="PRODUCT", choices=list("ABCD"),
                    help="print every name still owed in one product")
    ap.add_argument("--file", metavar="PATH",
                    help="print the names owed in one file")
    args = ap.parse_args(argv)

    found = unnamed_functions(PKG)

    if args.file:
        want = str(Path(args.file).resolve().relative_to(PKG))
        rows = [r for rows in found.values() for r in rows if r[0] == want]
        for rel, name, line in sorted(rows, key=lambda r: r[2]):
            print(f"  {rel}:{line}  {name}")
        print(f"  {len(rows)} owed in {want}")
        return 0

    if args.list:
        for rel, name, line in sorted(found.get(args.list, [])):
            print(f"  {rel}:{line}  {name}")
        print(f"  {len(found.get(args.list, []))} owed in product {args.list}")
        return 0

    print_counts(found)
    return 0


if __name__ == "__main__":
    sys.exit(main())
