"""The three bag pockets, and the items in one.

Items and balls carry a quantity; key items do not, and `apply` refuses one
that does. The distinction the whole editor turns on is the other one: an
empty list means *launch with an empty pocket*, an absent key means *leave
the template's alone*, and browsing a pocket must never turn the second into
the first.
"""

from __future__ import annotations

from .prompts import _int_in


class BagMenu:
    _BAG_POCKETS = [
        ("Items",     "items",     True,  "ITEM"),
        ("Balls",     "balls",     True,  "BALL"),
        ("Key items", "key_items", False, "KEY_ITEM"),
    ]

    def _edit_items(self) -> None:
        import questionary
        from questionary import Choice

        caps = self.inv.get("bag_caps")
        if not caps:
            print("(inventory has no bag_caps — rebuild it: --rebuild-inventory)")
            return

        while True:
            items_state = self.state.get("items") or {}
            choices: list = []
            for label, key, has_qty, want_pocket in self._BAG_POCKETS:
                if key in items_state:
                    status = f"{len(items_state[key])}/{caps[key]}"
                else:
                    status = "(template)"
                choices.append(
                    Choice(f"{label + ' pocket':18s} {status}", value=key)
                )
            choices.append(Choice("← Back", value="back"))

            choice = questionary.select("Edit items", choices=choices).ask()
            if choice is None or choice == "back":
                return
            label, key, has_qty, want_pocket = next(
                p for p in self._BAG_POCKETS if p[1] == choice
            )
            self._edit_pocket(
                label, key, has_qty=has_qty, cap=caps[key], want_pocket=want_pocket
            )

    def _edit_pocket(
        self, label: str, key: str, *, has_qty: bool, cap: int, want_pocket: str
    ) -> None:
        """Add/remove editor for one bag pocket, mirroring _edit_flag_group."""
        import questionary

        pocket_names = sorted(
            i["name"] for i in self.inv["items"] if i.get("pocket") == want_pocket
        )

        while True:
            items_state = self.state.setdefault("items", {})
            in_state = key in items_state
            entries = [_normalized(e, has_qty) for e in items_state.get(key, [])]
            items_state[key] = entries  # write back dict-form entries

            action = questionary.select(
                f"{label} pocket — {len(entries)}/{cap}",
                choices=_pocket_rows(entries, has_qty=has_qty, cap=cap,
                                     in_state=in_state),
            ).ask()
            if action is None or action[0] == "back":
                # Don't leave an empty dict behind if nothing was ever set.
                if not in_state and not items_state.get(key):
                    items_state.pop(key, None)
                if not items_state:
                    self.state.pop("items", None)
                return

            if action[0] == "add":
                self._add_to_pocket(entries, pocket_names, label, has_qty=has_qty)
            elif action[0] == "entry":
                self._set_pocket_quantity(entries, action[1])
            elif action[0] == "remove_one":
                entries.pop(action[1])
                self._save_state()
            elif action[0] == "clear":
                self._empty_the_pocket(items_state, key, label)
            elif action[0] == "template":
                if self._give_the_pocket_back(items_state, key, label):
                    return

    def _empty_the_pocket(self, items_state: dict, key: str, label: str) -> None:
        """Leave an explicit empty list — which means *launch with an empty
        pocket*, and is not the same as `_give_the_pocket_back`."""
        import questionary

        if questionary.confirm(
            f"Clear the {label.lower()} pocket?", default=False
        ).ask():
            items_state[key] = []
            self._save_state()

    def _give_the_pocket_back(self, items_state: dict, key: str,
                              label: str) -> bool:
        """Stop overriding this pocket, so the template's is used. True if it
        happened, which is also the caller's cue to close the menu — there is
        nothing left in it to look at."""
        import questionary

        if not questionary.confirm(
            f"Stop overriding the {label.lower()} pocket (use the template's)?",
            default=False,
        ).ask():
            return False
        items_state.pop(key, None)
        if not items_state:
            self.state.pop("items", None)
        self._save_state()
        return True

    def _add_to_pocket(self, entries: list[dict], pocket_names: list[str],
                       label: str, *, has_qty: bool) -> None:
        """Ask for an item this pocket does not already hold, and its quantity."""
        import questionary

        present = {e["name"] for e in entries}
        addable = [n for n in pocket_names if n not in present]
        val = questionary.autocomplete(
            "Item name (tab to autocomplete):",
            choices=addable,
            validate=lambda s: s in addable
            or (f"already in pocket: {s}" if s in present else f"unknown {label.lower()} item: {s}"),
        ).ask()
        if not val:
            return
        qty = 1
        if has_qty:
            raw = questionary.text(
                "Quantity (1–99):", default="1", validate=_int_in(1, 99)
            ).ask()
            if raw is None:
                return
            qty = int(raw)
        entries.append({"name": val, "qty": qty} if has_qty else {"name": val})
        self._save_state()

    def _set_pocket_quantity(self, entries: list[dict], i: int) -> None:
        """Re-ask one entry's quantity. Zero is how you take it out of the bag,
        which is why the prompt says so and the validator allows it."""
        import questionary

        raw = questionary.text(
            f"{entries[i]['name']} quantity (1–99, 0 removes):",
            default=str(entries[i].get("qty", 1)),
            validate=_int_in(0, 99),
        ).ask()
        if raw is None:
            return
        if int(raw) == 0:
            entries.pop(i)
        else:
            entries[i]["qty"] = int(raw)
        self._save_state()


def _normalized(raw, has_qty: bool) -> dict:
    """One pocket entry in dict form.

    state.json allows a bare-string shorthand for qty 1. Key items never carry
    a qty (apply rejects one).
    """
    if isinstance(raw, str):
        return {"name": raw, "qty": 1} if has_qty else {"name": raw}
    return raw


def _pocket_rows(entries: list[dict], *, has_qty: bool, cap: int,
                 in_state: bool) -> list:
    """The rows one pocket offers: what is in it, then what can be done to it.

    `Add item...` stays on the list when the pocket is full and is disabled with
    the reason, rather than disappearing — a row that vanishes leaves you
    wondering where it went.
    """
    from questionary import Choice, Separator

    rows: list = []
    for i, e in enumerate(entries):
        if has_qty:
            rows.append(Choice(f"  {e['name']} x{e.get('qty', 1)}", value=("entry", i)))
        else:
            rows.append(Choice(f"  [-] {e['name']}", value=("remove_one", i)))
    if entries:
        rows.append(Separator())
    if len(entries) >= cap:
        rows.append(Choice("Add item...", value=None, disabled="pocket full"))
    else:
        rows.append(Choice("Add item...", value=("add", None)))
    if entries:
        rows.append(Choice("Clear pocket  (launch writes an empty pocket)", value=("clear", None)))
    if in_state:
        rows.append(Choice("Use template's pocket  (remove from state)", value=("template", None)))
    rows.append(Choice("← Back", value=("back", None)))
    return rows
