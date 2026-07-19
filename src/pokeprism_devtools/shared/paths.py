"""Locate pokeprism build artifacts relative to the repo root."""

from __future__ import annotations

from pathlib import Path


class RepoNotFound(RuntimeError):
    pass


def repo_root(start: Path | None = None) -> Path:
    """Walk up from `start` (or cwd) until we find the Makefile."""
    p = (start or Path.cwd()).resolve()
    for candidate in [p, *p.parents]:
        if (candidate / "Makefile").exists() and (candidate / "main.asm").exists():
            return candidate
    raise RepoNotFound(
        f"Could not find pokeprism repo root from {p} — no Makefile + main.asm "
        "found in any parent directory."
    )


#: The two files every map parser here starts from. Their *presence* is what
#: makes a tree prism-shaped; every other gen-2 hack keeps these facts elsewhere.
_PRISM_LAYOUT = ("maps/second_map_headers.asm",
                 "constants/map_dimension_constants.asm")


def assert_prism_layout(root: Path) -> None:
    """Refuse, loudly, a repo whose map data these tools cannot read.

    Every gen-2 disassembly has a Makefile and a main.asm, so :func:`repo_root`
    accepts pokecrystal and polished-crystal as happily as pokeprism — and the
    map parsers then fail *silently*: `header_pairs` returns an empty list when
    `maps/second_map_headers.asm` does not exist, so the studio would open on a
    vanilla checkout and report zero maps, which reads as "empty repo", not as
    "wrong hack". Measured in docs/polished-crystal-feasibility.md, Phase 0:
    five of eight parsers fail this way. Until an adapter for the vanilla layout
    exists, the honest answer is an error that names the tree it found.
    """
    if all((root / rel).exists() for rel in _PRISM_LAYOUT):
        return
    looks_like = ("a pokecrystal-family checkout (map data under data/maps/)"
                  if (root / "data/maps/maps.asm").exists()
                  else "not a gen-2 map source layout these tools know")
    missing = ", ".join(rel for rel in _PRISM_LAYOUT if not (root / rel).exists())
    raise RepoNotFound(
        f"{root} is not laid out like pokeprism ({missing} missing) — it looks "
        f"like {looks_like}. Only the pokeprism layout can be read today; "
        "reading other hacks is sketched in docs/adapter-plan.md but not built."
    )


def rom_path(root: Path | None = None, *, debug: bool = False,
             fallback: bool = True) -> Path:
    """Return the path to the built ROM. Prefers the requested build and, by
    default, falls back to the other if the requested one is missing.

    **`fallback=False` if you just built one of them.** The fallback exists for a
    reader — `prism-usage` wants whichever ROM is lying around and either will do.
    It is wrong for anybody who *chose* a target: build `prism` while an old
    `pokeprism_nodebug.gbc` is still on disk and a falling-back caller will hand
    back the nodebug ROM, so you would patch a save against one game and play the
    other, with your new map missing from it and nothing on screen to say why.
    """
    root = root or repo_root()
    wanted = root / ("pokeprism.gbc" if debug else "pokeprism_nodebug.gbc")
    other = root / ("pokeprism_nodebug.gbc" if debug else "pokeprism.gbc")
    if wanted.exists():
        return wanted
    if fallback and other.exists():
        return other
    target = "prism" if debug else "nodebug"
    raise FileNotFoundError(
        f"No ROM at {wanted}. Run `make {target}` first."
        if not fallback else
        f"No ROM found. Expected {wanted} or {other}. Run `make nodebug` "
        "or `make prism` first."
    )


def sym_path(root: Path | None = None, *, debug: bool = False,
             fallback: bool = True) -> Path:
    """Return the path to the .sym file matching the available ROM."""
    return _sibling_artifact(rom_path(root, debug=debug, fallback=fallback), ".sym")


def map_path(root: Path | None = None, *, debug: bool = False) -> Path:
    return _sibling_artifact(rom_path(root, debug=debug), ".map")


def rom_bank_count(rom: Path) -> int:
    """Total number of 16 KiB ROM banks the cartridge declares — i.e. what the
    hardware sees, including the trailing padding banks rgbfix appends.

    Reads the ROM-size byte at $0148 (banks = 2 << code for codes $00–$08).
    Falls back to the file size if the byte is unreadable or non-standard;
    rgbfix always pads to a whole number of banks, so that's exact too.
    """
    try:
        with rom.open("rb") as f:
            f.seek(0x0148)
            code = f.read(1)
        if len(code) == 1 and code[0] <= 0x08:
            return 2 << code[0]
        return max(1, rom.stat().st_size // 16_384)
    except OSError:
        return 0


def sav_path(root: Path | None = None, *, debug: bool = False) -> Path:
    """Path to the .sav next to the ROM. May or may not exist yet."""
    return rom_path(root, debug=debug).with_suffix(".sav")


def _sibling_artifact(rom: Path, suffix: str) -> Path:
    candidate = rom.with_suffix(suffix)
    if not candidate.exists():
        raise FileNotFoundError(
            f"Expected {candidate} alongside {rom.name}. Rebuild to regenerate it."
        )
    return candidate
