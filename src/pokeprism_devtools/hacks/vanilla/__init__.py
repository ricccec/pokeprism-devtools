"""The pokecrystal adapter: vanilla's source dialect, read-only.

Vanilla is the family's median — polished and every modern hack write the
same `def_*` event grammar — so this package is the cheap validation of the
seam that `docs/polished-crystal-feasibility.md` Phase 3 asks for. It reads a
stock pokecrystal checkout into the records the `contract/` package declares and
offers nothing else: no linter, no writes, no emulator, no text physics.
Above the seam each of those degrades to absence, which is the whole point
of declaring capabilities instead of branching on names.
"""
