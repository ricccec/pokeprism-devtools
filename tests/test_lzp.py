#!/usr/bin/env python3
"""Verify polished's `.ablk.lzp` decompressor against ground truth.

Every compressed `maps/X.ablk.lzp` the build INCBINs was made by
`tools/lzpcompress` from the plain `maps/X.ablk` sibling that is tracked in the
tree — so the sibling *is* the correct decompression, sitting right next to the
input with no emulator or save needed. This runs the Python port over every pair
and asserts the bytes come back identical, which exercises the whole opcode set
(the base LZ commands and the three `$fc-$fe` nibble-packers) on real data.

The falsification proves the comparison discriminates: the same stream decoded
and checked against a *different* map's plain bytes must fail, or a byte-exact
match against the right sibling proves nothing.

    python tests/test_lzp.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pokeprism_devtools.hacks.polished import lzp  # noqa: E402

POLISHED = Path.home() / "code/ricccec/polishedcrystal"

_failures = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global _failures
    ok = bool(cond)
    if not ok:
        _failures += 1
    print(f"  {'ok  ' if ok else 'FAIL'} {label}"
          f"{(': ' + detail) if detail and not ok else ''}")


def _pairs() -> list[tuple[Path, Path]]:
    """(compressed, plain) for every `.ablk.lzp` with a plain `.ablk` sibling."""
    out = []
    for lz in sorted((POLISHED / "maps").glob("*.ablk.lzp")):
        plain = lz.with_suffix("")  # drop ".lzp" → "X.ablk"
        if plain.exists():
            out.append((lz, plain))
    return out


def test_round_trip() -> None:
    """Decompress every built block file back to its tracked plain sibling."""
    print("lzp — decompress every map's blocks back to its plain .ablk")
    if not (POLISHED / "maps").exists():
        check("polished tree is present", False, str(POLISHED))
        return
    pairs = _pairs()
    if not pairs:
        check("built .ablk.lzp files are present (run `make` in polished)",
              False, "no maps/*.ablk.lzp found")
        return

    trouble: list[str] = []
    for comp, plain in pairs:
        want = plain.read_bytes()
        try:
            got, _consumed = lzp.decompress(comp.read_bytes())
        except Exception as exc:  # noqa: BLE001 — a raise is a failure to report
            trouble.append(f"{plain.name}: raised {exc!r}")
            continue
        if got != want:
            n = next((i for i in range(min(len(got), len(want)))
                      if got[i] != want[i]), min(len(got), len(want)))
            trouble.append(
                f"{plain.name}: got {len(got)}B want {len(want)}B, "
                f"first diff at {n}")
    check(f"all {len(pairs)} map block files decompress byte-exact",
          not trouble, "; ".join(trouble[:4]))
    print(f"       ({len(pairs)} pairs checked)")


def test_falsified() -> None:
    """The match is byte-exact, so a wrong target must fail. Decode one map and
    compare it to a *different* map's plain bytes — if that passed, the round
    trip above would be asserting nothing."""
    print("falsification — a decode checked against the wrong map fails")
    pairs = _pairs()
    if len(pairs) < 2:
        check("two map pairs are present", False, f"{len(pairs)} found")
        return
    (comp, _plain), (_comp2, other_plain) = pairs[0], pairs[1]
    got, _ = lzp.decompress(comp.read_bytes())
    check("decoded blocks do not match a different map's plain bytes",
          got != other_plain.read_bytes(),
          "two maps decompressed to identical bytes — the check can't tell "
          "maps apart")


if __name__ == "__main__":
    test_round_trip()
    test_falsified()
    print(f"\n{'FAILURES: ' + str(_failures) if _failures else 'all ok'}")
    sys.exit(1 if _failures else 0)
