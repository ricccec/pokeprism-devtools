#!/usr/bin/env python3
"""Tests for `asmedit/flagalloc.py` — allocating a flag in a bucketed enum.

The hermetic half breaks the allocator the ways the survey actually broke:

  * ignoring `const_skip`, and ignoring its repeat count — the miss that had
    this module reporting one free slot in a bucket the file documents as full;
  * appending at end of file, which lands past the final `const_next` and
    outside the flag array altogether;
  * assuming the conventional bucket has room, when vanilla's sprite-visibility
    bucket has exactly none.

The real half loads both family trees. That is a stronger check than it looks:
`load` verifies every bucket against the file's own `; Unused: next N events`
caption and refuses on any disagreement, so loading vanilla at all means the
parser reproduced all six captions written by hand in the file. Then it
falsifies that check by corrupting a caption and requiring a refusal — a check
that cannot fail is not checking.

    python tests/test_flagalloc.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pokeprism_devtools.asmedit import flagalloc as F  # noqa: E402

VANILLA = Path.home() / "code/ricccec/pokecrystal"
POLISHED = Path.home() / "code/ricccec/polishedcrystal"
PRISM = Path.home() / "code/ricccec/pokeprism"

_failures = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global _failures
    ok = bool(cond)
    if not ok:
        _failures += 1
    print(f"  {'ok  ' if ok else 'FAIL'} {label}"
          f"{(': ' + detail) if detail and not ok else ''}")


# Two buckets. The first is full to the caption; the second has room. The
# `const_skip 3` is the trap: counting it as one slot (or as none) makes the
# first bucket look like it has room it does not have.
_BUCKETED = """\
; wEventFlags bit flags

	const_def
; Johto story events
	const EVENT_FIRST
	const EVENT_SECOND
	const_skip 3
	const EVENT_SIXTH
; Unused: next 4 events

	const_next 10
; Sprite visibility flags
	const EVENT_BALL_ONE
	const_skip
	const EVENT_BALL_THREE
; Unused: next 7 events

	const_next 20
DEF NUM_EVENTS EQU const_value
"""

# A hex bucket boundary. polished writes `const_next $8ff` and vanilla writes
# `const_next 2048`, and a pattern that matches only the decimal one does not
# raise — it silently drops the boundary, leaving the file looking like a single
# run with no headroom, so every allocation is refused for a false reason. That
# shipped once; this fixture is why it cannot again.
_HEX = """\
	const_def
; Hex bucket
	const EVENT_A
; Unused: next 3 events

	const_next $4
DEF NUM_EVENTS EQU const_value
"""

# Every bucket full. There is nowhere to put a flag and saying so is the job.
_FULL = """\
	const_def
; Only bucket
	const EVENT_A
	const EVENT_B
; Unused: next 0 events

	const_next 2
DEF NUM_EVENTS EQU const_value
"""


def _write(tmp: Path, text: str) -> Path:
    root = tmp
    (root / "constants").mkdir(parents=True, exist_ok=True)
    (root / "constants/event_flags.asm").write_text(text)
    return root


def test_hermetic(tmp: Path) -> None:
    print("hermetic — the allocator, broken on purpose")

    root = _write(tmp / "bucketed", _BUCKETED)
    ef = F.load(root)

    first, second = ef.buckets[0], ef.buckets[1]
    check("const_skip's repeat count is charged in full",
          first.used == 6, f"used {first.used}, expected 6 (3 const + skip 3)")
    check("a bare const_skip costs one slot",
          second.used == 3, f"used {second.used}, expected 3")
    check("headroom matches the file's own caption, bucket 1",
          first.free == 4, f"{first.free} free, caption says {first.claimed}")
    check("headroom matches the file's own caption, bucket 2",
          second.free == 7, f"{second.free} free, caption says {second.claimed}")
    check("the bucket label comes from the caption comment",
          second.label == "Sprite visibility flags", second.label)

    # The allocation lands inside the bucket, not at end of file.
    landed = ef.allocate("EVENT_BALL_FOUR", prefer="Sprite visibility flags")
    check("the flag goes to the bucket that was asked for",
          landed.label == "Sprite visibility flags", landed.label)
    out = ef.to_edit("test").new_text.splitlines()
    where = out.index("\tconst EVENT_BALL_FOUR")
    check("the new flag is inside the file, not appended after const_next",
          where < out.index("\tconst_next 20"),
          f"landed at line {where}, const_next 20 at {out.index(chr(9) + 'const_next 20')}")
    check("it lands after the bucket's last slot-consuming line",
          out[where - 1] == "\tconst EVENT_BALL_THREE", out[where - 1])
    check("the other bucket is untouched",
          out.index("\tconst EVENT_SIXTH") < out.index("\tconst_next 10"))

    # A full preferred bucket falls back rather than failing — the grouping is
    # documentation, and CheckObjectFlag never looks at the value range.
    root2 = _write(tmp / "fallback", _BUCKETED)
    ef2 = F.load(root2)
    ef2.buckets[1].used = ef2.buckets[1].end - ef2.buckets[1].start  # fill it
    landed2 = ef2.allocate("EVENT_SOMEWHERE", prefer="Sprite visibility flags")
    check("a full preferred bucket falls back to one with room, and reports it",
          landed2.label != "Sprite visibility flags", landed2.label)

    # The check every hermetic assertion above missed, and that reading real
    # output caught: allocate wrote a file its own loader refused, because the
    # caption still claimed the headroom the new flag had just consumed. Every
    # second allocation would have failed.
    rt = tmp / "roundtrip"
    ef_rt = F.load(_write(rt, _BUCKETED))
    ef_rt.allocate("EVENT_ONE_MORE", prefer="Sprite visibility flags")
    (rt / "constants/event_flags.asm").write_text(ef_rt.to_edit("t").new_text)
    try:
        again = F.load(rt)
        check("the file allocate writes is one load can read back", True)
        check("the caption was decremented, not left stale",
              again.bucket("Sprite visibility flags").claimed == 6,
              f"caption now {again.bucket('Sprite visibility flags').claimed}, "
              "expected 6")
        again.allocate("EVENT_AND_ANOTHER", prefer="Sprite visibility flags")
        check("a second allocation on the written file succeeds", True)
    except F.FlagError as exc:
        check("the file allocate writes is one load can read back", False,
              str(exc))

    hx = F.load(_write(tmp / "hex", _HEX))
    check("a hex `const_next $4` bounds its bucket like a decimal one",
          len(hx.buckets) == 2 and hx.buckets[0].free == 3,
          f"{len(hx.buckets)} bucket(s), first has "
          f"{hx.buckets[0].free} free (expected 3)")

    root3 = _write(tmp / "full", _FULL)
    ef3 = F.load(root3)
    try:
        ef3.allocate("EVENT_NOWHERE")
        check("a file with no room anywhere is refused", False, "no refusal")
    except F.FlagError as exc:
        check("a file with no room anywhere is refused", "full" in str(exc))

    ef4 = F.load(_write(tmp / "dup", _BUCKETED))
    try:
        ef4.allocate("EVENT_FIRST")
        check("allocating an existing name is refused", False, "no refusal")
    except F.FlagError as exc:
        check("allocating an existing name is refused",
              "already defined" in str(exc))

    # The caption check is the whole safety net. Prove it can fail.
    bad = _BUCKETED.replace("; Unused: next 4 events", "; Unused: next 99 events")
    try:
        F.load(_write(tmp / "badcaption", bad))
        check("a caption that disagrees with the count is refused", False,
              "loaded a file whose own comment contradicts it")
    except F.FlagError as exc:
        check("a caption that disagrees with the count is refused",
              "actually free" in str(exc))


def test_real(root: Path, name: str, expect: dict[str, int]) -> None:
    """Loading at all means every caption in the file was reproduced."""
    print(f"{name} — the real flag file")
    if not (root / "constants/event_flags.asm").exists():
        check(f"{name} tree is present", False, str(root))
        return
    try:
        ef = F.load(root)
    except F.FlagError as exc:
        check(f"{name}: parses, and agrees with every caption in the file",
              False, str(exc))
        return
    captioned = [b for b in ef.buckets if b.claimed is not None]
    check(f"{name}: parses, and agrees with all {len(captioned)} captions",
          True)
    for label, free in expect.items():
        b = ef.bucket(label)
        check(f"{name}: {label!r} has {free} free",
              b is not None and b.free == free,
              f"got {b.free if b else 'no such bucket'}")
    total = sum(b.free for b in ef.buckets)
    print(f"       ({len(ef.names)} flags, {total} free across "
          f"{len(ef.buckets)} buckets)")


def test_prism_refused() -> None:
    """prism has no `const_def` — it is one unbroken run with named `skip`
    placeholders, and `hacks/prism/eventflags` is its allocator. This one must
    not half-understand that file."""
    print("prism — a different reservation scheme entirely")
    if not (PRISM / "constants/event_flags.asm").exists():
        check("prism tree is present", False, str(PRISM))
        return
    try:
        F.load(PRISM)
        check("prism's unbucketed file is refused, not half-parsed", False,
              "parsed a file this allocator does not model")
    except F.FlagError as exc:
        check("prism's unbucketed file is refused, not half-parsed",
              "const_def" in str(exc), str(exc))


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        test_hermetic(Path(td))
    # Measured from the trees; each also appears as a caption in the file.
    test_real(VANILLA, "vanilla", {
        "Sprite visibility flags": 0,
        "Kanto story events": 339,
        "Kanto people": 48,
    })
    # Not an empty dict. An expectation of nothing is what let the dropped hex
    # boundary through: polished reported "0 free across 1 buckets" and the
    # test agreed with it, because it was asked to check nothing at all.
    test_real(POLISHED, "polished", {"(start)": 29})
    test_prism_refused()
    print(f"\n{'FAILURES: ' + str(_failures) if _failures else 'all ok'}")
    sys.exit(1 if _failures else 0)
