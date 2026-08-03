"""The fixed-width table prism-maps prints.

Column widths are measured with the ANSI escapes stripped, so a coloured cell
occupies the width the terminal actually gives it rather than the width of its
bytes.
"""

from __future__ import annotations

import re

from .mapinfo import MapInfo

_GREEN = "\033[32m"
_RED = "\033[31m"
_RESET = "\033[0m"


def _c(text: str, code: str, *, color: bool) -> str:
    return f"{code}{text}{_RESET}" if color else text


_HEADERS = ("NAME", "W", "H", "BLKS", "RAW", "LZ", "RATIO", "SCRIPT", "NPCS", "USED")


def _fmt_row(r: MapInfo, *, color: bool) -> tuple[str, ...]:
    def _dash(v: int | None) -> str:
        return "—" if v is None else str(v)

    if r.lz_ratio is None:
        ratio_str = "—"
    else:
        pct = f"{r.lz_ratio * 100:.0f}%"
        ratio_str = _c(pct, _RED, color=color) if r.lz_ratio > 1.0 else pct

    used_str = (
        _c("✓", _GREEN, color=color)
        if r.used
        else _c("✗", _RED, color=color)
    )

    return (
        r.name,
        str(r.width),
        str(r.height),
        str(r.blocks),
        _dash(r.blk_raw),
        _dash(r.blk_lz),
        ratio_str,
        _dash(r.script_src),
        _dash(r.npc_count),
        used_str,
    )


def _visible_len(s: str) -> int:
    return len(re.sub(r"\033\[[0-9;]*m", "", s))


def render_table(rows: list[MapInfo], *, color: bool) -> str:
    """Return a fixed-width table string."""
    formatted = [_fmt_row(r, color=color) for r in rows]
    widths = [len(h) for h in _HEADERS]
    for row in formatted:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], _visible_len(cell))

    def _pad(cell: str, width: int) -> str:
        return cell + " " * (width - _visible_len(cell))

    sep = "  ".join("-" * w for w in widths)
    header = "  ".join(h.ljust(w) for h, w in zip(_HEADERS, widths))
    lines = [header, sep]
    for row in formatted:
        lines.append("  ".join(_pad(c, w) for c, w in zip(row, widths)))
    return "\n".join(lines)
