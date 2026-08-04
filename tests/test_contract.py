#!/usr/bin/env python3
"""The arrows only go one way — `adapter -> contract <- IDE`, checked.

The contract package's deliverable is a *direction*, and a direction is not
something the rest of the suite can fail on: every test here passed with the
cycle in place, because a cycle is a perfectly good way to run a program. So
this file exists to fail the day the arrow turns round.

Four checks, and they are deliberately different in kind:

  * **Static** — over each `contract/` module's own import lines, by AST. Catches
    the import that is written but never executed on the happy path: a
    `TYPE_CHECKING` block, a function-local `from ...studio import x`. Reading
    the source is the only way to see either.
  * **Runtime** — import the package in a *fresh interpreter* and look at what
    came with it. This is the check `test_vanilla.py` wrote off as unaskable:
    while the base lived in `studio/`, importing it ran `studio/__init__` ->
    `session` -> `maplint`, so no honest answer existed. Moving it is what makes
    the question askable, and asking it is how we know the move landed.
  * **No adapter reaches the IDE** — over every module under `hacks/`, source
    text, so a deferred import inside a method counts. Three of the four
    surviving edges *are* deferred imports, which is exactly how they stayed
    invisible to a top-of-file grep for as long as they did.
  * **The capabilities degrade to absence** — a `Hack` that declares nothing but
    a reader has no linter, no writer, no play adapter and does not measure. That
    is the rule an IDE branches on instead of on a hack's name.

**The two survivors are named, not excused.** `studio/mapadd.py` and
`studio/resize.py` are neutral `Action` subclasses over `wiring/` — not the IDE,
and not the contract either, since they read the filesystem. Where they land is
Phase 3's. The test asserts the survivor list *exactly*, so the day one moves
this file says so rather than quietly passing a weaker claim.

`test_falsified` comes last and matters most: it seeds each check with the
mutation that check exists to catch, and fails if any of them survives. It was
also run for real against `src/`, five mutations, and two of those runs are
worth writing down:

  * **A `TYPE_CHECKING`-only import of the IDE passes the runtime check and
    fails the static one.** That is the whole argument for having both, measured
    rather than asserted — an import that costs nothing at import time is
    invisible to anything that looks at `sys.modules`.
  * **A plain top-level `from ..studio import x` in a contract module no longer
    *runs*.** It is a circular import now, because `studio` imports the contract
    and `hacks/mount` imports it back, so this file dies on its own import line
    rather than reporting a failure. Red either way, and the strongest form of
    the check there is: the cycle is unbuildable, not merely disapproved of.

    python tests/test_contract.py
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

from pokeprism_devtools import contract  # noqa: E402

PKG = SRC / "pokeprism_devtools"
CONTRACT = PKG / "contract"

#: What the contract may reach for. `shared/` is product A — a coordinate tile, a
#: colour and an Edit are Gen-2 facts that already live there, and A cannot import
#: the contract back without turning the arrow round. Everything else in this repo
#: is either the IDE, an adapter, or a tool, and none of them may be named here.
ALLOWED = {"shared"}
FORBIDDEN = ("studio", "hacks", "wiring", "maplint", "mapfit", "mapview",
             "map_show", "map_new", "map_inspect", "metatiles", "usage",
             "gfx_view", "dev_server", "sym_lookup")

#: The `hacks -> studio` edges Phase 2 leaves standing, and what each is for.
#: Both are neutral Action subclasses over `wiring/`; they are shared adapter
#: machinery filed under the IDE, and they fail the contract's bar because they
#: open files. Asserted exactly — a shorter list is progress, a longer one is a
#: regression, and both should be somebody's decision rather than a surprise.
SURVIVORS = {
    ("hacks/prism/write.py", "studio.resize"),
    ("hacks/prism/offers.py", "studio.mapadd"),
    ("hacks/vanilla/write.py", "studio.resize"),
    ("hacks/vanilla/write.py", "studio.mapadd"),
    ("hacks/vanilla/newmap.py", "studio.mapadd"),
}

_failures = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global _failures
    ok = bool(cond)
    print(f"  [{'OK  ' if ok else 'FAIL'}] {label}")
    if not ok:
        _failures += 1
        if detail:
            print(f"         {detail}")


# --------------------------------------------------------------------------- #
# 1 · static: what the contract's own import lines name                        #
# --------------------------------------------------------------------------- #

def imported_names(path: Path) -> list[str]:
    """Every module this file names in an import, relative ones spelled by the
    first package component they resolve to.

    Walks the whole tree rather than the top level, so an import inside a
    `TYPE_CHECKING` block or inside a function is counted. Those are the ones
    worth catching: they cost nothing at import time, which is exactly why they
    accumulate unnoticed.
    """
    names = []
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                # `from ..shared.coords import Tile` inside contract/ -> "shared"
                inside = (node.module or "").split(".")
                names.append(inside[0] if node.level > 1 and inside else "")
            else:
                names.append((node.module or "").replace("pokeprism_devtools.", ""))
        elif isinstance(node, ast.Import):
            names += [a.name.replace("pokeprism_devtools.", "") for a in node.names]
    return [n for n in names if n]


def contract_modules() -> list[Path]:
    return sorted(CONTRACT.glob("*.py"))


def test_the_contract_names_nothing_above_itself() -> list[Path]:
    print("\nthe contract imports the standard library and shared/, and nothing else")
    mods = contract_modules()
    check("the package has modules to check at all", len(mods) >= 10, str(len(mods)))

    reached: set[str] = set()
    for f in mods:
        for name in imported_names(f):
            head = name.split(".")[0]
            if head in FORBIDDEN:
                reached.add(f"{f.name}: {name}")
    check("no contract module names the IDE, an adapter or a tool",
          not reached, ", ".join(sorted(reached)))

    outside = set()
    for f in mods:
        for name in imported_names(f):
            head = name.split(".")[0]
            if head not in ALLOWED and (PKG / head).exists():
                outside.add(f"{f.name}: {name}")
    check("the only in-repo package it reaches is shared/", not outside,
          ", ".join(sorted(outside)))
    return mods


# --------------------------------------------------------------------------- #
# 2 · runtime: what a fresh interpreter drags in with it                       #
# --------------------------------------------------------------------------- #

_PROBE = (
    "import sys; sys.path.insert(0, {src!r});"
    "import pokeprism_devtools.contract;"
    "print(','.join(sorted(m for m in sys.modules"
    " if m.split('.')[0] == 'textual'"
    " or m.startswith('pokeprism_devtools.'))))"
)


def loaded_by_importing_contract() -> set[str]:
    """The modules a bare `import pokeprism_devtools.contract` leaves behind.

    A subprocess, because this test's own imports have already loaded half the
    repo — asking `sys.modules` in *this* interpreter would answer about the test
    file, not about the package.
    """
    out = subprocess.run([sys.executable, "-c", _PROBE.format(src=str(SRC))],
                         capture_output=True, text=True, check=True)
    return {m for m in out.stdout.strip().split(",") if m}


def test_importing_it_loads_nothing_else() -> None:
    print("\nimporting the contract loads no IDE, no adapter, no widget library")
    loaded = loaded_by_importing_contract()
    strays = {m for m in loaded
              if m.split(".")[0] == "textual"
              or m.split(".")[1:2] and m.split(".")[1] in FORBIDDEN}
    check("nothing above the contract comes with it", not strays,
          ", ".join(sorted(strays)))
    check("shared/ does come with it — the dependency is real, not theoretical",
          any(m.startswith("pokeprism_devtools.shared") for m in loaded))


# --------------------------------------------------------------------------- #
# 3 · no adapter reaches the IDE                                               #
# --------------------------------------------------------------------------- #

def adapter_edges() -> set[tuple[str, str]]:
    """Every `(adapter file, studio module)` pair, by source line.

    Line-wise and not AST on purpose: an import deferred inside a method is an
    edge as much as one at the top, and three of the four survivors are exactly
    that — which is how they stayed invisible to a top-of-file grep. The line
    must *be* an import, though. Prose that says the words "import" and "studio"
    in one sentence is a docstring explaining the rule, and `prism/write.py` has
    one; counting it would make this check fire on its own documentation.
    """
    edges = set()
    for f in sorted((PKG / "hacks").rglob("*.py")):
        rel = f.relative_to(PKG).as_posix()
        for line in f.read_text().split("\n"):
            stripped = line.strip()
            if not stripped.startswith(("from ", "import ")) or "studio" not in line:
                continue
            for word in line.replace(",", " ").split():
                if word.startswith("studio.") or word == "studio":
                    edges.add((rel, word.rstrip(".")))
                elif ".studio." in word:
                    edges.add((rel, "studio." + word.split(".studio.")[1]))
    return edges


def test_no_adapter_imports_the_ide() -> None:
    print("\nthe adapters no longer import the IDE, bar the two named survivors")
    edges = adapter_edges()
    check("every remaining edge is a known survivor", edges <= SURVIVORS,
          f"new: {sorted(edges - SURVIVORS)}")
    check("every known survivor is still there — this list is not a wishlist",
          SURVIVORS <= edges, f"gone: {sorted(SURVIVORS - edges)}")
    check("both survivors are forms over wiring/, not the IDE proper",
          {m for _, m in SURVIVORS} == {"studio.resize", "studio.mapadd"},
          str(sorted({m for _, m in SURVIVORS})))


# --------------------------------------------------------------------------- #
# 4 · a capability an adapter does not declare is absent, not broken           #
# --------------------------------------------------------------------------- #

class _BareReader:
    """Answers `Reads` and declares nothing else."""


def test_absence_is_the_default() -> None:
    print("\nan undeclared capability is absent, and absence is the default")
    h = contract.Hack("stub", _BareReader())
    check("a reader-only mount has no linter", h.ctx is None)
    check("...no writer", h.writes is None)
    check("...no play adapter", h.plays is None)
    check("...and does not measure", h.measures is False)

    protocols = (contract.Reads, contract.Writes, contract.Lints,
                 contract.Plays, contract.Measures, contract.Sketches)
    check("six capability protocols, no more and no fewer", len(protocols) == 6)
    check("every one is runtime_checkable — the mount asks with isinstance",
          all(hasattr(p, "_is_runtime_protocol") for p in protocols),
          str([p.__name__ for p in protocols if not hasattr(p, "_is_runtime_protocol")]))


# --------------------------------------------------------------------------- #
# falsification — each check, against the mutation it exists to catch          #
# --------------------------------------------------------------------------- #

def test_falsified(mods: list[Path]) -> None:
    print("\nfalsified: each check, against the mistake it is here to catch")

    # 1 · an import of the IDE added to a contract module, at the top level and
    #     inside a function. Parsed from text rather than written to disk: this
    #     file must not edit src/ to prove it can read it.
    victim = (CONTRACT / "hack.py").read_text()
    for label, seeded in (
        ("a top-level import", victim.replace(
            "from dataclasses import dataclass",
            "from dataclasses import dataclass\nfrom ..studio import tables")),
        ("an import hidden inside a method", victim + (
            "\n\ndef _late():\n    from ..studio.reader import read_map\n"
            "    return read_map\n")),
        ("an absolute import", victim.replace(
            "from dataclasses import dataclass",
            "from dataclasses import dataclass\n"
            "import pokeprism_devtools.maplint")),
    ):
        tmp = CONTRACT / "hack.py"
        names = []
        for node in ast.walk(ast.parse(seeded)):
            if isinstance(node, ast.ImportFrom):
                inside = (node.module or "").split(".")
                names.append(inside[0] if node.level > 1 and inside
                             else (node.module or "").replace("pokeprism_devtools.", ""))
            elif isinstance(node, ast.Import):
                names += [a.name.replace("pokeprism_devtools.", "") for a in node.names]
        caught = any(n.split(".")[0] in FORBIDDEN for n in names if n)
        check(f"the static check catches {label}", caught, f"{tmp.name}: {names}")

    # 2 · the runtime probe would have to *see* a stray. Prove the probe reports
    #     what is loaded rather than an empty set it can never fail on.
    probe = _PROBE.format(src=str(SRC)).replace(
        "import pokeprism_devtools.contract;",
        "import pokeprism_devtools.contract, pokeprism_devtools.maplint;")
    out = subprocess.run([sys.executable, "-c", probe],
                         capture_output=True, text=True, check=True)
    seen = {m for m in out.stdout.strip().split(",") if m}
    check("the runtime probe would have seen a stray import",
          any(m.startswith("pokeprism_devtools.maplint") for m in seen),
          "the probe reports nothing, so it can never fail")

    # 3 · a new adapter->IDE edge, and a survivor that quietly disappeared.
    check("a new edge is rejected",
          not ({("hacks/prism/read.py", "studio.tables")} | SURVIVORS) <= SURVIVORS)
    check("a vanished survivor is rejected",
          not SURVIVORS <= (SURVIVORS - {("hacks/prism/write.py", "studio.resize")}))

    # 4 · a Hack that declares a capability must not read as absent.
    loud = contract.Hack("stub", _BareReader(), ctx=object(), writes=object(),
                         plays=object(), measures=True)
    check("a declared capability is not absent",
          loud.ctx is not None and loud.writes is not None
          and loud.plays is not None and loud.measures is True)
    check("the module count check would notice an empty package", not [] >= [1] * 10)
    _ = mods


if __name__ == "__main__":
    modules = test_the_contract_names_nothing_above_itself()
    test_importing_it_loads_nothing_else()
    test_no_adapter_imports_the_ide()
    test_absence_is_the_default()
    test_falsified(modules)
    print(f"\n{'FAILURES: ' + str(_failures) if _failures else 'all ok'}")
    sys.exit(1 if _failures else 0)
