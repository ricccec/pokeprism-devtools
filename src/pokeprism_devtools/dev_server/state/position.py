"""Where you stand when the game comes up: which map, and which tile.

    The coord bounds are the only arithmetic here and they are the map's, not a
    constant: a map is `width x height` **blocks**, a block is two tiles per
    axis, so a coord runs 0..(blocks*2 - 1) from *that axis's own* dimension.
    A map the inventory has never heard of falls back to a whole byte, which is
    what a tile coord is.
    """

from __future__ import annotations

from .prompts import _int_in


class PositionMenu:
    def _edit_map(self) -> None:
        import questionary
        from questionary import Choice

        map_names = sorted(m["name"] for m in self.inv["maps"])

        while True:
            map_ = self.state.setdefault("map", {})
            choice = questionary.select(
                "Edit map / position",
                choices=[
                    Choice(f"Map name : {map_.get('name', '(unset)')}", value="name"),
                    Choice(f"X coord  : {map_.get('x', '(unset)')}",    value="x"),
                    Choice(f"Y coord  : {map_.get('y', '(unset)')}",    value="y"),
                    Choice("← Back", value="back"),
                ],
            ).ask()
            if choice is None or choice == "back":
                return

            if choice == "name":
                val = questionary.autocomplete(
                    "Map name (tab to autocomplete):",
                    choices=map_names,
                    default=str(map_.get("name", "")),
                    validate=lambda s: s in map_names or f"unknown map: {s}",
                ).ask()
                if val is not None:
                    map_["name"] = val
                    self._save_state()
            elif choice in ("x", "y"):
                bound = self._coord_bound(map_, choice)
                val = questionary.text(
                    f"{choice.upper()} coord (0–{bound}):",
                    default=str(map_.get(choice, 0)),
                    validate=_int_in(0, bound),
                ).ask()
                if val is not None:
                    map_[choice] = int(val)
                    self._save_state()
    def _coord_bound(self, map_: dict, axis: str) -> int:
        """Upper bound for a coord. The map's block grid is `width × height`
        blocks; each block is 2 tiles per axis, so walkable coords run
        0..(blocks*2 - 1). When the map name is unset or unknown, fall back
        to 0..255 (a tile coord is one byte)."""
        mdef = next(
            (m for m in self.inv["maps"] if m["name"] == map_.get("name")), None
        )
        if mdef is None:
            return 255
        return (mdef["width"] if axis == "x" else mdef["height"]) * 2 - 1
