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
        from questionary import Choice, Separator

        pocket_names = sorted(
            i["name"] for i in self.inv["items"] if i.get("pocket") == want_pocket
        )

        def _normalized(raw) -> dict:
            # state.json allows a bare-string shorthand for qty 1. Key items
            # never carry a qty (apply rejects one).
            if isinstance(raw, str):
                return {"name": raw, "qty": 1} if has_qty else {"name": raw}
            return raw

        while True:
            items_state = self.state.setdefault("items", {})
            in_state = key in items_state
            entries = [_normalized(e) for e in items_state.get(key, [])]
            items_state[key] = entries  # write back dict-form entries
            present = {e["name"] for e in entries}

            choices: list = []
            for i, e in enumerate(entries):
                if has_qty:
                    choices.append(
                        Choice(f"  {e['name']} x{e.get('qty', 1)}", value=("entry", i))
                    )
                else:
                    choices.append(Choice(f"  [-] {e['name']}", value=("remove_one", i)))
            if entries:
                choices.append(Separator())
            if len(entries) >= cap:
                choices.append(Choice("Add item...", value=None, disabled="pocket full"))
            else:
                choices.append(Choice("Add item...", value=("add", None)))
            if entries:
                choices.append(Choice("Clear pocket  (launch writes an empty pocket)", value=("clear", None)))
            if in_state:
                choices.append(Choice("Use template's pocket  (remove from state)", value=("template", None)))
            choices.append(Choice("← Back", value=("back", None)))

            action = questionary.select(
                f"{label} pocket — {len(entries)}/{cap}", choices=choices
            ).ask()
            if action is None or action[0] == "back":
                # Don't leave an empty dict behind if nothing was ever set.
                if not in_state and not items_state.get(key):
                    items_state.pop(key, None)
                if not items_state:
                    self.state.pop("items", None)
                return

            if action[0] == "add":
                addable = [n for n in pocket_names if n not in present]
                val = questionary.autocomplete(
                    "Item name (tab to autocomplete):",
                    choices=addable,
                    validate=lambda s: s in addable
                    or (f"already in pocket: {s}" if s in present else f"unknown {label.lower()} item: {s}"),
                ).ask()
                if not val:
                    continue
                qty = 1
                if has_qty:
                    raw = questionary.text(
                        "Quantity (1–99):", default="1", validate=_int_in(1, 99)
                    ).ask()
                    if raw is None:
                        continue
                    qty = int(raw)
                entries.append({"name": val, "qty": qty} if has_qty else {"name": val})
                self._save_state()
            elif action[0] == "entry":
                i = action[1]
                raw = questionary.text(
                    f"{entries[i]['name']} quantity (1–99, 0 removes):",
                    default=str(entries[i].get("qty", 1)),
                    validate=_int_in(0, 99),
                ).ask()
                if raw is None:
                    continue
                if int(raw) == 0:
                    entries.pop(i)
                else:
                    entries[i]["qty"] = int(raw)
                self._save_state()
            elif action[0] == "remove_one":
                entries.pop(action[1])
                self._save_state()
            elif action[0] == "clear":
                if questionary.confirm(
                    f"Clear the {label.lower()} pocket?", default=False
                ).ask():
                    items_state[key] = []
                    self._save_state()
            elif action[0] == "template":
                if questionary.confirm(
                    f"Stop overriding the {label.lower()} pocket (use the template's)?",
                    default=False,
                ).ask():
                    items_state.pop(key, None)
                    if not items_state:
                        self.state.pop("items", None)
                    self._save_state()
                    return
