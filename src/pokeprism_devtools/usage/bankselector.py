"""Bank numbers as they are typed on the command line.

A bank is written four ways in this codebase — `23`, `$17`, `0x17`, and bare
`17` meaning hex when it contains a hex digit — so the token `17` is ambiguous
by design and resolves to decimal. Ranges are inclusive and accept their ends in
either order.
"""

from __future__ import annotations


def _parse_bank_number(raw: str) -> int:
    if raw.startswith("$"):
        return int(raw[1:], 16)
    if raw.lower().startswith("0x"):
        return int(raw, 16)
    if any(c in "abcdefABCDEF" for c in raw):
        return int(raw, 16)
    return int(raw, 10)


def _parse_bank_selector(raw: str) -> list[int]:
    """A single CLI token: one bank number, or an inclusive range 'A-B'."""
    lo_s, sep, hi_s = raw.partition("-")
    if sep and lo_s and hi_s:
        lo, hi = _parse_bank_number(lo_s), _parse_bank_number(hi_s)
        if lo > hi:
            lo, hi = hi, lo
        return list(range(lo, hi + 1))
    return [_parse_bank_number(raw)]


def parse_bank_selectors(tokens: list[str]) -> list[int]:
    """Expand CLI tokens (numbers and/or 'A-B' ranges) into a sorted, deduped list."""
    numbers: set[int] = set()
    for tok in tokens:
        try:
            numbers.update(_parse_bank_selector(tok))
        except ValueError:
            raise ValueError(f"invalid bank number/range {tok!r}") from None
    return sorted(numbers)
