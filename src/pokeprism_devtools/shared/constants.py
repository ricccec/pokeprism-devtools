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
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class Const:
    name: str
    value: int


def as_int(s: str) -> int | None:
    """The number an argument denotes — decimal, `$hex`, `%binary` — or None if it
    is a symbol or an expression.

    Public because "is this the same number, written differently?" is a question
    anyone *rewriting* an entry must ask, and `int(s, 0)` cannot answer it: rgbasm
    spells hex `$b`, not `0xb`, and two thirds of prism's warps are written that
    way. An editor that got this wrong would reformat the lot.

    Shared rather than prism's, because it is rgbasm's syntax and not any one
    dialect's: every gen-2 tree writes its numbers this way, so every adapter and
    every piece of `wiring/` may read them without importing a hack to do it.
    """
    s = s.strip()
    try:
        if s.startswith("$"):
            return int(s[1:], 16)
        if s.startswith("%"):
            return int(s[1:], 2)
        return int(s, 10)
    except ValueError:
        return None


#: `const NAME`, `NAME EQU x`, `NAME = x`, `NAME EQUS "…"` — every way a name is
#: bound at file scope. Values are irrelevant to :func:`names`; only existence is.
_NAME_RE = re.compile(r"^\s*const\s+([A-Za-z_]\w*)\s*(?:;.*)?$")
#: The optional `DEF` is modern rgbds and is not decoration: polished writes
#: `DEF PAL_NPC_DEFAULT EQU 0` where prism writes `NAME EQU 0`, so without it a
#: real constant goes unread. Still anchored hard at column zero, because these
#: are *file-scope* bindings — the same spelling indented is a macro body, where
#: the name is `PAL_NPC_\1` and reading it yields the fragment `PAL_NPC_`.
_DEF_RE = re.compile(r"^(?:DEF\s+)?([A-Za-z_]\w*)\s+(?:EQU|EQUS|=)\s")


@dataclass(frozen=True)
class ConstSet:
    """Where one set of constants lives, and how this tree spells it.

    Declared by each write adapter, read by :func:`read_set`, so that "which
    file, which prefix, which spelling" crosses the seam as data — the same
    shape `wiring/warpdel.WarpGrammar` takes, and for the same reason.

    `macro` is the part a survey had to find rather than assume. Most trees
    write a set as plain `const PAL_OW_RED` lines. Polished writes its
    overworld palettes as `ow_npc_pal_const RED`, a macro that pastes the
    prefix on at assembly time — so the names *do not appear in the source at
    all*, and a scan for `const PAL_OW_` finds only the macro's own body and
    reports an empty set with a straight face. That is the worst kind of wrong
    here: an empty list is indistinguishable from "this field is free text", so
    the palette box would have quietly stopped suggesting anything on exactly
    one of the three trees.
    """
    rel: str
    prefix: str = ""
    #: A macro whose single argument names the constant, `prefix` pasted on.
    #: Empty means the names are written out as `const` lines.
    macro: str = ""


@lru_cache(maxsize=64)
def read_set(root: Path, cs: ConstSet) -> tuple[str, ...]:
    """Every name in one declared set, sorted. Empty for a file that isn't there,
    which is an answer — a tree without the file has none of that thing."""
    path = root / cs.rel
    if not path.exists():
        return ()
    found = {n for n in names(root, cs.rel) if n.startswith(cs.prefix)}
    if cs.macro:
        # Union, not replacement: a file that generates most of a set through a
        # macro may still spell one member out longhand, and polished's
        # `DEF PAL_NPC_DEFAULT EQU 0` is exactly that member.
        pat = re.compile(rf"^\s*{re.escape(cs.macro)}\s+([A-Za-z_]\w*)\s*(?:;.*)?$")
        found |= {cs.prefix + m.group(1)
                  for line in path.read_text(errors="replace").split("\n")
                  if (m := pat.match(line))}
    return tuple(sorted(found - _purged(path)))


def _purged(path: Path) -> frozenset[str]:
    """Names this file hands back to the assembler with `PURGE`.

    A small thing that would have shipped a wrong list: polished's
    `sprite_data_constants.asm` ends with `PURGE PAL_OW_YELLOW, PAL_OW_WHITE`,
    so those two symbols do not survive the file that appears to define them.
    Offering a constant the assembler will then reject is the one failure
    `studio/offers.py` calls worse than offering no list at all.
    """
    out: set[str] = set()
    for line in path.read_text(errors="replace").split("\n"):
        if m := re.match(r"^\s*PURGE\s+(.+?)\s*(?:;.*)?$", line):
            out |= {n.strip() for n in m.group(1).split(",") if n.strip()}
    return frozenset(out)


@lru_cache(maxsize=32)
def names(root: Path, rel: str) -> frozenset[str]:
    """Every constant name defined in one constants file.

    Shared rather than any adapter's, for the reason `as_int` is: this is rgbasm
    binding a name at file scope, and every gen-2 tree does it the same way. What
    differs per tree is *which file and which prefix*, which is why those are a
    :class:`ConstSet` an adapter declares and not an argument baked in here.
    """
    path = root / rel
    if not path.exists():
        return frozenset()

    out: set[str] = set()
    for line in path.read_text(errors="replace").split("\n"):
        if m := _NAME_RE.match(line):
            out.add(m.group(1))
        elif m := _DEF_RE.match(line):
            out.add(m.group(1))
    return frozenset(out)


def with_prefix(root: Path, rel: str, prefix: str) -> frozenset[str]:
    return frozenset(n for n in names(root, rel) if n.startswith(prefix))


def suggest(name: str, known: frozenset[str], limit: int = 3) -> list[str]:
    """The closest few real names, for an error message that helps."""
    import difflib
    return difflib.get_close_matches(name, known, n=limit, cutoff=0.6)


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
