#!/usr/bin/env python3
"""Prism's save now feeds `wVariableSprites` to the sprite-VRAM allocator.

A variable sprite (id >= `SPRITE_VARS`) names no graphic — it stands for whatever
the save's 16-byte `wVariableSprites` array points it at, and *that* sprite's type
decides its VRAM length (still = 4 tiles, walking = 12). Guess wrong and the
allocator's cumulative offsets shift every sprite the sort places after it, which
is how an NPC ends up rendering as another sprite. Vanilla has fed the array in
since the boot was proven; prism took the empty default, so its variable sprites
silently fell back to walking.

Wiring it is safe to do *now*, and this test is why: on prism as it stands the
wiring is a **provable no-op** — every `variablesprite` write in the tree points at
a walking sprite, so the resolved answer and the fallback agree on every input
prism can produce. That is a fact about prism's data, not a property of the code,
so it is asserted here rather than assumed: the day someone points a slot at a
still sprite, this test says so, and at that moment the wiring stops being a no-op
and starts being the thing that keeps the map right.

Which means "nothing changed" is a worthless result on its own — a `sprite_tiles`
that ignored the array entirely would pass it. So each no-op claim is paired with
its falsification: the same pool, the same call, one slot pointed at a *still*
sprite, and the tiles must **move**. That runs at both levels — the allocator
directly, and end to end through `apply_state`, which is what proves `apply.py`
actually reads the array out of prism's save and passes it on.

What this does *not* prove is the one thing neither tree can prove yet: that the
real engine agrees with our still-sprite sizing. No save in either tree points a
slot at a still sprite, so that half stays unverified — see `docs/save-patch.md`.

    ./.venv/bin/python tests/test_prism_variable_sprites.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pokeprism_devtools.dev_server import apply as apply_mod  # noqa: E402
from pokeprism_devtools.dev_server import inventory  # noqa: E402
from pokeprism_devtools.hacks.prism import maps, savefile, spritesets  # noqa: E402
from pokeprism_devtools.hacks.prism.mapformat import PRISM_FORMAT  # noqa: E402
from pokeprism_devtools.shared.overworld import blockdata, people, spritevram  # noqa: E402
from pokeprism_devtools.shared.symfile import SymFile  # noqa: E402

PRISM = Path.home() / "code/ricccec/pokeprism"
ROM = PRISM / "pokeprism.gbc"
SYM = PRISM / "pokeprism.sym"
SAV = PRISM / "pokeprism.sav"
DIMENSIONS = PRISM / "constants/map_dimension_constants.asm"

# The one prism map that places variable sprites. Named rather than searched for
# because it is also the fixture: if prism grows another, the census below says so.
FIXTURE_MAP = "CASTRO_GYM"

_VARIABLESPRITE_RE = re.compile(
    r"^\s*variablesprite\s+([A-Z_0-9]+)\s*,\s*([A-Z_0-9]+)\s*$")

_failures = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global _failures
    print(f"  [{'OK  ' if cond else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        _failures += 1


def variablesprite_writes(root: Path) -> list[tuple[str, str]]:
    """Every `variablesprite SLOT, REAL` the tree can execute, as (slot, real).

    These are the only writes to `wVariableSprites`, so they enumerate every value
    a prism save's array can hold — which is what makes the no-op claim checkable
    rather than merely plausible.
    """
    out: list[tuple[str, str]] = []
    for path in sorted(root.glob("**/*.asm")):
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            m = _VARIABLESPRITE_RE.match(line.split(";")[0])
            if m:
                out.append((m.group(1), m.group(2)))
    return out


def test_prism_is_inert_today() -> tuple[spritesets.SpriteData, dict[int, str]] | None:
    """The census: what prism's variable sprites can currently resolve to."""
    print("\nprism's variable sprites all resolve to walking sprites today")
    sd = spritesets.load(PRISM)
    writes = variablesprite_writes(PRISM)
    check("the tree writes wVariableSprites at all (else nothing below is a test)",
          bool(writes), f"{len(writes)} variablesprite lines")

    resolutions = {}
    non_walking = []
    for slot, real in writes:
        header = sd.header(real)
        resolutions[sd.sprite_ids.get(slot, -1)] = real
        if header is None or header.type != "WALKING_SPRITE":
            non_walking.append(f"{slot} -> {real} ({header.type if header else 'no header'})")
    check("every resolution the tree can produce is a WALKING sprite, so the "
          "resolved length equals the walking fallback — the wiring is a no-op "
          "on prism as it stands",
          not non_walking, "; ".join(non_walking) or f"{len(set(writes))} distinct writes")

    # An outdoor map's pool is its group's OutdoorSprites list, not its own NPCs,
    # so a variable sprite there would put every map in the group in play. None do.
    outdoor = [f"group {g}: {s}" for g, names in sd.outdoor_sets.items()
               for s in names if sd.is_variable_sprite(s)]
    check("no outdoor sprite pool carries a variable sprite, so only maps that "
          "place one themselves are affected at all", not outdoor, "; ".join(outdoor))
    return sd, resolutions


def _fixture_pool(sd: spritesets.SpriteData, syms: SymFile) -> list[int]:
    mdef = next(m for m in maps.parse_maps(DIMENSIONS) if m.name == FIXTURE_MAP)
    events = blockdata.object_events(ROM, syms, mdef.group, mdef.map_id,
                                     name=FIXTURE_MAP, format=PRISM_FORMAT)
    return [ev[0] for ev in events]


def _still_sprite_id(sd: spritesets.SpriteData) -> int:
    """Any id whose header says STILL — 4 tiles where a walker is 12."""
    return min(sd.sprite_ids[name] for name, h in sd.headers.items()
               if h.type == "STILL_SPRITE" and name in sd.sprite_ids)


def test_allocator_reads_the_array(sd, resolutions) -> None:
    """The allocator directly: no-op today, and shown biting when it isn't."""
    print(f"\nthe allocator on {FIXTURE_MAP}'s real pool")
    syms = SymFile.load(SYM)
    pool = _fixture_pool(sd, syms)
    variable = [s for s in pool if s >= sd.vars_sprite_id]
    check("the fixture map really places variable sprites (else this proves "
          "nothing)", bool(variable), " ".join(hex(s) for s in variable))

    player = sd.sprite_ids[sd.player_sprite()]

    def tiles(array: bytes) -> dict[int, int]:
        return spritevram.sprite_tiles(
            ROM, syms, player, pool,
            headers_symbol=PRISM_FORMAT.sprite_headers, variable_sprites=array)

    today = bytearray(16)
    for sid, real in resolutions.items():
        if sid >= sd.vars_sprite_id:
            today[sid - sd.vars_sprite_id] = sd.sprite_ids[real]

    unwired = tiles(b"")
    check("resolving the array gives byte-identical VRAM tiles to the old empty "
          "default — wiring prism changes nothing it renders today",
          tiles(bytes(today)) == unwired, str({hex(k): v for k, v in unwired.items()}))

    # Falsify: without this, the check above would pass on an allocator that
    # never looked at the array.
    still = bytearray(today)
    still[variable[0] - sd.vars_sprite_id] = _still_sprite_id(sd)
    moved = tiles(bytes(still))
    check("but point one slot at a STILL sprite and the tiles move — the array "
          "is read, and a wrong length really does shift the sort",
          moved != unwired,
          f"{hex(variable[0])}: {unwired[variable[0]]} -> {moved[variable[0]]}")


def test_apply_passes_the_array(sd, resolutions) -> None:
    """End to end: `apply.py` reads the array out of prism's own save layout."""
    print("\napply_state carries prism's wVariableSprites into the rebuild")
    syms = SymFile.load(SYM)
    inv = inventory.build(PRISM, SYM)
    entry = inv["sram_offsets"].get("wVariableSprites", {})
    check("the inventory resolves wVariableSprites, which is what off() needs",
          "sav_offset" in entry and entry.get("size") == 16, str(entry))
    if "sav_offset" not in entry:
        return

    vs_off = entry["sav_offset"]
    os_off = inv["sram_offsets"]["wObjectStructs"]["sav_offset"]
    raw = SAV.read_bytes()

    def sprite_tiles_written(array: bytes) -> dict[int, int]:
        sav = savefile.SaveFile(bytearray(raw))
        sav.data[vs_off:vs_off + 16] = array
        apply_mod.apply_state(
            sav, {"map": {"name": FIXTURE_MAP, "x": 4, "y": 8}}, inv,
            rom_path=ROM, syms=syms, keep_people=False)
        out = {}
        for i in range(people.NUM_OBJECT_STRUCTS):
            p = os_off + i * people.OBJECT_STRUCT_LEN
            sid = sav.data[p + people.OBJ_SPRITE]
            if sid:
                out[sid] = sav.data[p + people.OBJ_SPRITE_TILE]
        return out

    today = bytearray(16)
    for sid, real in resolutions.items():
        if sid >= sd.vars_sprite_id:
            today[sid - sd.vars_sprite_id] = sd.sprite_ids[real]

    zeroed = sprite_tiles_written(bytes(16))
    check("a save whose array is all zeroes and one holding prism's own walking "
          "resolutions write the same SPRITE_TILE bytes",
          sprite_tiles_written(bytes(today)) == zeroed,
          str({hex(k): v for k, v in zeroed.items()}))

    variable = [s for s in zeroed if s >= sd.vars_sprite_id]
    check("the map's variable sprites reached wObjectStructs at all",
          bool(variable), " ".join(hex(s) for s in variable))
    if not variable:
        return

    # Falsify the pass-through itself: before the fix apply.py passed no array, so
    # this would come back equal to `zeroed` and the check above would be vacuous.
    still = bytearray(today)
    still[variable[0] - sd.vars_sprite_id] = _still_sprite_id(sd)
    moved = sprite_tiles_written(bytes(still))
    check("and a still resolution changes the tile apply_state writes, so the "
          "array really travels from prism's save into the allocator",
          moved != zeroed,
          f"{hex(variable[0])}: {zeroed[variable[0]]} -> {moved.get(variable[0])}")


def main() -> int:
    for path in (PRISM, ROM, SYM, SAV):
        if not path.exists():
            print(f"  --   no {path} — skipping")
            return 0
    census = test_prism_is_inert_today()
    if census is not None:
        test_allocator_reads_the_array(*census)
        test_apply_passes_the_array(*census)
    print("\nall checks passed" if not _failures else f"\n{_failures} FAILED")
    return 1 if _failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
