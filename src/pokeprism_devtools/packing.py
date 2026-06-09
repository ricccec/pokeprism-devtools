"""Two-tier best-fit bank packer for placing new map data into a near-full ROM.

The pokeprism ROM is an MBC5 2 MB cartridge: 128 banks of 16 KiB. `romx.link`
only *declares* banks ``$01``–``$75``; the remaining ``$76``–``$7F`` are physical
``$ff`` padding the linker never touches, i.e. ten completely empty banks.

A section cannot span a bank, and the map cross-references are bank-aware
(``dba`` / ``db BANK(...)``), so each new map blob (block data, script/event,
secondary header) is an indivisible *item* that may be placed in any single
bank that has room. That makes the placement a small bin-packing problem.

Two tiers of free space, and a deliberate policy between them:

* **scraps** — the leftover bytes inside declared banks ``$01``–``$75``. Plentiful
  in aggregate but heavily fragmented (most gaps are well under 256 bytes).
* **empty high banks** — ``$76``–``$7F``, a full 16 KiB each, contiguous.

We pack small blobs into scraps first (best-fit, tightest gap that still fits)
so the contiguous empty banks stay available for things that genuinely need a
lot of room. Only when no scrap fits do we spill into a high bank.
"""

from __future__ import annotations

from dataclasses import dataclass, field


HIGH_BANK_START = 0x76      # first undeclared (empty) ROMX bank
MAX_ROM_BANK = 0x7F         # last bank in a 2 MB MBC5 cartridge
BANK_CAPACITY = 0x4000      # 16 KiB usable per ROMX bank


@dataclass(frozen=True)
class Item:
    """One indivisible thing to place: a named section and its byte size."""
    key: str          # human label, e.g. "Map Scripts MtEmberSmallRoom"
    size: int


@dataclass(frozen=True)
class Placement:
    item: Item
    bank: int
    tier: str         # "scrap" or "empty"


class NoFitError(RuntimeError):
    """Raised when an item fits in no single bank (even an empty one)."""

    def __init__(self, item: Item, largest_gap: int, largest_bank: int | None):
        self.item = item
        self.largest_gap = largest_gap
        self.largest_bank = largest_bank
        where = (
            f"largest single gap is {largest_gap} bytes "
            f"(bank ${largest_bank:02x})"
            if largest_bank is not None
            else "no banks available"
        )
        super().__init__(
            f"cannot place '{item.key}' ({item.size} bytes): {where}. "
            "A section must fit entirely in one 16 KiB bank — free a bank, "
            "shrink the blob, or split the map's script."
        )


@dataclass
class FreeSpace:
    """Per-bank free bytes for the ROMX region, both tiers included.

    Build with :meth:`from_mapfile`; banks ``$76``–``$7F`` are synthesised as
    fully free even when absent from the ``.map`` (the linker never lists the
    padding banks).
    """

    free: dict[int, int] = field(default_factory=dict)

    @classmethod
    def from_mapfile(cls, mapfile, *, max_bank: int = MAX_ROM_BANK) -> "FreeSpace":
        """Construct from a parsed :class:`mapfile.MapFile`.

        Uses each ROMX bank's reported free space, and treats every bank up to
        ``max_bank`` that the map never mentions as a fully empty 16 KiB bank.
        """
        free: dict[int, int] = {}
        for (region, number), bank in mapfile.banks.items():
            if region == "ROMX":
                free[number] = bank.free
        for n in range(1, max_bank + 1):
            free.setdefault(n, BANK_CAPACITY)
        return cls(free)

    def reserve(self, bank: int, amount: int) -> None:
        """Account for bytes consumed outside the packer (e.g. the +8 the
        positional primary header adds to whichever bank holds 'Map Headers')."""
        self.free[bank] = self.free.get(bank, BANK_CAPACITY) - amount

    def copy(self) -> "FreeSpace":
        return FreeSpace(dict(self.free))


def pack(
    items: list[Item],
    free: FreeSpace,
    *,
    margin: int = 16,
    high_bank_start: int = HIGH_BANK_START,
    strategy: str = "tight",
) -> list[Placement]:
    """Decreasing-size placement under one of two strategies.

    * ``"tight"`` (default, "consolidate") — best-fit into scraps first, spill
      to an empty high bank only if no scrap fits. Leaves the contiguous empty
      banks free and minimises wasted scrap.
    * ``"loose"`` ("park") — worst-fit: the single *largest* gap that fits,
      which is naturally an empty high bank (``$76``–``$7F``). Gives a still-
      growing map maximum headroom before it overflows its bank.

    ``margin`` reserves slack in each bank so a build that grows a hair past our
    estimate doesn't overflow. Placements come back in input order; ``free`` is
    not mutated. Raises :class:`NoFitError` for the first item that fits nowhere.
    """
    if strategy not in ("tight", "loose"):
        raise ValueError(f"unknown strategy {strategy!r} (use 'tight' or 'loose')")
    remaining = dict(free.free)
    placements: list[Placement] = []

    # Decreasing size: place the bulky script before the tiny headers, so a
    # big item claims the one bank that fits it before a small item wastes it.
    for item in sorted(items, key=lambda it: it.size, reverse=True):
        if strategy == "tight":
            bank, tier = _place_tight(remaining, item.size, margin, high_bank_start)
        else:
            bank, tier = _place_loose(remaining, item.size, margin, high_bank_start)
        if bank is None:
            largest_bank = _largest_gap_bank(remaining, margin)
            gap = remaining.get(largest_bank, 0) - margin if largest_bank else 0
            raise NoFitError(item, max(gap, 0), largest_bank)
        remaining[bank] -= item.size
        placements.append(Placement(item=item, bank=bank, tier=tier))

    by_key = {p.item.key: p for p in placements}
    return [by_key[it.key] for it in items]


def _place_tight(remaining, size, margin, high):
    """Best-fit scrap, else first empty high bank."""
    scrap = _best_fit(remaining, size, margin, lambda b: b < high)
    if scrap is not None:
        return scrap, "scrap"
    empty = _first_fit(remaining, size, margin, lambda b: b >= high)
    return (empty, "empty") if empty is not None else (None, None)


def _place_loose(remaining, size, margin, high):
    """Worst-fit across all banks: the largest gap that fits (parks growing
    maps in the roomiest bank, normally an empty high bank)."""
    best_bank = None
    best_gap = None
    for bank, gap in remaining.items():
        usable = gap - margin
        if usable >= size and (best_gap is None or usable > best_gap):
            best_bank, best_gap = bank, usable
    if best_bank is None:
        return None, None
    return best_bank, ("empty" if best_bank >= high else "scrap")


def _best_fit(remaining, size, margin, predicate):
    """Bank with the *smallest* sufficient gap (tightest fit), or None."""
    best_bank = None
    best_gap = None
    for bank, gap in remaining.items():
        if not predicate(bank):
            continue
        usable = gap - margin
        if usable >= size and (best_gap is None or usable < best_gap):
            best_bank, best_gap = bank, usable
    return best_bank


def _first_fit(remaining, size, margin, predicate):
    """Lowest-numbered bank that fits, or None."""
    for bank in sorted(remaining):
        if predicate(bank) and remaining[bank] - margin >= size:
            return bank
    return None


def _largest_gap_bank(remaining, margin):
    best_bank = None
    best_gap = -1
    for bank, gap in remaining.items():
        if gap - margin > best_gap:
            best_bank, best_gap = bank, gap - margin
    return best_bank
