"""One encounter slot.

The map's wild Pokémon cross as a `dict[table][time] -> list[WildMon]` — the two
keys are the adapter's own words for its encounter tables (GRASS, WATER) and its
times of day, and nothing above the seam enumerates either.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WildMon:
    """One encounter slot, in the seam's words.

    `form` is the axis polished adds: a mon there is `(species, form)`, with the
    ninth species bit living in the form byte. The hacks whose mon is a scalar —
    prism is one — fill it with the constant ``""``, and the column below only
    exists when some row doesn't. That is the whole negotiation: an adapter that
    has no forms never says so, it just has nothing to show.
    """
    level: int
    species: str
    form: str = ""
