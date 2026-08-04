"""The four products are separable — asserted, so a carve can be trusted.

`test_contract.py` asserts one arrow, B's. This asserts the other three, and it
is the test that makes the carve safe: if a later commit re-fuses two products,
it fails **here**, in the repo where that is one revert, rather than in four
repos that turn out to import each other.

    A · pret/RGBDS library   shared, asmedit, usage, sym_lookup
    B · adapter contract     contract                          -> A
    C · the IDE              studio, hacks/vanilla, hacks/polished -> A, B
    D · prism                hacks/prism and its nine CLIs      -> A, B

Four checks, and each exists because something real got past a weaker one:

  * **Membership is declared, not derived.** Every module under
    `src/pokeprism_devtools/` is named in exactly one product below. A module in
    none of them fails, so a new file cannot join a product by accident — which
    is the only way this test stays true after it is written.
  * **Every cross-product import points down**, by AST, over **both spellings**.
    Not hypothetical: the first edge map of Phase 3 walked relative imports only
    and reported `dev_server` as importing nothing at all, when it reaches
    `hacks.prism` five times — it is the one package written with absolute
    `from pokeprism_devtools.… import x`.
  * **No prism module reaches the IDE.** Overlaps `test_contract.py` on purpose
    and asks it the other way round: that one asserts a named survivor list,
    this one asserts a *direction* over every module, and a one-directional test
    over one folder pair is exactly what missed `studio -> hacks.mount` for as
    long as it did.
  * **Runtime, per product.** Importing B leaves C and D out of `sys.modules`;
    importing C leaves D out. Kept alongside the static check because Phase 2
    measured that a `TYPE_CHECKING`-only import passes a runtime check and fails
    a static one — neither subsumes the other.

`test_falsified` comes last and matters most: it seeds each check with the
mutation that check exists to catch, and fails if any survives.

    python tests/test_products.py
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
PKG = SRC / "pokeprism_devtools"

#: Every product, as the top-level paths it owns. Written down rather than
#: inferred: a rule that derives membership from imports can only ever say the
#: tree is consistent with itself, and what is wanted is whether it matches the
#: split somebody decided on.
PRODUCTS = {
    "A": ("shared", "asmedit", "usage", "sym_lookup"),
    "B": ("contract",),
    "C": ("studio", "hacks/vanilla", "hacks/polished"),
    "D": ("hacks/prism", "dev_server", "gfx_view", "map_inspect", "map_new",
          "map_show", "mapfit", "maplint", "mapview", "metatiles"),
}

#: What each product may import. A is the floor and imports nothing in this
#: repo; C and D are siblings and neither may reach the other.
MAY_IMPORT = {"A": set(), "B": {"A"}, "C": {"A", "B"}, "D": {"A", "B"}}

#: The namespace files that belong to no one product because every product that
#: carves needs its own copy — the package root, and the folder C and D both
#: keep adapters in. Listed rather than skipped, and checked to define nothing,
#: because four repos each holding a copy is only safe while they are empty.
SCAFFOLD = ("__init__.py", "hacks/__init__.py")

#: `hacks/vanilla` reaching `studio/mapadd.py`. Legal — `AddMap` is the generic
#: new-map form, two of the three hacks mount it as dialects, and vanilla ships
#: with the IDE — so these are C->C and invisible to the cross-product check.
#: Named here anyway, so that the day prism grows a dialect and this list can
#: shrink, somebody decides it rather than discovers it.
WITHIN_C = {
    ("hacks/vanilla/write.py", "studio/mapadd"),
    ("hacks/vanilla/newmap.py", "studio/mapadd"),
}

_failures = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global _failures
    ok = bool(cond)
    print(f"  [{'OK  ' if ok else 'FAIL'}] {label}{f' — {detail}' if detail else ''}")
    if not ok:
        _failures += 1


# --------------------------------------------------------------------------- #
# reading the tree                                                             #
# --------------------------------------------------------------------------- #

def product_of(rel: str) -> str | None:
    """Which product owns this path, or None if nothing claims it."""
    parts = rel.split("/")
    for name, owned in PRODUCTS.items():
        if parts[0] in owned or "/".join(parts[:2]) in owned:
            return name
    return None


def imports_of(f: Path) -> set[str]:
    """Every in-repo module this file names, as a slash path, **both spellings**.

    A relative `from ...shared import make` and an absolute
    `from pokeprism_devtools.shared import make` are the same edge and must
    answer the same. Deferred imports inside a function count: three of the four
    edges Phase 2 left standing were function-local, which is exactly how they
    stayed invisible to a top-of-file grep.

    **The imported names are recorded as well as the module**, because in
    `from ..hacks import prism` the module is `hacks` — which belongs to no
    product, being the folder C and D both keep adapters in — and the *name* is
    what carries the edge. Recording only the module dropped that import
    silently; found by falsifying this function rather than by reading it.
    A name that is a class rather than a module (`from ..contract import Hack`)
    yields a path that does not exist, and classifies to the same product its
    module does, so it costs nothing.
    """
    here = f.relative_to(PKG).parent.parts
    found: set[str] = set()

    def record(parts: list[str], names: list[str]) -> None:
        stem = [p for p in parts if p]
        if stem:
            found.add("/".join(stem))
        found.update("/".join(stem + [n]) for n in names)

    for node in ast.walk(ast.parse(f.read_text())):
        if isinstance(node, ast.ImportFrom):
            names = [a.name for a in node.names]
            if node.level:
                up = node.level - 1
                base = list(here[:len(here) - up]) if up else list(here)
                record(base + (node.module or "").split("."), names)
            elif (node.module or "").split(".")[0] == "pokeprism_devtools":
                record(node.module.split(".")[1:], names)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] == "pokeprism_devtools":
                    record(alias.name.split(".")[1:], [])
    return {m for m in found if m.strip("/")}


def modules() -> list[Path]:
    return sorted(f for f in PKG.rglob("*.py"))


# --------------------------------------------------------------------------- #
# 1 · every module belongs to exactly one product                              #
# --------------------------------------------------------------------------- #

def test_every_module_has_a_product() -> list[Path]:
    print("\nevery module under src/ belongs to exactly one product")
    files = modules()
    check("there are modules to check at all", len(files) > 100, str(len(files)))

    homeless = sorted(str(f.relative_to(PKG)) for f in files
                      if product_of(str(f.relative_to(PKG))) is None
                      and str(f.relative_to(PKG)) not in SCAFFOLD)
    check("no module is outside all four products", not homeless,
          ", ".join(homeless))

    for rel in SCAFFOLD:
        tree = ast.parse((PKG / rel).read_text())
        defined = [n for n in tree.body
                   if isinstance(n, (ast.FunctionDef, ast.ClassDef, ast.Assign))]
        check(f"the shared {rel} defines nothing, so four copies stay one thing",
              not defined, str([type(n).__name__ for n in defined]))
    return files


# --------------------------------------------------------------------------- #
# 2 · every cross-product import points down                                   #
# --------------------------------------------------------------------------- #

def cross_edges(files: list[Path]) -> set[tuple[str, str, str, str]]:
    """Every import that leaves its own product, as (from-product, file,
    to-product, target)."""
    out = set()
    for f in files:
        rel = str(f.relative_to(PKG))
        src = product_of(rel)
        if src is None:
            continue
        for target in imports_of(f):
            dst = product_of(target)
            if dst is not None and dst != src:
                out.add((src, rel, dst, target))
    return out


def test_every_cross_product_import_points_down(files: list[Path]) -> None:
    print("\nevery import that leaves a product points at one below it")
    edges = cross_edges(files)
    check("there are cross-product imports at all — a scan that sees none is "
          "broken, not clean", len(edges) > 50, str(len(edges)))

    illegal = sorted((s, f, d, t) for s, f, d, t in edges if d not in MAY_IMPORT[s])
    check("no product imports a sibling or something above it", not illegal,
          "; ".join(f"{s}({f}) -> {d}({t})" for s, f, d, t in illegal[:4]))

    # The measurement that makes this check worth running. `dev_server` uses
    # absolute imports exclusively, and a relative-only walk reports it as a
    # package that imports nothing at all.
    absolute_only = {f for s, f, d, t in edges if f.startswith("dev_server/")}
    check("the scan reads absolute imports — dev_server is written with nothing "
          "else", len(absolute_only) >= 3, str(sorted(absolute_only)))


# --------------------------------------------------------------------------- #
# 3 · no adapter outside the IDE's product imports the IDE                     #
# --------------------------------------------------------------------------- #

def test_no_adapter_outside_c_imports_the_ide(files: list[Path]) -> None:
    print("\nprism does not reach the IDE, and vanilla reaches only the one form")
    # Truncated to the module, because `imports_of` also records the names
    # pulled out of it and this check is about which *module* is reached.
    reaching = {(str(f.relative_to(PKG)), "/".join(t.split("/")[:2]))
                for f in files if str(f.relative_to(PKG)).startswith("hacks/")
                for t in imports_of(f) if t.split("/")[0] == "studio"}

    prism = sorted(f for f, _ in reaching if f.startswith("hacks/prism/"))
    check("no prism module imports the IDE", not prism, ", ".join(prism))

    check("what is left is exactly the C->C new-map edges, named above",
          reaching == WITHIN_C, str(sorted(reaching ^ WITHIN_C)))
    check("and every one of them is vanilla, not polished — polished mounts "
          "vanilla's writer rather than the form",
          all(f.startswith("hacks/vanilla/") for f, _ in reaching),
          str(sorted(f for f, _ in reaching)))


# --------------------------------------------------------------------------- #
# 4 · runtime: what importing a product actually drags in                      #
# --------------------------------------------------------------------------- #

_PROBE = (
    "import sys; sys.path.insert(0, {src!r});"
    "import pokeprism_devtools.{mod};"
    "print(','.join(sorted(m for m in sys.modules"
    " if m.split('.')[0] == 'textual'"
    " or m.startswith('pokeprism_devtools.'))))"
)


def loaded_by(mod: str) -> set[str]:
    """What a bare `import pokeprism_devtools.<mod>` leaves in `sys.modules`.

    A subprocess, because this file's own imports have already loaded half the
    repo — asking in *this* interpreter would answer about the test.
    """
    out = subprocess.run([sys.executable, "-c",
                          _PROBE.format(src=str(SRC), mod=mod)],
                         capture_output=True, text=True, check=True)
    return {m for m in out.stdout.strip().split(",") if m}


def products_loaded(mods: set[str]) -> set[str]:
    got = set()
    for m in mods:
        if m.startswith("pokeprism_devtools."):
            rel = "/".join(m.split(".")[1:])
            p = product_of(rel)
            if p:
                got.add(p)
    return got


def test_importing_a_product_loads_nothing_above_it() -> None:
    print("\nimporting a product loads nothing above it, in a real interpreter")

    b = loaded_by("contract")
    check("importing B loads B and A, and neither C nor D",
          products_loaded(b) == {"A", "B"}, str(sorted(products_loaded(b))))

    c = loaded_by("studio")
    check("importing the IDE loads no D", "D" not in products_loaded(c),
          str(sorted(products_loaded(c))))

    d = loaded_by("hacks.prism")
    check("importing prism loads no C", "C" not in products_loaded(d),
          str(sorted(products_loaded(d))))
    check("and no widget library comes with it",
          not any(m.split(".")[0] == "textual" for m in d))


# --------------------------------------------------------------------------- #
# 5 · falsified: each check against the mistake it exists to catch             #
# --------------------------------------------------------------------------- #

def test_falsified(files: list[Path]) -> None:
    print("\nfalsified: each check, against the mistake it is here to catch")

    # 1 · a module in no product. Simulated by asking the classifier, which is
    # the whole of what check 1 runs on.
    check("an unclaimed module is rejected", product_of("brand_new/thing.py") is None)
    check("...and a claimed one is not", product_of("shared/coords.py") == "A")
    check("a nested adapter is not swallowed by its parent folder",
          product_of("hacks/prism/read.py") == "D"
          and product_of("hacks/vanilla/read.py") == "C")

    # 2 · a sibling edge, and an upward one. Both are what the carve dies on.
    fake = {("D", "hacks/prism/read.py", "C", "studio/tables"),
            ("A", "shared/coords.py", "B", "contract/blocks")}
    bad = [e for e in fake if e[2] not in MAY_IMPORT[e[0]]]
    check("a prism -> IDE edge would be rejected", len(bad) == 2, str(sorted(bad)))

    # 3 · both spellings, on disk. The absolute form is the one a relative-only
    # walk missed for a whole package.
    probe = PKG / "shared" / "_falsify_probe.py"
    try:
        probe.write_text("from pokeprism_devtools.studio import tables\n"
                         "from ..hacks.prism import read\n")
        got = imports_of(probe)
        check("the scan sees an absolute import", "studio/tables" in got, str(got))
        check("the scan sees a relative import", "hacks/prism/read" in got, str(got))
    finally:
        probe.unlink(missing_ok=True)

    # A deferred import inside a method counts — three of Phase 2's four
    # surviving edges were exactly this shape.
    try:
        probe.write_text("def f():\n    from ...studio import tables\n")
        check("the scan sees an import hidden inside a function",
              "studio/tables" in imports_of(probe), str(imports_of(probe)))
    finally:
        probe.unlink(missing_ok=True)

    # 4 · the runtime probe can tell products apart at all.
    check("the runtime classifier maps a module back to its product",
          products_loaded({"pokeprism_devtools.hacks.prism.read",
                           "pokeprism_devtools.shared.coords"}) == {"A", "D"})


def main() -> int:
    files = test_every_module_has_a_product()
    test_every_cross_product_import_points_down(files)
    test_no_adapter_outside_c_imports_the_ide(files)
    test_importing_a_product_loads_nothing_above_it()
    test_falsified(files)

    print()
    if _failures:
        print(f"{_failures} check(s) FAILED")
        return 1
    print("all ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
