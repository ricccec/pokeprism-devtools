"""Taking content back out of a map — the half of it that is safe.

Adding is easy to make safe because appending disturbs nothing. Removing is not
symmetric: the things a map's content hangs off are reached by *position*, and
deleting one shifts everything below it.

Three of the four pieces come out cleanly:

    the person_event / signpost   an entry in a counted list; delete and fix the count
    the script or text block      a span of lines nothing else points at
    the event flag                rewritten to `const skip`, NOT deleted — see below

The fourth, a **trainer's party**, does not, and this module will not touch it.
Parties are 1-based ordinals into ``trainers/groups/<class>.asm`` (see
:mod:`..hacks.prism.trainercite`), so deleting one re-teams every trainer below it in
the group. What you get instead is a warning that the party is now an orphan,
and the linter's ``trainer-orphan`` will keep saying so until someone deals with
it deliberately.

The flag is the subtle one. Deleting a ``const EVENT_FOO`` line would renumber
every flag after it, and flag values are *save-file bit positions* — that
invalidates every existing save. So it is rewritten back to ``const skip``,
which returns the slot to the reserve and holds every other flag exactly where
it was.

Nothing is freed that anything else still uses: both the flag and the script
block are checked against the whole repo first, and left alone if anyone else
refers to them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ..hacks.prism import eventflags, eventheader as eh, mapsource, trainercite
from ..shared.edits import Edit

#: A person_event's flag argument when the object is unconditional.
_NO_FLAG = {"-1", "0"}

#: Files that *declare* names rather than use them. A flag's own `const EVENT_FOO`
#: line is not a reason to keep it allocated — it is the thing being freed.
_DECLARATIONS = {"constants/event_flags.asm"}

_LABEL_RE = re.compile(r"^(\w+):")
_HIDDEN_FLAG_RE = re.compile(r"^\s*dw\s+(EVENT_\w+)")
_TRAINER_RE = re.compile(r"^\s*trainer\s+(\w+)\s*,\s*(\w+)\s*,\s*(\w+)\s*,")
_EVENT_RE = re.compile(r"\bEVENT_\w+")


class RemovalError(RuntimeError):
    pass


def _own_flag(entry: eh.Entry) -> str | None:
    """The flag an entry carries itself. Only a person_event does — a signpost's
    last argument is its pointer, not a flag.

    Three people in this repo write it as an *expression* — `EVENT_X | $8000`,
    the engine's visibility bit — so what comes back is the flag's **name**, not
    the whole argument. The allocator has to find the thing in `event_flags.asm`,
    and there is no `const EVENT_X | $8000` in there to find. (The argument itself
    is not rewritten: the line it sits on is the line being deleted.)
    """
    if entry.macro != "person_event":
        return None
    flag = entry.event_flag.strip()
    if flag in _NO_FLAG:
        return None
    m = _EVENT_RE.search(flag)
    return m.group(0) if m else flag


@dataclass
class Removal:
    summary: str
    edits: list[Edit] = field(default_factory=list)
    freed_flag: str | None = None
    removed_label: str | None = None
    #: Things the caller must decide about, because this module won't guess.
    warnings: list[str] = field(default_factory=list)

    @property
    def changes(self) -> list[Edit]:
        return [e for e in self.edits if e.changed]


def remove(root: Path, map_const: str, *, label: str | None = None,
           flag: str | None = None, at: tuple[int, int] | None = None,
           index: int | None = None, kind: eh.ListKind | None = None) -> Removal:
    """Take one object out of a map, named however you can name it.

    Identify it by its `index` in the list `kind` — which is exact — or, when
    that is not what you have, by the script `label` it points at, by its event
    `flag`, or by its position `at` (y, x). Exactly one object must match; two is
    an error rather than a guess.

    **Prefer `index`.** The other three are *descriptions*, and a description need
    not be unique: Owsauri's game corner has sixteen slot machines running the one
    script, Saffron Gates has eight guards, and none of them can be named apart.
    The studio never has to guess, because you did not describe the thing you want
    gone — you pointed at it, and a `Ref` carries the list and the position.

    `kind` alone narrows the other three to one list, and the caller should pass it
    whenever it knows: a name is only unique *within* a list. CaperRidge has a
    trigger and an NPC that run the same script, so without it, naming either by
    its label matches both and neither can be deleted.
    """
    ctx = _Target(root, map_const, label=label, flag=flag, at=at,
                  index=index, kind=kind)
    edits: list[Edit] = []
    warnings: list[str] = []

    # The party, if this was a trainer, outlives the trainer. Say so.
    party = ctx.trainer_party()
    if party:
        cls, ordinal = party
        warnings.append(
            f"{cls} party #{ordinal} is left in place and will now be an orphan. "
            f"Deleting it would renumber every party below it in that group and "
            f"re-team every trainer citing them, so it is not done automatically."
        )

    ctx.drop_entry()
    if ctx.block_label and ctx.block_private:
        ctx.drop_block()
    elif ctx.block_label:
        warnings.append(f"{ctx.block_label} is referenced elsewhere — left in place.")
    edits.append(ctx.to_edit())

    freed = None
    if ctx.flag and ctx.flag_private:
        flags = eventflags.load(root)
        if ctx.flag in flags.by_name:
            slot = flags.free(ctx.flag)
            edits.append(flags.to_edit(
                root, f"{ctx.flag} -> const skip (slot {slot.value})"))
            freed = ctx.flag
        else:
            # An object can name a flag that was never allocated — `EVENT_0` is
            # spelled like one and isn't one. There is no slot to give back, and
            # the deletion is not the moment to argue about it.
            warnings.append(f"{ctx.flag} is not allocated in constants/event_flags.asm, "
                            f"so there is no slot to give back — left alone.")
    elif ctx.flag:
        warnings.append(f"{ctx.flag} still gates something else — left allocated.")

    return Removal(f"removed {ctx.describe()} from {map_const}",
                   edits, freed, ctx.block_label if ctx.dropped_block else None,
                   warnings)


class _Target:
    """The one object being removed, and everything hanging off it."""

    def __init__(self, root: Path, map_const: str, *, label: str | None,
                 flag: str | None, at: tuple[int, int] | None,
                 index: int | None = None, kind: eh.ListKind | None = None) -> None:
        if sum(x is not None for x in (label, flag, at, index)) != 1:
            raise RemovalError(
                "name the object by exactly one of index=, label=, flag= or at=")
        if index is not None and kind is None:
            raise RemovalError("index= is a position in a list, so it needs kind= too")

        self.want = kind
        self.root = root
        self.const = map_const
        self.dropped_block = False

        map_label = {c: l for l, c in mapsource.header_pairs(root)}.get(map_const)
        if map_label is None:
            raise RemovalError(f"{map_const} has no map_header_2")
        self.map_label = map_label
        self.path = root / "maps" / f"{map_label}.asm"
        self.rel = f"maps/{map_label}.asm"
        self._original = self.path.read_text()
        self.header = eh.parse_map(self.path)

        self.kind, self.index, self.entry = self._locate(label, flag, at, index)
        self.block_label = self._block_label()
        self.flag = self._flag()

        # Both of these read line numbers, and every mutation below invalidates
        # them. Settle the questions while the file is still the file we parsed.
        self.block_private = not self._referenced_elsewhere(self.block_label)
        self.flag_private = not self._referenced_elsewhere(self.flag)

    # -- finding it --------------------------------------------------------- #
    #: The lists this module will take an entry out of. Warps are not among them:
    #: a warp is a *position* other maps count to, so removing one renumbers the
    #: repo — see :mod:`.warpdel`, which is a different operation with a different
    #: blast radius, not a special case of this one.
    _LISTS = (eh.ListKind.OBJECT_EVENTS, eh.ListKind.BG_EVENTS,
              eh.ListKind.COORD_EVENTS)

    def _locate(self, label, flag, at, index):
        if index is not None:
            if self.want not in self._LISTS:
                raise RemovalError(f"{self.want.value} is not a list this removes from")
            entries = self.header.list_of(self.want).entries
            if not 0 <= index < len(entries):
                raise RemovalError(
                    f"{self.const}'s {self.want.value} has {len(entries)} entries, "
                    f"so there is no #{index + 1} to remove")
            return self.want, index, entries[index]

        hits = []
        for kind in self._LISTS:
            if self.want is not None and kind is not self.want:
                continue
            for i, entry in enumerate(self.header.list_of(kind).entries):
                if self._matches(entry, label, flag, at):
                    hits.append((kind, i, entry))

        named = label or flag or f"({at[0]}, {at[1]})"
        if not hits:
            raise RemovalError(f"{self.const} has no object matching {named}")
        if len(hits) > 1:
            where = ", ".join(f"{k.value}[{i}]" for k, i, _ in hits)
            raise RemovalError(
                f"{named} matches {len(hits)} objects in {self.const} ({where}) — "
                f"name it unambiguously"
            )
        return hits[0]

    def _matches(self, entry: eh.Entry, label, flag, at) -> bool:
        if label is not None:
            return entry.pointer == label
        if flag is not None:
            return _own_flag(entry) == flag or self._hidden_flag(entry) == flag
        return entry.coords == at

    # -- what hangs off it -------------------------------------------------- #
    def _block_label(self) -> str | None:
        """The script/text label this object points at, if it's defined here.

        An item ball's 'pointer' is an item const, not a label, so this correctly
        finds nothing for one.
        """
        pointer = self.entry.pointer
        return pointer if pointer and self._defines(pointer) else None

    def _flag(self) -> str | None:
        """The event flag this object owns — which lives in one of three places.

        An NPC or item ball carries it in the person_event's last argument. A
        hidden item doesn't: it sits in the record the signpost points at
        (``dw EVENT_…``). And a *trainer* doesn't either — its person_event says
        ``-1``, because the flag that remembers you beat him is the first
        argument of the ``trainer`` macro in his script block.
        """
        return (_own_flag(self.entry)
                or self._hidden_flag(self.entry)
                or self._trainer_flag(self.entry))

    def _hidden_flag(self, entry: eh.Entry) -> str | None:
        return self._flag_in_block(entry, _HIDDEN_FLAG_RE)

    def _trainer_flag(self, entry: eh.Entry) -> str | None:
        return self._flag_in_block(entry, _TRAINER_RE)

    def _flag_in_block(self, entry: eh.Entry, pattern: re.Pattern) -> str | None:
        pointer = entry.pointer
        if not pointer or not self._defines(pointer):
            return None
        for line in self._block(pointer):
            if m := pattern.match(line):
                return m.group(1)
        return None

    def trainer_party(self) -> tuple[str, int] | None:
        """The (class, ordinal) this object's trainer macro cites, if any."""
        if not self.block_label:
            return None
        consts = trainercite.party_consts(self.root)
        for line in self._block(self.block_label):
            if m := _TRAINER_RE.match(line):
                cls, written = m.group(2), m.group(3)
                if written.isdigit():
                    return cls, int(written)
                entry = consts.get(written)
                return (cls, entry[1]) if entry else None
        return None

    # -- is anyone else using it? ------------------------------------------- #
    def _referenced_elsewhere(self, name: str | None) -> bool:
        """Whether `name` is mentioned anywhere in the repo's asm, ignoring the
        entry and block we are about to remove.

        Deliberately conservative: a flag shared between two maps is a real thing
        in this repo (see maplint's `flag-shared`), and freeing it would let the
        allocator hand it out to a third party while the second still reads it.
        """
        if not name:
            return False

        wanted = re.compile(rf"\b{re.escape(name)}\b")
        block = set(self._block_span(self.block_label)) if self.block_label else set()
        block.add(self.entry.lineno)

        for path in sorted(self.root.rglob("*.asm")):
            if path.relative_to(self.root).as_posix() in _DECLARATIONS:
                continue                           # where the name is *defined*, not used
            lines = path.read_text().split("\n")
            for i, line in enumerate(lines):
                if path == self.path and i in block:
                    continue                       # the lines we're deleting
                if wanted.search(line.split(";")[0]):
                    return True
        return False

    # -- edits -------------------------------------------------------------- #
    def drop_entry(self) -> None:
        self.header.remove_entry(self.kind, self.index)

    def drop_block(self) -> None:
        span = self._block_span(self.block_label)
        if not span:
            return
        lo, hi = span[0], span[-1]
        # Take the blank line that separated it from the next block, so removing
        # doesn't leave a growing gap behind.
        while hi + 1 < len(self.header.lines) and not self.header.lines[hi + 1].strip():
            hi += 1
        del self.header.lines[lo:hi + 1]
        self.header.reparse()
        self.dropped_block = True

    def to_edit(self) -> Edit:
        text = self.header.to_text()
        return Edit(self.rel, text != self._original, f"removed {self.describe()}",
                    text, base=self._original)

    def describe(self) -> str:
        what = self.block_label or self.entry.pointer or self.entry.macro
        y, x = self.entry.coords
        return f"{what} at ({y}, {x})"

    # -- the file ----------------------------------------------------------- #
    def _defines(self, label: str) -> bool:
        return any(_LABEL_RE.match(ln) and ln.startswith(f"{label}:")
                   for ln in self.header.lines)

    def _block_span(self, label: str | None) -> list[int]:
        """The lines of `label`'s block: from its definition to just before the
        next top-level label. Local `.foo` labels inside it come along, which is
        what makes a trainer's three texts travel with its macro."""
        if not label:
            return []
        lines = self.header.lines
        start = next((i for i, ln in enumerate(lines) if ln.startswith(f"{label}:")), None)
        if start is None:
            return []

        end = start + 1
        while end < len(lines):
            m = _LABEL_RE.match(lines[end])
            if m and not lines[end].startswith("."):
                break                              # the next top-level label
            end += 1
        while end > start + 1 and not lines[end - 1].strip():
            end -= 1                               # don't swallow the trailing blank yet
        return list(range(start, end))

    def _block(self, label: str) -> list[str]:
        return [self.header.lines[i] for i in self._block_span(label)]
