"""How a byte count and a warning look on the way out.

Colour is decided once, here, and only when stdout is a terminal that has not
asked for `NO_COLOR` — so piping any command gives plain text without a flag.
"""

from __future__ import annotations

import os
import sys


def _color() -> bool:
    return sys.stdout.isatty() and "NO_COLOR" not in os.environ


def _red(s: str, c: bool) -> str:
    return f"\033[31m{s}\033[0m" if c else s


def _yellow(s: str, c: bool) -> str:
    return f"\033[33m{s}\033[0m" if c else s


def _green(s: str, c: bool) -> str:
    return f"\033[32m{s}\033[0m" if c else s


def _fmt(n: int) -> str:
    return f"{n:,}"
