#!/usr/bin/env python3
"""One battery, every adapter — the conformance test for `hacks/seam.py`.

Until now the seam was a docstring. Three adapters were written against it and
all three happen to agree, but nothing said so: `test_vanilla.py` and
`test_polished.py` each ask their own tree its own questions, and the overlap
between them is a coincidence that no failure would ever report. The property
this file buys is the one the prose could not: **adding a method to `Reads` or
`Writes` breaks every adapter that has not implemented it, in one file, by
name** — instead of at whichever pane asks the missing question third.

What is checked, and what deliberately is not:

  * **Names and parameters**, against the Protocol, by introspection. A method
    renamed on one side is a mount that succeeds and a pane that explodes.
  * **Record types**, by asking all three trees the nine questions for real and
    checking what comes back is the seam's records — `panels.MapTables` with
    its six lists, `panels.Link`, `panels.WildMon`. Not *values*: what Route 29
    contains is `test_vanilla.py`'s business, and duplicating it here would make
    this file fail every time a tree is updated.
  * **Return annotations are not compared.** They are strings under
    `from __future__ import annotations`, and two adapters spell the same type
    differently (`vanilla.Writer.editor` declares none at all). Comparing text
    would fail on agreement and pass on a lie. Calling the method and looking
    at what comes out is the check that means something.
  * The two optional protocols are checked **against the declared capability**,
    both ways: prism must answer `measure` because it declared `measures`, and
    the family must not be asked — that is the degrade-to-absence rule as a
    test rather than as a paragraph.

`test_falsified` comes last and matters most: it builds adapters that are wrong
in the five ways an adapter is actually wrong — a missing method, a renamed
parameter, a parameter added, a parameter that gained a default, and the one
that passes every name check while answering `None` to everything — and fails
if this file accepts any of them.

    python tests/test_seam.py
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pokeprism_devtools.hacks import mount as m  # noqa: E402
from pokeprism_devtools.hacks import seam  # noqa: E402
from pokeprism_devtools.studio import panels  # noqa: E402

TREES = {"prism": "pokeprism", "vanilla": "pokecrystal",
         "polished": "polishedcrystal"}

_failures = 0
_quiet = False          # set while running the battery *against a stub*


def say(line: str) -> None:
    """A section header — silent while the battery is running against a stub."""
    if not _quiet:
        print(line)


def check(label: str, cond: bool, detail: str = "") -> None:
    global _failures
    ok = bool(cond)
    if not ok:
        _failures += 1
    if not _quiet:
        print(f"  {'ok  ' if ok else 'FAIL'} {label}"
              f"{(': ' + detail) if detail and not ok else ''}")


def tried(fn) -> bool:
    """Run part of the battery against a stub: silence its report, and hand
    back whether it failed — the stub's failures are the caller's evidence, not
    this file's score."""
    global _failures, _quiet
    before, _quiet = _failures, True
    try:
        fn()
        return _failures > before
    finally:
        _failures, _quiet = before, False


def mounted() -> dict[str, seam.Hack]:
    """Every tree on this machine, mounted once. A tree that isn't checked out
    is skipped loudly — a battery that silently covers one adapter is worse
    than no battery, because the report still says "all ok"."""
    out = {}
    for name, folder in TREES.items():
        root = Path.home() / "code/ricccec" / folder
        if not root.exists():
            say(f"  SKIP {name}: no checkout at {root}")
            continue
        out[name] = m.mount(root)
    return out


# -- the surface ----------------------------------------------------------- #
def methods(proto: type) -> list[str]:
    return sorted(n for n, _ in inspect.getmembers(proto, inspect.isfunction)
                  if not n.startswith("_"))


def shape(fn) -> list[tuple[str, str, bool]]:
    """A signature reduced to what has to agree: each parameter's name, kind,
    and whether it has a default. `self` is dropped — the protocol declares it
    and a bound method does not."""
    params = list(inspect.signature(fn).parameters.values())
    return [(p.name, str(p.kind), p.default is not inspect.Parameter.empty)
            for p in params if p.name != "self"]


def conforms(obj, proto: type, who: str) -> None:
    """`obj` answers everything `proto` declares, with the same parameters."""
    for name in methods(proto):
        have = getattr(type(obj), name, None)
        if have is None:
            check(f"{who} answers {proto.__name__}.{name}", False,
                  "the method is missing entirely")
            continue
        want, got = shape(getattr(proto, name)), shape(have)
        check(f"{who}.{name}{inspect.signature(getattr(proto, name))}",
              want == got, f"declared {want}, found {got}")


def test_surface(hacks: dict[str, seam.Hack]) -> None:
    say("surface — what every adapter owes")

    for name, hack in hacks.items():
        check(f"{name} is a Reads", isinstance(hack.reads, seam.Reads))
        conforms(hack.reads, seam.Reads, f"{name}.reads")

        if hack.writes is None:
            check(f"{name} mounts read-only, so nothing is owed", True)
        else:
            check(f"{name} is a Writes", isinstance(hack.writes, seam.Writes))
            conforms(hack.writes, seam.Writes, f"{name}.writes")

    say("surface — the optional two, against the declared capability")
    for name, hack in hacks.items():
        # Both directions. A tree that answers `measure` without declaring
        # `measures` is as wrong as one that declares it and can't: the session
        # gates on the flag, so the method would never be reached and the
        # capability would be a lie in the other direction.
        check(f"{name} measures={hack.measures} matches its adapter",
              isinstance(hack.reads, seam.Measures) == hack.measures)
        if hack.measures:
            conforms(hack.reads, seam.Measures, f"{name}.reads")

        draws = any(cls.sketches
                    for kind in ("NPC", "warp", "signpost", "object",
                                 "trainer", "trigger")
                    for cls in (hack.writes.adders(kind) if hack.writes else ()))
        draws = draws or any(
            getattr(hack.writes.form(n), "sketches", False)
            for n in ("newmap", "resize", "reword") if hack.writes
            and hack.writes.form(n) is not None)
        check(f"{name} sketches exactly when one of its forms draws",
              isinstance(hack.reads, seam.Sketches) == draws,
              f"forms draw={draws}, adapter has sketch="
              f"{isinstance(hack.reads, seam.Sketches)}")
        if draws:
            conforms(hack.reads, seam.Sketches, f"{name}.reads")


# -- the records ----------------------------------------------------------- #
def readable(reads) -> tuple[str, str]:
    """A map of this tree that parses, so the record checks are asking about
    something real. The first one is not guaranteed to parse in any tree."""
    for label, const in reads.maps().items():
        if reads.parses(const):
            return label, const
    raise AssertionError("no map in this tree parses at all")


def test_records(hacks: dict[str, seam.Hack]) -> None:
    say("records — the nine answers, in the seam's types")

    for name, hack in hacks.items():
        r = hack.reads
        label, const = readable(r)
        who = f"{name} ({label})"

        cat = r.maps()
        check(f"{who} maps() is label -> const",
              isinstance(cat, dict) and cat
              and all(isinstance(k, str) and isinstance(v, str)
                      for k, v in cat.items()))

        check(f"{who} parses() is a bool", isinstance(r.parses(const), bool),
              f"got {type(r.parses(const)).__name__}")

        links = r.connections(const)
        check(f"{who} connections() is [Link]",
              isinstance(links, list)
              and all(isinstance(x, panels.Link) for x in links))

        t = r.tables(label)
        check(f"{who} tables() is MapTables", isinstance(t, panels.MapTables))
        check(f"{who} tables() carries all six lists, each a list",
              all(isinstance(getattr(t, f, None), list)
                  for f in ("npcs", "trainers", "props", "warps",
                            "signposts", "triggers")),
              str([f for f in ("npcs", "trainers", "props", "warps",
                               "signposts", "triggers")
                   if not isinstance(getattr(t, f, None), list)]))

        check(f"{who} attributes() is Attributes",
              isinstance(r.attributes(label, const), panels.Attributes))

        g = r.geometry(label)
        check(f"{who} geometry() is Blocks", isinstance(g, panels.Blocks))
        # Guarded on the type check above, not chained to it: a wrong record
        # should be one FAIL and a battery that keeps going, not a traceback
        # that takes the remaining checks down with it.
        check(f"{who} geometry() has a shape its blocks fit",
              isinstance(g, panels.Blocks) and g.height > 0 and g.width > 0
              and len(g.blocks) >= g.height * g.width,
              f"{g.height}x{g.width} but {len(g.blocks)} blocks"
              if isinstance(g, panels.Blocks) else "not Blocks at all")

        w = r.wild(const)
        check(f"{who} wild() is table -> time -> [WildMon]",
              isinstance(w, dict)
              and all(isinstance(times, dict) for times in w.values())
              and all(isinstance(mon, panels.WildMon)
                      for times in w.values()
                      for mons in times.values() for mon in mons))

        roof = r.roof(const)
        check(f"{who} roof() is Roof or None",
              roof is None or isinstance(roof, panels.Roof))

        tx = r.texts(label)
        check(f"{who} texts() is [TextRef]",
              isinstance(tx, list)
              and all(isinstance(x, panels.TextRef) for x in tx))


def test_unreadable(hacks: dict[str, seam.Hack]) -> None:
    say("records — the refusal is part of the protocol")

    # `tables` and `geometry` are the two that may fail, and the protocol says
    # they fail *loudly*. An adapter returning empty tables instead would pass
    # every type check above and tell the user the map is empty.
    for name, hack in hacks.items():
        r = hack.reads
        broken = [(lab, c) for lab, c in r.maps().items() if not r.parses(c)]
        if not broken:
            say(f"  --   {name}: every map parses, nothing to refuse with")
            continue
        label, _ = broken[0]
        try:
            r.tables(label)
        except panels.Unreadable as exc:
            check(f"{name} tables() on {label} raises Unreadable with a reason",
                  bool(str(exc).strip()), "the exception says nothing")
        except Exception as exc:  # noqa: BLE001 — the point is the type
            check(f"{name} tables() on {label} raises Unreadable", False,
                  f"raised {type(exc).__name__} instead")
        else:
            check(f"{name} tables() on {label} raises Unreadable", False,
                  "it returned tables for a map it said does not parse")


# -- falsification --------------------------------------------------------- #
class _Fine:
    """A reader that conforms — the control. Every stub below is this with one
    thing broken, so a stub that passes proves the break was not what failed."""

    def maps(self) -> dict[str, str]: return {"TownA": "TOWN_A"}
    def parses(self, const: str) -> bool: return True
    def connections(self, const: str): return []
    def tables(self, label: str): return None
    def attributes(self, label: str, const: str): return None
    def geometry(self, label: str): return None
    def wild(self, const: str): return {}
    def roof(self, const: str): return None
    def texts(self, label: str): return []


def test_falsified() -> None:
    say("falsified — the battery must reject these five")

    def rejects(what: str, obj) -> None:
        check(f"{what} is caught",
              tried(lambda: conforms(obj, seam.Reads, "stub")),
              "the battery accepted an adapter it should have refused")

    check("the control conforms",
          not tried(lambda: conforms(_Fine(), seam.Reads, "control")),
          "the control is broken, so nothing below proves anything")

    class Missing(_Fine):
        maps = None                 # the method a fourth adapter forgets

    class Renamed(_Fine):
        def texts(self, name: str): return []      # `label` in the protocol

    class Extra(_Fine):
        def roof(self, const: str, fallback: str): return None

    class Defaulted(_Fine):
        def parses(self, const: str = "") -> bool: return True

    rejects("a missing method", Missing())
    rejects("a renamed parameter", Renamed())
    rejects("an extra required parameter", Extra())
    rejects("a parameter that gained a default", Defaulted())

    # And the other half. `_Fine` passes `conforms` completely while answering
    # every question with `None` — which is exactly the adapter that mounts,
    # draws an empty studio, and blames the repo.
    check("an adapter with the right names and the wrong records is caught",
          tried(lambda: test_records({"stub": seam.Hack("stub", _Fine())})),
          "test_records accepted a reader that answers None to everything")

    # And the presence check on its own is not enough — this is why `conforms`
    # exists alongside `isinstance`.
    check("isinstance alone would have accepted the renamed parameter",
          isinstance(Renamed(), seam.Reads),
          "runtime_checkable got stricter; the comment above is now wrong")


if __name__ == "__main__":
    hacks = mounted()
    test_surface(hacks)
    test_records(hacks)
    test_unreadable(hacks)
    test_falsified()
    print(f"\n{'FAILURES: ' + str(_failures) if _failures else 'all ok'}")
    sys.exit(1 if _failures else 0)
