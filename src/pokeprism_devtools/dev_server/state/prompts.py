"""The validators the prompts share.

A questionary prompt validates its own answer, and more than one editor asks for
a bounded integer — a level, a quantity, a coord, a badge byte. One home for the
message they all give back.
"""

from __future__ import annotations


def make_int_range_validator(lo: int, hi: int):
    """A `validate=` for a questionary prompt that will take `lo..hi` and
    nothing else. It builds the check rather than being one, which is what the
    old name (`_int_in`) read as and was not."""

    def _validate(s: str):
        try:
            v = int(s)
        except ValueError:
            return "not an integer"
        if not (lo <= v <= hi):
            return f"must be {lo}..{hi}"
        return True
    return _validate
