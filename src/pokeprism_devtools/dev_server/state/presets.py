"""Replacing the whole state with a preset.

    The one editor that does not edit a section: it reads a file from
    `presets/` and puts it where the state was. It asks first, and it writes to
    `state.json` like every other edit does — a preset is a thing you reset
    *from*, never a thing this tool writes to.
    """

from __future__ import annotations

import json



class PresetMenu:
    def _reset_preset(self) -> None:
        import questionary
        from questionary import Choice

        presets = sorted(self.presets_dir.glob("*.json"))
        if not presets:
            print("(no presets in presets/)")
            return

        choice = questionary.select(
            "Reset state from preset",
            choices=[Choice(p.name, value=p) for p in presets]
            + [Choice("← Cancel", value=None)],
        ).ask()
        if choice is None:
            return

        ok = questionary.confirm(
            f"Overwrite {self._pretty(self.state_path)} with {choice.name}?",
            default=False,
        ).ask()
        if not ok:
            return

        self.state = json.loads(choice.read_text())
        self._save_state()
        print(f"Reset state from {choice.name}")
