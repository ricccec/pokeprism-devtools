#!/usr/bin/env python3
"""Tests for `wiring/regions.py` — the three regions of a family map file.

The hermetic half tries to break the boundary probe in the three ways the
survey actually got it wrong before the module existed:

  * matching the *first* `def_*` macro, which in vanilla is `def_scene_scripts`
    at the top of the file and not the event header at all — the mistake that
    mislocated 792 of 995 real files;
  * treating "no text block" as "no text region", which sends the first text
    ever written to a map to the end of the file;
  * assuming the label naming convention (`FooText`) marks a text block, when
    what actually marks it is the `text` macro on the following line.

The real half runs the probe over every map in both trees — 995 files — and
asserts the *invariant* rather than the day's line numbers: the three regions
tile the file in the layout's order, none overlaps its neighbour, and the event
header always lands inside the EVENTS span. Then it falsifies itself by
probing each tree with the other tree's layout, which must fail loudly; if
swapping the layouts changes nothing, the layout is not doing any work and
every measurement made with it is worthless.

    python tests/test_regions.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pokeprism_devtools.wiring import regions as R  # noqa: E402

VANILLA = Path.home() / "code/ricccec/pokecrystal"
POLISHED = Path.home() / "code/ricccec/polishedcrystal"

_failures = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global _failures
    ok = bool(cond)
    if not ok:
        _failures += 1
    print(f"  {'ok  ' if ok else 'FAIL'} {label}"
          f"{(': ' + detail) if detail and not ok else ''}")


# A vanilla-shaped file: the header's opening half at the top, scripts, texts,
# then the closing half. The `def_scene_scripts` at line 1 is the trap.
_VANILLA_MAP = """\
AzaleaGym_MapScripts:
\tdef_scene_scripts

\tdef_callbacks
\tcallback MAPCALLBACK_TILES, .Callback

TrainerTwins:
\ttrainer TWINS, AMY, EVENT_BEAT_TWINS, TwinsSeenText, TwinsBeatenText, 0, .After

.After:
\tend

TwinsSeenText:
\ttext "Hi!"
\tdone

AzaleaGym_MapEvents:
\tdb 0, 0 ; filler

\tdef_warp_events
\twarp_event  4, 17, AZALEA_TOWN, 5

\tdef_coord_events

\tdef_bg_events

\tdef_object_events
\tobject_event  4,  3, SPRITE_TWIN, 0, 0, -1, -1, 0, 0, TrainerTwins, -1
"""

# A polished-shaped file: the whole header first, then scripts, then texts.
_POLISHED_MAP = """\
Route32_MapScriptHeader:
\tdef_scene_scripts

\tdef_callbacks

\tdef_warp_events
\twarp_event  6, 53, ROUTE_32, 1

\tdef_coord_events

\tdef_bg_events

\tdef_object_events
\titemball_event  6, 53, GREAT_BALL, 1, EVENT_ROUTE_32_GREAT_BALL

GenericTrainerCamper:
\tgenerictrainer CAMPER, ROLAND, EVENT_BEAT_CAMPER, CamperSeenText, CamperBeatenText

CamperSeenText:
\ttext "Hello."
\tdone
"""

# No text block anywhere. The TEXTS region still exists — with zero lines, at
# the edge the layout names.
_NO_TEXTS = """\
Empty_MapScripts:
\tdef_scene_scripts

\tdef_callbacks

Empty_MapEvents:
\tdef_warp_events

\tdef_coord_events

\tdef_bg_events

\tdef_object_events
"""

# A text block whose label breaks the `*Text` convention. Only the `text` macro
# on the next line reveals it.
_ODD_LABEL = """\
Odd_MapScripts:
\tdef_scene_scripts

\tdef_callbacks

UnnamedGreeting:
\ttext "I do not end in Text."
\tdone

Odd_MapEvents:
\tdef_warp_events

\tdef_coord_events

\tdef_bg_events

\tdef_object_events
"""


def test_hermetic() -> None:
    print("hermetic — the probe, broken on purpose")

    v = R.spans(_VANILLA_MAP, R.VANILLA)
    lines = _VANILLA_MAP.splitlines()
    check("vanilla: EVENTS is the closing header, not the def_scene_scripts "
          "block at the top of the file",
          v[R.EVENTS].start > lines.index("\tdef_scene_scripts"),
          f"EVENTS starts at line {v[R.EVENTS].start}")
    check("vanilla: the trainer script is inside SCRIPTS",
          v[R.SCRIPTS].start <= lines.index("TrainerTwins:") < v[R.SCRIPTS].end)
    check("vanilla: the text label is inside TEXTS",
          v[R.TEXTS].start <= lines.index("TwinsSeenText:") < v[R.TEXTS].end)
    check("vanilla: TEXTS ends where EVENTS begins",
          v[R.TEXTS].end == v[R.EVENTS].start,
          f"{v[R.TEXTS].end} vs {v[R.EVENTS].start}")
    # The check above passes for the right answer AND for the wrong one, which
    # is how the first version of this module shipped a splice that cut the
    # event header's label off from its warp list. These two cannot.
    check("vanilla: the _MapEvents label is INSIDE the EVENTS region",
          lines[v[R.EVENTS].start] == "AzaleaGym_MapEvents:",
          f"EVENTS starts at {lines[v[R.EVENTS].start]!r}")
    check("vanilla: the header's filler bytes are inside EVENTS too",
          "db 0, 0 ; filler" in "\n".join(
              lines[v[R.EVENTS].start:v[R.EVENTS].end]))

    p = R.spans(_POLISHED_MAP, R.POLISHED)
    plines = _POLISHED_MAP.splitlines()
    check("polished: EVENTS comes first",
          p[R.EVENTS].start < p[R.SCRIPTS].start < p[R.TEXTS].start)
    check("polished: the generictrainer is inside SCRIPTS",
          p[R.SCRIPTS].start <= plines.index("GenericTrainerCamper:")
          < p[R.SCRIPTS].end)
    check("polished: TEXTS runs to end of file",
          p[R.TEXTS].end == len(plines), str(p[R.TEXTS].end))

    e = R.spans(_NO_TEXTS, R.VANILLA)
    check("no texts: TEXTS exists and is empty, not absent",
          R.TEXTS in e and e[R.TEXTS].empty and e[R.TEXTS].lines == 0)
    check("no texts: the empty TEXTS sits at the event header, not at EOF",
          e[R.TEXTS].start == e[R.EVENTS].start,
          f"{e[R.TEXTS].start} vs {e[R.EVENTS].start}")

    o = R.spans(_ODD_LABEL, R.VANILLA)
    olines = _ODD_LABEL.splitlines()
    check("a text block is found by its `text` macro, not its label's name",
          o[R.TEXTS].start == olines.index("UnnamedGreeting:"),
          f"TEXTS starts at {o[R.TEXTS].start}")

    try:
        R.spans("SomeFile:\n\tdb 0\n", R.VANILLA)
        check("a file with no event header is refused", False, "no refusal")
    except R.RegionError as exc:
        check("a file with no event header is refused", "map file" in str(exc))

    try:
        R.Layout((R.SCRIPTS, R.SCRIPTS, R.EVENTS))
        check("a layout naming a region twice is refused", False)
    except R.RegionError:
        check("a layout naming a region twice is refused", True)


def test_real(root: Path, layout: R.Layout, name: str) -> None:
    maps = sorted((root / "maps").glob("*.asm"))
    print(f"{name} — {len(maps)} real map files")
    if not maps:
        check(f"{name} tree is present", False, str(root))
        return

    bad_order, overlap, header_out, failed = [], [], [], []
    empty_texts = 0
    for p in maps:
        text = p.read_text(errors="replace")
        try:
            s = R.spans(text, layout)
        except R.RegionError as exc:
            failed.append(f"{p.name}: {exc}")
            continue
        got = [s[r].start for r in layout.order]
        if got != sorted(got):
            bad_order.append(p.name)
        for a, b in zip(layout.order, layout.order[1:]):
            if s[a].end > s[b].start:
                overlap.append(f"{p.name}: {a} ends {s[a].end} > {b} starts {s[b].start}")
        if "def_object_events" not in "\n".join(
                text.splitlines()[s[R.EVENTS].start:s[R.EVENTS].end]):
            header_out.append(p.name)
        if s[R.TEXTS].empty:
            empty_texts += 1

    check(f"{name}: every file probes without error", not failed,
          "; ".join(failed[:3]))
    check(f"{name}: regions appear in the declared order everywhere",
          not bad_order, ", ".join(bad_order[:5]))
    check(f"{name}: no region overlaps its neighbour", not overlap,
          "; ".join(overlap[:3]))
    check(f"{name}: def_object_events is inside EVENTS in every file",
          not header_out, ", ".join(header_out[:5]))
    print(f"       ({empty_texts} of {len(maps)} have an empty TEXTS region)")


def test_falsify(root: Path, right: R.Layout, wrong: R.Layout,
                 name: str) -> None:
    """The layout must be load-bearing. Probing a tree with the other tree's
    layout has to go visibly wrong — if it does not, the fork is decorative and
    every region this module reports is luck."""
    maps = sorted((root / "maps").glob("*.asm"))[:120]
    disagree = 0
    for p in maps:
        text = p.read_text(errors="replace")
        try:
            a = R.spans(text, right)
            b = R.spans(text, wrong)
        except R.RegionError:
            disagree += 1
            continue
        if a[R.SCRIPTS] != b[R.SCRIPTS] or a[R.TEXTS] != b[R.TEXTS]:
            disagree += 1
    check(f"{name}: the other tree's layout gives different answers",
          disagree > len(maps) // 2, f"only {disagree}/{len(maps)} differ")


if __name__ == "__main__":
    test_hermetic()
    test_real(VANILLA, R.VANILLA, "vanilla")
    test_real(POLISHED, R.POLISHED, "polished")
    print("falsification — is the layout doing any work?")
    test_falsify(VANILLA, R.VANILLA, R.POLISHED, "vanilla")
    test_falsify(POLISHED, R.POLISHED, R.VANILLA, "polished")
    print(f"\n{'FAILURES: ' + str(_failures) if _failures else 'all ok'}")
    sys.exit(1 if _failures else 0)
