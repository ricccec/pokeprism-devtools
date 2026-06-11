"""Parser for the `const NAME` enum pattern in `constants/*.asm`.

Handles the patterns used by pokemon_constants.asm, item_constants.asm,
event_flags.asm, and similar files:

    const_def              ; reset counter to 0
    const_def 1            ; reset counter to 1
    const_value = N        ; set counter to N
    const NAME             ; NAME EQU counter; counter += 1
    NUM_X EQU const_value  ; literal EQU (also captured if RHS is a literal)
    INCLUDE "path.asm"     ; followed when base_dir is provided

NOT handled (intentionally — too complex / not needed yet):
    - `mapgroup`/`newgroup` for map_constants.asm (dedicated parser elsewhere)
    - `shift_const` (1 << counter)
    - `enum`/`enum_start`
    - Arithmetic in EQU right-hand sides

The counter is a single integer threaded through the parse. For files like
`constants/pokemon_constants.asm` that don't set up their own counter, parse
the parent (`constants.asm`) instead — it does `const_def; const NO_POKEMON`
before INCLUDEing the child, so the counter is correctly set.

Lines that don't match anything are skipped silently.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Const:
    name: str
    value: int


_CONST_DEF_RE = re.compile(r"^\s*const_def(?:\s+(-?\d+|\$[0-9a-fA-F]+))?\s*$")
_CONST_VALUE_RE = re.compile(r"^\s*const_value\s*=\s*(-?\d+|\$[0-9a-fA-F]+)\s*$")
_CONST_RE = re.compile(r"^\s*const\s+([A-Za-z_][A-Za-z0-9_]*)\s*$")
_EQU_RE = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s+EQU\s+(.+?)\s*$"
)
_INCLUDE_RE = re.compile(r'^\s*INCLUDE\s+"([^"]+)"\s*$')


def parse_constants(
    path: Path,
    *,
    base_dir: Path | None = None,
    start_counter: int = 0,
    stop_at_reset: bool = False,
) -> list[Const]:
    """Parse a constants file.

    If `base_dir` is provided, `INCLUDE` directives are followed; paths
    inside them are resolved relative to `base_dir`. Pass the repo root.

    `start_counter` lets callers parse a child file directly without going
    through the parent.

    `stop_at_reset` halts parsing at the first `const_def` or `const_value =`
    encountered (the *initial* counter setup, if any, doesn't count — only
    resets that change the counter to a new value mid-stream). Useful for
    files that define an enum (e.g. pokemon species) followed by unrelated
    constants that share the file but reset the counter.
    """
    out: list[Const] = []
    _parse_into(
        path,
        out,
        [start_counter],
        base_dir,
        seen=set(),
        stop_at_reset=stop_at_reset,
        seen_first_token=[False],
    )
    return out


def _parse_into(
    path: Path,
    out: list[Const],
    counter_box: list[int],
    base_dir: Path | None,
    *,
    seen: set[Path],
    stop_at_reset: bool,
    seen_first_token: list[bool],
) -> None:
    resolved = path.resolve()
    if resolved in seen:
        return  # protect against accidental cycles
    seen.add(resolved)

    with path.open("r", encoding="utf-8") as f:
        for raw in f:
            line = _strip_comment(raw)
            if not line.strip():
                continue

            m = _CONST_DEF_RE.match(line)
            if m:
                if stop_at_reset and seen_first_token[0]:
                    return
                counter_box[0] = _to_int(m.group(1)) if m.group(1) else 0
                seen_first_token[0] = True
                continue

            m = _CONST_VALUE_RE.match(line)
            if m:
                if stop_at_reset and seen_first_token[0]:
                    return
                counter_box[0] = _to_int(m.group(1))
                seen_first_token[0] = True
                continue

            m = _CONST_RE.match(line)
            if m:
                out.append(Const(name=m.group(1), value=counter_box[0]))
                counter_box[0] += 1
                seen_first_token[0] = True
                continue

            m = _INCLUDE_RE.match(line)
            if m and base_dir is not None:
                child = base_dir / m.group(1)
                if child.exists():
                    _parse_into(
                        child,
                        out,
                        counter_box,
                        base_dir,
                        seen=seen,
                        stop_at_reset=stop_at_reset,
                        seen_first_token=seen_first_token,
                    )
                continue

            m = _EQU_RE.match(line)
            if m:
                name, expr = m.group(1), m.group(2).strip()
                value = _try_eval_simple(expr)
                if value is not None:
                    out.append(Const(name=name, value=value))


def to_dict(consts: list[Const]) -> dict[str, int]:
    """Last definition wins (matches rgbasm semantics for `EQU`)."""
    return {c.name: c.value for c in consts}


def _strip_comment(line: str) -> str:
    semi = line.find(";")
    return line if semi < 0 else line[:semi]


def _to_int(s: str) -> int:
    s = s.strip()
    if s.startswith("$"):
        return int(s[1:], 16)
    if s.startswith("%"):
        return int(s[1:], 2)
    return int(s, 10)


def _try_eval_simple(expr: str) -> int | None:
    """Evaluate trivial integer expressions. Supports literals only; bails on
    anything involving symbols (those would require a fuller symbol table)."""
    expr = expr.strip()
    if not expr:
        return None
    try:
        return _to_int(expr)
    except ValueError:
        return None
