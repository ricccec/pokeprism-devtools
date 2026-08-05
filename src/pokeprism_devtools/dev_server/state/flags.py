"""The event flags and the engine flags.

    Two lists with one editor between them: the group's label, which inventory
    key holds its names, and which key of `state["flags"]` it writes are the
    three arguments that tell them apart.
    """

from __future__ import annotations



class FlagMenu:
    def _edit_flags(self) -> None:
        import questionary
        from questionary import Choice

        while True:
            # Flags menu
            flags_state = self.state.setdefault("flags", {})
            n_ev = len(flags_state.get("event", []))
            n_en = len(flags_state.get("engine", []))
            choice = questionary.select(
                "Edit flags",
                choices=[
                    Choice(f"Event flags   ({n_ev} set)", value="event"),
                    Choice(f"Engine flags  ({n_en} set)", value="engine"),
                    Choice("← Back", value="back"),
                ],
            ).ask()
            if choice is None or choice == "back":
                return
            if choice == "event":
                self._edit_flag_group("Event flags", "event_flags", "event")
            else:
                self._edit_flag_group("Engine flags", "engine_flags", "engine")
    def _edit_flag_group(self, label: str, inv_key: str, state_key: str) -> None:
        """Generic add/remove editor for a named flag group (event or engine)."""
        import questionary
        from questionary import Choice, Separator

        flag_names = sorted(f["name"] for f in self.inv.get(inv_key, []))

        while True:
            flags_state = self.state.setdefault("flags", {})
            set_flags: list[str] = flags_state.setdefault(state_key, [])

            choices: list = []
            for name in sorted(set_flags):
                choices.append(Choice(f"  [-] {name}", value=("remove_one", name)))
            if set_flags:
                choices.append(Separator())
            choices.append(Choice("Set flag...", value=("add", None)))
            if set_flags:
                choices.append(Choice(f"Unset flag...  ({len(set_flags)} set)", value=("remove", None)))
                choices.append(Choice(f"Clear all {label.lower()}", value=("clear", None)))
            choices.append(Choice("← Back", value=("back", None)))

            action = questionary.select(
                f"{label} — {len(set_flags)} set", choices=choices
            ).ask()
            if action is None or action[0] == "back":
                return

            if action[0] == "add":
                val = questionary.autocomplete(
                    "Flag name (tab to autocomplete):",
                    choices=flag_names,
                    validate=lambda s: s in flag_names or f"unknown flag: {s}",
                ).ask()
                if val and val not in set_flags:
                    set_flags.append(val)
                    self._save_state()
            elif action[0] == "remove_one":
                name = action[1]
                if name in set_flags:
                    set_flags.remove(name)
                    self._save_state()
            elif action[0] == "remove":
                val = questionary.select(
                    "Unset which flag?",
                    choices=[Choice(n, value=n) for n in sorted(set_flags)]
                    + [Choice("← Cancel", value=None)],
                ).ask()
                if val and val in set_flags:
                    set_flags.remove(val)
                    self._save_state()
            elif action[0] == "clear":
                if questionary.confirm(f"Clear all {label.lower()}?", default=False).ask():
                    flags_state[state_key] = []
                    self._save_state()
