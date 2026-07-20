"""Allocating an event flag in a **bucketed** ``constants/event_flags.asm``.

An itemball that has no flag is an itemball the player can farm: the flag is
what remembers the ball was picked up, so the adder cannot skip it. But the
allocator prism already has (`hacks/prism/eventflags`) cannot read either family
tree's file — it raises on the first `const_def` it sees, and vanilla's is on
line 3. The two trees reserve headroom a different way, and vanilla partitions
its flag space besides:

    prism       one unbroken run + 807 `const skip` — a const literally *named*
                `skip`, redefined over and over, so a free slot is a named one
    vanilla     `const_def`, five internal `const_next` jumps, 40 `const_skip`
    polished    `const_def`, one `const_next`, 20 `const_skip`

`const skip` and `const_skip` are not the same thing and only one is a name.
`const_skip [N]` is a *directive* (`macros/const.asm`) that bumps the counter by
N and defines nothing — so it occupies slots without appearing as a flag, and a
parser that ignores it overcounts every bucket's headroom. Mine did, on the
first pass, and reported one free slot in a bucket the file itself documents as
full.

**The buckets.** `const_next N` jumps the counter forward to N, which leaves a
gap of deliberate headroom, and each gap is captioned in the file
(`; Unused: next 339 events`). Those captions are the oracle this module is
checked against — :func:`load` reproduces all six of vanilla's independently.
Flag values are save-file bit positions, so the gaps are the only place a new
flag can go: appending to the *file* would land past `const_next 2048` and
outside the array entirely.

Overflowing a bucket is at least loud. `const_next` fails the build rather than
letting the counter run backwards::

    fail "const_next cannot go backwards from {const_value} to \\1"

so the worst case is a broken build, not a renumbered save. This module refuses
before writing anyway, because a message naming the full bucket and the ones
with room beats a macro error naming a number.

**The captions are convention, not engine behaviour.** Vanilla groups itemball
flags under `; Sprite visibility flags` (1600-1899) and that bucket is full —
0 free, measured. It is tempting to read that as "no more itemballs", but
`CheckObjectFlag` (`engine/overworld/map_objects_2.asm`) reads the flag id out
of the object's own field and compares it against `-1` and nothing else; there
is no value-range test anywhere. The grouping is documentation. So
:meth:`allocate` prefers the conventional bucket and falls back to any bucket
with room, reporting which one it used rather than failing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ..shared.edits import Edit

_REL = "constants/event_flags.asm"
_INDENT = "\t"

_CONST = re.compile(r"^\s*const\s+([A-Za-z_]\w*)\s*(?:;.*)?$")
#: Numbers here are rgbds literals, and the bases are not decoration: vanilla
#: writes `const_next 2048` and polished writes `const_next $8ff`. A pattern of
#: `\w+` matches the first and not the second, which does not raise — it drops
#: polished's only bucket boundary and leaves the file looking like one run with
#: no headroom, so every allocation is refused for a reason that is not true.
_NUM = r"[-+]?[$%]?[0-9A-Fa-f_]+"
_CONST_DEF = re.compile(rf"^\s*const_def(?:\s+({_NUM}))?\s*(?:;.*)?$")
#: The directive the first pass of this module missed. The optional argument is
#: a repeat count, so `const_skip 4` costs four slots, not one.
_CONST_SKIP = re.compile(r"^\s*const_skip(?:\s+(\d+))?\s*(?:;.*)?$")
_CONST_NEXT = re.compile(rf"^\s*const_next\s+({_NUM})\s*(?:;.*)?$")
#: `; Unused: next 339 events` — the file's own headroom claim, which this
#: module checks itself against rather than trusting.
_CAPTION = re.compile(r"^;\s*Unused:\s*next\s+(\d+)\s+events?\b")
_NAME = re.compile(r"^[A-Za-z_]\w*$")


class FlagError(RuntimeError):
    """The flag file is not shaped the way this allocator can safely write to."""


def _to_int(s: str) -> int:
    s = s.strip()
    if s.startswith("$"):
        return int(s[1:], 16)
    if s.startswith("%"):
        return int(s[1:], 2)
    return int(s, 10)


@dataclass
class Bucket:
    """One run of flags between two `const_next` jumps, and the gap after it.

    `label` is the comment that captions the run in the file — it is what makes
    a message like "the Sprite visibility flags bucket is full" possible, and it
    is the only reason this module reads comments at all.
    """

    label: str
    start: int                  # first value in the run
    end: int | None             # value the next `const_next` jumps to
    used: int = 0               # slots consumed by `const` and `const_skip`
    last_line: int = 0          # index of the last line that consumed a slot
    claimed: int | None = None  # the `; Unused: next N events` caption, if any
    #: Where that caption sits, so allocating can decrement it. Consuming a slot
    #: without updating the caption leaves the file stating headroom it no
    #: longer has — and since `load` refuses on exactly that disagreement, an
    #: allocator that skipped this would write a file it could not read back.
    caption_line: int | None = None

    @property
    def free(self) -> int:
        return 0 if self.end is None else self.end - self.start - self.used

    @property
    def next_value(self) -> int:
        return self.start + self.used


@dataclass
class EventFlags:
    """A parsed bucketed flag file, and the edit that adds one flag to it."""

    path: Path
    rel: str
    lines: list[str]
    buckets: list[Bucket] = field(default_factory=list)
    _base: str = ""
    _eol: str = "\n"

    @property
    def names(self) -> set[str]:
        return {m.group(1) for ln in self.lines if (m := _CONST.match(ln))}

    def has(self, name: str) -> bool:
        return name in self.names

    def bucket(self, label: str) -> Bucket | None:
        for b in self.buckets:
            if b.label == label:
                return b
        return None

    def allocate(self, name: str, *, prefer: str = "") -> Bucket:
        """Add `name` to the preferred bucket, or to the first with room.

        Returns the bucket it landed in, so the caller can say where — an adder
        that silently puts a sprite-visibility flag among the Kanto people has
        done the right thing for the ROM and the wrong thing for the next person
        reading the file, and the difference is entirely in whether it said so.
        """
        if not _NAME.match(name):
            raise FlagError(f"{name!r} is not a valid flag name")
        if self.has(name):
            raise FlagError(
                f"{name} is already defined in {self.rel} — two names for one "
                "save bit is one of them silently shadowing the other")

        target = self.bucket(prefer) if prefer else None
        if target is None or target.free < 1:
            target = next((b for b in self.buckets if b.free > 0), None)
        if target is None:
            raise FlagError(
                f"every bucket in {self.rel} is full: "
                + ", ".join(f"{b.label} ({b.used}/{b.used + b.free})"
                            for b in self.buckets))

        # Update the caption before inserting: both indices come from the parse
        # and inserting first would shift the caption's line out from under us.
        if target.caption_line is not None and target.claimed is not None:
            self.lines[target.caption_line] = _caption_line(
                self.lines[target.caption_line], target.claimed - 1)
        self.lines.insert(target.last_line + 1, f"{_INDENT}const {name}")
        self._reparse()
        landed = self.bucket(target.label)
        assert landed is not None
        return landed

    def to_edit(self, detail: str) -> Edit:
        text = self._eol.join(self.lines)
        return Edit(self.rel, text != self._base, detail, text, base=self._base)

    def _reparse(self) -> None:
        self.buckets = _parse(self.lines, self.rel)


def _caption_line(old: str, n: int) -> str:
    """Rewrite `; Unused: next 6 events` to say `n`, keeping the file's own
    wording and pluralisation rather than imposing a house style on it."""
    return re.sub(r"(next\s+)\d+(\s+events?)",
                  lambda m: f"{m.group(1)}{n}"
                            f"{m.group(2) if n != 1 else ' event'}", old)


def _parse(lines: list[str], rel: str) -> list[Bucket]:
    buckets: list[Bucket] = []
    cur: Bucket | None = None
    counter = 0
    caption: int | None = None
    caption_at: int | None = None

    for i, ln in enumerate(lines):
        if m := _CONST_DEF.match(ln):
            counter = _to_int(m.group(1)) if m.group(1) else 0
            cur = Bucket("(start)", counter, None, last_line=i)
            buckets.append(cur)
            caption, caption_at = None, None
            continue
        if m := _CONST_NEXT.match(ln):
            target = _to_int(m.group(1))
            if cur is not None:
                cur.end = target
                cur.claimed, cur.caption_line = caption, caption_at
                if target < cur.next_value:
                    raise FlagError(
                        f"{rel}:{i + 1}: const_next {target} is behind the "
                        f"counter ({cur.next_value}) — this file does not "
                        "assemble as it stands")
            counter = target
            # The line after the jump captions the new run.
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            label = nxt.lstrip(";").strip() if nxt.lstrip().startswith(";") \
                else f"@{target}"
            cur = Bucket(label, counter, None, last_line=i)
            buckets.append(cur)
            caption, caption_at = None, None
            continue
        if m := _CAPTION.match(ln.strip()):
            caption, caption_at = int(m.group(1)), i
            continue
        if _CONST.match(ln):
            if cur is None:
                raise FlagError(f"{rel}:{i + 1}: a const before any const_def")
            cur.used += 1
            cur.last_line = i
            counter += 1
            continue
        if m := _CONST_SKIP.match(ln):
            n = int(m.group(1)) if m.group(1) else 1
            if cur is None:
                raise FlagError(f"{rel}:{i + 1}: a const_skip before any const_def")
            cur.used += n
            cur.last_line = i
            counter += n

    if cur is not None and cur.end is None:
        cur.claimed, cur.caption_line = caption, caption_at
    return buckets


def load(root: Path, rel: str = _REL) -> EventFlags:
    """Parse a tree's flag file, and check the parse against the file's own
    headroom captions.

    The captions are the closest thing to an independent oracle this file has:
    they were written by hand and they say what the gaps are. Reproducing all of
    them is what caught the missing `const_skip` — six captions agreed with each
    other and disagreed with me.
    """
    path = root / rel
    if not path.exists():
        raise FlagError(f"{path} not found")
    base = path.read_text()
    lines = base.split("\n")
    buckets = _parse(lines, rel)
    if not buckets:
        raise FlagError(f"{rel} has no const_def — is this a flag enum?")

    for b in buckets:
        if b.claimed is not None and b.end is not None and b.claimed != b.free:
            raise FlagError(
                f"{rel}: the {b.label!r} bucket says '; Unused: next "
                f"{b.claimed} events' but {b.free} slots are actually free. "
                "One of the two is wrong and this allocator will not guess "
                "which — a flag written on a bad count lands on a used bit.")
    return EventFlags(path=path, rel=rel, lines=lines, buckets=buckets,
                      _base=base)
