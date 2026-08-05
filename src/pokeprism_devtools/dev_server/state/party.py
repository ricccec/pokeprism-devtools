"""The six party slots, and what is in one.

A slot is reached by number, so opening slot 5 of a two-mon party has to
allocate the three in between. `_drop_slot_and_its_gaps` is what takes them
back out again: `apply._apply_party` refuses an entry with no species, so a
gap left behind is a launch that fails rather than a slot that looks empty.
"""

from __future__ import annotations

from .prompts import _int_in


class PartyMenu:

    def _edit_party(self) -> None:
        import questionary
        from questionary import Choice

        species_names = sorted(self.inv["species_data"].keys())
        move_names = sorted(m["name"] for m in self.inv["moves"])

        while True:
            party = self.state.setdefault("party", [])
            choices: list = []
            for i in range(6):
                if i < len(party):
                    mon = party[i]
                    label = (
                        f"Slot {i+1}: {mon.get('species', '?')} "
                        f"L{mon.get('level', '?')}"
                    )
                    if mon.get("nickname"):
                        label += f"  '{mon['nickname']}'"
                else:
                    label = f"Slot {i+1}: (empty)"
                choices.append(Choice(label, value=("slot", i)))
            if party:
                choices.append(Choice("Clear party", value=("clear", None)))
            choices.append(Choice("← Back", value=("back", None)))

            action = questionary.select("Edit party", choices=choices).ask()
            if action is None or action[0] == "back":
                return
            if action[0] == "clear":
                if questionary.confirm(
                    "Clear all party slots?", default=False
                ).ask():
                    self.state["party"] = []
                    self._save_state()
                continue
            self._edit_party_slot(action[1], species_names, move_names)

    def _edit_party_slot(
        self, idx: int, species_names: list[str], move_names: list[str]
    ) -> None:
        import questionary

        party = self.state.setdefault("party", [])
        existing = len(party)
        while idx >= len(party):
            # Lazily allocate an empty slot. Species required before save.
            party.append({})
        mon = party[idx]

        while True:
            choice = questionary.select(
                f"Edit slot {idx + 1}", choices=_slot_rows(mon)
            ).ask()
            if choice is None or choice == "back":
                # Drop the slot entirely if species was never set.
                if not mon.get("species"):
                    _drop_slot_and_its_gaps(party, idx, existing)
                    self._save_state()
                return

            if choice == "species":
                self._ask_species(mon, species_names)
            elif choice == "level":
                self._ask_level(mon)
            elif choice == "nickname":
                self._ask_nickname(mon)
            elif choice == "moves":
                self._edit_party_moves(mon, move_names)
            elif choice == "remove":
                _drop_slot_and_its_gaps(party, idx, existing)
                self._save_state()
                return

    def _ask_species(self, mon: dict, species_names: list[str]) -> None:
        """Name the slot's species, which is what makes it a slot at all — an
        entry without one is what `apply` refuses, so a level comes with it."""
        import questionary

        val = questionary.autocomplete(
            "Species (tab to autocomplete):",
            choices=species_names,
            default=str(mon.get("species", "")),
            validate=lambda s: s in species_names or f"unknown species: {s}",
        ).ask()
        if val is not None:
            mon["species"] = val
            # Stamp a sane default level if unset.
            mon.setdefault("level", 5)
            self._save_state()

    def _ask_level(self, mon: dict) -> None:
        import questionary

        val = questionary.text(
            "Level (1–100):",
            default=str(mon.get("level", 5)),
            validate=_int_in(1, 100),
        ).ask()
        if val is not None:
            mon["level"] = int(val)
            self._save_state()

    def _ask_nickname(self, mon: dict) -> None:
        """A blank answer removes the key rather than storing an empty string:
        no nickname means the game shows the species name, and `""` would be a
        pokemon called nothing."""
        import questionary

        val = questionary.text(
            "Nickname (blank = species name, max 10 chars):",
            default=str(mon.get("nickname") or ""),
            validate=lambda s: (len(s) <= 10) or "max 10 chars",
        ).ask()
        if val is None:
            return
        if val == "":
            mon.pop("nickname", None)
        else:
            mon["nickname"] = val
        self._save_state()

    def _edit_party_moves(self, mon: dict, move_names: list[str]) -> None:
        import questionary

        current = mon.get("moves") or []
        # Pad to 4 slots so the user can replace one at a time.
        current = (current + [""] * 4)[:4]
        out: list[str] = []
        for i in range(4):
            val = questionary.autocomplete(
                f"Move {i + 1} (blank = empty, '-' = revert to learnset):",
                choices=move_names,
                default=current[i],
                validate=lambda s: (
                    s == "" or s == "-" or s in move_names
                ) or f"unknown move: {s}",
            ).ask()
            if val is None:
                return
            if val == "-":
                mon.pop("moves", None)
                self._save_state()
                return
            if val:
                out.append(val)
        if out:
            mon["moves"] = out
        else:
            mon.pop("moves", None)
        self._save_state()


def _drop_slot_and_its_gaps(party: list[dict], idx: int, existing: int) -> None:
    """Remove one party slot, and the empty ones opening it created.

    Opening slot N allocates every slot up to N, so removing only the slot that
    was asked for leaves `{}` entries in the party — which `apply._apply_party`
    refuses, taking the next launch with it.

    `existing` is how many slots there were before the editor opened, which is
    what tells our gaps from a `{}` somebody wrote into state.json by hand.
    Dropping one of those would silently renumber every slot after it.
    """
    party.pop(idx)
    del party[existing:]


def _slot_rows(mon: dict) -> list:
    """The four fields of one party slot, each labelled with what it holds now
    — or with where its value comes from when it holds nothing, since "(from
    learnset)" and "(default)" are answers rather than blanks."""
    from questionary import Choice

    moves = ", ".join(mon["moves"]) if mon.get("moves") else "(from learnset)"
    return [
        Choice(f"Species  : {mon.get('species', '(unset)')}", value="species"),
        Choice(f"Level    : {mon.get('level', '(unset)')}",   value="level"),
        Choice(f"Nickname : {mon.get('nickname') or '(default)'}", value="nickname"),
        Choice(f"Moves    : {moves}",                         value="moves"),
        Choice("Remove slot",                                 value="remove"),
        Choice("← Back",                                      value="back"),
    ]
