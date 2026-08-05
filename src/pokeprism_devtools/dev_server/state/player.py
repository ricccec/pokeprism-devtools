"""The player: their name, their money, their badges.

The three fields the save carries about the trainer rather than about the
world. `badges` is one field asked for as three prompts, because the game
keeps a bitmask per region and there is no useful way to ask for all of
them at once.
"""

from __future__ import annotations

from .prompts import _int_in


class PlayerMenu:

    def _edit_player(self) -> None:
        import questionary
        from questionary import Choice

        while True:
            player = self.state.setdefault("player", {})
            choice = questionary.select(
                "Edit player",
                choices=[
                    Choice(f"Name    : {player.get('name', '(unset)')}",   value="name"),
                    Choice(f"Money   : {player.get('money', '(unset)')}", value="money"),
                    Choice(f"Badges  : {player.get('badges', '(unset)')}", value="badges"),
                    Choice("← Back", value="back"),
                ],
            ).ask()
            if choice is None or choice == "back":
                return

            if choice == "name":
                val = questionary.text(
                    "Player name (1–7 chars, GB charset):",
                    default=str(player.get("name", "")),
                    validate=lambda s: 1 <= len(s) <= 7 or "1–7 chars",
                ).ask()
                if val is not None:
                    player["name"] = val
                    self._save_state()
            elif choice == "money":
                val = questionary.text(
                    "Money (0–999999):",
                    default=str(player.get("money", 0)),
                    validate=_int_in(0, 999_999),
                ).ask()
                if val is not None:
                    player["money"] = int(val)
                    self._save_state()
            elif choice == "badges":
                cur = player.get("badges") or [0, 0, 0]
                parts = []
                for i, label in enumerate(("Naljo", "Rijon", "Other")):
                    v = questionary.text(
                        f"{label} badges (0–255 bitmask):",
                        default=str(cur[i]),
                        validate=_int_in(0, 255),
                    ).ask()
                    if v is None:
                        break
                    parts.append(int(v))
                if len(parts) == 3:
                    player["badges"] = parts
                    self._save_state()
