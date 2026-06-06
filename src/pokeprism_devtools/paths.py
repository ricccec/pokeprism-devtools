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


def rom_path(root: Path | None = None, *, debug: bool = False) -> Path:
    """Return the path to the built ROM. Prefers the requested build but falls
    back to the other if the requested one is missing."""
    root = root or repo_root()
    preferred = root / ("pokeprism.gbc" if debug else "pokeprism_nodebug.gbc")
    fallback = root / ("pokeprism_nodebug.gbc" if debug else "pokeprism.gbc")
    if preferred.exists():
        return preferred
    if fallback.exists():
        return fallback
    raise FileNotFoundError(
        f"No ROM found. Expected {preferred} or {fallback}. Run `make nodebug` "
        "or `make prism` first."
    )


def sym_path(root: Path | None = None, *, debug: bool = False) -> Path:
    """Return the path to the .sym file matching the available ROM."""
    return _sibling_artifact(rom_path(root, debug=debug), ".sym")


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
