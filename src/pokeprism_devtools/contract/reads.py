"""What the studio may ask a mounted tree, and the one way it may be told no.

The read half of the contract. Everything here is asked of `Hack.reads`.
"""

from __future__ import annotations


class Unreadable(RuntimeError):
    """An adapter's answer when a map's source cannot be read into records —
    the event block doesn't fit its shape, the blocks file is missing. The
    message is the interesting part: it is what the view shows in place of the
    tables, so it should name the file and the way it disappointed."""
