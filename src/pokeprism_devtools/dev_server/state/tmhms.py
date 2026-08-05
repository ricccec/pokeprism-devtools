"""Which TM/HMs the player owns.

Offered as `TM01 HEADBUTT` and stored as `TM_HEADBUTT`, ordered by the
ownership bit rather than by either spelling — the bit is the entry's index
in the inventory, which is the engine's `FlagAction` convention.
"""

from __future__ import annotations


class TmhmMenu:

    def _edit_tmhms(self) -> None:
        """Add/remove editor for TM/HM ownership, mirroring _edit_flag_group."""
        import questionary

        tmhms = self.inv.get("tmhms")
        if not tmhms:
            print("(inventory has no tmhms — rebuild it: --rebuild-inventory)")
            return

        entries_by_bit = sorted(tmhms, key=lambda e: e["bit"])
        label_of = {e["name"]: f"{e['kind']}{e['num']:02d} {e['move']}" for e in tmhms}
        bit_of = {e["name"]: e["bit"] for e in tmhms}
        all_labels = [label_of[e["name"]] for e in entries_by_bit]
        name_of_label = {label_of[e["name"]]: e["name"] for e in tmhms}

        while True:
            in_state = "tmhms" in self.state
            owned: list[str] = sorted(
                self.state.get("tmhms") or [], key=lambda n: bit_of.get(n, 0)
            )

            action = questionary.select(
                f"TM/HMs — {len(owned)}/{len(tmhms)} owned",
                choices=_tmhm_rows(owned, label_of, total=len(tmhms),
                                   in_state=in_state),
            ).ask()
            if action is None or action[0] == "back":
                return

            # Never write to self.state here except inside a branch that
            # actually changed something — an empty "tmhms": [] created just
            # by browsing this menu would mean "own nothing" on next launch.
            if action[0] == "add":
                self._own_another(owned, all_labels, name_of_label, bit_of)
            elif action[0] == "remove_one":
                name = action[1]
                if name in owned:
                    self.state["tmhms"] = [n for n in owned if n != name]
                    self._save_state()
            elif action[0] == "own_all":
                self._set_owned_if_confirmed(
                    f"Own all {len(tmhms)} TM/HMs?",
                    [e["name"] for e in entries_by_bit])
            elif action[0] == "clear":
                self._set_owned_if_confirmed("Clear all TM/HMs?", [])
            elif action[0] == "template":
                if self._give_the_tmhms_back():
                    return

    def _set_owned_if_confirmed(self, question: str, owned: list[str]) -> None:
        """Replace the owned list wholesale, having asked. An empty list is a
        real answer here — it means *launch owning none*, which is not the same
        as `_give_the_tmhms_back`."""
        import questionary

        if questionary.confirm(question, default=False).ask():
            self.state["tmhms"] = owned
            self._save_state()

    def _give_the_tmhms_back(self) -> bool:
        """Stop overriding TM/HMs, so the template's are used. True if it
        happened, which is the caller's cue to close the menu."""
        import questionary

        if not questionary.confirm(
            "Stop overriding TM/HMs (use the template's)?", default=False
        ).ask():
            return False
        self.state.pop("tmhms", None)
        self._save_state()
        return True

    def _own_another(self, owned: list[str], all_labels: list[str],
                     name_of_label: dict[str, str],
                     bit_of: dict[str, int]) -> None:
        """Ask for one more TM/HM, offered by its `TM01 HEADBUTT` label and
        stored by its `TM_HEADBUTT` name. The owned list is kept in bit order,
        which is neither of those two orderings."""
        import questionary

        present = set(owned)
        addable = [lbl for lbl in all_labels if name_of_label[lbl] not in present]
        val = questionary.autocomplete(
            "TM/HM (tab to autocomplete):",
            choices=addable,
            validate=lambda s: s in addable
            or (f"already owned: {s}" if s in all_labels else f"unknown TM/HM: {s}"),
        ).ask()
        if not val:
            return
        name = name_of_label[val]
        if name in owned:
            return
        new_owned = owned + [name]
        new_owned.sort(key=lambda n: bit_of.get(n, 0))
        self.state["tmhms"] = new_owned
        self._save_state()


def _tmhm_rows(owned: list[str], label_of: dict[str, str], *, total: int,
               in_state: bool) -> list:
    """The rows the TM/HM menu offers: what is owned, then what can be done."""
    from questionary import Choice, Separator

    rows: list = [
        Choice(f"  [-] {label_of.get(name, name)}", value=("remove_one", name))
        for name in owned
    ]
    if owned:
        rows.append(Separator())
    rows.append(Choice("Own TM/HM...", value=("add", None)))
    rows.append(Choice(f"Own all ({total})", value=("own_all", None)))
    if owned:
        rows.append(Choice("Clear all  (launch writes none owned)", value=("clear", None)))
    if in_state:
        rows.append(Choice("Use template's TM/HMs  (remove from state)", value=("template", None)))
    rows.append(Choice("← Back", value=("back", None)))
    return rows
