"""The bag's three pockets, and what tells them apart.

Which pockets there are, what each is called under `state.json`'s `items` key,
whether its entries carry a quantity, and which `pocket` attribute an item must
declare to belong in one. The writer needs all four to lay the bytes down and
the editor needs all four to offer the right items, and they were spelled out
twice — `apply._POCKETS` and the TUI's `_BAG_POCKETS`, the second carrying a
comment saying it mirrored the first.

The WRAM symbols a pocket is written *through* are not here. That is the save
format, which is `apply.py`'s business and nobody else's.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Pocket:
    """One bag pocket, as both halves of the tool need to know it."""

    #: What the editor's menu calls it.
    label: str
    #: Its sub-key under `state.json`'s `items`.
    key: str
    #: Whether an entry carries a quantity. `apply` rejects one on a key item.
    has_qty: bool
    #: The `pocket` an item must declare in `item_attributes.asm` to go here.
    attribute: str


POCKETS: tuple[Pocket, ...] = (
    Pocket("Items",     "items",     True,  "ITEM"),
    Pocket("Balls",     "balls",     True,  "BALL"),
    Pocket("Key items", "key_items", False, "KEY_ITEM"),
)
