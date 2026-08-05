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
        from questionary import Choice, Separator

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

            choices: list = []
            for name in owned:
                choices.append(
                    Choice(f"  [-] {label_of.get(name, name)}", value=("remove_one", name))
                )
            if owned:
                choices.append(Separator())
            choices.append(Choice("Own TM/HM...", value=("add", None)))
            if owned:
                choices.append(Choice(f"Own all ({len(tmhms)})", value=("own_all", None)))
                choices.append(Choice("Clear all  (launch writes none owned)", value=("clear", None)))
            else:
                choices.append(Choice(f"Own all ({len(tmhms)})", value=("own_all", None)))
            if in_state:
                choices.append(Choice("Use template's TM/HMs  (remove from state)", value=("template", None)))
            choices.append(Choice("← Back", value=("back", None)))

            action = questionary.select(
                f"TM/HMs — {len(owned)}/{len(tmhms)} owned", choices=choices
            ).ask()
            if action is None or action[0] == "back":
                return

            # Never write to self.state here except inside a branch that
            # actually changed something — an empty "tmhms": [] created just
            # by browsing this menu would mean "own nothing" on next launch.
            if action[0] == "add":
                present = set(owned)
                addable = [lbl for lbl in all_labels if name_of_label[lbl] not in present]
                val = questionary.autocomplete(
                    "TM/HM (tab to autocomplete):",
                    choices=addable,
                    validate=lambda s: s in addable
                    or (f"already owned: {s}" if s in all_labels else f"unknown TM/HM: {s}"),
                ).ask()
                if not val:
                    continue
                name = name_of_label[val]
                if name not in owned:
                    new_owned = owned + [name]
                    new_owned.sort(key=lambda n: bit_of.get(n, 0))
                    self.state["tmhms"] = new_owned
                    self._save_state()
            elif action[0] == "remove_one":
                name = action[1]
                if name in owned:
                    new_owned = [n for n in owned if n != name]
                    self.state["tmhms"] = new_owned
                    self._save_state()
            elif action[0] == "own_all":
                if questionary.confirm(
                    f"Own all {len(tmhms)} TM/HMs?", default=False
                ).ask():
                    self.state["tmhms"] = [e["name"] for e in entries_by_bit]
                    self._save_state()
            elif action[0] == "clear":
                if questionary.confirm("Clear all TM/HMs?", default=False).ask():
                    self.state["tmhms"] = []
                    self._save_state()
            elif action[0] == "template":
                if questionary.confirm(
                    "Stop overriding TM/HMs (use the template's)?", default=False
                ).ask():
                    self.state.pop("tmhms", None)
                    self._save_state()
                    return
