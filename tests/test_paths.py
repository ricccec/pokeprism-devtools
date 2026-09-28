#!/usr/bin/env python3
"""Tests for `shared/paths.py` — locating a pret repo's build artifacts.

Written **before** the module is changed, and green against it unmodified: this
is the oracle for Phase 5's step A2, and an oracle written after the edit proves
nothing about the edit. Two things are pinned and they are not the same kind of
thing:

  * **what must survive** — how a repo root is recognised, how a `.sym` and a
    `.map` are found beside the ROM, how a cartridge's bank count is read, and
    what `fallback=` means. The last is the one with teeth: build one target
    while a stale sibling is still on disk and a falling-back caller hands back
    the sibling, so you patch a save against one game and play the other.
  * **that no hack is named** — the bug this file was written for. `rom_path`
    used to spell prism's two ROM filenames out, so a fully-built pokecrystal
    tree resolved nothing and the error named a file that tree had never heard
    of; `pret-sym`, one of product A's *own* entry points, could not read a
    `.sym` on a pokecrystal checkout. The candidates now come from the tree's
    own `Makefile`, and which one a caller wants crosses the seam as data.

The fixtures are three hermetic trees, one per `Makefile` dialect measured in
the wild (2026-08-05) — prism's one-line `roms :=`, vanilla's continued over six
lines, and polished's **absence** of the assignment entirely. The third is the
one that decides the design: a reader that trusts `roms :=` answers two trees
and goes blind on the third.

Every check is falsified: each is seeded with the mutation it exists to catch
and the run fails if any survives.

    python tests/test_paths.py
"""

from __future__ import annotations

import contextlib
import io
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pokeprism_devtools.shared import paths  # noqa: E402

_failures = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global _failures
    ok = bool(cond)
    if not ok:
        _failures += 1
    print(f"  {'ok  ' if ok else 'FAIL'} {label}"
          f"{(': ' + detail) if detail and not ok else ''}")


# --------------------------------------------------------------------------- #
# the three Makefile dialects, transcribed from the real trees                 #
# --------------------------------------------------------------------------- #

#: prism: one logical line, two ROMs — and the *plain* name is the debug build,
#: which is why no textual rule over these three lists can find "the debug ROM".
PRISM_MAKEFILE = """\
### Build tools

roms := pokeprism.gbc pokeprism_nodebug.gbc

prism: pokeprism.gbc contents/contents.link
nodebug: pokeprism_nodebug.gbc contents/contents.link
"""

#: vanilla: one logical line spread over six physical ones with backslashes, and
#: a second `:=` block directly under it that a sloppy reader would sweep in.
VANILLA_MAKEFILE = """\
roms := \\
\tpokecrystal.gbc \\
\tpokecrystal11.gbc \\
\tpokecrystal_au.gbc \\
\tpokecrystal_debug.gbc \\
\tpokecrystal11_debug.gbc
patches := pokecrystal11.patch

rom_obj := \\
\taudio.o \\
\thome.o
"""

#: polished: no `roms :=` anywhere. The name is assembled by make, so the only
#: evidence a tool has is the `.gbc` sitting in the root.
POLISHED_MAKEFILE = """\
NAME = polishedcrystal
VERSION = 3.2.3
ROM_NAME = $(NAME)$(MODIFIERS)-$(VERSION)

crystal: $$(ROM_NAME).$$(EXTENSION)

$(ROM_NAME).$(EXTENSION): $(crystal_obj) layout.link
"""

PRISM_ROMS = ("pokeprism.gbc", "pokeprism_nodebug.gbc")
VANILLA_ROMS = ("pokecrystal.gbc", "pokecrystal11.gbc", "pokecrystal_au.gbc",
                "pokecrystal_debug.gbc", "pokecrystal11_debug.gbc")
POLISHED_ROMS = ("polishedcrystal-3.2.3.gbc",)


def make_tree(parent: Path, name: str, makefile: str,
              built: tuple[str, ...] = (), *, artifacts: str = "") -> Path:
    """A pret-shaped checkout: a Makefile, a main.asm, and whatever is built.

    `artifacts` is the space-free suffix string to drop beside each built ROM —
    a real build leaves a `.sym` and a `.map` next to the `.gbc`, and half the
    functions under test exist to find them.
    """
    root = parent / name
    (root / "maps").mkdir(parents=True)
    (root / "Makefile").write_text(makefile)
    (root / "main.asm").write_text('INCLUDE "constants.asm"\n')
    for rom in built:
        (root / rom).write_bytes(rom_bytes())
        for suffix in artifacts.split():
            (root / rom).with_suffix(f".{suffix}").write_text("")
    return root


def rom_bytes(size_code: int = 0x06) -> bytes:
    """A ROM whose header declares `2 << size_code` banks — 128 by default, a
    2 MiB cartridge. The size byte lives at $0148."""
    data = bytearray(b"\x00" * 0x8000)
    data[0x0148] = size_code
    return bytes(data)


# --------------------------------------------------------------------------- #
# what must survive                                                            #
# --------------------------------------------------------------------------- #

def test_repo_root(tmp: Path) -> None:
    """Both halves of the pret signature are load-bearing, and this says so.

    A `Makefile` is in half the directories on a developer's machine; a
    `main.asm` alone is an extracted source dump that cannot build. Only the
    pair is evidence.
    """
    print("\nfinding a repo root")
    root = make_tree(tmp, "root_prism", PRISM_MAKEFILE)

    check("the root of a pret tree is the tree",
          paths.find_repo_root(root) == root.resolve())
    check("a subdirectory walks up to it",
          paths.find_repo_root(root / "maps") == root.resolve())

    for name, files in (("half", {"Makefile": "all:\n"}),
                        ("other", {"main.asm": ""})):
        d = tmp / name
        d.mkdir()
        for fn, text in files.items():
            (d / fn).write_text(text)
        raised = False
        try:
            paths.find_repo_root(d)
        except paths.RepoNotFound:
            raised = True
        check(f"a lone {list(files)[0]} is not a pret tree", raised)


def test_sibling_artifacts(tmp: Path) -> None:
    """A `.sym` and a `.map` are found beside the ROM, and absence is loud.

    A missing `.sym` is not a missing ROM: the tree built, it just built without
    symbols, and saying "no ROM" would send the reader to the wrong fix.
    """
    print("\nartifacts beside the ROM")

    root = make_tree(tmp, "sib", PRISM_MAKEFILE, PRISM_ROMS, artifacts="sym")
    check("the .sym beside the resolved ROM",
          paths.find_built_sym(root, prefer=("pokeprism.gbc",)).name == "pokeprism.sym")

    raised = ""
    try:
        paths.find_built_map(root, prefer=("pokeprism.gbc",))
    except FileNotFoundError as e:
        raised = str(e)
    check("a missing .map names the file and says to rebuild",
          ".map" in raised and "Rebuild" in raised, raised)


def test_rom_bank_count(tmp: Path) -> None:
    """Banks from the header byte at $0148, with the file size as the backstop.

    rgbfix always pads to a whole number of banks, so the fallback is exact too
    — but it is only *reached* when the byte is unreadable or non-standard, and
    which is which is the thing worth pinning.
    """
    print("\ncounting a cartridge's banks")

    root = make_tree(tmp, "banks", PRISM_MAKEFILE)
    rom = root / "pokeprism.gbc"

    rom.write_bytes(rom_bytes(0x06))
    check("the $0148 byte decides: code 6 is 128 banks",
          paths.count_rom_banks(rom) == 128, str(paths.count_rom_banks(rom)))
    rom.write_bytes(rom_bytes(0x00))
    check("code 0 is 2 banks", paths.count_rom_banks(rom) == 2)

    data = bytearray(rom_bytes())
    data[0x0148] = 0x40                    # outside $00-$08, so not believed
    rom.write_bytes(bytes(data))
    check("a non-standard code falls back to the file size",
          paths.count_rom_banks(rom) == len(data) // 16_384,
          str(paths.count_rom_banks(rom)))

    check("an unreadable ROM is 0 banks, not an exception",
          paths.count_rom_banks(root / "nothing.gbc") == 0)


def test_fallback(tmp: Path) -> None:
    """What `fallback=` means, which is the one behaviour here with teeth.

    `fallback=True` is for a reader that wants whichever ROM is lying around.
    It is wrong for anybody who *chose* a target: build one while a stale
    sibling is still on disk and a falling-back caller hands back the sibling,
    so you patch a save against one game and play the other, with your new map
    missing from it and nothing on screen to say why.
    """
    print("\nfallback, and what it costs when it is wrong")

    # Both built, so the preference is directly observable. A fixture with only
    # one ROM on disk cannot tell "honoured the request" from "fell back to the
    # only candidate" — the two agree on every answer, and a transposed
    # preference would sail through. Phase 1b, Phase 4: the survivor is the
    # fixture's shape, never the missing assertion.
    both = make_tree(tmp, "fallback_both", PRISM_MAKEFILE, PRISM_ROMS)
    check("a preference is honoured when both are on disk",
          paths.find_built_rom(both, prefer=("pokeprism.gbc",)).name
          == "pokeprism.gbc")
    check("...and the other preference picks the other one",
          paths.find_built_rom(both, prefer=("pokeprism_nodebug.gbc",)).name
          == "pokeprism_nodebug.gbc")
    check("with no preference, the Makefile's first entry wins",
          paths.find_built_rom(both).name == "pokeprism.gbc")

    root = make_tree(tmp, "fallback", PRISM_MAKEFILE, ("pokeprism_nodebug.gbc",))

    check("the requested build, when it is on disk",
          paths.find_built_rom(root, prefer=("pokeprism_nodebug.gbc",)).name
          == "pokeprism_nodebug.gbc")
    check("falling back to the other one when it is not",
          paths.find_built_rom(root, prefer=("pokeprism.gbc",)).name
          == "pokeprism_nodebug.gbc")

    raised = ""
    try:
        paths.find_built_rom(root, prefer=("pokeprism.gbc",), fallback=False)
    except FileNotFoundError as e:
        raised = str(e)
    check("fallback=False refuses rather than handing back the stale sibling",
          "pokeprism.gbc" in raised, raised)

    unbuilt = make_tree(tmp, "fallback_unbuilt", PRISM_MAKEFILE)
    raised = ""
    try:
        paths.find_built_rom(unbuilt)
    except FileNotFoundError as e:
        raised = str(e)
    check("a tree with nothing built says so, and says to run make",
          "make" in raised, raised)
    check("...and names the targets this tree does build",
          "pokeprism.gbc" in raised, raised)


# --------------------------------------------------------------------------- #
# the candidates, and that no hack is named                                    #
# --------------------------------------------------------------------------- #

def test_built_roms(tmp: Path) -> None:
    """The candidate list, in each of the three dialects.

    Order is asserted, not just membership: the `Makefile`'s order is the tree
    author's own preference, and it is what a caller with no opinion gets.
    """
    print("\nreading the Makefile's ROM list")

    prism = make_tree(tmp, "roms_prism", PRISM_MAKEFILE)
    check("prism: both ROMs, in Makefile order",
          paths.read_built_roms(prism) == PRISM_ROMS, str(paths.read_built_roms(prism)))

    vanilla = make_tree(tmp, "roms_vanilla", VANILLA_MAKEFILE)
    check("vanilla: a continued `roms :=` reads to the end of the block",
          paths.read_built_roms(vanilla) == VANILLA_ROMS,
          str(paths.read_built_roms(vanilla)))
    check("vanilla: the `rom_obj :=` block below it is not swept in",
          all(r.endswith(".gbc") for r in paths.read_built_roms(vanilla)))

    # No list at all, and nothing built: the honest empty answer rather than a
    # guessed name. This is the tree that decides the design.
    unbuilt = make_tree(tmp, "roms_polished_unbuilt", POLISHED_MAKEFILE)
    check("polished, never built: no list and no ROMs — the empty answer",
          paths.read_built_roms(unbuilt) == ())

    built = make_tree(tmp, "roms_polished", POLISHED_MAKEFILE, POLISHED_ROMS)
    check("polished, built: the ROM on disk is the candidate",
          paths.read_built_roms(built) == POLISHED_ROMS,
          str(paths.read_built_roms(built)))

    broken = tmp / "roms_broken"
    (broken / "maps").mkdir(parents=True)
    (broken / "main.asm").write_text("")
    (broken / "Makefile").write_bytes(b"\xff\xfe not text at all")
    check("an unreadable Makefile yields no candidates rather than raising",
          paths.read_built_roms(broken) == ())


def test_no_hack_is_named(tmp: Path) -> None:
    """**The bug this file exists for, as a test.**

    `rom_path` used to spell `pokeprism.gbc` and `pokeprism_nodebug.gbc` out, so
    a fully-built pokecrystal tree resolved nothing and the error named a file
    that tree had never heard of. Every function reaching through it — the
    `.sym` and `.map` finders — inherited it, which is why `pret-sym`, an entry
    point of the library this module belongs to, was prism-only in practice.

    Now all three dialects resolve. Named in `test_products.py::KNOWN_LEAKS`
    until this landed; the rows left with it.
    """
    print("\nthe leak: a library that names no hack")

    for name, makefile, roms in (("prism", PRISM_MAKEFILE, PRISM_ROMS),
                                 ("vanilla", VANILLA_MAKEFILE, VANILLA_ROMS),
                                 ("polished", POLISHED_MAKEFILE, POLISHED_ROMS)):
        root = make_tree(tmp, f"neutral_{name}", makefile, roms,
                         artifacts="sym map")
        rom = paths.find_built_rom(root)
        check(f"{name}: a ROM resolves", rom.exists(), str(rom))
        check(f"{name}: its .sym is beside it",
              paths.find_built_sym(root).name == rom.with_suffix(".sym").name)
        check(f"{name}: its .map is beside it",
              paths.find_built_map(root).name == rom.with_suffix(".map").name)

    # And the module names no hack in anything it *executes*. Scoped to
    # non-docstring string constants for the reason `test_products.py` gives:
    # prose that names the debt honestly must not itself trip the check, and
    # `built_roms` explains the polished fallback by naming polished.
    import ast
    tree = ast.parse(Path(paths.__file__).read_text())
    docstrings = {id(ast.get_docstring(n, clean=False))
                  for n in ast.walk(tree)
                  if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef))}
    live = [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and not any(n.value == d for d in
                        (ast.get_docstring(m, clean=False)
                         for m in ast.walk(tree)
                         if isinstance(m, (ast.Module, ast.FunctionDef,
                                           ast.ClassDef))) if d)]
    named = [s for s in live
             for w in ("pokeprism", "pokecrystal", "polished") if w in s.lower()]
    check("no hack is named in anything the module executes", not named,
          str(named))


def test_prism_declares_its_own(tmp: Path) -> None:
    """Prism's preference crosses the seam as data, and is the thing the library
    could never have inferred.

    Prism inverts the family convention — the *plain* name is the debug build —
    so a name test would be right on pokecrystal, silent on polishedcrystal and
    backwards here. The declaration is the whole point, and this is what says the
    two halves still fit together.
    """
    print("\nprism's preference, declared on prism's side")

    from pokeprism_devtools.hacks.prism.save import roms

    root = make_tree(tmp, "prefer_prism", PRISM_MAKEFILE, PRISM_ROMS)
    check("debug resolves the plain name, which is prism's trap",
          paths.find_built_rom(root, prefer=roms.prefer_prism_rom(True)).name
          == "pokeprism.gbc")
    check("release resolves the suffixed one",
          paths.find_built_rom(root, prefer=roms.prefer_prism_rom(False)).name
          == "pokeprism_nodebug.gbc")
    check("both names it declares are targets prism's Makefile really lists",
          set(paths.read_built_roms(root)) == {roms.DEBUG_ROM, roms.RELEASE_ROM})


# --------------------------------------------------------------------------- #
# falsification                                                                #
# --------------------------------------------------------------------------- #

_survivors: list[str] = []


def seeded(label: str, patch: dict, run) -> None:
    """Install a mutation, run the checks it should break, restore, report.

    Phase 1b and Phase 4 both measured that a survivor is almost never a missing
    assertion — it is the fixture's *shape*. So each mutation is applied to the
    real function and run against the real fixtures.
    """
    global _failures
    saved = {name: getattr(paths, name) for name in patch}
    before = _failures
    with contextlib.redirect_stdout(io.StringIO()):
        for name, fn in patch.items():
            setattr(paths, name, fn)
        try:
            with tempfile.TemporaryDirectory() as d:
                run(Path(d))
        except Exception:
            _failures += 1                 # a mutation that raises is caught
        finally:
            for name, fn in saved.items():
                setattr(paths, name, fn)
    caught = _failures > before
    _failures = before                     # seeded failures are not real ones
    print(f"  {'ok  ' if caught else 'FAIL'} caught: {label}")
    if not caught:
        _survivors.append(label)
        _failures += 1


def test_falsified() -> None:
    print("\nfalsification — does each check catch its own mutation?")
    real_find = paths.find_built_rom
    real_built = paths.read_built_roms

    seeded("find_repo_root accepting a lone Makefile",
           {"find_repo_root": lambda start=None: (start or Path.cwd()).resolve()},
           test_repo_root)

    seeded("fallback=False honoured as True — the stale-ROM bug",
           {"find_built_rom": lambda root=None, *, prefer=(), fallback=True:
               real_find(root, prefer=prefer, fallback=True)},
           test_fallback)

    seeded("the caller's preference ignored",
           {"find_built_rom": lambda root=None, *, prefer=(), fallback=True:
               real_find(root, prefer=(), fallback=fallback)},
           test_fallback)

    seeded("the preference list consulted after the candidates, not before",
           {"find_built_rom": lambda root=None, *, prefer=(), fallback=True:
               real_find(root, prefer=tuple(reversed(prefer)) if len(prefer) > 1
                         else (), fallback=fallback)},
           test_prism_declares_its_own)

    seeded("a missing sibling artifact returned instead of refused",
           {"_find_sibling_artifact": lambda rom, suffix: rom.with_suffix(suffix)},
           test_sibling_artifacts)

    seeded("the $0148 byte ignored, size used always",
           {"count_rom_banks": lambda rom: max(1, rom.stat().st_size // 16_384)
               if rom.exists() else 0},
           test_rom_bank_count)

    # The four that aim at the leak itself. The first is the bug restored, and
    # it is the mutation this whole file was written to catch.
    seeded("the leak restored — read_built_roms answers prism's names on any tree",
           {"read_built_roms": lambda root=None: PRISM_ROMS},
           test_no_hack_is_named)

    seeded("a `roms :=` reader that stops at the first physical line",
           {"read_built_roms": lambda root=None: real_built(root)[:1]},
           test_built_roms)

    def _no_disk_fallback(root=None):
        """The polished case dropped: no `roms :=` means no answer, ever."""
        try:
            text = (root / "Makefile").read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return ()
        return real_built(root) if "roms :=" in text else ()
    seeded("the disk fallback dropped — polished goes blind",
           {"read_built_roms": _no_disk_fallback}, test_built_roms)

    seeded("read_built_roms sorted instead of read in Makefile order",
           {"read_built_roms": lambda root=None: tuple(sorted(real_built(root)))},
           test_built_roms)


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        test_repo_root(tmp)
        test_sibling_artifacts(tmp)
        test_rom_bank_count(tmp)
        test_built_roms(tmp)
        test_fallback(tmp)
        test_no_hack_is_named(tmp)
        test_prism_declares_its_own(tmp)
    test_falsified()
    if _survivors:
        print("\nsurvived, so the check above it is not doing its job:")
        for s in _survivors:
            print(f"  - {s}")
    print(f"\n{'FAILURES: ' + str(_failures) if _failures else 'all ok'}")
    sys.exit(1 if _failures else 0)
