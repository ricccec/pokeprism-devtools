"""The validators the prompts share.

A questionary prompt validates its own answer, and more than one editor asks for
a bounded integer — a level, a quantity, a coord, a badge byte. One home for the
message they all give back.
"""

from __future__ import annotations


def _int_in(lo: int, hi: int):

    def _validate(s: str):
        try:
            v = int(s)
        except ValueError:
            return "not an integer"
        if not (lo <= v <= hi):
            return f"must be {lo}..{hi}"
        return True
    return _validate
