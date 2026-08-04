"""Where in a family map file a block goes — the three regions, and their order.

Every write Phase 8 needs is "put these lines in the right part of this file",
and a family map file has three parts. `add_entry` already handles one of them
(the event lists); this module is the other two, and the reason it exists as
mechanism rather than a helper is that **the parts are not in the same order in
the two trees.**

    vanilla     SCRIPTS -> TEXTS -> EVENTS
    polished    EVENTS  -> SCRIPTS -> TEXTS

Measured, not assumed: of the 331 vanilla maps that have a text block, 331 put
their texts before the event header; of polished's 461, all 461 put them after.
Zero exceptions in either tree, and the two trees never agree. So the order is
declared data (:class:`Layout`), the same way `MapShape` declares the dimension
macro's argument order.

The cost of getting this wrong is why it is measured rather than reasoned. A
writer that appends a text block "just before the event header" is correct in
vanilla and, in polished, splices into the middle of the warp list — where it
lands between two `warp_event` lines that the header counts by position. It
would assemble. The map would simply have the wrong doors.

Two more things that look like they should be one thing and are not:

* **The event header is split in vanilla.** `def_scene_scripts` and
  `def_callbacks` open the file; `def_warp_events` through `def_object_events`
  close it, a couple of hundred lines later. Only the second half is the EVENTS
  region. A boundary probe that matches the first `def_*` it sees mislocates
  792 of the 995 files — it is the first mistake this module's survey made.
* **A region can be empty and still exist.** 57 vanilla maps and 146 polished
  ones have no text block at all. That is not a missing region: it is a region
  with nothing in it yet, and the first text written to such a map has to
  *create* it at the boundary the layout names. An empty region that reports
  itself as absent would send that first block to the end of the file.

This module locates and splices. It does not know what a trainer is.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..shared.edits import Edit

#: The three parts of a family map file, in no particular order — see `Layout`.
SCRIPTS, TEXTS, EVENTS = "scripts", "texts", "events"
REGIONS = (SCRIPTS, TEXTS, EVENTS)

#: The event header's closing half. `def_scene_scripts`/`def_callbacks` are the
#: *opening* half and deliberately not here: in vanilla they sit at the top of
#: the file, hundreds of lines from these four.
_EVENT_OPEN = re.compile(r"^\s*def_warp_events\b")
_EVENT_LAST = re.compile(r"^\s*def_object_events\b")

#: A label at column zero. Local labels (`.AfterScript`) are deliberately not
#: matched: they belong to the block above them and are never a region start.
_LABEL = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):")

#: What makes a labelled block a *text* block rather than a script one. This is
#: the only way to tell them apart — the label naming convention is a habit
#: (`FooText`), not a rule, and 3 vanilla maps break it.
_TEXTLINE = re.compile(r"^\s*(text|rawchar|text_far|text_ram|text_start)\b")


class RegionError(RuntimeError):
    """The file does not have the shape the layout says it has."""


@dataclass(frozen=True)
class Layout:
    """One tree's answer to "which part comes first".

    `order` is the three region names, outermost first. It is the whole fork:
    everything else in this module is the same for both trees.
    """

    order: tuple[str, str, str]

    def __post_init__(self) -> None:
        if tuple(sorted(self.order)) != tuple(sorted(REGIONS)):
            raise RegionError(
                f"a layout names each region exactly once, got {self.order}")

    @property
    def texts_first(self) -> bool:
        """Do the texts precede the event header? Vanilla yes, polished no."""
        return self.order.index(TEXTS) < self.order.index(EVENTS)


#: The two trees, measured. Named rather than inlined so a reader can see that
#: the difference is exactly one thing.
VANILLA = Layout((SCRIPTS, TEXTS, EVENTS))
POLISHED = Layout((EVENTS, SCRIPTS, TEXTS))


@dataclass(frozen=True)
class Span:
    """Half-open line range `[start, end)` of one region, plus whether it has
    anything in it. An empty span still has a position — that position is where
    the first block goes."""

    name: str
    start: int
    end: int
    empty: bool

    @property
    def lines(self) -> int:
        return self.end - self.start


def _first_text_label(lines: list[str], lo: int, hi: int) -> int | None:
    """Line of the first label in `[lo, hi)` whose block opens with text."""
    for i in range(lo, min(hi, len(lines))):
        if not _LABEL.match(lines[i]):
            continue
        j = i + 1
        while j < len(lines) and not lines[j].strip():
            j += 1
        if j < len(lines) and _TEXTLINE.match(lines[j]):
            return i
    return None


def spans(text: str, layout: Layout) -> dict[str, Span]:
    """Locate all three regions in one map file.

    The event header is found by its macros, which are unambiguous. The
    scripts/texts boundary is found by the first text block, because there is no
    macro that marks it — and when there is no text block at all, the boundary
    is the far edge of the scripts region, which is what makes the empty TEXTS
    span land in the right place.
    """
    lines = text.splitlines()
    n = len(lines)

    open_i = last_i = None
    for i, ln in enumerate(lines):
        if open_i is None and _EVENT_OPEN.match(ln):
            open_i = i
        if _EVENT_LAST.match(ln):
            last_i = i
    if open_i is None or last_i is None:
        raise RegionError(
            "no event header here — expected def_warp_events and "
            "def_object_events; is this a map file?")

    # The events region runs from the *label* that introduces it to the end of
    # the last list — not from `def_warp_events`. In vanilla, `Foo_MapEvents:`
    # and a `db 0, 0 ; filler` sit between the two, and a TEXTS region that
    # ended at the macro would splice new text between the label and the warp
    # list it introduces. That assembles. The header then reads text bytes as
    # its first warp.
    ev_start = _block_start(lines, open_i)
    ev_end = _list_end(lines, last_i)
    events = Span(EVENTS, ev_start, ev_end, empty=False)

    # Scripts and texts share whatever is left, on one side of the header.
    if layout.texts_first:
        lo, hi = _header_end(lines), ev_start    # both live above the header
    else:
        lo, hi = ev_end, n                       # both live below it

    cut = _first_text_label(lines, lo, hi)
    if cut is None:
        # No texts yet. The region exists with zero lines, at the far edge —
        # which for vanilla is just before the header and for polished is EOF.
        cut = hi
    return {
        SCRIPTS: Span(SCRIPTS, lo, cut, empty=cut <= lo),
        TEXTS: Span(TEXTS, cut, hi, empty=cut >= hi),
        EVENTS: events,
    }


def _block_start(lines: list[str], i: int) -> int:
    """Walk back from a macro line to the top-level label that introduces it.

    Everything between the label and the macro belongs with them — in vanilla
    that is the `db 0, 0 ; filler` byte pair, which is part of the event header
    and not part of the texts above it.
    """
    j = i - 1
    while j >= 0:
        ln = lines[j]
        if not ln.strip() or ln[:1] in (" ", "\t"):
            j -= 1
            continue
        if _LABEL.match(ln):
            return j
        break                                   # some other top-level thing
    return i


def _header_end(lines: list[str]) -> int:
    """Line after the opening half of the event header (`def_scene_scripts`,
    `def_callbacks` and their entries). Vanilla only — in polished the whole
    header is one block and this returns 0, which is correct there because the
    scripts region starts after the EVENTS span instead."""
    last = 0
    for i, ln in enumerate(lines):
        if re.match(r"^\s*def_(scene_scripts|callbacks)\b", ln):
            last = _list_end(lines, i)
    return last


def _list_end(lines: list[str], start: int) -> int:
    """End of the macro list opened at `start`: the def_ line plus the indented
    entries under it, stopping at the first line that is neither."""
    i = start + 1
    while i < len(lines):
        ln = lines[i]
        if not ln.strip():                      # a blank line may be interior
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines) and _entry(lines[j]):
                i = j
                continue
            return i
        if not _entry(ln):
            return i
        i += 1
    return len(lines)


def _entry(line: str) -> bool:
    """An indented macro entry — a list item, not a new top-level thing."""
    return bool(line[:1] in (" ", "\t") and line.strip()
                and not line.lstrip().startswith(";"))


def append(root: Path, rel: str, region: str, block: list[str], *,
           layout: Layout, detail: str = "") -> Edit:
    """Add `block` at the end of one region, returning a whole-file Edit.

    Appending rather than inserting is deliberate and is the same reasoning
    `asmedit/mapnew` uses for the parallel arrays: the event lists are counted by
    position, so anything that shifts an existing entry renumbers it. Texts and
    scripts are addressed by label and do not care where they sit — but they
    share a file with the lists that do, so a splice that is merely "somewhere
    in the right region" is not good enough. The end of the region is the one
    place that moves nothing above it.
    """
    text = (root / rel).read_text()
    out = spliced(text, region, block, layout=layout)
    return Edit(path=rel, changed=out != text, base=text, new_text=out,
                detail=detail or f"{len(block)} lines into {region}")


def spliced(text: str, region: str, block: list[str], *,
            layout: Layout) -> str:
    """:func:`append`'s answer as *text*, for a caller with more than one write
    to make to the same file.

    Adding an item ball is two writes to one map file — this block, and the
    `object_event` line pointing at it — and they cannot be two
    :class:`~.edits.Edit`s. An `Edit` carries the whole file plus the text it
    was derived from, and `apply_edits` refuses the second of two edits built
    off the same base rather than let one silently drop the other. That refusal
    is right and this is the way past it: splice the block in memory, hand the
    result to the parser that adds the entry line, and let the *entry* writer
    produce the single Edit whose base is still what is on disk.
    """
    found = spans(text, layout)
    if region not in found:
        raise RegionError(f"no region named {region!r}")
    at = found[region]
    lines = text.splitlines()

    # Both trees separate top-level blocks with exactly one blank line, so the
    # splice normalises rather than just inserting: it absorbs whatever run of
    # blanks already sits at the end of the region and re-emits one. Inserting
    # naively leaves a double gap above the block and none below it, which is
    # not a correctness problem but shows up in every diff the user reads.
    head = lines[:at.end]
    while head and not head[-1].strip():
        head.pop()

    body = [ln for ln in block]
    while body and not body[-1].strip():
        body.pop()

    tail = lines[at.end:]
    new = head + ([""] if head else []) + body + ([""] if tail else []) + tail
    out = "\n".join(new)
    if text.endswith("\n"):
        out += "\n"
    return out
