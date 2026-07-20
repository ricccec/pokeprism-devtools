"""Where a new map's blobs go, and the three different questions that is.

A new map is several kilobytes of data that has to end up *somewhere* in a ROM
made of 16 KiB banks, and the three trees do not disagree about the answer so
much as about the question. Prism asks "which bank?". Vanilla asks "which of
these buckets?". Polished asks "which bucket?" for the script and does not ask
at all for the blocks, because there every map gets a section of its own.

So placement has three **shapes**, and which shape applies is a property of the
*blob*, not of the tree — polished uses two of them at once:

``PIN``   name a bank, or leave it blank and let the linker place the section.
          Prism, whose `mapfit` packer measures the blobs and pins what it
          chose in `contents/romx.link`.
``JOIN``  append into a section that already exists, inheriting whatever bank
          that section has. Vanilla's 25 `Map Scripts N` and 3 `Map Blocks N`;
          polished's 119 thematic script sections.
``MINT``  give the blob a section of its own, named from the map's label by a
          convention the tree already follows. Polished's blocks:
          `<Label>_BlockData`, 436 of them, one per map.

This is what the plan's earlier model was one shape short of. "The choices a
tree offers become a form field exactly when they exist" describes ``JOIN``
perfectly and cannot express ``MINT``, because minting has no list to choose
from — the answer does not exist until the map does.

Pinned is not a spelling of "in an asm file"
--------------------------------------------
Neither family tree writes a bank into its `SECTION` lines: all 436 of
polished's and all 28 of vanilla's are a bare ``SECTION "name", ROMX``. The
pinning lives in the **link script**, `layout.link`, which names sections under
a bank heading, and it is the reason vanilla's buckets behave like fixed
addresses while polished's minted sections float. Measured: vanilla pins all 25
script and all 3 block sections; polished pins 11 of its 119 script sections and
essentially none of its blockdata. A reader that looked only at the asm would
conclude, wrongly, that nothing in either tree is pinned.

What follows from that, and is a note rather than a check: joining a *pinned*
bucket puts the blob in a bank someone already decided is full enough to name,
so the failure mode is `rgblink` overflowing that specific bank. Knowing whether
it will means measuring the section, and measuring means building — minutes,
not keystrokes, which is the same reason `studio/newmap.py` refuses to pack a
bank inside a modal dialog. This module reports what it can see and does not
guess at what it cannot.

Nothing here imports the studio or a hack. A tree declares its
:class:`Placement`s; the form renders them; :meth:`Placement.resolve` turns an
answer back into the :class:`Section` a blob lands in.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .objedit import EditError

#: The three shapes. See the module docstring; prism's `mapspec.BANK`/`INTO`/
#: `AUTO` are the same distinctions drawn one layer down, where `AUTO` means
#: "mint a section and let the packer pin it later" rather than "leave it
#: floating" — which is why this vocabulary is separate rather than imported.
PIN, JOIN, MINT = "pin", "join", "mint"

KINDS = (PIN, JOIN, MINT)

_SECTION_RE = re.compile(r'^\s*SECTION\s+"([^"]+)"')

#: A link script names a bank and then lists the sections in it, one quoted
#: string per line. `ROM0` has no number; every other heading carries one.
_BANK_RE = re.compile(r"^\s*(ROM0|ROMX|WRAM0|WRAMX|SRAM|VRAM|HRAM|OAM)"
                      r"(?:\s+\$?([0-9a-fA-F]+))?\s*$")
_NAMED_RE = re.compile(r'^\s*"([^"]+)"\s*$')


@dataclass(frozen=True)
class Section:
    """One `SECTION`, and the bank the link script puts it in.

    ``bank is None`` means the linker places it — which is the ordinary state of
    a minted section and an outright bug in nothing.
    """
    name: str
    bank: int | None = None

    @property
    def pinned(self) -> bool:
        return self.bank is not None

    def describe(self) -> str:
        return (f"{self.name} (bank ${self.bank:02X})" if self.pinned
                else f"{self.name} (unpinned)")


@dataclass(frozen=True)
class Placement:
    """How one blob of a new map gets placed, as the tree declares it.

    `choices` is populated for ``JOIN`` and empty otherwise; `convention` is a
    format string taking `label` and is what ``MINT`` names its section, and
    what ``PIN`` names the section it pins.
    """
    #: What is being placed — "script" or "blocks". The tree's own word for it.
    blob: str
    #: One of :data:`KINDS`.
    kind: str
    #: The asm file the blob's entry gets written into, repo-relative.
    path: str
    #: ``JOIN``: every section the blob may be appended into, file order.
    choices: tuple[Section, ...] = ()
    #: ``MINT``/``PIN``: `"{label}_BlockData"`, say.
    convention: str = ""
    #: ``JOIN``: which choice the form starts on. Blank means the last one,
    #: which is where a tree that numbers its buckets has been adding lately.
    default: str = ""

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"unknown placement kind {self.kind!r}")
        if self.kind == JOIN and not self.choices:
            raise ValueError(f"{self.blob}: JOIN with nothing to join")
        if self.kind in (MINT, PIN) and not self.convention:
            raise ValueError(f"{self.blob}: {self.kind} needs a section name")

    @property
    def asks(self) -> bool:
        """Whether this blob has a question for the form at all.

        ``MINT`` does not: the section's name follows from the label, and there
        is no bank to name. A field offering one choice is worse than no field.
        """
        return self.kind != MINT

    def preset(self) -> str:
        """What the field starts filled in with."""
        if self.kind != JOIN:
            return ""
        return self.default or self.choices[-1].name

    def resolve(self, answer: str, label: str) -> Section:
        """The section this blob lands in, given what the form came back with.

        Every refusal here names the reason and the alternatives, because the
        thing this prevents — a section name that does not exist, or a bank
        typed the way Python spells one — surfaces otherwise as an `rgblink`
        message minutes later that does not mention the map.
        """
        answer = answer.strip()
        if self.kind == MINT:
            return Section(answer or self.convention.format(label=label), None)
        if self.kind == JOIN:
            return self._joined(answer)
        return Section(self.convention.format(label=label), _bank(answer))

    def _joined(self, answer: str) -> Section:
        if not answer:
            raise EditError(f"{self.blob}: pick a section in {self.path}")
        for section in self.choices:
            if section.name == answer:
                return section
        # Minting into a JOIN tree is a decision, not a typo recovery: a new
        # `Map Blocks 4` is not pinned by `layout.link` and so does not behave
        # like the three sections it is named after. Refuse and say why, rather
        # than create something that looks like the convention and isn't.
        raise EditError(
            f"{self.blob}: no section named {answer!r} in {self.path}. "
            f"This tree places {self.blob} by joining one of "
            f"{len(self.choices)} existing sections — a new one would not be "
            f"in layout.link, so it would float where its neighbours are "
            f"pinned. Pick one of: "
            f"{', '.join(s.name for s in self.choices)}")


def _bank(raw: str) -> int | None:
    """A bank the way a link script spells it. `$7C`, not `0x7c`, and blank
    means the section floats — which is a legitimate answer, not a missing one."""
    if not raw:
        return None
    try:
        bank = int(raw.replace("$", "0x"), 0)
    except ValueError:
        raise EditError(f"{raw!r} is not a bank — write it like $7C") from None
    if not 0 <= bank <= 0xFF:
        raise EditError(f"${bank:X} is not a ROM bank")
    return bank


# --------------------------------------------------------------------------- #
# reading the tree: which sections exist, and which of them are pinned         #
# --------------------------------------------------------------------------- #

def sections(root: Path, rel: str, banks: dict[str, int] | None = None
             ) -> tuple[Section, ...]:
    """Every `SECTION` declared in an asm file, in file order, with its bank.

    File order is the useful order: a tree that numbers its buckets appends to
    the highest one, so the last entry is the sensible default. Duplicates are
    kept out — rgbds treats a repeated `SECTION "name"` as a continuation of the
    same section, so it is one choice however many times it is written.
    """
    path = root / rel
    if not path.exists():
        raise EditError(f"{rel} is missing")
    banks = {} if banks is None else banks
    out: list[Section] = []
    seen: set[str] = set()
    for line in path.read_text().split("\n"):
        m = _SECTION_RE.match(line)
        if m and m.group(1) not in seen:
            seen.add(m.group(1))
            out.append(Section(m.group(1), banks.get(m.group(1))))
    return tuple(out)


def banks(root: Path, rel: str = "layout.link") -> dict[str, int]:
    """`section name -> bank`, read from a linker script.

    This is the only place either family tree records that a section has a
    fixed bank; the asm says nothing about it. A tree with no link script is
    not an error — it means nothing is pinned, which the empty dict says.
    """
    path = root / rel
    if not path.exists():
        return {}
    out: dict[str, int] = {}
    bank: int | None = None
    for line in path.read_text().split("\n"):
        line = line.split(";", 1)[0]
        if m := _BANK_RE.match(line):
            # ROM0 and the single-bank regions carry no number and are bank 0.
            bank = int(m.group(2), 16) if m.group(2) else 0
        elif (m := _NAMED_RE.match(line)) and bank is not None:
            out[m.group(1)] = bank
    return out
