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

        flag_names = sorted(f["name"] for f in self.inv.get(inv_key, []))

        while True:
            flags_state = self.state.setdefault("flags", {})
            set_flags: list[str] = flags_state.setdefault(state_key, [])

            action = questionary.select(
                f"{label} — {len(set_flags)} set",
                choices=_flag_rows(set_flags, label),
            ).ask()
            if action is None or action[0] == "back":
                return

            if action[0] == "add":
                self._set_a_flag(set_flags, flag_names)
            elif action[0] == "remove_one":
                self._unset_a_flag(set_flags, action[1])
            elif action[0] == "remove":
                self._unset_a_flag(set_flags, _pick_a_set_flag(set_flags))
            elif action[0] == "clear":
                if questionary.confirm(f"Clear all {label.lower()}?", default=False).ask():
                    flags_state[state_key] = []
                    self._save_state()

    def _set_a_flag(self, set_flags: list[str], flag_names: list[str]) -> None:
        """Set one flag. The prompt takes any flag the tree defines, set or not,
        so setting one that is already set has to be a no-op rather than a
        second entry in the list."""
        import questionary

        val = questionary.autocomplete(
            "Flag name (tab to autocomplete):",
            choices=flag_names,
            validate=lambda s: s in flag_names or f"unknown flag: {s}",
        ).ask()
        if val and val not in set_flags:
            set_flags.append(val)
            self._save_state()

    def _unset_a_flag(self, set_flags: list[str], name: str | None) -> None:
        """Unset one flag, whether it was pressed in the list or picked from
        the menu. None is a cancel from either."""
        if name and name in set_flags:
            set_flags.remove(name)
            self._save_state()


def _flag_rows(set_flags: list[str], label: str) -> list:
    """The rows one flag group offers. What is set is listed alphabetically and
    each row unsets itself; the picker below is the same job for a list too long
    to walk."""
    from questionary import Choice, Separator

    rows: list = [Choice(f"  [-] {n}", value=("remove_one", n))
                  for n in sorted(set_flags)]
    if set_flags:
        rows.append(Separator())
    rows.append(Choice("Set flag...", value=("add", None)))
    if set_flags:
        rows.append(Choice(f"Unset flag...  ({len(set_flags)} set)", value=("remove", None)))
        rows.append(Choice(f"Clear all {label.lower()}", value=("clear", None)))
    rows.append(Choice("← Back", value=("back", None)))
    return rows


def _pick_a_set_flag(set_flags: list[str]) -> str | None:
    """Which of the set flags to unset. None if the picker was cancelled."""
    import questionary
    from questionary import Choice

    return questionary.select(
        "Unset which flag?",
        choices=[Choice(n, value=n) for n in sorted(set_flags)]
        + [Choice("← Cancel", value=None)],
    ).ask()
