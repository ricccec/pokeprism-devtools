"""Which of prism's two ROMs is the debug build — the one thing about them that
cannot be read from source.

`shared/paths.read_built_roms` reads the candidates out of the `Makefile`, and on
prism that is exactly `roms := pokeprism.gbc pokeprism_nodebug.gbc`. What the
`Makefile` does not say is which of the two carries symbols, and **prism inverts
the family's convention to boot**: the plain name is the debug build and the
suffixed one is the release. A tool that guessed from the filename would be
right on pokecrystal, silent on polishedcrystal and backwards here.

So it is declared, on prism's side of the seam, and crosses as data — a
`prefer` list handed to `find_built_rom`. The library resolves it and never
learns whose names these are.
"""

from __future__ import annotations

#: `make prism` — the build with symbols, whose plain name is the trap.
DEBUG_ROM = "pokeprism.gbc"

#: `make nodebug` — the release build.
RELEASE_ROM = "pokeprism_nodebug.gbc"


def prefer_prism_rom(debug: bool) -> tuple[str, ...]:
    """The preference list for `find_built_rom`, given a debug/release choice.

    One name, not two: the second candidate a caller would accept is already
    `built_roms`' job, and spelling both here would re-implement the fallback
    that `find_built_rom` owns — including for the caller who passed
    `fallback=False` precisely to refuse it.
    """
    return (DEBUG_ROM if debug else RELEASE_ROM,)
